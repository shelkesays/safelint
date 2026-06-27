"""complexity rule - cyclomatic complexity must not exceed max_complexity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.c import FUNCTION_TYPES as _C_FUNCTION_TYPES
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
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
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
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
        "if_statement",
        "for_statement",
        "for_in_statement",  # also covers ``for...of`` in tree-sitter-javascript
        "while_statement",
        "do_statement",
        "switch_case",
        "catch_clause",
        "ternary_expression",
    }
)
_JAVA_BRANCHING_TYPES = frozenset(
    {
        "if_statement",
        "for_statement",
        "enhanced_for_statement",
        "while_statement",
        "do_statement",
        "switch_block_statement_group",  # colon-form ``case X: stmt;``
        "switch_rule",  # arrow-form ``case X -> stmt;`` (Java 14+)
        "catch_clause",
        "ternary_expression",
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
        "if_expression",
        "for_expression",
        "while_expression",
        "loop_expression",
        "match_arm",
        "try_expression",
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
        "if_statement",
        "for_statement",
        "expression_case",
        "type_case",
        "communication_case",
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
        "if_statement",
        "else_if_clause",
        "while_statement",
        "do_statement",
        "for_statement",
        "foreach_statement",
        "case_statement",
        "match_conditional_expression",
        "catch_clause",
        "conditional_expression",
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
        "if_statement",
        "while_statement",
        "do_statement",
        "for_statement",
        "case_statement",
        "conditional_expression",
    }
)
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
}

# JavaScript: ``binary_expression`` covers many operators (``+``, ``>``,
# etc.) that are NOT branches. Only short-circuiting / null-coalescing
# operators add complexity.
_JS_BRANCHING_BINARY_OPS = frozenset({"&&", "||", "??"})

# Java: same idea, no ``??`` (Java uses ``Optional`` / ``Objects.requireNonNullElse``
# for the null-coalescing role; both call expressions, not operators).
_JAVA_BRANCHING_BINARY_OPS = frozenset({"&&", "||"})

# Rust: ``&&`` / ``||`` short-circuit just like JS / Java. Rust has no
# ``??`` operator (the ``?`` operator is ``try_expression``, not a
# binary operator, and is already counted via the branching-types set).
_RUST_BRANCHING_BINARY_OPS = frozenset({"&&", "||"})

# Go: ``&&`` / ``||`` short-circuit like the others; no ``??``.
_GO_BRANCHING_BINARY_OPS = frozenset({"&&", "||"})

# PHP: ``&&`` / ``||`` / ``??`` plus the lower-precedence keyword
# operators ``and`` / ``or`` (``xor`` excluded - it does not
# short-circuit, so it adds no decision path).
_PHP_BRANCHING_BINARY_OPS = frozenset({"&&", "||", "??", "and", "or"})

# C: ``&&`` / ``||`` short-circuit; no ``??``.
_C_BRANCHING_BINARY_OPS = frozenset({"&&", "||"})

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
}


class ComplexityRule(BaseRule):
    """Reject functions whose cyclomatic complexity exceeds max_complexity."""

    name = "complexity"
    code = "SAFE104"
    language = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c")

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
                name_node = node.child_by_field_name("name")
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
    if node.type != "binary_expression":
        return False
    branching_ops = _BRANCHING_BINARY_OPS_BY_LANG.get(lang_name)
    if branching_ops is None:
        return False
    op = node.child_by_field_name("operator")
    if op is None or op.text is None:
        return False
    return op.text.decode("utf-8") in branching_ops
