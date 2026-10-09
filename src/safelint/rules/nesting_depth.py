"""nesting_depth rule - control-flow nesting must not exceed max_depth."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages import c as _c
from safelint.languages import cpp as _cpp
from safelint.languages import go as _go
from safelint.languages import java as _java
from safelint.languages import javascript as _js
from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages import rust as _rust
from safelint.languages import typescript as _ts
from safelint.languages._node_utils import function_name_node, node_text, resolve_lang_name, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF}),
    "javascript": _js.FUNCTION_TYPES,
    "typescript": _js.FUNCTION_TYPES,
    "java": _java.FUNCTION_TYPES,
    "rust": _rust.FUNCTION_TYPES,
    "go": _go.FUNCTION_TYPES,
    "php": _php.FUNCTION_TYPES,
    "c": _c.FUNCTION_TYPES,
    "cpp": _cpp.FUNCTION_TYPES,
}

# Per-language node-type sets that count as one nesting step.
#
# Resource and error-handling wrappers - ``with`` / ``try`` / ``try``-with-resources
# - are NOT steps (#166). The rule exists to keep *decisions* shallow, which is
# what makes a function hard to follow and to test; those constructs add
# indentation without adding a branch. The asymmetry that settles it is
# actionability: a developer told to reduce nesting in
# ``with session: for x: if y:`` has no good move short of restructuring resource
# handling, which is a worse outcome than the nesting it was flagged for, so the
# finding was not actionable even when the count was literally correct.
#
# This extends a principle the table already applied rather than introducing one:
# Java's ``synchronized_statement`` and Rust's ``unsafe_block`` were excluded on
# exactly this reasoning. Rust, Go and C have no entry to remove - Rust and Go
# have no ``try`` block and C has no exceptions - so the set is now consistent
# across all nine languages. ``switch`` / ``match`` stay: they branch.
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
# Rust: ``if_expression`` / ``if_let_expression`` / ``for_expression`` /
# ``while_expression`` / ``while_let_expression`` / ``loop_expression``
# / ``match_expression``. Rust expressions are also statements (``if``
# can return a value); we count them as nesting steps regardless. The
# ``unsafe_block`` is NOT a nesting step - same rationale as Java's
# ``synchronized_statement``: visual indent without a control-flow branch.
# Go: ``for_statement`` is the only loop keyword (all four loop forms);
# ``if_statement``; the two switch forms (``expression_switch_statement``
# / ``type_switch_statement``); and ``select_statement``. The per-arm
# case nodes (``expression_case`` / ``type_case`` / ``communication_case``)
# are NOT counted - the switch / select that contains them is the single
# nesting step, the same way Python's ``match`` counts once rather than
# once per ``case_clause``.
# PHP: ``if_statement`` / ``while_statement`` / ``do_statement`` /
# ``for_statement`` / ``foreach_statement`` / ``switch_statement`` /
# ``try_statement`` / ``match_expression``. ``else_if_clause`` is NOT a
# nesting step - it is a child of its ``if_statement`` (which already
# counts once), so the elseif body sits at the if's depth+1, mirroring
# Python's ``elif_clause`` handling. ``case_statement`` /
# ``match_conditional_expression`` arms are not counted - the enclosing
# ``switch`` / ``match`` is the single step.
_DEPTH_NODE_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.IF_STATEMENT, _py.FOR_STATEMENT, _py.WHILE_STATEMENT, _py.MATCH_STATEMENT}),
    "javascript": frozenset({_js.IF_STATEMENT, _js.FOR_STATEMENT, _js.FOR_IN_STATEMENT, _js.WHILE_STATEMENT, _js.DO_STATEMENT, _js.SWITCH_STATEMENT}),
    "typescript": frozenset({_ts.IF_STATEMENT, _ts.FOR_STATEMENT, _ts.FOR_IN_STATEMENT, _ts.WHILE_STATEMENT, _ts.DO_STATEMENT, _ts.SWITCH_STATEMENT}),
    "java": frozenset(
        {
            _java.IF_STATEMENT,
            _java.FOR_STATEMENT,
            _java.ENHANCED_FOR_STATEMENT,
            _java.WHILE_STATEMENT,
            _java.DO_STATEMENT,
            _java.SWITCH_EXPRESSION,
        }
    ),
    "rust": frozenset({_rust.IF_EXPRESSION, _rust.IF_LET_EXPRESSION, _rust.FOR_EXPRESSION, _rust.WHILE_EXPRESSION, _rust.WHILE_LET_EXPRESSION, _rust.LOOP_EXPRESSION, _rust.MATCH_EXPRESSION}),
    "go": frozenset({_go.IF_STATEMENT, _go.FOR_STATEMENT, _go.EXPRESSION_SWITCH_STATEMENT, _go.TYPE_SWITCH_STATEMENT, _go.SELECT_STATEMENT}),
    "php": frozenset({_php.IF_STATEMENT, _php.WHILE_STATEMENT, _php.DO_STATEMENT, _php.FOR_STATEMENT, _php.FOREACH_STATEMENT, _php.SWITCH_STATEMENT, _php.MATCH_EXPRESSION}),
    # C: the four loop forms, ``if``, and ``switch``. No try/catch; ``goto``
    # targets are flat labels, not nesting.
    "c": frozenset({_c.IF_STATEMENT, _c.FOR_STATEMENT, _c.WHILE_STATEMENT, _c.DO_STATEMENT, _c.SWITCH_STATEMENT}),
    # C++: the C set plus the range-for. ``try_statement`` is NOT a step - see
    # the resource-wrapper note above.
    "cpp": frozenset({_cpp.IF_STATEMENT, _cpp.FOR_STATEMENT, _cpp.FOR_RANGE_LOOP, _cpp.WHILE_STATEMENT, _cpp.DO_STATEMENT, _cpp.SWITCH_STATEMENT}),
}


#: Per-language ``(if-node types, else-clause type)`` used to recognise an
#: ``else if`` continuation, which must not count as a nesting step.
#:
#: Python and PHP are absent: their grammars give ``elif`` / ``elseif`` a node
#: type of its own, which was never in the depth set, so they were already
#: correct. Every other language expresses the same idea structurally, in one of
#: two shapes - the continuation ``if`` sits under an ``else_clause``
#: (JavaScript, TypeScript, Rust, C, C++), or it is the ``alternative`` child of
#: the enclosing ``if`` (Java, Go). Both are handled by
#: :func:`_is_else_if_continuation`.
_ELSE_IF_SHAPES_BY_LANG: dict[str, tuple[frozenset[str], str | None]] = {
    "javascript": (frozenset({_js.IF_STATEMENT}), _js.ELSE_CLAUSE),
    "typescript": (frozenset({_ts.IF_STATEMENT}), _js.ELSE_CLAUSE),
    "java": (frozenset({_java.IF_STATEMENT}), None),
    "rust": (frozenset({_rust.IF_EXPRESSION}), _rust.ELSE_CLAUSE),
    "go": (frozenset({_go.IF_STATEMENT}), None),
    "c": (frozenset({_c.IF_STATEMENT}), _c.ELSE_CLAUSE),
    "cpp": (frozenset({_cpp.IF_STATEMENT}), _cpp.ELSE_CLAUSE),
}


def _is_else_if_continuation(node: tree_sitter.Node, if_types: frozenset[str], else_clause_type: str | None) -> bool:
    """Return True if *node* is the ``if`` half of an ``else if``, not a new level.

    A flat ``if / else if / else if`` chain branches once; counting each
    continuation as a further level over-counted a chain of N by N-1, so the most
    ordinary branching idiom reported as deeply nested on seven of the nine
    languages. Python and PHP were already right because their grammars name
    ``elif`` / ``elseif`` separately.

    Only ``if`` nodes qualify. ``else while (x);`` is legal C and *is* a real
    nesting step, so the node's own type is checked rather than just its parent's.
    An ``else { if (..) }`` written with braces also still counts: the inner
    ``if``'s parent is then the block, not the ``else``.
    """
    if node.type not in if_types:
        return False
    parent = node.parent
    if parent is None:
        return False
    if else_clause_type is not None and parent.type == else_clause_type:
        return True
    alternative = parent.child_by_field_name("alternative")
    return alternative is not None and alternative.id == node.id


class NestingDepthRule(BaseRule):
    """Reject functions whose control-flow nesting exceeds the configured depth."""

    name = "nesting_depth"
    code = "SAFE102"
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _go.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function whose maximum control-flow nesting depth exceeds max_depth."""
        max_depth: int = self.config.get("max_depth", 2)
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        depth_types = _DEPTH_NODE_TYPES_BY_LANG[lang_name]
        else_if_shape = _ELSE_IF_SHAPES_BY_LANG.get(lang_name)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            depth = self._max_depth(node, function_types, depth_types, else_if_shape)
            if depth > max_depth:
                name_node = function_name_node(node, lang_name)
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
    def _max_depth(
        root: tree_sitter.Node,
        function_types: frozenset[str],
        depth_types: frozenset[str],
        else_if_shape: tuple[frozenset[str], str | None] | None,
    ) -> int:
        """Return the maximum control-flow nesting depth rooted at *root*.

        Skips nested function definitions - those are scored as their
        own functions by the outer ``check_file`` walk and must not inflate
        the parent's nesting count. An ``else if`` continuation is not counted
        either; see :func:`_is_else_if_continuation`.
        """
        if_types, else_clause_type = else_if_shape if else_if_shape is not None else (frozenset(), None)
        max_seen = 0
        stack: list[tuple[tree_sitter.Node, int]] = [(root, 0)]
        while len(stack) > 0:
            node, depth = stack.pop()
            if node.type in depth_types and not _is_else_if_continuation(node, if_types, else_clause_type):
                depth += 1
            max_seen = max(max_seen, depth)
            if node is not root and node.type in function_types:
                continue
            stack.extend((child, depth) for child in node.named_children)
        return max_seen
