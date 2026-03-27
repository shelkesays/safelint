"""loop_safety rule - while True must have a break; others must use comparisons."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class UnboundedLoopRule(BaseRule):
    """Flag while loops that lack a provable bound."""

    name = "unbounded_loops"
    code = "SAFE501"

    def _check_while_node(self, filepath: str, node: ast.While) -> Violation | None:
        """Return a violation if *node* is an unbounded while loop, else None."""
        is_literal_true = isinstance(node.test, ast.Constant) and node.test.value is True
        if is_literal_true and not any(isinstance(n, ast.Break) for n in ast.walk(node)):
            return self._v(
                filepath, node.lineno, "while True loop has no break - potential infinite loop"
            )
        if not is_literal_true and not isinstance(node.test, ast.Compare):
            return self._v(
                filepath,
                node.lineno,
                "while loop condition is not a comparison - verify the loop is bounded",
            )
        return None

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag while loops that may be infinite."""
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.While):
                continue
            v = self._check_while_node(filepath, node)
            if v:
                violations.append(v)
        return violations
