"""loop_safety rule - infinite-truthy loops must have a break; others must use comparisons.

Cross-language: Python ``while True:`` and JavaScript ``while (true)``
are the same hazard — fires when no ``break`` reaches the loop. The
non-comparison-condition heuristic stays Python-only (JS idioms like
``while (queue.length)`` are commonly bounded — flagging them would
be noise).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
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
    "typescript": "while_statement",
}

# Per-language: ``break`` statement type. Same name in both grammars.
_BREAK_STATEMENT_BY_LANG: dict[str, str] = {
    "python": BREAK_STATEMENT,
    "javascript": "break_statement",
    "typescript": "break_statement",
}

# Per-language: literal-``true`` condition node type. Python emits
# ``true``; JavaScript emits ``true`` as well. Listed for symmetry.
_TRUE_LITERAL_BY_LANG: dict[str, str] = {
    "python": TRUE,
    "javascript": "true",
    "typescript": "true",
}

# Per-language: node types that bound a ``break`` statement's scope —
# walking out of an outer ``while`` should *not* see a ``break`` inside
# a nested loop or function definition (those breaks belong to the
# inner construct, not the outer ``while`` we're checking).
_JS_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    "for_statement",
    "for_in_statement",  # also covers ``for...of``
    "while_statement",
    "do_statement",
    # Switch arms also stop ``break`` propagation.
    "switch_statement",
    *sorted(_JS_FUNCTION_TYPES),
)
_BREAK_SCOPE_BOUNDARIES_BY_LANG: dict[str, tuple[str, ...]] = {
    "python": (FOR_STATEMENT, WHILE_STATEMENT, FUNCTION_DEF, ASYNC_FUNCTION_DEF),
    "javascript": _JS_BREAK_SCOPE_BOUNDARIES,
    "typescript": _JS_BREAK_SCOPE_BOUNDARIES,
}


def _outer_while_label(while_node: tree_sitter.Node) -> str | None:
    """Return the label name if *while_node* is the body of a ``labeled_statement``.

    JavaScript ``outer: while (true) { ... }`` parses as a
    ``labeled_statement`` wrapping the ``while_statement``. A
    ``break outer;`` inside a nested loop / switch is the labelled
    form of breaking out — we need the label name to recognise
    that break as exiting *this* while. Python has no labelled-
    break construct so this helper returns None on Python (no
    ``labeled_statement`` parent ever appears).
    """
    parent = while_node.parent
    if parent is None or parent.type != "labeled_statement":
        return None
    label = parent.child_by_field_name("label")
    return node_text(label) if label is not None else None


def _is_unlabelled_break(break_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *break_node* is a bare ``break`` (no label).

    Python ``break`` is always unlabelled. JavaScript ``break`` may
    carry a ``statement_identifier`` child (the labelled form
    ``break outer;``) — those count only via the labelled-break
    path, not the direct-scope path.
    """
    if lang_name not in ("javascript", "typescript"):
        return True
    return not any(child.type == "statement_identifier" for child in break_node.named_children)


def _has_direct_break(while_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *while_node* contains an unlabelled break in direct scope.

    The pruned walk skips nested loops / switches / functions so
    their own breaks don't falsely satisfy this outer while.
    """
    boundaries = _BREAK_SCOPE_BOUNDARIES_BY_LANG[lang_name]
    break_type = _BREAK_STATEMENT_BY_LANG[lang_name]
    return any(c.type == break_type and _is_unlabelled_break(c, lang_name) for c in walk(while_node, skip_types=boundaries))


def _has_labelled_break_to(while_node: tree_sitter.Node, label: str) -> bool:
    """Return True if any ``break <label>;`` inside *while_node* targets *label* (JavaScript).

    Walks without pruning loops / switches — labelled breaks legally
    cross those — but does prune function bodies, because in JS
    labels don't cross function scope (a labelled break inside a
    nested function is a SyntaxError).
    """
    function_boundaries = tuple(sorted(_JS_FUNCTION_TYPES))
    for c in walk(while_node, skip_types=function_boundaries):
        if c.type != "break_statement":
            continue
        if any(child.type == "statement_identifier" and node_text(child) == label for child in c.named_children):
            return True
    return False


def _has_exiting_break(while_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *while_node*'s body contains a break that exits it.

    Two cases, OR'd together: an unlabelled break in direct scope
    (see :func:`_has_direct_break`), or — JavaScript only — a
    labelled break targeting this while's own label
    (``outer: while (true) { for (...) { break outer; } }`` —
    see :func:`_has_labelled_break_to`).
    """
    if _has_direct_break(while_node, lang_name):
        return True
    if lang_name not in ("javascript", "typescript"):
        return False
    label = _outer_while_label(while_node)
    if label is None:
        return False
    return _has_labelled_break_to(while_node, label)


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
    language = ("python", "javascript", "typescript")

    def _check_while_node(self, filepath: str, node: tree_sitter.Node, lang_name: str) -> Violation | None:
        """Return a violation if *node* is an unbounded while loop, else None."""
        condition = node.child_by_field_name("condition")
        # ``while`` without a condition can't appear in valid source; this
        # is a defensive guard in case the parser produces an ERROR node.
        if condition is None:  # pragma: no cover
            return None

        # JavaScript wraps the condition in a ``parenthesized_expression``
        # because of the mandatory ``while (...)`` syntax. Extra formatting
        # parentheses can nest (``while ((true))``, ``while ((((x)))) ``),
        # so unwrap until we reach the underlying expression — otherwise
        # ``is_literal_true`` would be False on the outer wrapper and the
        # ``while (true)`` check would silently skip.
        while condition.type == "parenthesized_expression" and condition.named_children:  # nosafe: SAFE501
            condition = condition.named_children[0]

        is_literal_true = condition.type == _TRUE_LITERAL_BY_LANG[lang_name]
        if is_literal_true:
            if not _has_exiting_break(node, lang_name):
                # Match the violation message to the source language's
                # surface syntax — Python's ``while True:`` and
                # JavaScript's ``while (true)`` are the same hazard but
                # written differently. Same per-language wording pattern
                # as ``EmptyExceptRule`` / ``LoggingOnErrorRule``.
                construct = "while (true)" if lang_name in ("javascript", "typescript") else "while True"
                return self._make_violation_for_node(
                    filepath,
                    node,
                    f"{construct} loop has no break - potential infinite loop",
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
        lang_name = resolve_lang_name(filepath)
        while_type = _WHILE_STATEMENT_BY_LANG[lang_name]
        violations = []
        for node in walk(tree.root_node):
            if node.type != while_type:
                continue
            v = self._check_while_node(filepath, node, lang_name)
            if v:
                violations.append(v)
        return violations
