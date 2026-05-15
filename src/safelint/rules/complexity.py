"""complexity rule - cyclomatic complexity must not exceed max_complexity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
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


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
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
}

# JavaScript: ``binary_expression`` covers many operators (``+``, ``>``,
# etc.) that are NOT branches. Only short-circuiting / null-coalescing
# operators add complexity.
_JS_BRANCHING_BINARY_OPS = frozenset({"&&", "||", "??"})

# Java: same idea, no ``??`` (Java uses ``Optional`` / ``Objects.requireNonNullElse``
# for the null-coalescing role; both call expressions, not operators).
_JAVA_BRANCHING_BINARY_OPS = frozenset({"&&", "||"})


class ComplexityRule(BaseRule):
    """Reject functions whose cyclomatic complexity exceeds max_complexity."""

    name = "complexity"
    code = "SAFE104"
    language = ("python", "javascript", "typescript", "java")

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
    JavaScript / TypeScript / Java need a side check because ``&&`` / ``||``
    (and ``??`` for JS / TS) parse as ``binary_expression`` (a node type
    that also covers ``+``, ``>``, ``-``, etc., which are *not* branches) -
    we filter on the operator string.
    """
    if node.type in branching_types:
        return True
    if node.type != "binary_expression":
        return False
    op = node.child_by_field_name("operator")
    if op is None or op.text is None:
        return False
    op_text = op.text.decode("utf-8")
    if lang_name in ("javascript", "typescript"):
        return op_text in _JS_BRANCHING_BINARY_OPS
    if lang_name == "java":
        return op_text in _JAVA_BRANCHING_BINARY_OPS
    return False
