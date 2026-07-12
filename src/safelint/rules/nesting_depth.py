"""nesting_depth rule - control-flow nesting must not exceed max_depth."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import function_name_node, node_text, resolve_lang_name, walk
from safelint.languages.c import DO_STATEMENT as _C_DO_STATEMENT
from safelint.languages.c import EXTRA_NAME as _C_EXTRA_NAME
from safelint.languages.c import FOR_STATEMENT as _C_FOR_STATEMENT
from safelint.languages.c import FUNCTION_TYPES as _C_FUNCTION_TYPES
from safelint.languages.c import IF_STATEMENT as _C_IF_STATEMENT
from safelint.languages.c import SWITCH_STATEMENT as _C_SWITCH_STATEMENT
from safelint.languages.c import WHILE_STATEMENT as _C_WHILE_STATEMENT
from safelint.languages.cpp import DO_STATEMENT as _CPP_DO_STATEMENT
from safelint.languages.cpp import EXTRA_NAME as _CPP_EXTRA_NAME
from safelint.languages.cpp import FOR_RANGE_LOOP as _CPP_FOR_RANGE_LOOP
from safelint.languages.cpp import FOR_STATEMENT as _CPP_FOR_STATEMENT
from safelint.languages.cpp import FUNCTION_TYPES as _CPP_FUNCTION_TYPES
from safelint.languages.cpp import IF_STATEMENT as _CPP_IF_STATEMENT
from safelint.languages.cpp import SWITCH_STATEMENT as _CPP_SWITCH_STATEMENT
from safelint.languages.cpp import TRY_STATEMENT as _CPP_TRY_STATEMENT
from safelint.languages.cpp import WHILE_STATEMENT as _CPP_WHILE_STATEMENT
from safelint.languages.go import EXPRESSION_SWITCH_STATEMENT as _GO_EXPRESSION_SWITCH_STATEMENT
from safelint.languages.go import EXTRA_NAME as _GO_EXTRA_NAME
from safelint.languages.go import FOR_STATEMENT as _GO_FOR_STATEMENT
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.go import IF_STATEMENT as _GO_IF_STATEMENT
from safelint.languages.go import SELECT_STATEMENT as _GO_SELECT_STATEMENT
from safelint.languages.go import TYPE_SWITCH_STATEMENT as _GO_TYPE_SWITCH_STATEMENT
from safelint.languages.java import DO_STATEMENT as _JAVA_DO_STATEMENT
from safelint.languages.java import ENHANCED_FOR_STATEMENT as _JAVA_ENHANCED_FOR_STATEMENT
from safelint.languages.java import EXTRA_NAME as _JAVA_EXTRA_NAME
from safelint.languages.java import FOR_STATEMENT as _JAVA_FOR_STATEMENT
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.java import IF_STATEMENT as _JAVA_IF_STATEMENT
from safelint.languages.java import SWITCH_EXPRESSION as _JAVA_SWITCH_EXPRESSION
from safelint.languages.java import TRY_STATEMENT as _JAVA_TRY_STATEMENT
from safelint.languages.java import TRY_WITH_RESOURCES_STATEMENT as _JAVA_TRY_WITH_RESOURCES_STATEMENT
from safelint.languages.java import WHILE_STATEMENT as _JAVA_WHILE_STATEMENT
from safelint.languages.javascript import DO_STATEMENT as _JS_DO_STATEMENT
from safelint.languages.javascript import EXTRA_NAME as _JS_EXTRA_NAME
from safelint.languages.javascript import FOR_IN_STATEMENT as _JS_FOR_IN_STATEMENT
from safelint.languages.javascript import FOR_STATEMENT as _JS_FOR_STATEMENT
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.javascript import IF_STATEMENT as _JS_IF_STATEMENT
from safelint.languages.javascript import SWITCH_STATEMENT as _JS_SWITCH_STATEMENT
from safelint.languages.javascript import TRY_STATEMENT as _JS_TRY_STATEMENT
from safelint.languages.javascript import WHILE_STATEMENT as _JS_WHILE_STATEMENT
from safelint.languages.php import DO_STATEMENT as _PHP_DO_STATEMENT
from safelint.languages.php import EXTRA_NAME as _PHP_EXTRA_NAME
from safelint.languages.php import FOR_STATEMENT as _PHP_FOR_STATEMENT
from safelint.languages.php import FOREACH_STATEMENT as _PHP_FOREACH_STATEMENT
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
from safelint.languages.php import IF_STATEMENT as _PHP_IF_STATEMENT
from safelint.languages.php import MATCH_EXPRESSION as _PHP_MATCH_EXPRESSION
from safelint.languages.php import SWITCH_STATEMENT as _PHP_SWITCH_STATEMENT
from safelint.languages.php import TRY_STATEMENT as _PHP_TRY_STATEMENT
from safelint.languages.php import WHILE_STATEMENT as _PHP_WHILE_STATEMENT
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    EXTRA_NAME,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IF_STATEMENT,
    MATCH_STATEMENT,
    TRY_STATEMENT,
    WHILE_STATEMENT,
    WITH_STATEMENT,
)
from safelint.languages.rust import EXTRA_NAME as _RUST_EXTRA_NAME
from safelint.languages.rust import FOR_EXPRESSION as _RUST_FOR_EXPRESSION
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.languages.rust import IF_EXPRESSION as _RUST_IF_EXPRESSION
from safelint.languages.rust import IF_LET_EXPRESSION as _RUST_IF_LET_EXPRESSION
from safelint.languages.rust import LOOP_EXPRESSION as _RUST_LOOP_EXPRESSION
from safelint.languages.rust import MATCH_EXPRESSION as _RUST_MATCH_EXPRESSION
from safelint.languages.rust import WHILE_EXPRESSION as _RUST_WHILE_EXPRESSION
from safelint.languages.rust import WHILE_LET_EXPRESSION as _RUST_WHILE_LET_EXPRESSION
from safelint.languages.typescript import DO_STATEMENT as _TS_DO_STATEMENT
from safelint.languages.typescript import EXTRA_NAME as _TS_EXTRA_NAME
from safelint.languages.typescript import FOR_IN_STATEMENT as _TS_FOR_IN_STATEMENT
from safelint.languages.typescript import FOR_STATEMENT as _TS_FOR_STATEMENT
from safelint.languages.typescript import IF_STATEMENT as _TS_IF_STATEMENT
from safelint.languages.typescript import SWITCH_STATEMENT as _TS_SWITCH_STATEMENT
from safelint.languages.typescript import TRY_STATEMENT as _TS_TRY_STATEMENT
from safelint.languages.typescript import WHILE_STATEMENT as _TS_WHILE_STATEMENT
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
    "rust": _RUST_FUNCTION_TYPES,
    "go": _GO_FUNCTION_TYPES,
    "php": _PHP_FUNCTION_TYPES,
    "c": _C_FUNCTION_TYPES,
    "cpp": _CPP_FUNCTION_TYPES,
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
    "python": frozenset({IF_STATEMENT, FOR_STATEMENT, WHILE_STATEMENT, WITH_STATEMENT, TRY_STATEMENT, MATCH_STATEMENT}),
    "javascript": frozenset({_JS_IF_STATEMENT, _JS_FOR_STATEMENT, _JS_FOR_IN_STATEMENT, _JS_WHILE_STATEMENT, _JS_DO_STATEMENT, _JS_SWITCH_STATEMENT, _JS_TRY_STATEMENT}),
    "typescript": frozenset({_TS_IF_STATEMENT, _TS_FOR_STATEMENT, _TS_FOR_IN_STATEMENT, _TS_WHILE_STATEMENT, _TS_DO_STATEMENT, _TS_SWITCH_STATEMENT, _TS_TRY_STATEMENT}),
    "java": frozenset(
        {
            _JAVA_IF_STATEMENT,
            _JAVA_FOR_STATEMENT,
            _JAVA_ENHANCED_FOR_STATEMENT,
            _JAVA_WHILE_STATEMENT,
            _JAVA_DO_STATEMENT,
            _JAVA_TRY_STATEMENT,
            _JAVA_TRY_WITH_RESOURCES_STATEMENT,
            _JAVA_SWITCH_EXPRESSION,
        }
    ),
    "rust": frozenset({_RUST_IF_EXPRESSION, _RUST_IF_LET_EXPRESSION, _RUST_FOR_EXPRESSION, _RUST_WHILE_EXPRESSION, _RUST_WHILE_LET_EXPRESSION, _RUST_LOOP_EXPRESSION, _RUST_MATCH_EXPRESSION}),
    "go": frozenset({_GO_IF_STATEMENT, _GO_FOR_STATEMENT, _GO_EXPRESSION_SWITCH_STATEMENT, _GO_TYPE_SWITCH_STATEMENT, _GO_SELECT_STATEMENT}),
    "php": frozenset({_PHP_IF_STATEMENT, _PHP_WHILE_STATEMENT, _PHP_DO_STATEMENT, _PHP_FOR_STATEMENT, _PHP_FOREACH_STATEMENT, _PHP_SWITCH_STATEMENT, _PHP_TRY_STATEMENT, _PHP_MATCH_EXPRESSION}),
    # C: the four loop forms, ``if``, and ``switch``. No try/catch; ``goto``
    # targets are flat labels, not nesting.
    "c": frozenset({_C_IF_STATEMENT, _C_FOR_STATEMENT, _C_WHILE_STATEMENT, _C_DO_STATEMENT, _C_SWITCH_STATEMENT}),
    # C++: the C set plus ``try_statement`` (a try block nests its body).
    "cpp": frozenset({_CPP_IF_STATEMENT, _CPP_FOR_STATEMENT, _CPP_FOR_RANGE_LOOP, _CPP_WHILE_STATEMENT, _CPP_DO_STATEMENT, _CPP_SWITCH_STATEMENT, _CPP_TRY_STATEMENT}),
}


class NestingDepthRule(BaseRule):
    """Reject functions whose control-flow nesting exceeds the configured depth."""

    name = "nesting_depth"
    code = "SAFE102"
    language = (EXTRA_NAME, _JS_EXTRA_NAME, _TS_EXTRA_NAME, _JAVA_EXTRA_NAME, _RUST_EXTRA_NAME, _GO_EXTRA_NAME, _PHP_EXTRA_NAME, _C_EXTRA_NAME, _CPP_EXTRA_NAME)

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
    def _max_depth(root: tree_sitter.Node, function_types: frozenset[str], depth_types: frozenset[str]) -> int:
        """Return the maximum control-flow nesting depth rooted at *root*.

        Skips nested function definitions - those are scored as their
        own functions by the outer ``check_file`` walk and must not inflate
        the parent's nesting count.
        """
        max_seen = 0
        stack: list[tuple[tree_sitter.Node, int]] = [(root, 0)]
        while len(stack) > 0:
            node, depth = stack.pop()
            if node.type in depth_types:
                depth += 1
            max_seen = max(max_seen, depth)
            if node is not root and node.type in function_types:
                continue
            stack.extend((child, depth) for child in node.named_children)
        return max_seen
