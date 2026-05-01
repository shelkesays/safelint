from __future__ import annotations

import pytest
import tree_sitter
import tree_sitter_python


_PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())


@pytest.fixture()
def parse_python():
    """Return a function that parses Python source into a Tree-sitter Tree."""

    def _parse(source: str) -> tree_sitter.Tree:
        parser = tree_sitter.Parser(_PYTHON_LANGUAGE)
        return parser.parse(source.encode("utf-8"))

    return _parse
