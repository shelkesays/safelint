"""loop_safety rule - infinite-truthy loops must have a break; others must use comparisons.

Cross-language: Python ``while True:`` and JavaScript ``while (true)``
are the same hazard - fires when no ``break`` reaches the loop. The
non-comparison-condition heuristic stays Python-only (JS idioms like
``while (queue.length)`` are commonly bounded - flagging them would
be noise).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
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
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# Per-language: ``while``-statement node type. Python / JS / TS / Java
# all use ``while_statement``; Rust uses ``while_expression`` (Rust
# treats most control flow as expressions).
_WHILE_STATEMENT_BY_LANG: dict[str, str] = {
    "python": WHILE_STATEMENT,
    "javascript": "while_statement",
    "typescript": "while_statement",
    "java": "while_statement",
    "rust": "while_expression",
}

# Per-language: unconditional-``loop`` construct, or None if the
# language has no equivalent. Rust's ``loop { }`` is the idiomatic
# infinite loop and is the headline SAFE501 case for Rust source.
_INFINITE_LOOP_STATEMENT_BY_LANG: dict[str, str | None] = {
    "python": None,
    "javascript": None,
    "typescript": None,
    "java": None,
    "rust": "loop_expression",
}

# Per-language: ``break`` statement node type. Python / JS / TS / Java
# share ``break_statement``; Rust uses ``break_expression``.
_BREAK_STATEMENT_BY_LANG: dict[str, str] = {
    "python": BREAK_STATEMENT,
    "javascript": "break_statement",
    "typescript": "break_statement",
    "java": "break_statement",
    "rust": "break_expression",
}

# Per-language: literal-``true`` condition node type. Python / JS / TS
# / Java emit ``true`` for the boolean literal. Rust uses
# ``boolean_literal`` (a single node type that covers both ``true`` and
# ``false``), so a node-type match alone is insufficient - the literal
# check for Rust additionally inspects the token text via
# :func:`_is_literal_true`.
_TRUE_LITERAL_BY_LANG: dict[str, str] = {
    "python": TRUE,
    "javascript": "true",
    "typescript": "true",
    "java": "true",
    "rust": "boolean_literal",
}

# Per-language: the node type used by a labelled-break's argument.
# JavaScript wraps the label in a dedicated ``statement_identifier`` node;
# Java uses a plain ``identifier``. Rust uses a ``label`` wrapper
# (whose inner ``identifier`` carries the name). Python has no
# labelled break.
_BREAK_LABEL_TYPE_BY_LANG: dict[str, str | None] = {
    "python": None,
    "javascript": "statement_identifier",
    "typescript": "statement_identifier",
    "java": "identifier",
    "rust": "label",
}

# Per-language: node types that bound a ``break`` statement's scope -
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
_JAVA_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    "for_statement",
    "enhanced_for_statement",
    "while_statement",
    "do_statement",
    # Switch arms stop ``break`` propagation (Java's classic colon-form
    # switch uses ``break`` to exit a case; the modern arrow-form
    # ``case X -> stmt`` does not).
    "switch_expression",
    *sorted(_JAVA_FUNCTION_TYPES),
)
# Rust: any nested loop type stops a bare ``break`` from referring to
# the outer one. ``match_expression`` is NOT a boundary - Rust ``break``
# inside a match arm legally targets the enclosing loop (there is no
# ``break`` exit from a match).
_RUST_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    "for_expression",
    "while_expression",
    "loop_expression",
    *sorted(_RUST_FUNCTION_TYPES),
)
_BREAK_SCOPE_BOUNDARIES_BY_LANG: dict[str, tuple[str, ...]] = {
    "python": (FOR_STATEMENT, WHILE_STATEMENT, FUNCTION_DEF, ASYNC_FUNCTION_DEF),
    "javascript": _JS_BREAK_SCOPE_BOUNDARIES,
    "typescript": _JS_BREAK_SCOPE_BOUNDARIES,
    "java": _JAVA_BREAK_SCOPE_BOUNDARIES,
    "rust": _RUST_BREAK_SCOPE_BOUNDARIES,
}


def _is_unlabelled_break(break_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *break_node* is a bare ``break`` (no label).

    Python ``break`` is always unlabelled. JavaScript / Java ``break``
    may carry a label argument (``break outer;``) - those count only
    via the labelled-break path, not the direct-scope path. Rust's
    ``break 'outer;`` parses with a ``label`` named child. The label
    argument node type differs per language and is looked up via
    :data:`_BREAK_LABEL_TYPE_BY_LANG`.
    """
    label_type = _BREAK_LABEL_TYPE_BY_LANG.get(lang_name)
    if label_type is None:
        return True
    return not any(child.type == label_type for child in break_node.named_children)


def _has_direct_break(while_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *while_node* contains an unlabelled break in direct scope.

    The pruned walk skips nested loops / switches / functions so
    their own breaks don't falsely satisfy this outer while.
    """
    boundaries = _BREAK_SCOPE_BOUNDARIES_BY_LANG[lang_name]
    break_type = _BREAK_STATEMENT_BY_LANG[lang_name]
    return any(c.type == break_type and _is_unlabelled_break(c, lang_name) for c in walk(while_node, skip_types=boundaries))


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
    "rust": _RUST_FUNCTION_TYPES,
}


def _rust_label_name(label_node: tree_sitter.Node) -> str | None:
    """Return the bare name carried by a Rust ``label`` wrapper node, or None.

    Rust labels parse as a ``label`` node containing a single
    ``identifier`` child. ``node_text`` on the label itself returns
    ``'outer`` (with the leading apostrophe); reaching into the
    identifier returns the bare name (``outer``) for comparison.
    """
    ident = next((c for c in label_node.named_children if c.type == "identifier"), None)
    return node_text(ident) if ident is not None else None


# Rust nodes that can carry a *naming* label as a direct child.
# (``break_expression`` also has a ``label`` child but that's the
# *target* of the break, not a name for the break itself.)
_RUST_LABELABLE_NODE_TYPES: frozenset[str] = frozenset(
    {
        "loop_expression",
        "while_expression",
        "for_expression",
    }
)


def _node_label_name(node: tree_sitter.Node, lang_name: str) -> str | None:
    """Return the label name attached to *node*, or None if unlabelled.

    Per language, labels are attached differently:

    * JavaScript / TypeScript: the labelled construct sits inside a
      ``labeled_statement`` wrapper, with the label name in the
      ``label`` field of type ``statement_identifier``. *node* should
      be the labeled_statement itself.
    * Java: same wrapper, no ``label`` field - the label is the first
      ``identifier`` named child of the labeled_statement.
    * Rust: labels are a direct named child of a loop node (no
      wrapper). Only the loop-expression types in
      :data:`_RUST_LABELABLE_NODE_TYPES` count - ``break_expression``
      also has a ``label`` child but that's its *target*, not a name
      attached to the break itself.
    """
    if lang_name == "rust":
        if node.type not in _RUST_LABELABLE_NODE_TYPES:
            return None
        label = next((c for c in node.named_children if c.type == "label"), None)
        return None if label is None else _rust_label_name(label)
    if node.type != "labeled_statement":
        return None
    if lang_name == "java":
        ident = next((c for c in node.named_children if c.type == "identifier"), None)
        return node_text(ident) if ident is not None else None
    label = node.child_by_field_name("label")
    return node_text(label) if label is not None else None


def _break_label_target(break_node: tree_sitter.Node, lang_name: str) -> str | None:
    """Return the label-name a labelled ``break`` targets, or None for a bare break."""
    label_type = _BREAK_LABEL_TYPE_BY_LANG.get(lang_name)
    if label_type is None:  # pragma: no cover - only Python maps to None and Python is guarded out by callers
        return None
    label_child = next((c for c in break_node.named_children if c.type == label_type), None)
    if label_child is None:
        return None
    if lang_name == "rust":
        return _rust_label_name(label_child)
    return node_text(label_child)


def _labels_strictly_inside(while_node: tree_sitter.Node, lang_name: str) -> frozenset[str]:
    """Return the set of label names declared strictly inside *while_node*.

    A labelled break that targets one of these names is exiting an
    inner labelled construct, NOT *while_node*. Conversely, a
    labelled break whose target is *not* in this set must target
    *while_node* itself or an ancestor, and therefore exits this loop.

    Walks descendants of *while_node*, pruning function / closure
    bodies (labels don't cross function scope). *while_node* itself
    is excluded - its own label (if any) is on a parent
    ``labeled_statement`` (JS / Java) or attached as a sibling of
    its body (Rust), in either case not a descendant.
    """
    function_types = _FUNCTION_TYPES_BY_LANG.get(lang_name)
    if function_types is None:  # pragma: no cover - guarded by callers
        return frozenset()
    function_boundaries = tuple(sorted(function_types))
    labels: set[str] = set()
    for desc in walk(while_node, skip_types=function_boundaries):
        if desc is while_node:
            continue
        name = _node_label_name(desc, lang_name)
        if name is not None:
            labels.add(name)
    return frozenset(labels)


def _has_outward_labelled_break(while_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if any labelled break inside *while_node* exits it.

    A labelled break inside loop X exits X iff its target label is
    NOT defined strictly inside X (in which case the target is at X
    or an ancestor, and the break passes through X's scope on its
    way out). This correctly distinguishes:

    * ``outer: while (true) { inner: for (...) { break inner; } }``
      - ``inner`` is inside outer, so the break does NOT exit outer.
    * ``'outer: loop { loop { break 'outer; } }`` - ``outer`` is the
      enclosing loop label, NOT inside the inner unlabelled loop,
      so ``break 'outer`` exits the inner loop too.
    """
    function_types = _FUNCTION_TYPES_BY_LANG.get(lang_name)
    if function_types is None:  # pragma: no cover - guarded by callers
        return False
    function_boundaries = tuple(sorted(function_types))
    break_type = _BREAK_STATEMENT_BY_LANG[lang_name]
    inner_labels = _labels_strictly_inside(while_node, lang_name)
    for c in walk(while_node, skip_types=function_boundaries):
        if c.type != break_type:
            continue
        target = _break_label_target(c, lang_name)
        if target is not None and target not in inner_labels:
            return True
    return False


def _has_exiting_break(while_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *while_node*'s body contains a break that exits it.

    Two cases, OR'd together: an unlabelled break in direct scope
    (see :func:`_has_direct_break`), or - in languages with labelled
    break (JavaScript / TypeScript / Java / Rust) - a labelled break
    whose target is NOT a label defined strictly inside *while_node*
    (see :func:`_has_outward_labelled_break`).
    """
    if _has_direct_break(while_node, lang_name):
        return True
    if lang_name not in ("javascript", "typescript", "java", "rust"):
        return False
    return _has_outward_labelled_break(while_node, lang_name)


def _is_literal_true(condition: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *condition* is the ``true`` literal under *lang_name*'s grammar.

    Most languages emit a dedicated ``true`` node type for the boolean
    literal, so a single node-type comparison suffices. Rust collapses
    both boolean literals into a single ``boolean_literal`` node type,
    so the check additionally inspects the token text.
    """
    expected = _TRUE_LITERAL_BY_LANG[lang_name]
    if condition.type != expected:
        return False
    if lang_name != "rust":
        return True
    return node_text(condition) == "true"


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
    or ``while (token)`` are common and intentional - the false-positive
    rate would dwarf the catches.
    """

    name = "unbounded_loops"
    code = "SAFE501"
    language = ("python", "javascript", "typescript", "java", "rust")

    @staticmethod
    def _while_true_construct(lang_name: str) -> str:
        """Return the source-language spelling of ``while true`` for messages."""
        if lang_name in ("javascript", "typescript", "java"):
            return "while (true)"
        if lang_name == "rust":
            return "while true"
        return "while True"

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
        # so unwrap until we reach the underlying expression - otherwise
        # ``is_literal_true`` would be False on the outer wrapper and the
        # ``while (true)`` check would silently skip.
        while condition.type == "parenthesized_expression":
            if not condition.named_children:
                break
            condition = condition.named_children[0]

        if _is_literal_true(condition, lang_name):
            if not _has_exiting_break(node, lang_name):
                construct = self._while_true_construct(lang_name)
                return self._make_violation_for_node(
                    filepath,
                    node,
                    f"{construct} loop has no break - potential infinite loop",
                )
            return None

        # The non-comparison-condition heuristic is Python-specific.
        # JS / Rust idioms like ``while (queue.length)`` or
        # ``while let Some(x) = iter.next()`` are common and bounded;
        # firing on every non-comparison would be too noisy.
        if lang_name != "python":
            return None

        if condition.type != COMPARISON_OPERATOR:
            return self._make_violation_for_node(
                filepath,
                node,
                "while loop condition is not a comparison - verify the loop is bounded",
            )
        return None

    def _check_loop_node(self, filepath: str, node: tree_sitter.Node, lang_name: str) -> Violation | None:
        """Return a violation if Rust's unconditional ``loop { }`` lacks a break."""
        if _has_exiting_break(node, lang_name):
            return None
        return self._make_violation_for_node(
            filepath,
            node,
            "loop has no break - potential infinite loop",
        )

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag while / loop constructs that may be infinite."""
        lang_name = resolve_lang_name(filepath)
        while_type = _WHILE_STATEMENT_BY_LANG[lang_name]
        loop_type = _INFINITE_LOOP_STATEMENT_BY_LANG[lang_name]
        violations = []
        for node in walk(tree.root_node):
            if node.type == while_type:
                v = self._check_while_node(filepath, node, lang_name)
            elif loop_type is not None and node.type == loop_type:
                v = self._check_loop_node(filepath, node, lang_name)
            else:
                continue
            if v:
                violations.append(v)
        return violations
