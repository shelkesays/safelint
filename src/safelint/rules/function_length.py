"""SAFE101 — function-length rule."""

from __future__ import annotations

import ast
from pathlib import Path

from safelint.rules.base import Rule, Violation


class FunctionLengthRule(Rule):
    """Report functions that exceed the configured line-count limit."""

    name = "function-length"
    code = "SAFE101"
    description = "Functions should remain short and reviewable"

    def check(self, path: Path, tree: ast.AST, source: str) -> list[Violation]:
        """Walk *tree* and flag any function longer than the configured limit."""
        violations: list[Violation] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            length = end - start + 1
            if length > self.config.max_function_lines:
                violations.append(
                    self.violation(
                        f"Function '{node.name}' spans {length} lines;"
                        f" limit is {self.config.max_function_lines}",
                        start,
                        getattr(node, "col_offset", 0),
                    )
                )
        return violations
