"""The property-typed sanitiser contract shared by every taint tracker.

A single value object bundles the two opt-in property tables so each tracker's
constructor takes one extra argument rather than two (keeping every tracker
within the project's ``max_arguments`` limit). The contract is inert by default:
with both tables empty, a sanitiser clears every sink exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import tree_sitter


# ---------------------------------------------------------------------------
# Property-labelled taint helpers (shared by every tracker)
#
# Taint is tracked as ``dict[str, frozenset[str]]`` mapping a tainted variable to
# the set of safety properties it is already safe for (cleared by a property-typed
# sanitiser on its path); absence from the dict means clean. These free functions
# hold the property arithmetic so the seven sibling trackers do not each duplicate
# it - each tracker still owns its own ``_is_tainted`` worklist and node types.
# ---------------------------------------------------------------------------


def identifier_tainted(tainted: dict[str, frozenset[str]], name: str, required_property: str | None) -> bool:
    """Return True if variable *name* is still tainted for *required_property*.

    A tracked variable is tainted for a sink requiring ``P`` unless ``P`` is among
    the properties it is safe for. A no-property sink (``required_property is
    None``) is never cleared by a property-typed sanitiser, so any tracked
    variable is tainted for it.
    """
    cleared = tainted.get(name)
    if cleared is None:
        return False
    return required_property is None or required_property not in cleared


def value_status(is_tainted: Callable[[tree_sitter.Node, str | None], bool], properties: frozenset[str], value: tree_sitter.Node) -> frozenset[str] | None:
    """Return ``None`` if *value* is clean, else the properties it is safe for.

    Labels a value at assignment time: tainted iff any raw taint reaches it
    (``required_property=None``), and safe for property ``P`` when no taint
    survives a sanitiser establishing ``P`` on the path - computed by asking the
    tracker's own ``is_tainted`` once per property in the contract's universe.
    """
    if not is_tainted(value, None):
        return None
    return frozenset(p for p in properties if not is_tainted(value, p))


def combine_status(a: frozenset[str] | None, b: frozenset[str] | None) -> frozenset[str] | None:
    """OR-combine two taint statuses: tainted iff either is; safe only for shared properties."""
    if a is None:
        return b
    if b is None:
        return a
    return a & b


def set_status(tainted: dict[str, frozenset[str]], name: str, status: frozenset[str] | None) -> None:
    """Record *status* for variable *name* (``None`` clears it)."""
    if status is None:
        tainted.pop(name, None)
    else:
        tainted[name] = status


def assignment_sink_name(target: tree_sitter.Node, member_fields: Mapping[str, tuple[str, bool]]) -> str | None:
    """Return the property name an assignment WRITES to, or None.

    Some sinks are assigned to rather than called - ``element.innerHTML =
    tainted`` is the canonical one - and writing the property *is* the
    injection, so the target has to be matched against the sink list just as a
    callee is. *member_fields* maps each target node type to ``(field, keyed)``:
    the field holding the name, and whether that field is a SUBSCRIPT KEY
    rather than a written-out property.

    The distinction matters. ``o.danger`` names the property ``danger``, but
    ``o[key]`` names whatever ``key`` holds at runtime - its *spelling* is not
    the property. Matching a computed key against the sink list turns every
    local variable called ``run`` / ``load`` / ``query`` into a false positive,
    so a keyed field is accepted only when it is a quoted literal, which does
    name the property (``o["danger"]`` is ``o.danger``).
    """
    entry = member_fields.get(target.type)
    if entry is None:
        return None
    field, keyed = entry
    name_node = target.child_by_field_name(field)
    if name_node is None:
        return None
    text = node_text(name_node)
    if text.startswith(('"', "'", "`")):
        return text.strip("\"'`") or None
    return None if keyed else (text or None)


@dataclass(frozen=True)
class AssignmentShapes:
    """Per-language node types for finding sink-named assignment targets.

    Only this table differs between languages; the traversal that uses it is
    shared, so a semantic fix lands once rather than in seven trackers.

    * ``fields`` - target type -> ``(field, keyed)``. ``keyed`` marks a
      SUBSCRIPT key rather than a written-out property: ``o[k]`` names whatever
      ``k`` holds, so its spelling is only a property name when it is a quoted
      literal.
    * ``unwrap`` - transparent wrappers around a target, e.g. the parentheses
      in ``(el.innerHTML) = x``, which JavaScript and Python both permit.
    * ``patterns`` - unpack targets (``[a, obj.sink] = ...``), whose elements
      are themselves targets and pair positionally with the value list.
    * ``chains`` - assignment node types, so a chained ``a.sink = b = tainted``
      resolves to the value actually written rather than the inner assignment.
    """

    fields: Mapping[str, tuple[str, bool]]
    unwrap: frozenset[str] = frozenset()
    patterns: frozenset[str] = frozenset()
    chains: frozenset[str] = frozenset()


def _peel(node: tree_sitter.Node, wrappers: frozenset[str]) -> tree_sitter.Node:
    """Strip transparent wrapper nodes (parentheses) from *node*."""
    cur = node
    for _ in range(8):
        if cur.type not in wrappers:
            return cur
        inner = cur.named_child(0)
        if inner is None:
            return cur
        cur = inner
    return cur  # pragma: no cover - defensive: parens do not nest 8 deep in practice


def terminal_assigned_value(right: tree_sitter.Node, shapes: AssignmentShapes) -> tree_sitter.Node:
    """Resolve a chained assignment RHS to the value actually written.

    ``el.innerHTML = x = tainted`` stores *tainted*, not the inner assignment,
    so the sink check has to look through the chain or it sees a node that
    carries no taint of its own.
    """
    cur = right
    for _ in range(16):
        if cur.type not in shapes.chains:
            return cur
        inner = cur.child_by_field_name("right")
        if inner is None:
            return cur
        cur = inner
    return cur  # pragma: no cover - defensive: assignment chains are not 16 deep


def iter_assignment_writes(left: tree_sitter.Node, right: tree_sitter.Node, shapes: AssignmentShapes) -> list[tuple[str, tree_sitter.Node]]:
    """Return ``(sink_name, written_value)`` for every sink-named target in *left*.

    Handles the three shapes a naive ``left`` lookup misses: a parenthesised
    target, an unpack target (paired positionally with the value list, falling
    back to the whole RHS when the shapes do not line up), and a chained RHS.
    """
    value = terminal_assigned_value(right, shapes)
    target = _peel(left, shapes.unwrap)
    if target.type not in shapes.patterns:
        name = assignment_sink_name(target, shapes.fields)
        return [(name, value)] if name is not None else []
    elements = list(target.named_children)
    values = list(value.named_children) if value.type in shapes.patterns or len(elements) == len(value.named_children) else []
    writes: list[tuple[str, tree_sitter.Node]] = []
    for index, element in enumerate(elements):
        name = assignment_sink_name(_peel(element, shapes.unwrap), shapes.fields)
        if name is not None:
            writes.append((name, values[index] if index < len(values) else value))
    return writes


@dataclass(frozen=True)
class SinkKinds:
    """How a sink receives its attacker-controlled payload.

    Most sinks take it as an **argument** (``exec(tainted)``) and need no entry
    here. Two shapes do not:

    * ``receiver`` - the payload is the receiver itself, so the call fires
      regardless of its arguments (``url.openConnection(proxy)`` is SSRF even
      when ``proxy`` is clean).
    * ``assignment`` - the sink is *written to* rather than called, so the
      injection is the write (``element.innerHTML = tainted``).

    ``assignment`` is deliberately its own list rather than being read from the
    flat ``sinks`` list: outside JavaScript those are FUNCTION names, so reusing
    them would report every field write called ``query`` / ``args`` / ``load``
    as an injection. A name must be declared here to be treated as a write-sink.

    Bundled into one value object so each tracker constructor stays within the
    project's ``max_arguments`` limit, exactly as :class:`PropertyContract` is.
    """

    receiver: frozenset[str] = frozenset()
    assignment: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PropertyContract:
    """Opt-in property-typed sanitiser / sink contract.

    ``sanitizer_properties`` maps a sanitiser name to the safety properties it
    establishes (e.g. ``escape -> {html_escaped}``); ``sink_properties`` maps a
    sink name to the single property it requires (e.g. ``execute -> sql_escaped``).
    A property-typed sanitiser clears a sink only when it establishes that sink's
    required property; a sink with no declared property is cleared only by the flat
    (universal) ``sanitizers`` list, never by a property-typed sanitiser. Both
    default empty, so the shipped behaviour is unchanged until a user opts in.
    """

    sanitizer_properties: Mapping[str, frozenset[str]] = field(default_factory=dict)
    sink_properties: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Make the two tables genuinely read-only.

        ``frozen=True`` only stops the *fields* being rebound - it says nothing
        about the mappings they point at, so a caller who kept a reference to
        the dict it passed in could still mutate a "frozen" contract and change
        the verdict of every tracker holding it. Copy into a
        :class:`~types.MappingProxyType` so the contract owns immutable tables.
        """
        object.__setattr__(self, "sanitizer_properties", MappingProxyType(dict(self.sanitizer_properties)))
        object.__setattr__(self, "sink_properties", MappingProxyType(dict(self.sink_properties)))

    def __hash__(self) -> int:
        """Hash by content.

        ``frozen=True`` auto-generates a ``__hash__`` that hashes the field
        tuple, and a mapping is unhashable - so the generated one raised
        ``TypeError`` for every contract, making an apparently-hashable value
        object unusable as a dict key or cache key. Hash the table *contents*
        instead (property values are ``frozenset`` / ``str``, both hashable).
        """
        return hash((frozenset(self.sanitizer_properties.items()), frozenset(self.sink_properties.items())))

    def clears(self, name: str | None, required_property: str | None) -> bool:
        """Return True if property-typed sanitiser *name* clears *required_property*.

        Only the property-typed table is consulted here; the flat/universal
        ``sanitizers`` list is checked by the tracker first. A property-typed
        sanitiser clears **only** a sink that declares a property this sanitiser
        establishes - it does NOT clear a sink with no declared property
        (``required_property is None``), because establishing e.g.
        ``html_escaped`` does not make a value safe for an ``eval`` / no-property
        sink. Use the flat ``sanitizers`` list for a universal clear.
        """
        established = self.sanitizer_properties.get(name) if name is not None else None
        if established is None:
            return False
        return required_property is not None and required_property in established

    def required_for(self, sink: str | None) -> str | None:
        """Return the property *sink* requires, or ``None`` when it declares none."""
        return self.sink_properties.get(sink) if sink is not None else None

    def all_properties(self) -> frozenset[str]:
        """Return every property named anywhere in the contract (the property universe).

        The trackers use this to label a tainted variable at assignment time: for
        each property here, they record whether the assigned value is already safe
        for it, so a later sink requiring that property clears correctly through
        the variable.
        """
        established: frozenset[str] = frozenset().union(*self.sanitizer_properties.values())
        # Only a property that some sanitiser establishes AND some sink requires can
        # ever change a verdict: ``required_property`` reaches the trackers solely via
        # ``required_for`` (sink_properties), and a property no sanitiser establishes
        # can never enter a cleared set. Anything else would cost a provably dead
        # worklist traversal per assignment, so intersect rather than union.
        return established & frozenset(self.sink_properties.values())
