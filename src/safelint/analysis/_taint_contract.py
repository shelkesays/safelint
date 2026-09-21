"""The property-typed sanitiser contract shared by every taint tracker.

A single value object bundles the two opt-in property tables so each tracker's
constructor takes one extra argument rather than two (keeping every tracker
within the project's ``max_arguments`` limit). The contract is inert by default:
with both tables empty, a sanitiser clears every sink exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class PropertyContract:
    """Opt-in property-typed sanitiser / sink contract.

    ``sanitizer_properties`` maps a sanitiser name to the safety properties it
    establishes (e.g. ``escape -> {html_escaped}``); ``sink_properties`` maps a
    sink name to the single property it requires (e.g. ``execute -> sql_escaped``).
    A property-typed sanitiser clears a sink only when it establishes that sink's
    required property; a sink with no declared property is cleared by any
    sanitiser. Both default empty, so the shipped behaviour is unchanged until a
    user opts in.
    """

    sanitizer_properties: Mapping[str, frozenset[str]] = field(default_factory=dict)
    sink_properties: Mapping[str, str] = field(default_factory=dict)

    def clears(self, name: str | None, required_property: str | None) -> bool:
        """Return True if property-typed sanitiser *name* clears *required_property*.

        Only the property-typed table is consulted here; the flat/universal
        ``sanitizers`` list is checked by the tracker first. A property-typed
        sanitiser clears when the sink declares no property (``required_property is
        None``) or the sanitiser establishes that property.
        """
        established = self.sanitizer_properties.get(name) if name is not None else None
        if established is None:
            return False
        return required_property is None or required_property in established

    def required_for(self, sink: str | None) -> str | None:
        """Return the property *sink* requires, or ``None`` when it declares none."""
        return self.sink_properties.get(sink) if sink is not None else None
