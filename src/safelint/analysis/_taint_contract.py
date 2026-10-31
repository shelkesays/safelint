"""The property-typed sanitiser contract shared by every taint tracker.

A single value object bundles the two opt-in property tables so each tracker's
constructor takes one extra argument rather than two (keeping every tracker
within the project's ``max_arguments`` limit). The contract is inert by default:
with both tables empty, a sanitiser clears every sink exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

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


# ---------------------------------------------------------------------------
# Taint ORIGIN (#158 item 3)
#
# Every tracker seeds taint from two very different places. A recognised SOURCE
# (``$_GET['q']``, ``request.args``, ``getenv``) is evidence that attacker data
# is in play. A function PARAMETER is not: seeding parameters is what makes an
# intra-procedural analysis useful, but it means any helper taking an argument
# and calling a dangerous builtin lights up whether or not a request can reach
# it. On FreeScout none of the ten SAFE801 findings had a traced source, yet
# every message read "Tainted variable", which states a fact the analysis does
# not have. Keeping the two apart is what lets the message say which it is.
# ---------------------------------------------------------------------------


def hit_key(call_node: tree_sitter.Node, var: str, sink: str) -> tuple[int, str, str]:
    """Return the identity of a sink hit: its call position, variable and sink.

    One owner for the key, because three things key off it - de-duplicating the
    double-analysed lambda bodies, recording which hits traced to a source, and
    looking that up again when the message is built. Position rather than node
    id so a hit found by two different trackers over the same tree matches.
    """
    return (call_node.start_byte, var, sink)


def traces_to_source(
    is_tainted: Callable[[tree_sitter.Node, str | None], bool],
    tainted: dict[str, frozenset[str]],
    source_seeded: set[str],
    value: tree_sitter.Node,
    required_property: str | None = None,
) -> bool:
    """Return True when *value*'s taint survives without parameter seeding.

    Asks the tracker's own ``is_tainted`` a second time with *tainted* narrowed
    to the variables whose taint came from a recognised source, so a path that
    rests only on a seeded parameter answers False. Direct source reads are
    unaffected: a tracker recognises ``$_GET['q']`` or ``getenv()`` from the
    syntax, not from the tainted set, so they still answer True with the set
    narrowed to nothing.

    Re-using ``is_tainted`` rather than growing a parallel worklist is
    deliberate: the origin answer then cannot drift from the taint answer, and a
    tracker that learns a new propagation shape gets it here for free. The
    narrowing is done in place and restored, because the callable closes over
    the very dict passed in; it only ever REMOVES entries, so a failure part way
    through cannot invent taint.
    """
    keep = dict(tainted)
    tainted.clear()
    tainted.update({name: cleared for name, cleared in keep.items() if name in source_seeded})
    try:
        return is_tainted(value, required_property)
    finally:
        tainted.clear()
        tainted.update(keep)


class ValueState(NamedTuple):
    """A value's taint status, plus whether that taint traced to a real source.

    Bundled rather than passed as two arguments so the seventeen assignment
    sites across the seven trackers keep handing ``_update_name`` a single
    value, and so a tracker cannot record the status while forgetting the
    origin.
    """

    status: frozenset[str] | None
    from_source: bool


#: A clean value: no taint, and therefore no origin.
CLEAN_STATE = ValueState(None, from_source=False)


def value_state(
    is_tainted: Callable[[tree_sitter.Node, str | None], bool],
    properties: frozenset[str],
    tainted: dict[str, frozenset[str]],
    source_seeded: set[str],
    value: tree_sitter.Node,
) -> ValueState:
    """Return *value*'s taint status and whether that taint traced to a source."""
    status = value_status(is_tainted, properties, value)
    if status is None:
        return CLEAN_STATE
    return ValueState(status, traces_to_source(is_tainted, tainted, source_seeded, value))


def combine_state(a: ValueState, b: ValueState) -> ValueState:
    """OR-combine two value states: tainted iff either is, sourced iff either is.

    Used for a read-modify-write (``x += tainted``), where x keeps whatever it
    already carried. A parameter-seeded x that is then appended a superglobal
    read is source-traced from that point on.
    """
    status = combine_status(a.status, b.status)
    return ValueState(status, status is not None and (a.from_source or b.from_source))


def combine_with_recorded(tainted: dict[str, frozenset[str]], source_seeded: set[str], name: str, state: ValueState) -> ValueState:
    """OR *state* with whatever is currently recorded for *name*."""
    return combine_state(ValueState(tainted.get(name), name in source_seeded), state)


class ScopeTaint(NamedTuple):
    """A finished scope's taint state, for seeding a closure defined inside it.

    The two halves travel together for the same reason :class:`ValueState`
    bundles its own: a closure capturing a source-tainted local must inherit
    that origin, or its sink hit would be worded as parameter-derived when a
    real source was traced through the capture.
    """

    tainted: dict[str, frozenset[str]]
    source_seeded: set[str]


#: An empty scope, for a closure whose enclosing function is not in the cache.
EMPTY_SCOPE = ScopeTaint({}, set())


def record_state(tainted: dict[str, frozenset[str]], source_seeded: set[str], name: str, state: ValueState) -> None:
    """Record *state* for variable *name*, status and origin together.

    Assignment OVERWRITES, so the origin is overwritten too: ``$x = $param``
    after ``$x = $_GET['q']`` leaves ``$x`` parameter-seeded, which is what the
    message should then say.
    """
    set_status(tainted, name, state.status)
    if state.status is not None and state.from_source:
        source_seeded.add(name)
    else:
        source_seeded.discard(name)


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

    def receiver_is_payload(self, name: str) -> bool:
        """Return True when *name* is declared to take its payload as the receiver.

        Membership in :attr:`receiver` is the ONLY evidence accepted, which is
        what the class docstring above has always described. Every tracker used
        to OR this with "...or the call has no arguments", on the reasoning that
        a no-argument call must be carrying its payload in the receiver. That
        inference does not hold, and #158 is the worked example:

            $messages = $folder->query()->unseen()->get();

        ``$folder`` is a webklex/php-imap folder, ``query()`` builds an IMAP
        search rather than SQL, and it takes no arguments - so there was neither
        an argument nor a receiver carrying user data, and the finding claimed
        an injection that cannot exist. 6 of 10 SAFE801 findings on FreeScout
        were this one shape.

        A no-argument call conveys no payload on its own. If a sink really does
        take its payload as the receiver, say so: ``receiver_sinks_<lang>``
        exists for exactly that, and Java's ``openConnection`` / ``openStream``
        defaults are the precedent.
        """
        return name in self.receiver


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
