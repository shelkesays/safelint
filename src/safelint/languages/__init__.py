"""Language registry — maps file extensions to LanguageDefinition instances."""

from __future__ import annotations

from pathlib import Path

from safelint.languages._types import LanguageDefinition
from safelint.languages.javascript import JAVASCRIPT
from safelint.languages.python import PYTHON
from safelint.languages.typescript import TSX, TYPESCRIPT


_REGISTRY: dict[str, LanguageDefinition] = {}

# Note: ``TYPESCRIPT`` and ``TSX`` share the same ``name="typescript"`` but
# use different Tree-sitter grammars — ``TYPESCRIPT`` handles ``.ts`` and
# ``.as`` (AssemblyScript, parsed by the standard TypeScript grammar),
# ``TSX`` handles ``.tsx``. The registry keys on file extension so each
# extension maps to its correct parser; rules' ``language`` tuples
# reference the logical name once and cover all three.
for _lang in [PYTHON, JAVASCRIPT, TYPESCRIPT, TSX]:
    for _ext in _lang.file_extensions:
        _REGISTRY[_ext] = _lang


def get_language_for_file(filepath: str) -> LanguageDefinition | None:
    """Return the LanguageDefinition for *filepath* based on its extension, or None."""
    suffix = Path(filepath).suffix
    return _REGISTRY.get(suffix)


def supported_extensions() -> frozenset[str]:
    """Return the set of file extensions that have a registered language.

    Each extension includes the leading dot, e.g. ``".py"``. Use this when
    discovering source files in a directory; pair with
    :func:`get_language_for_file` to retrieve the matching definition.
    """
    return frozenset(_REGISTRY)


__all__ = [
    "JAVASCRIPT",
    "PYTHON",
    "TSX",
    "TYPESCRIPT",
    "LanguageDefinition",
    "get_language_for_file",
    "supported_extensions",
]
