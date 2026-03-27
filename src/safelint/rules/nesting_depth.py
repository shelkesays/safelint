"""nesting_depth rule — control-flow nesting must not exceed max_depth."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class NestingDepthRule(BaseRule):
    """Reject functions whose control-flow nesting exceeds the configured depth."""

    name = "nesting_depth"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag any function whose maximum control-flow nesting depth exceeds max_depth."""
        max_depth: int = self.config.get("max_depth", 2)
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            depth = self._max_depth(node)
            if depth > max_depth:
                violations.append(
                    self._v(
                        filepath,
                        node.lineno,
                        f'Function "{node.name}" nesting depth is {depth} (max {max_depth})',
                    )
                )
        return violations

    def _max_depth(self, node: ast.AST, current: int = 0) -> int:
        """Return the maximum control-flow nesting depth rooted at *node*.

        Control-flow nodes (if/for/while/with/try) increment the depth; all
        other nodes pass through unchanged. ``elif`` chains are represented in
        the AST as an ``ast.If`` inside the ``orelse`` of another ``ast.If``
        — they are at the *same* logical depth as the parent ``if``, so we
        pass ``current - 1`` to counteract the increment the child will add.
        """
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            current += 1
        depths = [current]
        for child in ast.iter_child_nodes(node):
            # elif: an If directly in the orelse of an If is logically
            # at the same depth as the parent if, not one level deeper.
            if isinstance(node, ast.If) and isinstance(child, ast.If) and child in node.orelse:
                depths.append(self._max_depth(child, current - 1))
            else:
                depths.append(self._max_depth(child, current))
        return max(depths)
