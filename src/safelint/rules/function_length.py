"""function_length rule - body must not exceed max_lines."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from safelint.rules.base import Violation


class FunctionLengthRule(BaseRule):
    """Reject functions whose body exceeds the configured line limit."""

    name = "function_length"
    code = "SAFE101"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag any function or async function longer than max_lines."""
        max_lines: int = self.config.get("max_lines", 60)
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.end_lineno is None:  # pragma: no cover
                continue
            length = node.end_lineno - node.lineno
            if length > max_lines:
                violations.append(
                    self._v(
                        filepath,
                        node.lineno,
                        f'Function "{node.name}" is {length} lines (max {max_lines})',
                    )
                )
        return violations
