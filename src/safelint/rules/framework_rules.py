"""Shared cross-framework rules (SAFE905-907) for the Python + PHP presets.

Each rule serves multiple frameworks and is gated purely by ``enabled`` (a
framework preset flips it on), exactly like the Spring 9xx rules. Detection is
language-family aware (Python vs PHP node shapes), not specific-framework aware:
the preset decides *whether* the rule runs, and the rule matches every known
pattern for the file's language. All tree walks are iterative (SAFE105).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_PY_DEBUG_KWARGS = frozenset({"debug", "reload"})
_PY_DEBUG_ATTR_NAMES = frozenset({"debug", "DEBUG"})
_PHP_STRING_TYPES = frozenset({_php.STRING, _php.ENCAPSED_STRING})


def _py_attr_last_name(attr: tree_sitter.Node) -> str:
    """Return the final identifier of a Python ``attribute`` (``app.debug`` -> ``debug``)."""
    kids = attr.named_children
    return node_text(kids[-1]) if kids else ""


class DebugModeEnabledRule(BaseRule):
    """Flag a framework debug / reload flag hard-enabled in code (SAFE905).

    Debug mode in production leaks stack traces, settings, and (Flask/Werkzeug)
    an interactive console. Detected patterns:

    * **Python**: ``DEBUG = True`` (Django settings), ``app.debug = True`` /
      ``app.run(debug=True)`` (Flask), ``uvicorn.run(..., reload=True)`` /
      ``debug=True`` (FastAPI/ASGI).
    * **PHP**: a config array entry ``'app.debug' => true`` (Laravel
      ``config([...])``). ``.env`` files are not parsed, so this is code-only -
      a documented limit.

    Serves django / flask / fastapi (python) + laravel (php); default-disabled,
    enabled by those presets.
    """

    name = "debug_mode_enabled"
    code = "SAFE905"
    language = ("python", "php")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Dispatch to the per-language detector for *filepath*."""
        lang = resolve_lang_name(filepath)
        if lang == "python":
            return self._check_python(filepath, tree)
        if lang == "php":
            return self._check_php(filepath, tree)
        return []  # pragma: no cover - engine dispatch already filters by language tuple

    def _check_python(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            message = self._python_hit(node)
            if message is not None:
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    def _python_hit(self, node: tree_sitter.Node) -> str | None:
        if node.type == _py.ASSIGNMENT:
            return self._python_assignment_hit(node)
        if node.type == _py.KEYWORD_ARGUMENT:
            return self._python_kwarg_hit(node)
        return None

    def _python_assignment_hit(self, node: tree_sitter.Node) -> str | None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or right.type != _py.TRUE:
            return None
        if left.type == _py.IDENTIFIER and node_text(left) == "DEBUG":
            return "DEBUG = True - never enable debug mode in production (Django)"
        if left.type == _py.ATTRIBUTE and _py_attr_last_name(left) in _PY_DEBUG_ATTR_NAMES:
            return f"debug mode enabled via {node_text(left)} = True - disable it in production"
        return None

    def _python_kwarg_hit(self, node: tree_sitter.Node) -> str | None:
        kids = node.named_children
        if len(kids) < 2 or kids[1].type != _py.TRUE:
            return None
        name = node_text(kids[0])
        if name in _PY_DEBUG_KWARGS:
            return f"{name}=True enables debug/reload mode - do not enable it in production"
        return None

    def _check_php(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != _php.ARRAY_ELEMENT_INITIALIZER:
                continue
            message = self._php_hit(node)
            if message is not None:
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    def _php_hit(self, node: tree_sitter.Node) -> str | None:
        kids = node.named_children
        if len(kids) < 2 or kids[0].type not in _PHP_STRING_TYPES or kids[1].type != _php.BOOLEAN:
            return None
        if node_text(kids[1]).lower() != "true":
            return None
        key = node_text(kids[0]).strip("'\"").lower()
        if key.endswith("debug"):
            return f"config '{key}' => true enables debug mode - disable it in production"
        return None
