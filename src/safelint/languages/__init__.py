"""Language registry — maps file extensions to LanguageDefinition instances."""

from __future__ import annotations

from pathlib import Path

from safelint.languages._types import LanguageDefinition
from safelint.languages.python import PYTHON


_REGISTRY: dict[str, LanguageDefinition] = {}

for _lang in [PYTHON]:
    for _ext in _lang.file_extensions:
        _REGISTRY[_ext] = _lang


def get_language_for_file(filepath: str) -> LanguageDefinition | None:
    """Return the LanguageDefinition for *filepath* based on its extension, or None."""
    suffix = Path(filepath).suffix
    return _REGISTRY.get(suffix)


__all__ = ["PYTHON", "LanguageDefinition", "get_language_for_file"]
