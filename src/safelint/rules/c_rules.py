"""C-only rules - the "Power of Ten homecoming".

C is Holzmann's original target language, so several clauses every other
language *adapts away* apply literally here. These five rules express them
directly, slotted by category into the existing 1xx-3xx bands:

* **SAFE106** ``nonlocal_jumps`` (1xx, rule 1 literal) - every ``goto`` and
  every ``setjmp`` / ``longjmp`` family call. **Enabled, severity=warning**:
  ``goto err`` cleanup chains are idiomatic, so it surfaces without blocking;
  annotate sanctioned cleanups with ``// nosafe: SAFE106``.
* **SAFE310** ``dynamic_allocation`` (3xx, rule 3 literal) - calls to the
  ``malloc`` family. Disabled by default (embedded / safety-critical opt-in).
* **SAFE311** ``complex_macro`` (3xx, rule 8) - function-like macros using
  token paste (``##``) or ``__VA_ARGS__``, and object-like macros whose
  replacement is not a balanced syntactic unit. Disabled by default.
* **SAFE312** ``conditional_compilation`` (3xx, rule 8) - every ``#if`` /
  ``#ifdef`` / ``#ifndef`` beyond the include-guard pattern. Disabled by default.
* **SAFE313** ``restricted_pointers`` (3xx, rule 9 literal) - declarators with
  more than one pointer level (``int **p``) and function-pointer declarators.
  Disabled by default.

All read their configurable lists from ``_c``-suffixed config keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list
from safelint.languages._node_utils import call_name, node_text, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# ---------------------------------------------------------------------------
# SAFE106 - nonlocal_jumps (enabled, warning)
# ---------------------------------------------------------------------------


class NonlocalJumpsRule(BaseRule):
    """Flag ``goto`` statements and ``setjmp`` / ``longjmp`` family calls (Power of Ten rule 1)."""

    name = "nonlocal_jumps"
    code = "SAFE106"
    language = ("c",)

    _DEFAULT_JUMP_CALLS: ClassVar[list[str]] = ["setjmp", "longjmp", "sigsetjmp", "siglongjmp"]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every ``goto_statement`` and every configured non-local-jump call."""
        jump_calls = frozenset(_validated_string_list(self.config.get("nonlocal_jump_calls_c", self._DEFAULT_JUMP_CALLS), "nonlocal_jump_calls_c"))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type == "goto_statement":
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        "`goto` is a non-local jump - restrict control flow to structured constructs (Power of Ten rule 1); annotate a sanctioned `goto err` cleanup with `// nosafe: SAFE106`",
                    )
                )
            elif node.type == "call_expression" and call_name(node) in jump_calls:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'"{call_name(node)}()" performs a non-local jump - it bypasses structured control flow (Power of Ten rule 1)',
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# SAFE310 - dynamic_allocation (disabled)
# ---------------------------------------------------------------------------


class DynamicAllocationRule(BaseRule):
    """Flag heap allocation / free calls - rule 3 bans dynamic memory after init."""

    name = "dynamic_allocation"
    code = "SAFE310"
    language = ("c",)

    _DEFAULT_ALLOCATION_CALLS: ClassVar[list[str]] = ["malloc", "calloc", "realloc", "aligned_alloc", "free", "strdup"]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every configured heap-allocation / free call."""
        allocation_calls = frozenset(_validated_string_list(self.config.get("allocation_calls_c", self._DEFAULT_ALLOCATION_CALLS), "allocation_calls_c"))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "call_expression":
                continue
            name = call_name(node)
            if name is not None and name in allocation_calls:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'"{name}()" allocates / frees heap memory - prefer static or stack allocation after initialisation (Power of Ten rule 3)',
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# SAFE311 - complex_macro (disabled)
# ---------------------------------------------------------------------------


def _macro_replacement_text(node: tree_sitter.Node) -> str:
    """Return the replacement-list text of a ``#define`` (its ``preproc_arg``), or ``""``."""
    value = node.child_by_field_name("value")
    return node_text(value) if value is not None else ""


def _scan_char(ch: str, quote: str, *, escaped: bool) -> tuple[bool, str, bool]:
    """Advance the quote-stripping state machine one char; return ``(keep, quote, escaped)``.

    ``quote`` is the active delimiter (``""`` when outside a literal). Characters
    inside a string or char literal are never kept, so brackets within them do
    not affect the balance count.
    """
    if quote == "":
        if ch in ('"', "'"):
            return False, ch, False
        return True, "", False
    if escaped:
        return False, quote, False
    if ch == "\\":
        return False, quote, True
    if ch == quote:
        return False, "", False
    return False, quote, False


def _strip_quoted(text: str) -> str:
    """Return *text* with the contents of string/char literals removed."""
    out: list[str] = []
    quote = ""
    escaped = False
    for ch in text:
        keep, quote, escaped = _scan_char(ch, quote, escaped=escaped)
        if keep:
            out.append(ch)
    return "".join(out)


_BRACKET_PAIRS = {")": "(", "}": "{", "]": "["}


def _is_unbalanced(text: str) -> bool:
    """Return True if *text*'s ``()`` / ``{}`` / ``[]`` are not properly nested and matched.

    Brackets inside string and char literals (e.g. ``#define OPEN "["``) are
    stripped first so they do not register as unbalanced. Stack-based matching
    (not bare counting) so order/nesting errors like ``)(`` or ``([)]`` - which
    have equal open/close counts - are still caught as non-complete units.
    """
    stripped = _strip_quoted(text)
    stack: list[str] = []
    for ch in stripped:
        if ch in "({[":
            stack.append(ch)
            continue
        opener = _BRACKET_PAIRS.get(ch)
        if opener is not None and (not stack or stack.pop() != opener):
            return True
    return bool(stack)


class ComplexMacroRule(BaseRule):
    """Flag function-like macros using ``##`` / ``__VA_ARGS__`` and unbalanced object-like macros (rule 8)."""

    name = "complex_macro"
    code = "SAFE311"
    language = ("c",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag complex preprocessor macros (token paste, variadic, or non-balanced replacement)."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            reason = self._macro_violation_reason(node)
            if reason is not None:
                violations.append(self._make_violation_for_node(filepath, node, reason))
        return violations

    @staticmethod
    def _macro_violation_reason(node: tree_sitter.Node) -> str | None:
        """Return a reason string if *node* is a complex macro, else None."""
        if node.type == "preproc_function_def":
            text = _macro_replacement_text(node)
            if "##" in text:
                return "Function-like macro uses token pasting (`##`) - macros must be simple, complete syntactic units (Power of Ten rule 8)"
            if "__VA_ARGS__" in text:
                return "Variadic macro (`__VA_ARGS__`) - macros must be simple, complete syntactic units (Power of Ten rule 8)"
            return None
        if node.type == "preproc_def" and _is_unbalanced(_macro_replacement_text(node)):
            return "Object-like macro replacement is not a complete syntactic unit (unbalanced brackets) - macros must be simple (Power of Ten rule 8)"
        return None


# ---------------------------------------------------------------------------
# SAFE312 - conditional_compilation (disabled)
# ---------------------------------------------------------------------------


def _ifndef_guard_name(node: tree_sitter.Node) -> str | None:
    """Return the guard macro name of an ``#ifndef X`` directive, or None.

    The grammar uses ``preproc_ifdef`` for both ``#ifdef`` and ``#ifndef``; only
    the ``#ifndef`` form is the include-guard candidate. The directive keyword is
    the node's first child token.
    """
    if node.type != "preproc_ifdef":
        return None
    first = node.children[0] if node.children else None
    if first is None or node_text(first) != "#ifndef":
        return None
    name = node.child_by_field_name("name")
    return node_text(name) if name is not None else None


def _first_body_define_name(node: tree_sitter.Node) -> str | None:
    """Return the macro name defined by the *first* body statement of *node*, or None.

    ``named_children`` is ``[condition-name, first-body, ...]`` so the opener is
    index 1. Requiring the ``#define`` to be first - rather than merely present
    somewhere in the block - stops an unrelated ``#define`` deeper in the body
    from disguising a real conditional as an include guard.
    """
    opener = node.named_children[1] if len(node.named_children) > 1 else None
    if opener is None or opener.type != "preproc_def":
        return None
    defined = opener.child_by_field_name("name")
    return node_text(defined) if defined is not None else None


def _is_include_guard(node: tree_sitter.Node) -> bool:
    """Return True if *node* is an ``#ifndef X`` whose body *opens* with ``#define X``."""
    guard = _ifndef_guard_name(node)
    return guard is not None and _first_body_define_name(node) == guard


class ConditionalCompilationRule(BaseRule):
    """Flag ``#if`` / ``#ifdef`` / ``#ifndef`` beyond include guards - each doubles the test matrix (rule 8)."""

    name = "conditional_compilation"
    code = "SAFE312"
    language = ("c",)

    _MESSAGE: ClassVar[str] = "Conditional compilation directive - each `#if` / `#ifdef` doubles the build configurations to test (Power of Ten rule 8); prefer runtime configuration"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every conditional-compilation directive that is not an include guard."""
        return [self._make_violation_for_node(filepath, node, self._MESSAGE) for node in walk(tree.root_node) if node.type in ("preproc_if", "preproc_ifdef") and not _is_include_guard(node)]


# ---------------------------------------------------------------------------
# SAFE313 - restricted_pointers (disabled)
# ---------------------------------------------------------------------------


def _pointer_depth(declarator: tree_sitter.Node | None) -> int:
    """Return the consecutive ``pointer_declarator`` nesting depth at *declarator* (bounded loop)."""
    depth = 0
    cur = declarator
    for _ in range(32):
        if cur is None or cur.type != "pointer_declarator":
            return depth
        depth += 1
        cur = cur.child_by_field_name("declarator")
    return depth


class RestrictedPointersRule(BaseRule):
    """Flag multi-level pointers (``int **p``) and function-pointer declarators (Power of Ten rule 9)."""

    name = "restricted_pointers"
    code = "SAFE313"
    language = ("c",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag declarators with more than one pointer level, and function-pointer declarators."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            reason = self._pointer_violation_reason(node)
            if reason is not None:
                violations.append(self._make_violation_for_node(filepath, node, reason))
        return violations

    @staticmethod
    def _pointer_violation_reason(node: tree_sitter.Node) -> str | None:
        """Return a reason if *node* is a restricted-pointer declarator, else None.

        A function pointer parses as a ``function_declarator`` whose ``declarator``
        is a ``parenthesized_declarator`` (``void (*fp)(int)``); a normal function
        has an ``identifier`` there. A multi-level pointer is an *outermost*
        ``pointer_declarator`` (its parent is not itself a ``pointer_declarator``)
        with depth > 1, so each ``**`` chain is reported once.
        """
        if node.type == "function_declarator":
            inner = node.child_by_field_name("declarator")
            if inner is not None and inner.type == "parenthesized_declarator":
                return "Function-pointer declarator - rule 9 restricts pointer use to a single level of dereferencing (Power of Ten rule 9)"
            return None
        if node.type == "pointer_declarator":
            parent = node.parent
            if (parent is None or parent.type != "pointer_declarator") and _pointer_depth(node) > 1:
                return "Declarator has more than one level of pointer indirection - rule 9 restricts pointers to a single dereference (Power of Ten rule 9)"
        return None
