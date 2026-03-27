"""resource_lifecycle rule - tracked resource functions must use context managers."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class ResourceLifecycleRule(BaseRule):
    """Require tracked resource-acquisition calls to be wrapped in a with statement.

    If a tracked function (open, connect, session, …) is called outside a
    ``with`` block, the resource may not be released when an exception occurs.
    Configure ``tracked_functions`` and ``cleanup_patterns`` in .ai-safety.yaml.
    """

    name = "resource_lifecycle"
    code = "SAFE401"

    def _collect_guarded(self, tree: ast.AST, tracked: frozenset[str]) -> set[int]:
        """Return the set of node IDs for tracked calls already inside a with block."""
        return {
            id(item.context_expr)
            for node in ast.walk(tree)
            if isinstance(node, ast.With)
            for item in node.items
            if isinstance(item.context_expr, ast.Call)
            and self._call_name(item.context_expr.func) in tracked
        }

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag unguarded calls to tracked resource-acquisition functions."""
        tracked: frozenset[str] = frozenset(self.config.get("tracked_functions", ["open"]))
        cleanup: frozenset[str] = frozenset(self.config.get("cleanup_patterns", ["close"]))
        guarded = self._collect_guarded(tree, tracked)
        cleanup_str = " / ".join(sorted(cleanup))

        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = self._call_name(node.func)
            if not call_name or call_name not in tracked or id(node) in guarded:
                continue
            violations.append(
                self._v(
                    filepath,
                    node.lineno,
                    f'"{call_name}()" called outside a with block'
                    f" - use a context manager or ensure {cleanup_str} is called on all exit paths",
                )
            )
        return violations
