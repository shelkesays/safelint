"""complexity rule - cyclomatic complexity must not exceed max_complexity."""

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
        _js.IF_STATEMENT,
        _js.FOR_STATEMENT,
        _js.FOR_IN_STATEMENT,  # also covers ``for...of`` in tree-sitter-javascript
        _js.WHILE_STATEMENT,
        _js.DO_STATEMENT,
        _js.SWITCH_CASE,
        _js.CATCH_CLAUSE,
        _js.TERNARY_EXPRESSION,
    }
)
_JAVA_BRANCHING_TYPES = frozenset(
    {
        _java.IF_STATEMENT,
        _java.FOR_STATEMENT,
        _java.ENHANCED_FOR_STATEMENT,
        _java.WHILE_STATEMENT,
        _java.DO_STATEMENT,
        _java.SWITCH_BLOCK_STATEMENT_GROUP,  # colon-form ``case X: stmt;``
        _java.SWITCH_RULE,  # arrow-form ``case X -> stmt;`` (Java 14+)
        _java.CATCH_CLAUSE,
        _java.TERNARY_EXPRESSION,
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
        _rust.IF_EXPRESSION,
        _rust.FOR_EXPRESSION,
        _rust.WHILE_EXPRESSION,
        _rust.LOOP_EXPRESSION,
        _rust.MATCH_ARM,
        _rust.TRY_EXPRESSION,
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
        _go.IF_STATEMENT,
        _go.FOR_STATEMENT,
        _go.EXPRESSION_CASE,
        _go.TYPE_CASE,
        _go.COMMUNICATION_CASE,
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
        _php.IF_STATEMENT,
        _php.ELSE_IF_CLAUSE,
        _php.WHILE_STATEMENT,
        _php.DO_STATEMENT,
        _php.FOR_STATEMENT,
        _php.FOREACH_STATEMENT,
        _php.CASE_STATEMENT,
        _php.MATCH_CONDITIONAL_EXPRESSION,
        _php.CATCH_CLAUSE,
        _php.CONDITIONAL_EXPRESSION,
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
        _c.IF_STATEMENT,
        _c.WHILE_STATEMENT,
        _c.DO_STATEMENT,
        _c.FOR_STATEMENT,
        _c.CASE_STATEMENT,
        _c.CONDITIONAL_EXPRESSION,
    }
)
# C++: the C set plus ``catch_clause`` (each ``catch`` is a branch).
_CPP_BRANCHING_TYPES = _C_BRANCHING_TYPES | frozenset({_cpp.CATCH_CLAUSE, _cpp.FOR_RANGE_LOOP})
_BRANCHING_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset(
        {
            _py.IF_STATEMENT,
            _py.ELIF_CLAUSE,
            _py.FOR_STATEMENT,
            _py.WHILE_STATEMENT,
            _py.EXCEPT_CLAUSE,
            _py.CONDITIONAL_EXPRESSION,
            _py.IF_CLAUSE,
            _py.BOOLEAN_OPERATOR,
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
_JS_BRANCHING_BINARY_OPS = frozenset({_js.AMP_AMP, _js.PIPE_PIPE, _js.QQ})

# Java: same idea, no ``??`` (Java uses ``Optional`` / ``Objects.requireNonNullElse``
# for the null-coalescing role; both call expressions, not operators).
_JAVA_BRANCHING_BINARY_OPS = frozenset({_java.AMP_AMP, _java.PIPE_PIPE})

# Rust: ``&&`` / ``||`` short-circuit just like JS / Java. Rust has no
# ``??`` operator (the ``?`` operator is ``try_expression``, not a
# binary operator, and is already counted via the branching-types set).
_RUST_BRANCHING_BINARY_OPS = frozenset({_rust.AMP_AMP, _rust.PIPE_PIPE})

# Go: ``&&`` / ``||`` short-circuit like the others; no ``??``.
_GO_BRANCHING_BINARY_OPS = frozenset({_go.AMP_AMP, _go.PIPE_PIPE})

# PHP: ``&&`` / ``||`` / ``??`` plus the lower-precedence keyword
# operators ``and`` / ``or`` (``xor`` excluded - it does not
# short-circuit, so it adds no decision path).
_PHP_BRANCHING_BINARY_OPS = frozenset({_php.AMP_AMP, _php.PIPE_PIPE, _php.QQ, _php.AND_KW, _php.OR_KW})

# C: ``&&`` / ``||`` short-circuit; no ``??``.
_C_BRANCHING_BINARY_OPS = frozenset({_c.AMP_AMP, _c.PIPE_PIPE})

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
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _go.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

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
    # ``binary_expression`` is the same node type in every supported grammar, so
    # this generic (all-language) check is language-neutral; the constant is
    # sourced from the c module arbitrarily, not because the check is C-specific.
    if node.type != _c.BINARY_EXPRESSION:
        return False
    branching_ops = _BRANCHING_BINARY_OPS_BY_LANG.get(lang_name)
    if branching_ops is None:
        return False
    op = node.child_by_field_name("operator")
    if op is None or op.text is None:
        return False
    return op.text.decode("utf-8") in branching_ops
