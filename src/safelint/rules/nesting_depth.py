"""nesting_depth rule - control-flow nesting must not exceed max_depth."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IF_STATEMENT,
    TRY_STATEMENT,
    WHILE_STATEMENT,
    WITH_STATEMENT,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation

_DEPTH_NODE_TYPES = frozenset(
    {
        IF_STATEMENT,
        FOR_STATEMENT,
        WHILE_STATEMENT,
        WITH_STATEMENT,
        TRY_STATEMENT,
    }
)


class NestingDepthRule(BaseRule):
    """Reject functions whose control-flow nesting exceeds the configured depth."""

    name = "nesting_depth"
    code = "SAFE102"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function whose maximum control-flow nesting depth exceeds max_depth."""
        max_depth: int = self.config.get("max_depth", 2)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            depth = self._max_depth(node)
            if depth > max_depth:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" nesting depth is {depth} (max {max_depth})',
                    )
                )
        return violations

    @staticmethod
    def _max_depth(root: tree_sitter.Node) -> int:
        """Return the maximum control-flow nesting depth rooted at *root*.

        Only the node types in _DEPTH_NODE_TYPES increment the depth counter.
        ``elif_clause`` is NOT in this set — in Tree-sitter's Python grammar,
        elif is its own node type, so it does not double-count like it did with
        the ast module's representation.

        Skips nested ``def`` / ``async def`` bodies — those are scored as their
        own functions by the outer ``check_file`` walk and must not inflate the
        parent's nesting count.
        """
        max_seen = 0
        stack: list[tuple[tree_sitter.Node, int]] = [(root, 0)]
        while stack:  # nosafe: SAFE501
            node, depth = stack.pop()
            if node.type in _DEPTH_NODE_TYPES:
                depth += 1
            max_seen = max(max_seen, depth)
            if node is not root and node.type in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            stack.extend((child, depth) for child in node.named_children)
        return max_seen
