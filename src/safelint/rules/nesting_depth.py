"""nesting_depth rule - control-flow nesting must not exceed max_depth."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IF_STATEMENT,
    MATCH_STATEMENT,
    TRY_STATEMENT,
    WHILE_STATEMENT,
    WITH_STATEMENT,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
}

# Per-language node-type sets that count as one nesting step.
# Python: ``if`` / ``for`` / ``while`` / ``with`` / ``try`` / ``match``
# (PEP 634, Python 3.10+ - safelint requires 3.11+ so the construct is
# always available). ``elif_clause`` is *not* in this set - in
# Tree-sitter's Python grammar elif is its own node type, so it does
# not double-count like it did with ``ast``-module representation.
# JavaScript: same shape plus ``do_statement`` and ``switch_statement``;
# ``for_in_statement`` covers both ``for...in`` and ``for...of`` in
# tree-sitter-javascript.
# Java: ``if`` / ``for`` (C-style) / ``enhanced_for`` (for-each) /
# ``while`` / ``do`` / ``try`` / ``try_with_resources`` / ``switch_expression``
# (Java 14+ unified switch). ``synchronized_statement`` is *not* a
# nesting step in safelint's sense - it adds visual indentation but not
# a control-flow branch the way an ``if`` does.
_DEPTH_NODE_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({IF_STATEMENT, FOR_STATEMENT, WHILE_STATEMENT, WITH_STATEMENT, TRY_STATEMENT, MATCH_STATEMENT}),
    "javascript": frozenset({"if_statement", "for_statement", "for_in_statement", "while_statement", "do_statement", "switch_statement", "try_statement"}),
    "typescript": frozenset({"if_statement", "for_statement", "for_in_statement", "while_statement", "do_statement", "switch_statement", "try_statement"}),
    "java": frozenset({"if_statement", "for_statement", "enhanced_for_statement", "while_statement", "do_statement", "try_statement", "try_with_resources_statement", "switch_expression"}),
}


class NestingDepthRule(BaseRule):
    """Reject functions whose control-flow nesting exceeds the configured depth."""

    name = "nesting_depth"
    code = "SAFE102"
    language = ("python", "javascript", "typescript", "java")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function whose maximum control-flow nesting depth exceeds max_depth."""
        max_depth: int = self.config.get("max_depth", 2)
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        depth_types = _DEPTH_NODE_TYPES_BY_LANG[lang_name]
        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            depth = self._max_depth(node, function_types, depth_types)
            if depth > max_depth:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Function "{func_name}" nesting depth is {depth} (max {max_depth})',
                    )
                )
        return violations

    @staticmethod
    def _max_depth(root: tree_sitter.Node, function_types: frozenset[str], depth_types: frozenset[str]) -> int:
        """Return the maximum control-flow nesting depth rooted at *root*.

        Skips nested function definitions - those are scored as their
        own functions by the outer ``check_file`` walk and must not inflate
        the parent's nesting count.
        """
        max_seen = 0
        stack: list[tuple[tree_sitter.Node, int]] = [(root, 0)]
        while stack:  # nosafe: SAFE501
            node, depth = stack.pop()
            if node.type in depth_types:
                depth += 1
            max_seen = max(max_seen, depth)
            if node is not root and node.type in function_types:
                continue
            stack.extend((child, depth) for child in node.named_children)
        return max_seen
