"""SAFE301 — module-level side-effects rule."""

from __future__ import annotations

import ast
from pathlib import Path

from safelint.rules.base import Rule, Violation

ALLOWED_MODULE_CALLS = {"__all__.append"}


class SideEffectsRule(Rule):
    """Flag executable statements at module scope that run on import."""

    name = "side-effects"
    code = "SAFE301"
    description = "Imports should not trigger executable behavior"

    def check(self, path: Path, tree: ast.AST, source: str) -> list[Violation]:
        """Inspect module-level statements and report disallowed side effects."""
        if self.config.allow_top_level_side_effects:
            return []

        violations: list[Violation] = []
        module = tree if isinstance(tree, ast.Module) else None
        if module is None:
            return violations

        for statement in module.body:
            if isinstance(
                statement,
                (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                continue
            if isinstance(statement, ast.If) and self._is_main_guard(statement.test):
                continue
            if isinstance(statement, ast.Assign) and isinstance(
                statement.value, (ast.Constant, ast.List, ast.Dict, ast.Set, ast.Tuple)
            ):
                continue
            if isinstance(statement, ast.AnnAssign) and isinstance(
                statement.value, (ast.Constant, type(None))
            ):
                continue
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                continue
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call_name = self._call_name(statement.value)
                if call_name in ALLOWED_MODULE_CALLS:
                    continue
            violations.append(
                self.violation(
                    "Avoid module-level executable side effects",
                    statement.lineno,
                    getattr(statement, "col_offset", 0),
                )
            )
        return violations

    def _call_name(self, node: ast.Call) -> str | None:
        """Return a dotted name string for *node* if it is a simple name or attribute call."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            return f"{node.func.value.id}.{node.func.attr}"
        return None

    def _is_main_guard(self, node: ast.AST) -> bool:
        """Return ``True`` if *node* is the ``__name__ == '__main__'`` guard expression."""
        if not isinstance(node, ast.Compare):
            return False
        if len(node.ops) != 1 or len(node.comparators) != 1:
            return False
        if not isinstance(node.ops[0], ast.Eq):
            return False

        left = node.left
        right = node.comparators[0]
        return (
            isinstance(left, ast.Name)
            and left.id == "__name__"
            and isinstance(right, ast.Constant)
            and right.value == "__main__"
        )
