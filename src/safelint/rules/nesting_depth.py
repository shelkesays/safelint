"""SAFE102 — nesting-depth rule."""

from __future__ import annotations

import ast
from pathlib import Path

from safelint.rules.base import Rule, Violation

CONTROL_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Match,
)


class NestingDepthRule(Rule):
    """Report functions whose control-flow nesting exceeds the configured depth."""

    name = "nesting-depth"
    code = "SAFE102"
    description = "Control flow should stay shallow"

    def check(self, path: Path, tree: ast.AST, source: str) -> list[Violation]:
        """Walk *tree* and flag functions that exceed the maximum nesting depth."""
        violations: list[Violation] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            depth = self._max_depth(node, 0)
            if depth > self.config.max_nesting_depth:
                violations.append(
                    self.violation(
                        f"Function '{node.name}' reaches nesting depth {depth};"
                        f" limit is {self.config.max_nesting_depth}",
                        node.lineno,
                        node.col_offset,
                    )
                )
        return violations

    def _max_depth(self, node: ast.AST, depth: int) -> int:
        """Recursively compute the maximum control-flow nesting depth under *node*."""
        child_depths = [depth]
        for child in ast.iter_child_nodes(node):
            next_depth = depth + 1 if isinstance(child, CONTROL_NODES) else depth
            child_depths.append(self._max_depth(child, next_depth))
        return max(child_depths)
