"""complexity rule — cyclomatic complexity must not exceed max_complexity."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class ComplexityRule(BaseRule):
    """Reject functions whose cyclomatic complexity exceeds max_complexity.

    Cyclomatic complexity starts at 1 and increments for each branching
    decision point: if/elif, for, while, except, ternary, boolean operators,
    and comprehension conditions.
    """

    name = "complexity"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag functions whose cyclomatic complexity exceeds the configured maximum."""
        max_cc: int = self.config.get("max_complexity", 10)
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            cc = self._cyclomatic_complexity(node)
            if cc > max_cc:
                violations.append(
                    self._v(
                        filepath,
                        node.lineno,
                        f'Function "{node.name}" has cyclomatic complexity {cc}'
                        f" (max {max_cc}) — split into smaller functions",
                    )
                )
        return violations

    @staticmethod
    def _cyclomatic_complexity(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """Count cyclomatic complexity for *func* (McCabe 1976)."""
        cc = 1  # base complexity
        for node in ast.walk(func):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.IfExp)):
                cc += 1
            elif isinstance(node, ast.BoolOp):  # `and` / `or` chains
                cc += len(node.values) - 1
            elif isinstance(node, ast.comprehension) and node.ifs:
                cc += len(node.ifs)
        return cc
