"""SAFE401 — resource-lifecycle rule."""

from __future__ import annotations

import ast
from pathlib import Path

from safelint.rules.base import Rule, Violation


class ResourceLifecycleRule(Rule):
    """Flag bare ``open()`` calls that are not wrapped in a ``with`` statement."""

    name = "resource-lifecycle"
    code = "SAFE401"
    description = "Resources should be acquired through structured lifetimes"

    def check(self, path: Path, tree: ast.AST, source: str) -> list[Violation]:
        """Visit *tree* and return violations for unguarded ``open()`` calls."""
        visitor = _ResourceVisitor()
        visitor.visit(tree)
        return [
            self.violation("Wrap open() calls in a with statement", line=line, column=column)
            for line, column in visitor.unsafe_open_calls
        ]


class _ResourceVisitor(ast.NodeVisitor):
    """AST visitor that tracks open() calls and whether they are inside a with block."""

    def __init__(self) -> None:
        """Initialise counters and the list of unsafe open calls."""
        self.with_open_stack = 0
        self.unsafe_open_calls: list[tuple[int, int]] = []

    def visit_With(self, node: ast.With) -> None:
        """Increment the open-in-with counter while visiting the with block."""
        tracked = sum(
            1
            for item in node.items
            if isinstance(item.context_expr, ast.Call) and self._is_open_call(item.context_expr)
        )
        self.with_open_stack += tracked
        self.generic_visit(node)
        self.with_open_stack -= tracked

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        """Handle async with blocks the same as regular with blocks."""
        tracked = sum(
            1
            for item in node.items
            if isinstance(item.context_expr, ast.Call) and self._is_open_call(item.context_expr)
        )
        self.with_open_stack += tracked
        self.generic_visit(node)
        self.with_open_stack -= tracked

    def visit_Call(self, node: ast.Call) -> None:
        """Record bare open() calls found outside any with block."""
        if self._is_open_call(node) and self.with_open_stack == 0:
            self.unsafe_open_calls.append((node.lineno, node.col_offset))
        self.generic_visit(node)

    def _is_open_call(self, node: ast.Call) -> bool:
        """Return ``True`` if *node* is a direct call to the builtin ``open``."""
        return isinstance(node.func, ast.Name) and node.func.id == "open"
