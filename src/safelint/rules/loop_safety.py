"""loop_safety rule - while True must have a break; others must use comparisons."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    BREAK_STATEMENT,
    COMPARISON_OPERATOR,
    FOR_STATEMENT,
    FUNCTION_DEF,
    TRUE,
    WHILE_STATEMENT,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class UnboundedLoopRule(BaseRule):
    """Flag while loops that lack a provable bound."""

    name = "unbounded_loops"
    code = "SAFE501"

    # A break inside a nested loop, def, or async def belongs to that inner
    # construct, not to the outer while we're checking. Stop the walk at
    # those boundaries when looking for an exit.
    _BREAK_SCOPE_BOUNDARIES = (
        FOR_STATEMENT,
        WHILE_STATEMENT,
        FUNCTION_DEF,
        ASYNC_FUNCTION_DEF,
    )

    def _check_while_node(self, filepath: str, node: tree_sitter.Node) -> Violation | None:
        """Return a violation if *node* is an unbounded while loop, else None."""
        condition = node.child_by_field_name("condition")
        # ``while`` without a condition can't appear in valid Python; this
        # is a defensive guard in case the parser produces an ERROR node.
        if condition is None:  # pragma: no cover
            return None

        is_literal_true = condition.type == TRUE

        if is_literal_true:
            has_break = any(c.type == BREAK_STATEMENT for c in walk(node, skip_types=self._BREAK_SCOPE_BOUNDARIES))
            if not has_break:
                return self._make_violation(
                    filepath,
                    lineno(node),
                    "while True loop has no break - potential infinite loop",
                )
            return None

        if condition.type != COMPARISON_OPERATOR:
            return self._make_violation(
                filepath,
                lineno(node),
                "while loop condition is not a comparison - verify the loop is bounded",
            )
        return None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag while loops that may be infinite."""
        violations = []
        for node in walk(tree.root_node):
            if node.type != WHILE_STATEMENT:
                continue
            v = self._check_while_node(filepath, node)
            if v:
                violations.append(v)
        return violations
