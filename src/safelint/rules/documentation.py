"""documentation rule — functions should contain at least one assert (heuristic)."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class MissingAssertionsRule(BaseRule):
    """Warn when a function contains no assert statements (disabled by default)."""

    name = "missing_assertions"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag functions that lack any assert statement."""
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(n, ast.Assert) for n in ast.walk(node)):
                violations.append(
                    self._v(
                        filepath,
                        node.lineno,
                        f'Function "{node.name}" has no assert statements',
                    )
                )
        return violations
