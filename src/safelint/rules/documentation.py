"""documentation rule - functions should contain at least one assert (heuristic)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, walk
from safelint.languages.python import ASSERT_STATEMENT, ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class MissingAssertionsRule(BaseRule):
    """Warn when a function contains no assert statements (disabled by default)."""

    name = "missing_assertions"
    code = "SAFE601"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions that lack any assert statement."""
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            # Don't credit the outer function for asserts that live inside
            # nested defs — those are scored as their own functions.
            inner = walk(node, skip_types=(FUNCTION_DEF, ASYNC_FUNCTION_DEF))
            has_assert = any(c.type == ASSERT_STATEMENT for c in inner)
            if not has_assert:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Function "{func_name}" has no assert statements',
                    )
                )
        return violations
