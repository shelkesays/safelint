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
