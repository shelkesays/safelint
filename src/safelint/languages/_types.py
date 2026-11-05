"""Language definition dataclass - one instance per supported language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable

    import tree_sitter


@dataclass(frozen=True)
class LanguageDefinition:
    """All language-specific configuration needed by the engine and suppression parser.

    To add a new language: create a new module in this package, instantiate this
    dataclass, and register it in ``__init__.py``.
    """

    name: str
    file_extensions: frozenset[str]
    comment_node_type: str
    comment_prefix: str
    create_parser: Callable[[], tree_sitter.Parser]
    #: Appended to the ``SAFE000`` parse-error message instead of the generic
    #: "check syntax" advice. Set it only where a parse failure is routinely
    #: NOT the user's mistake, so the default message would misattribute
    #: blame; ``None`` keeps the generic wording.
    parse_error_hint: str | None = None


def preprocessor_parse_hint(display_name: str) -> str:
    """Return the parse-error hint for a language safelint reads unpreprocessed.

    Owned here rather than duplicated per module: C and C++ share the wording
    and only the display name differs. Tree-sitter sees the source as written,
    so an ``#if`` spanning part of a construct, or a macro standing in for a
    declarator, is not standalone-valid even though a compiler accepts the
    file after ``cpp`` has run. Measured on four real projects, this accounts
    for 25-54% of their files (see ``docs/languages/c.md``), which is why the
    generic "check syntax" advice is wrong often enough to be worth replacing.
    """
    return f"safelint parses {display_name} without running the preprocessor, so conditional compilation or a macro-expanded declaration can defeat the parser even when the code compiles"
