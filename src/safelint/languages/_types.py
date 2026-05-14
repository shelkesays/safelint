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
