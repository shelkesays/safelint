"""max_arguments rule - argument count (excluding self/cls) must not exceed max_args."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class MaxArgumentsRule(BaseRule):
    """Reject functions whose argument count (excluding self/cls) exceeds the limit."""

    name = "max_arguments"
    code = "SAFE103"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag any function with more arguments than max_args."""
        max_args: int = self.config.get("max_args", 7)
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args.args
            if args and args[0].arg in ("self", "cls"):
                args = args[1:]
            count = len(args) + len(node.args.kwonlyargs)
            if count > max_args:
                violations.append(
                    self._v(
                        filepath,
                        node.lineno,
                        f'Function "{node.name}" has {count} arguments (max {max_args})',
                    )
                )
        return violations
