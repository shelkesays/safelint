"""complexity rule - cyclomatic complexity must not exceed max_complexity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import function_name_node, node_text, resolve_lang_name, walk
from safelint.languages.c import AMP_AMP as _C_AMP_AMP
from safelint.languages.c import BINARY_EXPRESSION as _C_BINARY_EXPRESSION
from safelint.languages.c import CASE_STATEMENT as _C_CASE_STATEMENT
from safelint.languages.c import DO_STATEMENT as _C_DO_STATEMENT
from safelint.languages.c import EXTRA_NAME as _C_EXTRA_NAME
from safelint.languages.c import FUNCTION_TYPES as _C_FUNCTION_TYPES
from safelint.languages.c import PIPE_PIPE as _C_PIPE_PIPE
from safelint.languages.cpp import CATCH_CLAUSE as _CPP_CATCH_CLAUSE
from safelint.languages.cpp import EXTRA_NAME as _CPP_EXTRA_NAME
from safelint.languages.cpp import FUNCTION_TYPES as _CPP_FUNCTION_TYPES
from safelint.languages.go import AMP_AMP as _GO_AMP_AMP
from safelint.languages.go import COMMUNICATION_CASE as _GO_COMMUNICATION_CASE
from safelint.languages.go import EXPRESSION_CASE as _GO_EXPRESSION_CASE
from safelint.languages.go import EXTRA_NAME as _GO_EXTRA_NAME
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.go import PIPE_PIPE as _GO_PIPE_PIPE
from safelint.languages.go import TYPE_CASE as _GO_TYPE_CASE
from safelint.languages.java import AMP_AMP as _JAVA_AMP_AMP
from safelint.languages.java import ENHANCED_FOR_STATEMENT as _JAVA_ENHANCED_FOR_STATEMENT
from safelint.languages.java import EXTRA_NAME as _JAVA_EXTRA_NAME
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.java import PIPE_PIPE as _JAVA_PIPE_PIPE
from safelint.languages.java import SWITCH_BLOCK_STATEMENT_GROUP as _JAVA_SWITCH_BLOCK_STATEMENT_GROUP
from safelint.languages.java import SWITCH_RULE as _JAVA_SWITCH_RULE
from safelint.languages.java import TERNARY_EXPRESSION as _JAVA_TERNARY_EXPRESSION
from safelint.languages.javascript import EXTRA_NAME as _JS_EXTRA_NAME
from safelint.languages.javascript import FOR_IN_STATEMENT as _JS_FOR_IN_STATEMENT
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.javascript import SWITCH_CASE as _JS_SWITCH_CASE
from safelint.languages.php import AMP_AMP as _PHP_AMP_AMP
from safelint.languages.php import AND_KW as _PHP_AND_KW
from safelint.languages.php import ELSE_IF_CLAUSE as _PHP_ELSE_IF_CLAUSE
from safelint.languages.php import EXTRA_NAME as _PHP_EXTRA_NAME
from safelint.languages.php import FOREACH_STATEMENT as _PHP_FOREACH_STATEMENT
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
from safelint.languages.php import MATCH_CONDITIONAL_EXPRESSION as _PHP_MATCH_CONDITIONAL_EXPRESSION
from safelint.languages.php import OR_KW as _PHP_OR_KW
from safelint.languages.php import PIPE_PIPE as _PHP_PIPE_PIPE
from safelint.languages.php import QQ as _PHP_QQ
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    BOOLEAN_OPERATOR,
    CONDITIONAL_EXPRESSION,
    ELIF_CLAUSE,
    EXCEPT_CLAUSE,
    EXTRA_NAME,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IF_CLAUSE,
    IF_STATEMENT,
    WHILE_STATEMENT,
)
from safelint.languages.rust import EXTRA_NAME as _RUST_EXTRA_NAME
from safelint.languages.rust import FOR_EXPRESSION as _RUST_FOR_EXPRESSION
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.languages.rust import IF_EXPRESSION as _RUST_IF_EXPRESSION
from safelint.languages.rust import LOOP_EXPRESSION as _RUST_LOOP_EXPRESSION
from safelint.languages.rust import MATCH_ARM as _RUST_MATCH_ARM
from safelint.languages.rust import TRY_EXPRESSION as _RUST_TRY_EXPRESSION
from safelint.languages.rust import WHILE_EXPRESSION as _RUST_WHILE_EXPRESSION
from safelint.languages.typescript import EXTRA_NAME as _TS_EXTRA_NAME
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

# Node types that add 1 to cyclomatic complexity. Both languages: every
# ``if`` / ``for`` / ``while`` / ``except``/``catch`` / ternary adds a
# branch. Python also counts ``elif_clause`` (separate node), comprehension
# ``if_clause``, and ``boolean_operator`` (a single node containing chained
# ``and`` / ``or``). JavaScript uses ``binary_expression`` for ``&&`` /
# ``||`` / ``??`` and the operator must be inspected - see the special
# branch in ``_cyclomatic_complexity``. TypeScript (``.ts`` / ``.tsx`` /
# ``.as``) reuses the JavaScript branching set - the type system doesn't
# introduce new branches.
# Java: similar shape to JS, with two switch-case node types because
# Java 14+ added arrow-form switch alongside the colon-form. Each
# ``switch_block_statement_group`` (old colon form, ``case X: stmt``) and
# each ``switch_rule`` (new arrow form, ``case X -> stmt``) counts as
# one branch. ``&&`` / ``||`` add complexity inside ``binary_expression``
# (same operator-filter pattern as JS); Java does not have ``??``.
_JS_BRANCHING_TYPES = frozenset(
    {
        IF_STATEMENT,
        FOR_STATEMENT,
        _JS_FOR_IN_STATEMENT,  # also covers ``for...of`` in tree-sitter-javascript
        WHILE_STATEMENT,
        _C_DO_STATEMENT,
        _JS_SWITCH_CASE,
        _CPP_CATCH_CLAUSE,
        _JAVA_TERNARY_EXPRESSION,
    }
)
_JAVA_BRANCHING_TYPES = frozenset(
    {
        IF_STATEMENT,
        FOR_STATEMENT,
        _JAVA_ENHANCED_FOR_STATEMENT,
        WHILE_STATEMENT,
        _C_DO_STATEMENT,
        _JAVA_SWITCH_BLOCK_STATEMENT_GROUP,  # colon-form ``case X: stmt;``
        _JAVA_SWITCH_RULE,  # arrow-form ``case X -> stmt;`` (Java 14+)
        _CPP_CATCH_CLAUSE,
        _JAVA_TERNARY_EXPRESSION,
    }
)
# Rust: ``if`` / ``for`` / ``while`` / ``loop`` are control-flow
# constructs in their own right. ``if let`` and ``while let`` parse as
# the standard ``if_expression`` / ``while_expression`` with a
# ``let_condition`` child (tree-sitter-rust 0.24.x), so they are
# covered without a separate node type. ``match_arm`` plays the same
# role as Java's switch_block_statement_group / switch_rule - one
# branch per arm. ``try_expression`` is the ``?`` operator
# (``foo()?``); it is conditional early-return, so it counts as one
# branch (analogous to ``catch_clause`` in Java). Rust has no
# ternary; ``if`` is itself an expression and is already counted.
_RUST_BRANCHING_TYPES = frozenset(
    {
        _RUST_IF_EXPRESSION,
        _RUST_FOR_EXPRESSION,
        _RUST_WHILE_EXPRESSION,
        _RUST_LOOP_EXPRESSION,
        _RUST_MATCH_ARM,
        _RUST_TRY_EXPRESSION,
    }
)
# Go: ``if`` / ``for`` (the only loop keyword - all four forms parse as
# ``for_statement``) are control-flow branches. Each switch / select arm
# adds one branch: ``expression_case`` (value switch), ``type_case``
# (type switch), and ``communication_case`` (select). The ``default_case``
# is deliberately excluded - it is the fall-through "else" and adds no
# decision, the same way Python's bare ``else`` is not counted. ``&&`` /
# ``||`` add complexity inside ``binary_expression`` (operator filter
# below); Go has no ternary and no ``??``.
_GO_BRANCHING_TYPES = frozenset(
    {
        IF_STATEMENT,
        FOR_STATEMENT,
        _GO_EXPRESSION_CASE,
        _GO_TYPE_CASE,
        _GO_COMMUNICATION_CASE,
    }
)
# PHP: ``if_statement`` plus ``else_if_clause`` (PHP's ``elseif`` is a
# distinct node, counted like Python's ``elif_clause``); the four loop
# forms (``while`` / ``do`` / ``for`` / ``foreach``); each switch arm
# (``case_statement`` - ``default_statement`` excluded as the
# fall-through else) and each ``match`` arm
# (``match_conditional_expression`` - ``match_default_expression``
# excluded); ``catch_clause``; and the ternary
# (``conditional_expression``). ``&&`` / ``||`` / ``??`` plus the
# keyword forms ``and`` / ``or`` add complexity inside
# ``binary_expression`` (operator filter below).
_PHP_BRANCHING_TYPES = frozenset(
    {
        IF_STATEMENT,
        _PHP_ELSE_IF_CLAUSE,
        WHILE_STATEMENT,
        _C_DO_STATEMENT,
        FOR_STATEMENT,
        _PHP_FOREACH_STATEMENT,
        _C_CASE_STATEMENT,
        _PHP_MATCH_CONDITIONAL_EXPRESSION,
        _CPP_CATCH_CLAUSE,
        CONDITIONAL_EXPRESSION,
    }
)
# C: ``if_statement``; the four loop forms (``while`` / ``do`` / ``for``);
# each switch arm (``case_statement`` - this node covers both ``case X:`` and
# the fall-through ``default:``, a minor over-count accepted for the
# node-type-only approach); and the ternary (``conditional_expression``).
# ``&&`` / ``||`` add complexity inside ``binary_expression`` (operator
# filter below). C has no try/catch, so no catch-arm node.
_C_BRANCHING_TYPES = frozenset(
    {
        IF_STATEMENT,
        WHILE_STATEMENT,
        _C_DO_STATEMENT,
        FOR_STATEMENT,
        _C_CASE_STATEMENT,
        CONDITIONAL_EXPRESSION,
    }
)
# C++: the C set plus ``catch_clause`` (each ``catch`` is a branch).
_CPP_BRANCHING_TYPES = _C_BRANCHING_TYPES | frozenset({_CPP_CATCH_CLAUSE, "for_range_loop"})
_BRANCHING_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset(
        {
            IF_STATEMENT,
            ELIF_CLAUSE,
            FOR_STATEMENT,
            WHILE_STATEMENT,
            EXCEPT_CLAUSE,
            CONDITIONAL_EXPRESSION,
            IF_CLAUSE,
            BOOLEAN_OPERATOR,
        }
    ),
    "javascript": _JS_BRANCHING_TYPES,
    "typescript": _JS_BRANCHING_TYPES,
    "java": _JAVA_BRANCHING_TYPES,
    "rust": _RUST_BRANCHING_TYPES,
    "go": _GO_BRANCHING_TYPES,
    "php": _PHP_BRANCHING_TYPES,
    "c": _C_BRANCHING_TYPES,
    "cpp": _CPP_BRANCHING_TYPES,
}

# JavaScript: ``binary_expression`` covers many operators (``+``, ``>``,
# etc.) that are NOT branches. Only short-circuiting / null-coalescing
# operators add complexity.
_JS_BRANCHING_BINARY_OPS = frozenset({_C_AMP_AMP, _C_PIPE_PIPE, _PHP_QQ})

# Java: same idea, no ``??`` (Java uses ``Optional`` / ``Objects.requireNonNullElse``
# for the null-coalescing role; both call expressions, not operators).
_JAVA_BRANCHING_BINARY_OPS = frozenset({_JAVA_AMP_AMP, _JAVA_PIPE_PIPE})

# Rust: ``&&`` / ``||`` short-circuit just like JS / Java. Rust has no
# ``??`` operator (the ``?`` operator is ``try_expression``, not a
# binary operator, and is already counted via the branching-types set).
_RUST_BRANCHING_BINARY_OPS = frozenset({_C_AMP_AMP, _C_PIPE_PIPE})

# Go: ``&&`` / ``||`` short-circuit like the others; no ``??``.
_GO_BRANCHING_BINARY_OPS = frozenset({_GO_AMP_AMP, _GO_PIPE_PIPE})

# PHP: ``&&`` / ``||`` / ``??`` plus the lower-precedence keyword
# operators ``and`` / ``or`` (``xor`` excluded - it does not
# short-circuit, so it adds no decision path).
_PHP_BRANCHING_BINARY_OPS = frozenset({_PHP_AMP_AMP, _PHP_PIPE_PIPE, _PHP_QQ, _PHP_AND_KW, _PHP_OR_KW})

# C: ``&&`` / ``||`` short-circuit; no ``??``.
_C_BRANCHING_BINARY_OPS = frozenset({_C_AMP_AMP, _C_PIPE_PIPE})

# Per-language allow-list for ``binary_expression`` operators that add
# one to cyclomatic complexity. Languages absent from this map (e.g.
# Python, where ``boolean_operator`` is its own node type) fall through
# to the empty set.
_BRANCHING_BINARY_OPS_BY_LANG: dict[str, frozenset[str]] = {
    "javascript": _JS_BRANCHING_BINARY_OPS,
    "typescript": _JS_BRANCHING_BINARY_OPS,
    "java": _JAVA_BRANCHING_BINARY_OPS,
    "rust": _RUST_BRANCHING_BINARY_OPS,
    "go": _GO_BRANCHING_BINARY_OPS,
    "php": _PHP_BRANCHING_BINARY_OPS,
    "c": _C_BRANCHING_BINARY_OPS,
    "cpp": _C_BRANCHING_BINARY_OPS,
}


class ComplexityRule(BaseRule):
    """Reject functions whose cyclomatic complexity exceeds max_complexity."""

    name = "complexity"
    code = "SAFE104"
    language = (EXTRA_NAME, _JS_EXTRA_NAME, _TS_EXTRA_NAME, _JAVA_EXTRA_NAME, _RUST_EXTRA_NAME, _GO_EXTRA_NAME, _PHP_EXTRA_NAME, _C_EXTRA_NAME, _CPP_EXTRA_NAME)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions whose cyclomatic complexity exceeds the configured maximum."""
        max_cc: int = self.config.get("max_complexity", 10)
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        branching_types = _BRANCHING_TYPES_BY_LANG[lang_name]
        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            complexity = self._cyclomatic_complexity(node, lang_name, function_types, branching_types)
            if complexity > max_cc:
                name_node = function_name_node(node, lang_name)
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Function "{func_name}" has cyclomatic complexity {complexity} (max {max_cc}) - split into smaller functions',
                    )
                )
        return violations

    @staticmethod
    def _cyclomatic_complexity(
        func_node: tree_sitter.Node,
        lang_name: str,
        function_types: frozenset[str],
        branching_types: frozenset[str],
    ) -> int:
        """Count cyclomatic complexity for *func_node* (McCabe 1976).

        Skips nested function definitions - they are scored separately by the
        outer ``check_file`` walk so their branches must not also count toward
        the parent.
        """
        complexity = 1
        for node in walk(func_node, skip_types=tuple(function_types)):
            if _is_branch_node(node, lang_name, branching_types):
                complexity += 1
        return complexity


def _is_branch_node(node: tree_sitter.Node, lang_name: str, branching_types: frozenset[str]) -> bool:
    """Return True if *node* contributes 1 to the enclosing function's cyclomatic complexity.

    Most languages can answer this with a simple node-type set membership.
    JavaScript / TypeScript / Java / Rust need a side check because
    ``&&`` / ``||`` (and ``??`` for JS / TS) parse as
    ``binary_expression`` (a node type that also covers ``+``, ``>``,
    ``-``, etc., which are *not* branches) - we filter on the operator
    string via ``_BRANCHING_BINARY_OPS_BY_LANG``.
    """
    if node.type in branching_types:
        return True
    if node.type != _C_BINARY_EXPRESSION:
        return False
    branching_ops = _BRANCHING_BINARY_OPS_BY_LANG.get(lang_name)
    if branching_ops is None:
        return False
    op = node.child_by_field_name("operator")
    if op is None or op.text is None:
        return False
    return op.text.decode("utf-8") in branching_ops
