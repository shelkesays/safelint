"""The run-level coverage numbers carried in a formatter's ``summary`` block.

Grouped into one value object rather than passed as loose keywords for two
reasons. It keeps ``format_json`` / ``format_sarif`` within the project's
``max_arguments`` bar, and more importantly it leaves the existing
``files_checked`` keyword exactly as it was: both formatters are exported in
``safelint.formatters.__all__`` and documented as pure functions for editor
integrations, so their signature is a public contract that additive work must
not reshape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class RunCoverage:
    """How much of what safelint reached was actually analysed.

    ``files_skipped`` counts the files that could not be turned into a usable
    tree, so no rule ran against them: they were reached but not analysed
    (#175). A caller cannot derive this from the violation list, because a
    ``SAFE000`` violation disappears under ``ignore = ["SAFE000"]`` while the
    coverage gap it stood for does not.

    ``by_language`` is a sparse ``{language name: files reached}`` map (#196).
    Sparse by choice: a language that contributed nothing is absent rather
    than present with a zero, so the common single-language case stays small
    and "absent means none read" is unambiguous. The names are the ones
    ``--language`` accepts.
    """

    files_skipped: int = 0
    by_language: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Take ownership of ``by_language`` as a read-only mapping.

        ``frozen=True`` only stops the field being rebound; it says nothing
        about the dict it points at, so a caller holding the mapping it passed
        in could otherwise still mutate a "frozen" value object. Same
        reasoning as ``PropertyContract`` in :mod:`safelint.analysis`.
        """
        object.__setattr__(self, "by_language", MappingProxyType(dict(self.by_language)))
