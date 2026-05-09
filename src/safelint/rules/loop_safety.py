"""loop_safety rule - while True must have a break; others must use comparisons."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages import get_language_for_file
from safelint.languages._node_utils import walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
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


# Per-language: ``while``-statement node type. Both grammars happen to
# call it the same thing today; keeping the table explicit so a new
# language with a different node name plugs in by appending an entry.
_WHILE_STATEMENT_BY_LANG: dict[str, str] = {
    "python": WHILE_STATEMENT,
    "javascript": "while_statement",
}

# Per-language: ``break`` statement type. Same name in both grammars.
_BREAK_STATEMENT_BY_LANG: dict[str, str] = {
    "python": BREAK_STATEMENT,
    "javascript": "break_statement",
}

# Per-language: literal-``true`` condition node type. Python emits
# ``true``; JavaScript emits ``true`` as well. Listed for symmetry.
_TRUE_LITERAL_BY_LANG: dict[str, str] = {
    "python": TRUE,
    "javascript": "true",
}

# Per-language: node types that bound a ``break`` statement's scope —
# walking out of an outer ``while`` should *not* see a ``break`` inside
# a nested loop or function definition (those breaks belong to the
# inner construct, not the outer ``while`` we're checking).
_BREAK_SCOPE_BOUNDARIES_BY_LANG: dict[str, tuple[str, ...]] = {
    "python": (FOR_STATEMENT, WHILE_STATEMENT, FUNCTION_DEF, ASYNC_FUNCTION_DEF),
    "javascript": (
        "for_statement",
        "for_in_statement",  # also covers ``for...of``
        "while_statement",
        "do_statement",
        # Switch arms also stop ``break`` propagation.
        "switch_statement",
        *sorted(_JS_FUNCTION_TYPES),
    ),
}


class UnboundedLoopRule(BaseRule):
    """Flag while loops that lack a provable bound.

    Python ``while True:`` without a ``break`` is a guaranteed infinite
    loop; ``while <condition>:`` where the condition isn't a comparison
    expression is harder to verify (Python idioms like ``while queue:``
    or ``while x is not None:`` are common but the rule prefers an
    explicit comparison).

    JavaScript ``while (true)`` without a ``break`` follows the same
    contract. The "non-comparison condition" heuristic is *not*
    applied to JS because idiomatic loops like ``while (queue.length)``
    or ``while (token)`` are common and intentional — the false-positive
    rate would dwarf the catches.
    """

    name = "unbounded_loops"
    code = "SAFE501"
    language = ("python", "javascript")

    def _check_while_node(self, filepath: str, node: tree_sitter.Node, lang_name: str) -> Violation | None:
        """Return a violation if *node* is an unbounded while loop, else None."""
        condition = node.child_by_field_name("condition")
        # ``while`` without a condition can't appear in valid source; this
        # is a defensive guard in case the parser produces an ERROR node.
        if condition is None:  # pragma: no cover
            return None

        # JavaScript wraps the condition in a ``parenthesized_expression``
        # because of the mandatory ``while (...)`` syntax. Reach inside.
        if condition.type == "parenthesized_expression" and condition.named_children:
            condition = condition.named_children[0]

        is_literal_true = condition.type == _TRUE_LITERAL_BY_LANG[lang_name]
        if is_literal_true:
            boundaries = _BREAK_SCOPE_BOUNDARIES_BY_LANG[lang_name]
            break_type = _BREAK_STATEMENT_BY_LANG[lang_name]
            has_break = any(c.type == break_type for c in walk(node, skip_types=boundaries))
            if not has_break:
                return self._make_violation_for_node(
                    filepath,
                    node,
                    "while True loop has no break - potential infinite loop",
                )
            return None

        # The non-comparison-condition heuristic is Python-specific.
        # JS idioms like ``while (queue.length)`` or ``while (token)``
        # are common and bounded; firing on every non-comparison would
        # be too noisy. Skip this branch on JS.
        if lang_name != "python":
            return None

        if condition.type != COMPARISON_OPERATOR:
            return self._make_violation_for_node(
                filepath,
                node,
                "while loop condition is not a comparison - verify the loop is bounded",
            )
        return None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag while loops that may be infinite."""
        lang = get_language_for_file(filepath)
        assert lang is not None, "engine guarantees a registered language at this point"
        while_type = _WHILE_STATEMENT_BY_LANG[lang.name]
        violations = []
        for node in walk(tree.root_node):
            if node.type != while_type:
                continue
            v = self._check_while_node(filepath, node, lang.name)
            if v:
                violations.append(v)
        return violations
