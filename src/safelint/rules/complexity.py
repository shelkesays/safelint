"""complexity rule - cyclomatic complexity must not exceed max_complexity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    BOOLEAN_OPERATOR,
    CONDITIONAL_EXPRESSION,
    ELIF_CLAUSE,
    EXCEPT_CLAUSE,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IF_CLAUSE,
    IF_STATEMENT,
    WHILE_STATEMENT,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class ComplexityRule(BaseRule):
    """Reject functions whose cyclomatic complexity exceeds max_complexity."""

    name = "complexity"
    code = "SAFE104"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions whose cyclomatic complexity exceeds the configured maximum."""
        max_cc: int = self.config.get("max_complexity", 10)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            complexity = self._cyclomatic_complexity(node)
            if complexity > max_cc:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" has cyclomatic complexity {complexity} (max {max_cc}) - split into smaller functions',
                    )
                )
        return violations

    @staticmethod
    def _cyclomatic_complexity(func_node: tree_sitter.Node) -> int:
        """Count cyclomatic complexity for *func_node* (McCabe 1976).

        Skips nested function definitions — they are scored separately by the
        outer ``check_file`` walk so their branches must not also count toward
        the parent.
        """
        complexity = 1
        for node in walk(func_node, skip_types=(FUNCTION_DEF, ASYNC_FUNCTION_DEF)):
            if (
                node.type
                in (
                    IF_STATEMENT,
                    ELIF_CLAUSE,
                    FOR_STATEMENT,
                    WHILE_STATEMENT,
                    EXCEPT_CLAUSE,
                    CONDITIONAL_EXPRESSION,
                    IF_CLAUSE,
                )
                or node.type == BOOLEAN_OPERATOR
            ):
                complexity += 1
        return complexity
