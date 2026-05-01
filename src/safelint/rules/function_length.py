"""function_length rule - body must not exceed max_lines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import end_lineno, lineno, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class FunctionLengthRule(BaseRule):
    """Reject functions whose body exceeds the configured line limit."""

    name = "function_length"
    code = "SAFE101"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function or async function longer than max_lines."""
        max_lines: int = self.config.get("max_lines", 60)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            length = end_lineno(node) - lineno(node)
            if length > max_lines:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" is {length} lines (max {max_lines})',
                    )
                )
        return violations
