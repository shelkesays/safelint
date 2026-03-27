"""SAFE201 — exception-handling rule."""

from __future__ import annotations

import ast
from pathlib import Path

from safelint.rules.base import Rule, Violation


class ErrorHandlingRule(Rule):
    """Flag bare excepts and pass-only handlers."""

    name = "error-handling"
    code = "SAFE201"
    description = "Exception handling should stay explicit and actionable"

    def check(self, path: Path, tree: ast.AST, source: str) -> list[Violation]:
        """Walk *tree* and report bare-except or pass-only handler violations."""
        violations: list[Violation] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if handler.type is None:
                    violations.append(
                        self.violation(
                            "Avoid bare except clauses", handler.lineno, handler.col_offset
                        )
                    )
                if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                    violations.append(
                        self.violation(
                            "Exception handlers must not swallow errors with pass",
                            handler.lineno,
                            handler.col_offset,
                        )
                    )
        return violations
