"""Rust-idiom rules: SAFE204 / SAFE205 / SAFE206 / SAFE207 / SAFE306 / SAFE602.

Rules in this file are Rust-language-specific (no cross-language
counterpart). Codes are slotted into the existing category bands by
closest theme, per the SafeLint rule-numbering policy in CLAUDE.md:

* **SAFE204** ``panic_macros_outside_tests`` (error handling) - flags
  ``panic!`` / ``todo!`` / ``unimplemented!`` macros in non-test code
  (production paths should return ``Result`` instead of crashing).
* **SAFE205** ``lock_poisoning_ignored`` (error handling) - flags
  ``mutex.lock().unwrap()`` and ``rwlock.read().unwrap()`` /
  ``rwlock.write().unwrap()`` - patterns that silently swallow lock
  poisoning instead of handling the ``PoisonError``.
* **SAFE206** ``silent_result_discard`` (error handling) - the Rust
  spiritual analogue of SAFE202 (empty_except). Flags empty ``Err``
  arms in ``match`` and empty ``if let Err(_) = ... { }`` bodies.
* **SAFE207** ``unlogged_error_branch`` (error handling) - the Rust
  spiritual analogue of SAFE203 (logging_on_error). Flags ``Err``
  arms / branches with non-empty bodies that contain no log call
  and don't propagate the error.
* **SAFE306** ``dangerous_mem_ops`` (side effects) - flags calls to
  ``std::mem::transmute``, ``std::mem::forget``, ``std::mem::zeroed``,
  and ``std::mem::uninitialized``. All four have safer Rust idioms.
* **SAFE602** ``undocumented_unsafe`` (documentation) - flags
  ``unsafe { ... }`` blocks that lack a ``// SAFETY:`` comment on a
  preceding line documenting the safety invariants.

All disabled by default; opt in via
``[tool.safelint.rules.<name>] enabled = true``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_PANIC_MACRO_NAMES: frozenset[str] = frozenset({"panic", "todo", "unimplemented"})

#: ``unreachable!()`` is deliberately excluded - it's the idiomatic Rust
#: way to express "this branch can't be hit" (genuine unreachable code
#: pattern) and firing on it produces false positives in valid match
#: arms / Option::None handling. Users who want it flagged can override
#: ``panic_macros_rust`` to add it.
_LOCK_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "lock",
        "read",
        "write",
        "try_lock",
        "try_read",
        "try_write",
    }
)

_UNWRAP_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "unwrap",
        "expect",
    }
)

#: The std::mem footguns. Per-default list is conservative - everything
#: here has a safe alternative in modern Rust:
#:
#: * ``transmute`` -> use ``From`` / ``TryFrom`` / ``bytemuck``
#: * ``forget`` -> use ``mem::ManuallyDrop`` or just let Drop run
#: * ``zeroed`` -> use ``MaybeUninit::zeroed()`` (requires unsafe to
#:   read, makes the hazard explicit at the use site)
#: * ``uninitialized`` -> deprecated in 1.39+, use ``MaybeUninit``
_DANGEROUS_MEM_OP_NAMES: frozenset[str] = frozenset(
    {
        "transmute",
        "transmute_copy",
        "forget",
        "zeroed",
        "uninitialized",
    }
)

#: Log-call macro names recognised by SAFE207 as "this error branch is
#: logged". Covers the ``log`` crate (``log::error!`` / ``warn!`` /
#: ``info!`` / ``debug!`` / ``trace!``), the ``tracing`` crate (same
#: names plus ``event!`` / ``span!``), and bare stderr / stdout writers
#: (``eprintln!`` / ``eprint!`` / ``println!`` / ``print!`` / ``dbg!``).
#: ``log::log!`` (the generic macro) is included via the bare ``log``
#: entry. ``call_name`` (extended for Rust ``scoped_identifier``) and
#: ``_rust_macro_name`` both strip qualifiers, so ``log::error!`` and
#: ``error!`` and ``tracing::error!`` all resolve to ``"error"``.
_LOG_CALL_NAMES: frozenset[str] = frozenset(
    {
        # log / tracing crate level macros
        "error",
        "warn",
        "info",
        "debug",
        "trace",
        "event",
        "log",
        # stderr / stdout writers (also count as "made the failure visible")
        "eprintln",
        "eprint",
        "println",
        "print",
        "dbg",
    }
)

#: Panic-like macros that, when present in an error-handling branch,
#: count as "the failure was made loudly observable" - SAFE207 exempts
#: bodies containing them. Same set as SAFE204's recognised panic
#: macros plus ``unreachable!`` (which is excluded from SAFE204's
#: panic-in-non-test check but DOES make a failure visible).
_PANIC_LIKE_MACROS: frozenset[str] = frozenset(
    {
        "panic",
        "todo",
        "unimplemented",
        "unreachable",
    }
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _rust_macro_name(macro_node: tree_sitter.Node | None) -> str | None:
    """Return the bareword macro name from a Rust ``macro_invocation`` ``macro`` field.

    Bare ``panic!`` resolves to ``"panic"``; scoped ``std::panic!``
    also resolves to ``"panic"`` (trailing identifier extracted).
    Returns ``None`` when *macro_node* is None (e.g. a malformed
    ``macro_invocation`` lacking the ``macro`` field) so callers can
    pass ``child_by_field_name("macro")`` directly.
    """
    if macro_node is None:  # pragma: no cover - defensive: every macro_invocation has a macro field
        return None
    if macro_node.type == "identifier":
        return node_text(macro_node)
    if macro_node.type == "scoped_identifier":
        name = macro_node.child_by_field_name("name")
        return node_text(name) if name is not None else None
    return None  # pragma: no cover - defensive: macro field is always identifier or scoped_identifier


def _attribute_marks_test(attr_item: tree_sitter.Node) -> bool:
    """Return True if *attr_item* is ``#[test]`` or ``#[cfg(test)]``.

    Mirrors :func:`safelint.rules.test_coverage._attribute_is_rust_test_marker`
    but takes the outer ``attribute_item`` so the call site doesn't
    need to know about the wrapper. Returns False for any other
    attribute shape (``#[derive(...)]``, ``#[cfg(unix)]``, ``#[inline]``,
    etc.).
    """
    attribute = next((c for c in attr_item.named_children if c.type == "attribute"), None)
    if attribute is None:  # pragma: no cover - defensive: every attribute_item wraps an attribute
        return False
    children = attribute.named_children
    if not children:  # pragma: no cover - defensive: every attribute has at least a name child
        return False
    first = children[0]
    if first.type != "identifier":  # pragma: no cover - defensive: path-attribute shape (#[a::b]) is rare and not a test marker
        return False
    first_name = node_text(first)
    if first_name == "test":
        return True
    if first_name != "cfg":
        return False
    return _cfg_token_tree_mentions_test(children[1:])


def _cfg_token_tree_mentions_test(children: list[tree_sitter.Node]) -> bool:
    """Return True if any ``token_tree`` in *children* directly contains ``identifier "test"``."""
    for child in children:
        if child.type != "token_tree":  # pragma: no cover - ``#[cfg = "value"]`` shape isn't a test marker
            continue
        if any(inner.type == "identifier" and node_text(inner) == "test" for inner in child.named_children):
            return True
    return False


def _node_has_test_marker_attribute(node: tree_sitter.Node) -> bool:
    """Return True if *node* has a ``#[test]`` or ``#[cfg(test)]`` attribute attached.

    In tree-sitter-rust, attributes parse as ``attribute_item`` *preceding
    siblings* of the function / mod / impl they decorate. Walks the
    ``prev_named_sibling`` chain while it yields attribute_items.
    """
    cursor = node.prev_named_sibling
    while cursor is not None and cursor.type == "attribute_item":  # nosafe: SAFE501
        if _attribute_marks_test(cursor):
            return True
        cursor = cursor.prev_named_sibling
    return False


def _is_in_test_context(node: tree_sitter.Node) -> bool:
    """Return True if *node* sits inside test code.

    Test code means EITHER:

    * the enclosing function is ``#[test]``-attributed, OR
    * any ancestor function / mod is ``#[cfg(test)]``-gated.

    Walks parents up to the source-file root. Stops at the first match.
    """
    cursor: tree_sitter.Node | None = node.parent
    while cursor is not None:
        if cursor.type in ("function_item", "mod_item") and _node_has_test_marker_attribute(cursor):
            return True
        cursor = cursor.parent
    return False


def _scoped_path_text(scoped_id: tree_sitter.Node) -> str:
    """Return the full source text of a ``scoped_identifier`` for prefix matching.

    Used by SAFE306 to distinguish ``mem::transmute`` (the dangerous
    stdlib call) from a user-defined ``transmute`` in some other path.
    Returns the raw text including ``::`` separators.
    """
    return node_text(scoped_id)


def _unwrap_to_scoped_identifier(func: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Peel a ``generic_function`` wrapper and return the inner ``scoped_identifier``, or None.

    Bare calls (``transmute(x)``) parse as ``identifier`` on the
    ``function`` field; turbofish calls (``mem::transmute::<u8, i8>(0)``)
    parse as ``generic_function`` wrapping a ``scoped_identifier``;
    qualified non-turbofish calls (``mem::transmute(0)``) parse as
    ``scoped_identifier`` directly. Only the last two are matchable
    for SAFE306 - returns ``None`` for everything else.
    """
    if func is None:  # pragma: no cover - defensive: every call_expression has a function field
        return None
    if func.type == "generic_function":
        func = func.child_by_field_name("function")
        if func is None:  # pragma: no cover - defensive: every generic_function has an inner function field
            return None
    return func if func.type == "scoped_identifier" else None


# ---------------------------------------------------------------------------
# SAFE204 - panic_macros_outside_tests
# ---------------------------------------------------------------------------


class PanicMacrosOutsideTestsRule(BaseRule):
    """Flag ``panic!`` / ``todo!`` / ``unimplemented!`` macros in non-test code.

    Production code should return ``Result<_, _>`` instead of panicking.
    Panics in test code (``#[test] fn`` or ``#[cfg(test)] mod``) are
    expected and intentional - they're the test framework's failure
    signal. The rule's test-context detection walks parent
    ``function_item`` / ``mod_item`` nodes for ``#[test]`` /
    ``#[cfg(test)]`` attributes.

    ``unreachable!()`` is deliberately NOT in the default panic-macro
    set - it's idiomatic for "this branch is statically impossible"
    (exhaustive match arms, Option::None handling after a ``is_some()``
    check). Add it via ``panic_macros_rust`` if your project wants it
    flagged.
    """

    name = "panic_macros_outside_tests"
    code = "SAFE204"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag panic-macro invocations outside test code."""
        macros = frozenset(self.config.get("panic_macros_rust", sorted(_PANIC_MACRO_NAMES)))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "macro_invocation":
                continue
            macro_field = node.child_by_field_name("macro")
            if macro_field is None:  # pragma: no cover - defensive: every macro_invocation has a macro field
                continue
            name = _rust_macro_name(macro_field)
            if name is None or name not in macros:
                continue
            if _is_in_test_context(node):
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"{name}!" macro in non-test code - return Result<_, _> instead of panicking, or move this branch under #[cfg(test)]',
                )
            )
        return violations


# ---------------------------------------------------------------------------
# SAFE205 - lock_poisoning_ignored
# ---------------------------------------------------------------------------


def _is_lock_method_call(call_node: tree_sitter.Node) -> str | None:
    """If *call_node* is ``<receiver>.lock()`` / ``.read()`` / ``.write()`` etc., return the method name."""
    func = call_node.child_by_field_name("function")
    if func is None or func.type != "field_expression":
        return None  # pragma: no cover - guarded by caller (SAFE205 only reaches here for field_expression calls)
    field = func.child_by_field_name("field")
    if field is None:  # pragma: no cover - defensive: every field_expression has a field child
        return None
    method = node_text(field)
    return method if method in _LOCK_METHOD_NAMES else None


class LockPoisoningIgnoredRule(BaseRule):
    """Flag ``mutex.lock().unwrap()`` / ``rwlock.read().unwrap()`` etc.

    When a thread panics while holding a ``Mutex`` / ``RwLock`` guard,
    the lock becomes *poisoned*: subsequent ``.lock()`` calls return
    ``Err(PoisonError)``. ``.unwrap()`` silently propagates the panic
    to every other lock holder, often masking the original failure
    and producing a fan-out of related panics that obscure the root
    cause.

    The idiomatic alternative is to ``match`` on the ``PoisonResult``,
    recover from poisoning explicitly (``e.into_inner()`` returns the
    guard regardless of poisoning), or use a ``parking_lot::Mutex``
    which has no poison state. The rule fires on every
    ``<call>.unwrap()`` / ``<call>.expect(...)`` where ``<call>``'s
    trailing method name is in :data:`_LOCK_METHOD_NAMES`.
    """

    name = "lock_poisoning_ignored"
    code = "SAFE205"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag ``.unwrap()`` / ``.expect()`` on a lock-acquisition call."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "call_expression":
                continue
            unwrap_method = self._unwrap_method_or_none(node)
            if unwrap_method is None:
                continue
            inner = self._inner_lock_call(node)
            if inner is None:
                continue  # pragma: no cover - covered by ``_inner_lock_call``'s None-receiver branch (defensive)
            lock_method = _is_lock_method_call(inner)
            if lock_method is None:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'".{lock_method}().{unwrap_method}()" ignores lock poisoning - match on PoisonError or call .into_inner() to recover explicitly',
                )
            )
        return violations

    @staticmethod
    def _unwrap_method_or_none(call_node: tree_sitter.Node) -> str | None:
        """If *call_node* is ``<x>.unwrap()`` / ``<x>.expect(...)``, return the method name."""
        func = call_node.child_by_field_name("function")
        if func is None or func.type != "field_expression":
            return None  # pragma: no cover - SAFE205 walks every call_expression; most aren't field_expression calls
        field = func.child_by_field_name("field")
        if field is None:  # pragma: no cover - defensive: every field_expression has a field child
            return None
        method = node_text(field)
        return method if method in _UNWRAP_METHOD_NAMES else None

    @staticmethod
    def _inner_lock_call(call_node: tree_sitter.Node) -> tree_sitter.Node | None:
        """Return the inner call expression being unwrapped, or None."""
        func = call_node.child_by_field_name("function")
        if func is None:  # pragma: no cover - guarded by caller
            return None
        receiver = func.child_by_field_name("value")
        if receiver is None or receiver.type != "call_expression":
            return None  # pragma: no cover - the .unwrap-on-non-call case is rare and not the SAFE205 hazard shape
        return receiver


# ---------------------------------------------------------------------------
# SAFE306 - dangerous_mem_ops
# ---------------------------------------------------------------------------


class DangerousMemOpsRule(BaseRule):
    """Flag calls to ``std::mem::transmute`` / ``forget`` / ``zeroed`` / ``uninitialized``.

    All four are footguns:

    * ``transmute`` - reinterpret bits as a different type. Almost
      always replaceable with ``From`` / ``TryFrom`` / ``bytemuck::cast``.
    * ``forget`` - skip Drop. Use ``mem::ManuallyDrop`` if you need
      explicit Drop control; raw ``forget`` leaks the resource without
      the type system flagging it.
    * ``zeroed`` - construct a zero-initialised value of any type.
      Sound only for types whose all-zero bit pattern is a valid
      value (which the type system doesn't enforce). Use
      ``MaybeUninit::zeroed`` + an explicit unsafe read instead, so
      the hazard is visible at the use site.
    * ``uninitialized`` - deprecated since 1.39 in favour of
      ``MaybeUninit::uninit()``; same rationale as ``zeroed``.

    The rule walks ``call_expression`` nodes and checks the trailing
    bareword on the ``function`` field against the configured set.
    Path qualification is checked when the function is a
    ``scoped_identifier`` to avoid firing on a user-defined ``transmute``
    in some unrelated module - the qualifier must contain ``"mem"``
    (matches both ``std::mem::transmute`` and ``core::mem::transmute``,
    plus any ``mem::transmute`` after ``use std::mem``).
    """

    name = "dangerous_mem_ops"
    code = "SAFE306"
    language = ("rust",)

    _DEFAULT_DANGEROUS_OPS: ClassVar[frozenset[str]] = _DANGEROUS_MEM_OP_NAMES

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag dangerous ``std::mem`` operation calls."""
        dangerous = frozenset(self.config.get("dangerous_mem_ops_rust", sorted(self._DEFAULT_DANGEROUS_OPS)))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "call_expression":
                continue
            op_name = self._resolved_mem_op_name(node, dangerous)
            if op_name is None:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"std::mem::{op_name}" is a footgun - use a safe alternative (From/TryFrom, ManuallyDrop, or MaybeUninit) where possible',
                )
            )
        return violations

    @staticmethod
    def _resolved_mem_op_name(call_node: tree_sitter.Node, dangerous: frozenset[str]) -> str | None:
        """Return the dangerous op name if *call_node* matches; ``None`` otherwise.

        Match shape:

        * ``mem::transmute(...)`` - ``function`` is ``scoped_identifier``
          whose path contains ``"mem"``. Returns the trailing bareword.
        * ``std::mem::transmute(...)`` - ditto; path contains ``"mem"``.
        * ``transmute(...)`` (bare call) - ``function`` is ``identifier``
          matching a dangerous name. We do NOT fire on bare calls
          because they're indistinguishable from a user-defined helper
          of the same name; users who want bare-call detection can
          add ``transmute`` to the configured set explicitly via
          ``dangerous_mem_ops_rust`` and accept the false-positive
          rate.

        The ``generic_function`` wrapper (used for turbofish calls like
        ``mem::transmute::<u8, i8>(0)``) is peeled before the path check.
        """
        scoped = _unwrap_to_scoped_identifier(call_node.child_by_field_name("function"))
        if scoped is None:
            return None
        name_node = scoped.child_by_field_name("name")
        if name_node is None:  # pragma: no cover - defensive: every scoped_identifier has a name field
            return None
        op = node_text(name_node)
        if op not in dangerous or "mem" not in _scoped_path_text(scoped):
            return None
        return op


# ---------------------------------------------------------------------------
# SAFE602 - undocumented_unsafe
# ---------------------------------------------------------------------------


_SAFETY_COMMENT_PREFIX = "safety"


class UndocumentedUnsafeRule(BaseRule):
    """Flag ``unsafe { ... }`` blocks missing a ``// SAFETY:`` comment.

    The ``// SAFETY:`` comment convention (also enforced by
    ``clippy::undocumented_unsafe_blocks``) documents why a particular
    use of ``unsafe`` is sound - which invariants the surrounding code
    upholds, why the safety contract of each unsafe operation is met.
    Without it, future readers (including the original author six
    months later) can't audit whether the unsafe is still justified.

    The rule walks ``unsafe_block`` nodes and looks at the previous
    sibling chain for a ``line_comment`` whose text contains
    ``"SAFETY"`` (case-insensitive). Comments on the line *immediately
    preceding* the unsafe block count; comments separated by an
    unrelated statement do not.

    ``unsafe fn`` declarations are deliberately NOT checked here -
    they require ``/// # Safety`` doc comments rather than ``// SAFETY:``
    line comments, a different convention with its own detection
    shape. A future rule may extend this; for now SAFE602 covers
    only ``unsafe { ... }`` blocks.
    """

    name = "undocumented_unsafe"
    code = "SAFE602"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag unsafe blocks lacking a preceding ``// SAFETY:`` comment."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "unsafe_block":
                continue
            if self._has_safety_comment(node):
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    'unsafe block lacks a "// SAFETY:" comment - document the invariants that make this unsafe code sound',
                )
            )
        return violations

    @staticmethod
    def _has_safety_comment(unsafe_block: tree_sitter.Node) -> bool:
        """Return True if a ``// SAFETY:`` comment immediately precedes *unsafe_block*.

        tree-sitter-rust wraps the unsafe block in an
        ``expression_statement`` when it's used at statement position
        inside a function body, so the relevant "previous sibling" is
        the expression_statement's previous sibling, not the unsafe
        block's. The method walks up at most one statement wrapper to
        find the right anchor before checking.
        """
        anchor = unsafe_block
        parent = unsafe_block.parent
        if parent is not None and parent.type == "expression_statement":
            anchor = parent
        prev = anchor.prev_sibling
        while prev is not None and prev.type in ("line_comment", "block_comment"):  # nosafe: SAFE501
            if _SAFETY_COMMENT_PREFIX in node_text(prev).lower():
                return True
            prev = prev.prev_sibling
        return False


# ---------------------------------------------------------------------------
# Shared helpers for SAFE206 / SAFE207 (Err-branch analysis)
# ---------------------------------------------------------------------------


def _is_err_pattern(pattern: tree_sitter.Node | None) -> bool:
    """Return True if *pattern* is ``Err(...)`` (binding or wildcard).

    Both ``Err(_)`` and ``Err(e)`` parse as ``tuple_struct_pattern``
    whose first named child is an ``identifier`` ``"Err"``. The
    inner pattern (``_`` vs ``e``) doesn't matter for either rule:
    SAFE206 cares about empty body, SAFE207 cares about absence of
    log call, neither cares about the binding form.
    """
    if pattern is None or pattern.type != "tuple_struct_pattern":
        return False
    children = pattern.named_children
    if not children or children[0].type != "identifier":  # pragma: no cover - defensive: tuple_struct_pattern always has a leading identifier
        return False
    return node_text(children[0]) == "Err"


def _match_arm_pattern_and_body(arm: tree_sitter.Node) -> tuple[tree_sitter.Node | None, tree_sitter.Node | None]:
    """Return ``(pattern_inner, body)`` for *arm*, or ``(None, None)``.

    ``match_arm`` has a ``match_pattern`` first named child wrapping the
    actual pattern; the body is the second named child (either a
    ``block`` for ``Err(_) => { ... }`` or a bare expression for
    ``Err(_) => expr,``).
    """
    children = arm.named_children
    if len(children) < 2 or children[0].type != "match_pattern":  # pragma: no cover - defensive: every match_arm has match_pattern + body
        return None, None
    pattern_inner = next((c for c in children[0].named_children), None)
    return pattern_inner, children[1]


def _if_let_err_pattern_and_body(if_expr: tree_sitter.Node) -> tuple[tree_sitter.Node | None, tree_sitter.Node | None]:
    """Return ``(pattern, body_block)`` if *if_expr* is ``if let Err(...) = ...``, else ``(None, None)``.

    tree-sitter-rust parses ``if let`` as an ``if_expression`` whose
    first named child is ``let_condition``. The let_condition has the
    pattern as its first named child and the matched value second.
    The ``block`` body is the next named child of ``if_expression``.
    """
    condition = next((c for c in if_expr.named_children if c.type == "let_condition"), None)
    if condition is None:
        return None, None  # plain ``if cond { ... }`` without ``let`` - not an if-let
    pattern = next((c for c in condition.named_children), None)
    if not _is_err_pattern(pattern):
        return None, None
    block = next((c for c in if_expr.named_children if c.type == "block"), None)
    return pattern, block


_NOOP_LEAF_TYPES: frozenset[str] = frozenset(
    {
        "integer_literal",
        "float_literal",
        "string_literal",
        "char_literal",
        "boolean_literal",
        "unit_expression",
    }
)


def _body_is_noop(body: tree_sitter.Node | None) -> bool:
    """Return True if *body* is effectively empty / a no-op.

    A no-op body is one of:

    * Empty block ``{}`` - ``block`` with no named children.
    * Block containing only a single literal / unit expression
      (``{ () }``, ``{ 0 }``, ``{ "TODO" }``).
    * A bare literal / unit expression in tail-form arm
      (``Err(_) => 0,`` / ``Err(_) => (),``).
    """
    if body is None:  # pragma: no cover - defensive: callers guard body presence
        return False
    if body.type in _NOOP_LEAF_TYPES:
        return True
    if body.type != "block":
        return False
    return _block_is_noop(body)


def _block_is_noop(block: tree_sitter.Node) -> bool:
    """Return True if *block* (a ``block`` node) is empty or holds only a noop leaf."""
    named = block.named_children
    if not named:
        return True
    if len(named) > 1:
        return False
    only = named[0]
    if only.type in _NOOP_LEAF_TYPES:
        return True
    if only.type != "expression_statement":  # pragma: no cover - rare: noop-leaf single-stmt blocks parse as direct leaf (tail form) or expression_statement (semicolon-terminated)
        return False
    inner = next((c for c in only.named_children), None)
    return inner is not None and inner.type in _NOOP_LEAF_TYPES


_RUST_FUNCTION_TYPES_FOR_SKIP: tuple[str, ...] = ("function_item", "closure_expression")


def _node_resolves_to_log_call(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a macro or call resolving to a log-call name."""
    if node.type == "macro_invocation":
        return _rust_macro_name(node.child_by_field_name("macro")) in _LOG_CALL_NAMES
    if node.type == "call_expression":
        return call_name(node) in _LOG_CALL_NAMES
    return False


def _body_has_log_call(body: tree_sitter.Node | None) -> bool:
    """Return True if *body* contains at least one log-call macro or function call.

    Skips into nested function / closure bodies so a log call inside
    an inner closure that never runs synchronously doesn't count.
    """
    if body is None:  # pragma: no cover - defensive: caller guards body presence
        return False
    return any(_node_resolves_to_log_call(n) for n in walk(body, skip_types=_RUST_FUNCTION_TYPES_FOR_SKIP))


def _node_is_panic_like_macro(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a panic-like macro invocation."""
    if node.type != "macro_invocation":
        return False
    return _rust_macro_name(node.child_by_field_name("macro")) in _PANIC_LIKE_MACROS


def _body_propagates_or_panics(body: tree_sitter.Node | None) -> bool:
    """Return True if *body* propagates the error or panics loudly.

    SAFE207 exempts bodies that:

    * Contain a ``return_expression`` (any return; ``return Err(e)``,
      ``return;``, ``return some_default``).
    * Contain a panic-like macro (``panic!`` / ``todo!`` /
      ``unreachable!`` / ``unimplemented!``).
    * Tail-position re-raise: the body's single tail expression is
      a ``call_expression`` whose callee is bare ``Err``
      (``Err(_) => Err(e),`` or ``Err(e) => { Err(e) }``).

    All three signal "the failure isn't being silently absorbed",
    so logging is optional. Skips nested function / closure bodies
    so unrelated returns / panics inside closures don't count.
    """
    if body is None:  # pragma: no cover - defensive: caller guards body presence
        return False
    for node in walk(body, skip_types=_RUST_FUNCTION_TYPES_FOR_SKIP):
        if node.type == "return_expression" or _node_is_panic_like_macro(node):
            return True
    return _body_tail_is_err_constructor(body)


def _body_tail_is_err_constructor(body: tree_sitter.Node) -> bool:
    """Return True if *body*'s tail expression is ``Err(...)`` (re-raise pattern)."""
    if body.type == "call_expression" and _is_err_constructor_call(body):
        return True
    if body.type != "block":
        return False
    named = body.named_children
    if not named:  # pragma: no cover - defensive: callers reach this only for non-empty bodies
        return False
    tail = named[-1]
    if tail.type == "call_expression":
        return _is_err_constructor_call(tail)  # pragma: no cover - tail-form ``Err(...)`` in a block is rare (typically a bare expression at the arm level)
    if tail.type == "expression_statement":
        inner = next((c for c in tail.named_children), None)
        return inner is not None and inner.type == "call_expression" and _is_err_constructor_call(inner)
    return False  # pragma: no cover - non-call tail (let_declaration etc.) - body isn't a re-raise


def _is_err_constructor_call(call_node: tree_sitter.Node) -> bool:
    """Return True if *call_node* is ``Err(...)`` (the bare constructor)."""
    func = call_node.child_by_field_name("function")
    if func is None or func.type != "identifier":
        return False  # pragma: no cover - rare: ``Err`` used via method or scoped path isn't matched
    return node_text(func) == "Err"


# ---------------------------------------------------------------------------
# SAFE206 - silent_result_discard
# ---------------------------------------------------------------------------


class SilentResultDiscardRule(BaseRule):
    """Flag empty ``Err`` arms in ``match`` and empty ``if let Err(_) = ...`` bodies.

    The Rust spiritual analogue of SAFE202 (``empty_except``):
    "I caught the error and did literally nothing." Two shapes fire:

    * ``match res { Ok(v) => ..., Err(_) => {} }`` - empty Err arm.
    * ``if let Err(_) = res { }`` - empty if-let-Err body.

    Both ``Err(_)`` (wildcard) and ``Err(e)`` (with binding) trigger
    the rule when the body is empty - the silent thing is the no-op
    body, not the pattern. ``let _ = res;`` (the idiomatic explicit
    discard) does NOT fire; that's a deliberately auditable
    statement, not a silent swallow.
    """

    name = "silent_result_discard"
    code = "SAFE206"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag empty Err arms / if-let-Err bodies."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            violation = self._check_node(filepath, node)
            if violation is not None:
                violations.append(violation)
        return violations

    def _check_node(self, filepath: str, node: tree_sitter.Node) -> Violation | None:
        """Dispatch *node* to the right shape check; return a violation or None."""
        if node.type == "match_arm":
            pattern, body = _match_arm_pattern_and_body(node)
            if _is_err_pattern(pattern) and _body_is_noop(body):
                return self._make_violation_for_node(
                    filepath,
                    node,
                    'Empty "Err" arm silently discards the error - log the failure or return / propagate it',
                )
            return None
        if node.type == "if_expression":
            _, body = _if_let_err_pattern_and_body(node)
            if body is not None and _body_is_noop(body):
                return self._make_violation_for_node(
                    filepath,
                    node,
                    'Empty "if let Err(...)" body silently discards the error - log the failure or return / propagate it',
                )
        return None


# ---------------------------------------------------------------------------
# SAFE207 - unlogged_error_branch
# ---------------------------------------------------------------------------


class UnloggedErrorBranchRule(BaseRule):
    """Flag ``Err`` arms / branches with non-empty bodies that don't log and don't propagate.

    The Rust spiritual analogue of SAFE203 (``logging_on_error``):
    handling an error without logging it loses the failure context
    for debugging. Two shapes fire:

    * ``match res { Err(e) => { cleanup(); } ... }`` - Err arm body
      with no log call and no propagation.
    * ``if let Err(e) = res { cleanup(); }`` - same shape for if-let.

    The body is exempted when:

    * It contains any ``return_expression`` (propagating /
      early-returning is an explicit response).
    * It contains a panic-like macro (``panic!`` / ``todo!`` /
      ``unreachable!`` / ``unimplemented!``) - the failure is loud.
    * Its tail expression is ``Err(...)`` (re-raise pattern in
      ``Result``-returning functions).

    Empty bodies are handled by SAFE206, not this rule.
    """

    name = "unlogged_error_branch"
    code = "SAFE207"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag Err arms / if-let-Err bodies that handle the error silently."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            violation = self._check_node(filepath, node)
            if violation is not None:
                violations.append(violation)
        return violations

    def _check_node(self, filepath: str, node: tree_sitter.Node) -> Violation | None:
        """Dispatch *node* and return a violation if the Err-branch body is silent."""
        if node.type == "match_arm":
            pattern, body = _match_arm_pattern_and_body(node)
            if not _is_err_pattern(pattern):
                return None
            if self._is_silent_handle(body):
                return self._make_violation_for_node(
                    filepath,
                    node,
                    '"Err" arm handles the error but does not log it - add a log::error! / tracing::error! call or propagate the error',
                )
            return None
        if node.type == "if_expression":
            _, body = _if_let_err_pattern_and_body(node)
            if body is None:
                return None
            if self._is_silent_handle(body):
                return self._make_violation_for_node(
                    filepath,
                    node,
                    '"if let Err(...)" body handles the error but does not log it - add a log::error! / tracing::error! call or propagate the error',
                )
        return None

    @staticmethod
    def _is_silent_handle(body: tree_sitter.Node | None) -> bool:
        """Return True if *body* is non-empty, has no log call, and doesn't propagate."""
        if body is None or _body_is_noop(body):
            return False
        if _body_has_log_call(body):
            return False
        return not _body_propagates_or_panics(body)
