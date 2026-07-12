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
from safelint.languages.c import BREAK_STATEMENT as _C_BREAK_STATEMENT
from safelint.languages.c import CONDITION_CLAUSE as _C_CONDITION_CLAUSE
from safelint.languages.c import DO_STATEMENT as _C_DO_STATEMENT
from safelint.languages.c import EXTRA_NAME as _C_EXTRA_NAME
from safelint.languages.c import FOR_STATEMENT as _C_FOR_STATEMENT
from safelint.languages.c import FUNCTION_DEFINITION as _C_FUNCTION_DEFINITION
from safelint.languages.c import FUNCTION_TYPES as _C_FUNCTION_TYPES
from safelint.languages.c import GOTO_STATEMENT as _C_GOTO_STATEMENT
from safelint.languages.c import IDENTIFIER as _C_IDENTIFIER
from safelint.languages.c import LABELED_STATEMENT as _C_LABELED_STATEMENT
from safelint.languages.c import NUMBER_LITERAL as _C_NUMBER_LITERAL
from safelint.languages.c import PARENTHESIZED_EXPRESSION as _C_PARENTHESIZED_EXPRESSION
from safelint.languages.c import SWITCH_STATEMENT as _C_SWITCH_STATEMENT
from safelint.languages.c import TRUE as _C_TRUE
from safelint.languages.c import WHILE_STATEMENT as _C_WHILE_STATEMENT
from safelint.languages.cpp import BREAK_STATEMENT as _CPP_BREAK_STATEMENT
from safelint.languages.cpp import EXTRA_NAME as _CPP_EXTRA_NAME
from safelint.languages.cpp import FOR_STATEMENT as _CPP_FOR_STATEMENT
from safelint.languages.cpp import FUNCTION_TYPES as _CPP_FUNCTION_TYPES
from safelint.languages.cpp import LAMBDA_EXPRESSION as _CPP_LAMBDA_EXPRESSION
from safelint.languages.cpp import WHILE_STATEMENT as _CPP_WHILE_STATEMENT
from safelint.languages.go import BREAK_STATEMENT as _GO_BREAK_STATEMENT
from safelint.languages.go import COMMENT as _GO_COMMENT
from safelint.languages.go import EXPRESSION_SWITCH_STATEMENT as _GO_EXPRESSION_SWITCH_STATEMENT
from safelint.languages.go import EXTRA_NAME as _GO_EXTRA_NAME
from safelint.languages.go import FOR_STATEMENT as _GO_FOR_STATEMENT
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.go import LABEL_NAME as _GO_LABEL_NAME
from safelint.languages.go import SELECT_STATEMENT as _GO_SELECT_STATEMENT
from safelint.languages.go import TYPE_SWITCH_STATEMENT as _GO_TYPE_SWITCH_STATEMENT
from safelint.languages.java import BREAK_STATEMENT as _JAVA_BREAK_STATEMENT
from safelint.languages.java import DO_STATEMENT as _JAVA_DO_STATEMENT
from safelint.languages.java import ENHANCED_FOR_STATEMENT as _JAVA_ENHANCED_FOR_STATEMENT
from safelint.languages.java import EXTRA_NAME as _JAVA_EXTRA_NAME
from safelint.languages.java import FOR_STATEMENT as _JAVA_FOR_STATEMENT
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.java import IDENTIFIER as _JAVA_IDENTIFIER
from safelint.languages.java import SWITCH_EXPRESSION as _JAVA_SWITCH_EXPRESSION
from safelint.languages.java import TRUE as _JAVA_TRUE
from safelint.languages.java import WHILE_STATEMENT as _JAVA_WHILE_STATEMENT
from safelint.languages.javascript import BREAK_STATEMENT as _JS_BREAK_STATEMENT
from safelint.languages.javascript import DO_STATEMENT as _JS_DO_STATEMENT
from safelint.languages.javascript import EXTRA_NAME as _JS_EXTRA_NAME
from safelint.languages.javascript import FOR_IN_STATEMENT as _JS_FOR_IN_STATEMENT
from safelint.languages.javascript import FOR_STATEMENT as _JS_FOR_STATEMENT
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.javascript import SWITCH_STATEMENT as _JS_SWITCH_STATEMENT
from safelint.languages.javascript import TRUE as _JS_TRUE
from safelint.languages.javascript import WHILE_STATEMENT as _JS_WHILE_STATEMENT
from safelint.languages.php import BOOLEAN as _PHP_BOOLEAN
from safelint.languages.php import BREAK_STATEMENT as _PHP_BREAK_STATEMENT
from safelint.languages.php import DO_STATEMENT as _PHP_DO_STATEMENT
from safelint.languages.php import EXTRA_NAME as _PHP_EXTRA_NAME
from safelint.languages.php import FOR_STATEMENT as _PHP_FOR_STATEMENT
from safelint.languages.php import FOREACH_STATEMENT as _PHP_FOREACH_STATEMENT
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
from safelint.languages.php import INTEGER as _PHP_INTEGER
from safelint.languages.php import SWITCH_STATEMENT as _PHP_SWITCH_STATEMENT
from safelint.languages.php import WHILE_STATEMENT as _PHP_WHILE_STATEMENT
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    BREAK_STATEMENT,
    COMPARISON_OPERATOR,
    EXTRA_NAME,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IDENTIFIER,
    TRUE,
    WHILE_STATEMENT,
)
from safelint.languages.rust import BOOLEAN_LITERAL as _RUST_BOOLEAN_LITERAL
from safelint.languages.rust import BREAK_EXPRESSION as _RUST_BREAK_EXPRESSION
from safelint.languages.rust import EXTRA_NAME as _RUST_EXTRA_NAME
from safelint.languages.rust import FOR_EXPRESSION as _RUST_FOR_EXPRESSION
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.languages.rust import IDENTIFIER as _RUST_IDENTIFIER
from safelint.languages.rust import LABEL as _RUST_LABEL
from safelint.languages.rust import LOOP_EXPRESSION as _RUST_LOOP_EXPRESSION
from safelint.languages.rust import WHILE_EXPRESSION as _RUST_WHILE_EXPRESSION
from safelint.languages.typescript import BREAK_STATEMENT as _TS_BREAK_STATEMENT
from safelint.languages.typescript import EXTRA_NAME as _TS_EXTRA_NAME
from safelint.languages.typescript import STATEMENT_IDENTIFIER as _TS_STATEMENT_IDENTIFIER
from safelint.languages.typescript import TRUE as _TS_TRUE
from safelint.languages.typescript import WHILE_STATEMENT as _TS_WHILE_STATEMENT
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# Per-language: ``while``-statement node type, or None for languages with
# no ``while`` keyword. Python / JS / TS / Java use ``while_statement``;
# Rust uses ``while_expression``; Go has no ``while`` at all - its only
# loop keyword is ``for``, and the infinite form (bare ``for {}``) is
# handled through the unconditional-loop path below, not here.
_WHILE_STATEMENT_BY_LANG: dict[str, str | None] = {
    "python": WHILE_STATEMENT,
    "javascript": _JS_WHILE_STATEMENT,
    "typescript": _TS_WHILE_STATEMENT,
    "java": _JAVA_WHILE_STATEMENT,
    "rust": _RUST_WHILE_EXPRESSION,
    "go": None,
    "php": _PHP_WHILE_STATEMENT,
    "c": _C_WHILE_STATEMENT,
    "cpp": _CPP_WHILE_STATEMENT,
}

# Per-language: unconditional-``loop`` construct, or None if the
# language has no equivalent. Rust's ``loop { }`` is the idiomatic
# infinite loop and is the headline SAFE501 case for Rust source.
# Go reuses ``for_statement`` here: a bare ``for {}`` (no condition,
# clause, or range header) is Go's ``while true``. Because the same
# node type also covers bounded ``for`` loops, ``_check_loop_node``
# guards on :func:`_is_go_infinite_for` so only the bare form fires.
_INFINITE_LOOP_STATEMENT_BY_LANG: dict[str, str | None] = {
    "python": None,
    "javascript": None,
    "typescript": None,
    "java": None,
    "rust": _RUST_LOOP_EXPRESSION,
    "go": _GO_FOR_STATEMENT,
    # PHP ``for (;;)`` is the headerless infinite loop. Same node type as a
    # bounded ``for``, so ``_check_loop_node`` guards on
    # :func:`_is_php_infinite_for` (absence of the ``condition`` field).
    "php": _PHP_FOR_STATEMENT,
    # C: ``for (;;)`` headerless infinite loop (same node type as a bounded
    # ``for``; the :func:`_is_c_infinite_for` guard checks for an absent condition).
    "c": _C_FOR_STATEMENT,
    "cpp": _CPP_FOR_STATEMENT,
}

# Per-language: ``break`` statement node type. Python / JS / TS / Java /
# Go share ``break_statement``; Rust uses ``break_expression``.
_BREAK_STATEMENT_BY_LANG: dict[str, str] = {
    "python": BREAK_STATEMENT,
    "javascript": _JS_BREAK_STATEMENT,
    "typescript": _TS_BREAK_STATEMENT,
    "java": _JAVA_BREAK_STATEMENT,
    "rust": _RUST_BREAK_EXPRESSION,
    "go": _GO_BREAK_STATEMENT,
    "php": _PHP_BREAK_STATEMENT,
    "c": _C_BREAK_STATEMENT,
    "cpp": _CPP_BREAK_STATEMENT,
}

# Per-language: literal-``true`` condition node type. Python / JS / TS
# / Java emit ``true`` for the boolean literal. Rust uses
# ``boolean_literal`` (a single node type that covers both ``true`` and
# ``false``), so a node-type match alone is insufficient - the literal
# check for Rust additionally inspects the token text via
# :func:`_is_literal_true`.
_TRUE_LITERAL_BY_LANG: dict[str, str] = {
    "python": TRUE,
    "javascript": _JS_TRUE,
    "typescript": _TS_TRUE,
    "java": _JAVA_TRUE,
    "rust": _RUST_BOOLEAN_LITERAL,
    # PHP emits a single ``boolean`` node for both ``true`` and ``false``
    # (like Rust's ``boolean_literal``), so ``_is_literal_true`` inspects
    # the token text in addition to the node type.
    "php": _PHP_BOOLEAN,
    # C ``while (1)`` is a ``number_literal``; ``while (true)`` (stdbool) an
    # identifier. ``_is_literal_true`` special-cases C to handle both.
    "c": _C_NUMBER_LITERAL,
    # C++: unused directly (``_is_c_literal_true`` handles both ``1`` and ``true``).
    "cpp": _C_NUMBER_LITERAL,
}

# Per-language: the node type used by a labelled-break's argument.
# JavaScript wraps the label in a dedicated ``statement_identifier`` node;
# Java uses a plain ``identifier``. Rust uses a ``label`` wrapper
# (whose inner ``identifier`` carries the name). Go uses a ``label_name``
# node (``break outer``). Python has no labelled break.
_BREAK_LABEL_TYPE_BY_LANG: dict[str, str | None] = {
    "python": None,
    "javascript": _TS_STATEMENT_IDENTIFIER,
    "typescript": _TS_STATEMENT_IDENTIFIER,
    "java": _JAVA_IDENTIFIER,
    "rust": _RUST_LABEL,
    "go": _GO_LABEL_NAME,
    "c": None,  # C has no labelled break
    "cpp": None,  # C++ has no labelled break either
}

# Per-language: node types that bound a ``break`` statement's scope -
# walking out of an outer ``while`` should *not* see a ``break`` inside
# a nested loop or function definition (those breaks belong to the
# inner construct, not the outer ``while`` we're checking).
_JS_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    _JS_FOR_STATEMENT,
    _JS_FOR_IN_STATEMENT,  # also covers ``for...of``
    _JS_WHILE_STATEMENT,
    _JS_DO_STATEMENT,
    # Switch arms also stop ``break`` propagation.
    _JS_SWITCH_STATEMENT,
    *sorted(_JS_FUNCTION_TYPES),
)
_JAVA_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    _JAVA_FOR_STATEMENT,
    _JAVA_ENHANCED_FOR_STATEMENT,
    _JAVA_WHILE_STATEMENT,
    _JAVA_DO_STATEMENT,
    # Switch arms stop ``break`` propagation (Java's classic colon-form
    # switch uses ``break`` to exit a case; the modern arrow-form
    # ``case X -> stmt`` does not).
    _JAVA_SWITCH_EXPRESSION,
    *sorted(_JAVA_FUNCTION_TYPES),
)
# Rust: any nested loop type stops a bare ``break`` from referring to
# the outer one. ``match_expression`` is NOT a boundary - Rust ``break``
# inside a match arm legally targets the enclosing loop (there is no
# ``break`` exit from a match).
_RUST_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    _RUST_FOR_EXPRESSION,
    _RUST_WHILE_EXPRESSION,
    _RUST_LOOP_EXPRESSION,
    *sorted(_RUST_FUNCTION_TYPES),
)
# Go: a nested ``for`` stops a bare ``break`` from referring to the outer
# loop, and ``break`` inside a ``switch`` / ``select`` exits THAT construct
# (not the enclosing loop) - so the two switch forms and ``select`` are
# boundaries too, the same way Java's ``switch_expression`` is.
_GO_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    _GO_FOR_STATEMENT,
    _GO_EXPRESSION_SWITCH_STATEMENT,
    _GO_TYPE_SWITCH_STATEMENT,
    _GO_SELECT_STATEMENT,
    *sorted(_GO_FUNCTION_TYPES),
)
# C: a nested loop or ``switch`` stops a bare ``break`` from exiting the outer
# loop. ``function_definition`` bounds the scope too. C has no labelled break -
# ``goto`` is the multi-level escape, handled separately as a loop exit.
_C_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (
    _C_FOR_STATEMENT,
    _C_WHILE_STATEMENT,
    _C_DO_STATEMENT,
    _C_SWITCH_STATEMENT,
    _C_FUNCTION_DEFINITION,
)
# C++ adds ``lambda_expression`` to C's boundary set: a ``break`` inside a
# lambda body exits that lambda, not an enclosing loop.
_CPP_BREAK_SCOPE_BOUNDARIES: tuple[str, ...] = (*_C_BREAK_SCOPE_BOUNDARIES, _CPP_LAMBDA_EXPRESSION)
_BREAK_SCOPE_BOUNDARIES_BY_LANG: dict[str, tuple[str, ...]] = {
    "python": (FOR_STATEMENT, WHILE_STATEMENT, FUNCTION_DEF, ASYNC_FUNCTION_DEF),
    "javascript": _JS_BREAK_SCOPE_BOUNDARIES,
    "typescript": _JS_BREAK_SCOPE_BOUNDARIES,
    "java": _JAVA_BREAK_SCOPE_BOUNDARIES,
    "rust": _RUST_BREAK_SCOPE_BOUNDARIES,
    "go": _GO_BREAK_SCOPE_BOUNDARIES,
    "c": _C_BREAK_SCOPE_BOUNDARIES,
    "cpp": _CPP_BREAK_SCOPE_BOUNDARIES,
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
    "go": _GO_FUNCTION_TYPES,
    "php": _PHP_FUNCTION_TYPES,
    "c": _C_FUNCTION_TYPES,
    "cpp": _CPP_FUNCTION_TYPES,
}

# PHP loop / switch constructs that a ``break N`` counts as one "level".
# ``break;`` (level 1) exits the innermost; ``break 2;`` exits two. ``match``
# is excluded - it has no ``break`` statement.
_PHP_LOOP_SWITCH_TYPES: frozenset[str] = frozenset(
    {
        _PHP_FOR_STATEMENT,
        _PHP_FOREACH_STATEMENT,
        _PHP_WHILE_STATEMENT,
        _PHP_DO_STATEMENT,
        _PHP_SWITCH_STATEMENT,
    }
)


#: Per-language message for an unconditional / headerless infinite loop
#: (the ``_check_loop_node`` path). Languages absent here fall back to the
#: generic wording.
_INFINITE_LOOP_MESSAGE_BY_LANG: dict[str, str] = {
    "go": "`for {}` loop has no break - potential infinite loop",
    "php": "`for (;;)` loop has no break - potential infinite loop",
    "c": "`for (;;)` loop has no break - potential infinite loop",
    "cpp": "`for (;;)` loop has no break - potential infinite loop",
}


def _is_php_infinite_for(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a headerless ``for (;;)`` (PHP's infinite loop).

    A bounded ``for`` carries a ``condition`` field; the infinite form omits
    it (``for (;;)`` / ``for (; ; $i++)``), so absence of the condition is the
    infinite marker.
    """
    return node.child_by_field_name("condition") is None


def _php_break_level(break_node: tree_sitter.Node) -> int:
    """Return the numeric level of a PHP ``break`` (``break 2;`` -> 2, bare ``break;`` -> 1)."""
    for child in break_node.named_children:
        if child.type == _PHP_INTEGER:
            text = node_text(child)
            return int(text) if text.isdigit() else 1
    return 1


def _php_has_exiting_break(loop_node: tree_sitter.Node) -> bool:
    """Return True if *loop_node* contains a ``break`` that exits it (PHP numeric levels).

    PHP has no named labels; ``break N`` exits N enclosing loop / ``switch``
    constructs. A break exits *loop_node* iff its level exceeds the number of
    loop / switch boundaries between it and *loop_node* (depth): a bare
    ``break;`` (level 1) in direct scope (depth 0) exits; a ``break 2;`` inside
    one nested loop (depth 1) exits too. A ``break;`` inside a nested
    ``switch`` (depth 1) exits only the switch, not *loop_node* - matching the
    behaviour of the named-label languages.
    """
    funcs = tuple(_PHP_FUNCTION_TYPES)
    stack: list[tuple[tree_sitter.Node, int]] = [(loop_node, 0)]
    while len(stack) > 0:
        node, depth = stack.pop()
        if node is not loop_node and node.type in funcs:
            continue
        if node.type == _PHP_BREAK_STATEMENT and _php_break_level(node) >= depth + 1:
            return True
        child_depth = depth + 1 if (node is not loop_node and node.type in _PHP_LOOP_SWITCH_TYPES) else depth
        stack.extend((child, child_depth) for child in node.named_children)
    return False


def _is_c_infinite_for(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a headerless ``for (;;)`` (C's infinite loop).

    A bounded C ``for`` carries a ``condition`` field; the infinite form omits
    it (``for (;;)`` / ``for (i = 0; ; i++)``), so absence of the condition is
    the infinite marker.
    """
    return node.child_by_field_name("condition") is None


def _c_labels_defined_in(loop_node: tree_sitter.Node, skip: tuple[str, ...]) -> set[str]:
    """Return the set of label names defined within *loop_node* (skipping nested functions)."""
    names: set[str] = set()
    for child in walk(loop_node, skip_types=skip):
        if child.type != _C_LABELED_STATEMENT:
            continue
        label = child.child_by_field_name("label")
        if label is not None:
            names.add(node_text(label))
    return names


def _c_has_goto_exit(loop_node: tree_sitter.Node) -> bool:
    """Return True if *loop_node*'s body contains a ``goto`` that leaves the loop.

    A ``goto`` whose target label is defined *within* the loop body is intra-loop
    control flow (a jump to a label still inside the loop), not an exit, so it
    does not satisfy rule 5's bound requirement - a ``while (1)`` that only ever
    jumps back inside itself is still unbounded. Only a ``goto`` targeting a label
    outside the loop counts as an exit. Nested function bodies are skipped.
    """
    skip = tuple(_C_FUNCTION_TYPES)
    inner_labels = _c_labels_defined_in(loop_node, skip)
    for child in walk(loop_node, skip_types=skip):
        if child.type != _C_GOTO_STATEMENT:
            continue
        target = child.child_by_field_name("label")
        if target is not None and node_text(target) not in inner_labels:
            return True
    return False


def _is_go_infinite_for(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a bare ``for {}`` (Go's ``while true``).

    Go's only loop keyword is ``for``; the bare form with no condition,
    no three-clause ``for_clause`` header, and no ``range_clause`` is the
    unconditional infinite loop. Those bounded forms each add a header
    named child alongside the ``body`` block, so a loop whose only
    non-comment named child is its body is the infinite form.
    """
    # Compare by ``.id`` (stable per underlying node), not ``is``:
    # tree-sitter hands out a fresh Python wrapper on every access, so
    # ``child is body`` is always False even for the same node.
    body = node.child_by_field_name("body")
    body_id = body.id if body is not None else None
    return all(child.id == body_id or child.type == _GO_COMMENT for child in node.named_children)


def _rust_label_name(label_node: tree_sitter.Node) -> str | None:
    """Return the bare name carried by a Rust ``label`` wrapper node, or None.

    Rust labels parse as a ``label`` node containing a single
    ``identifier`` child. ``node_text`` on the label itself returns
    ``'outer`` (with the leading apostrophe); reaching into the
    identifier returns the bare name (``outer``) for comparison.
    """
    ident = next((c for c in label_node.named_children if c.type == _RUST_IDENTIFIER), None)
    return node_text(ident) if ident is not None else None


# Rust nodes that can carry a *naming* label as a direct child.
# (``break_expression`` also has a ``label`` child but that's the
# *target* of the break, not a name for the break itself.)
_RUST_LABELABLE_NODE_TYPES: frozenset[str] = frozenset(
    {
        _RUST_LOOP_EXPRESSION,
        _RUST_WHILE_EXPRESSION,
        _RUST_FOR_EXPRESSION,
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
        return _rust_node_label_name(node)
    if node.type != _C_LABELED_STATEMENT:
        return None
    return _labeled_statement_name(node, lang_name)


def _rust_node_label_name(node: tree_sitter.Node) -> str | None:
    """Return the label name on a Rust loop node, or None.

    Rust labels are a direct ``label`` named child of a loop expression
    (no ``labeled_statement`` wrapper); only the loop-expression types in
    :data:`_RUST_LABELABLE_NODE_TYPES` count.
    """
    if node.type not in _RUST_LABELABLE_NODE_TYPES:
        return None
    label = next((c for c in node.named_children if c.type == _RUST_LABEL), None)
    return None if label is None else _rust_label_name(label)


def _labeled_statement_name(node: tree_sitter.Node, lang_name: str) -> str | None:
    """Return the label name on a ``labeled_statement`` (JS / TS / Java / Go).

    Java's label is the first ``identifier`` named child; Go's is a
    ``label_name`` child (``outer: for { ... }``); JS / TS expose it on the
    ``label`` field (a ``statement_identifier``).
    """
    if lang_name == "java":
        ident = next((c for c in node.named_children if c.type == IDENTIFIER), None)
        return node_text(ident) if ident is not None else None
    if lang_name == "go":
        label_name = next((c for c in node.named_children if c.type == _GO_LABEL_NAME), None)
        return node_text(label_name) if label_name is not None else None
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
    if lang_name == "php":
        # PHP uses numeric ``break N`` levels rather than named labels, so a
        # dedicated depth-counting walk replaces both the direct-break and
        # labelled-break paths.
        return _php_has_exiting_break(while_node)
    if lang_name in (_C_EXTRA_NAME, _CPP_EXTRA_NAME):
        # C / C++ have no labelled break; a ``goto`` leaving the loop is the multi-level
        # escape. ``_c_has_goto_exit`` counts a ``goto`` as an exit only when its
        # target label is defined outside the loop body - a ``goto`` to an in-loop
        # label is intra-loop control flow, not an exit, so a ``while (1)`` that
        # only jumps back inside itself stays unbounded.
        return _has_direct_break(while_node, lang_name) or _c_has_goto_exit(while_node)
    if _has_direct_break(while_node, lang_name):
        return True
    if lang_name not in (_JS_EXTRA_NAME, _TS_EXTRA_NAME, _JAVA_EXTRA_NAME, _RUST_EXTRA_NAME, _GO_EXTRA_NAME):
        return False
    return _has_outward_labelled_break(while_node, lang_name)


def _is_c_literal_true(condition: tree_sitter.Node) -> bool:
    """Return True if *condition* is C's always-true loop condition.

    C has two infinite-``while`` spellings: ``while (1)`` (a ``number_literal``
    whose text is ``1``) and ``while (true)`` (``true`` from ``<stdbool.h>``,
    which parses as an ``identifier`` or a ``true`` keyword node). Any other
    non-zero constant (``while (2)``) is deliberately NOT treated as the
    canonical infinite idiom.
    """
    text = node_text(condition)
    if condition.type == _C_NUMBER_LITERAL:
        return text == "1"
    return condition.type in (_C_IDENTIFIER, _C_TRUE) and text == _C_TRUE


def _is_literal_true(condition: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *condition* is the ``true`` literal under *lang_name*'s grammar.

    Most languages emit a dedicated ``true`` node type for the boolean
    literal, so a single node-type comparison suffices. Rust collapses
    both boolean literals into a single ``boolean_literal`` node type,
    so the check additionally inspects the token text. C is special-cased
    (``1`` or ``true``) via :func:`_is_c_literal_true`.
    """
    if lang_name in (_C_EXTRA_NAME, _CPP_EXTRA_NAME):
        return _is_c_literal_true(condition)
    expected = _TRUE_LITERAL_BY_LANG[lang_name]
    if condition.type != expected:
        return False
    # Rust and PHP collapse both boolean literals into one node type, so the
    # token text must be inspected; the others emit a dedicated ``true`` node.
    if lang_name not in (_RUST_EXTRA_NAME, _PHP_EXTRA_NAME):
        return True
    text = node_text(condition)
    # PHP boolean literals are case-insensitive (``true`` / ``TRUE`` / ``True``
    # all denote the same value), so ``while (TRUE)`` must still fire SAFE501.
    # Rust's ``true`` is case-sensitive, so it keeps the exact comparison.
    return text.lower() == TRUE if lang_name == _PHP_EXTRA_NAME else text == TRUE


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
    language = (EXTRA_NAME, _JS_EXTRA_NAME, _TS_EXTRA_NAME, _JAVA_EXTRA_NAME, _RUST_EXTRA_NAME, _GO_EXTRA_NAME, _PHP_EXTRA_NAME, _C_EXTRA_NAME, _CPP_EXTRA_NAME)

    @staticmethod
    def _while_true_construct(lang_name: str) -> str:
        """Return the source-language spelling of ``while true`` for messages."""
        if lang_name in (_JS_EXTRA_NAME, _TS_EXTRA_NAME, _JAVA_EXTRA_NAME):
            return "while (true)"
        if lang_name == "rust":
            return "while true"
        if lang_name == "cpp":
            return "while (true)"
        if lang_name == "c":
            return "while (1)"
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
        # ``while (true)`` check would silently skip. C++ wraps the condition
        # in a ``condition_clause`` instead (it can hold a declaration), whose
        # inner expression is likewise the first named child - unwrap it too.
        while condition.type in (_C_PARENTHESIZED_EXPRESSION, _C_CONDITION_CLAUSE):
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
        """Return a violation if an unconditional loop lacks an exiting break.

        Covers Rust's ``loop { }`` and Go's bare ``for {}``. For Go the
        ``for_statement`` node type also represents bounded loops, so only
        the headerless infinite form (see :func:`_is_go_infinite_for`) is
        considered; bounded ``for`` loops return ``None`` immediately.
        """
        if lang_name == _GO_EXTRA_NAME and not _is_go_infinite_for(node):
            return None
        if lang_name == _PHP_EXTRA_NAME and not _is_php_infinite_for(node):
            return None
        if lang_name in (_C_EXTRA_NAME, _CPP_EXTRA_NAME) and not _is_c_infinite_for(node):
            return None
        if _has_exiting_break(node, lang_name):
            return None
        message = _INFINITE_LOOP_MESSAGE_BY_LANG.get(lang_name, "loop has no break - potential infinite loop")
        return self._make_violation_for_node(filepath, node, message)

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
