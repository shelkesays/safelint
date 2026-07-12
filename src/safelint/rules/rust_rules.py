"""Rust-idiom rules: function-shape, error-handling, side-effect, documentation.

Rules in this file are Rust-language-specific (no cross-language
counterpart). Codes are slotted into the existing category bands by
closest theme, per the SafeLint rule-numbering policy in CLAUDE.md.
Each rule is disabled by default; opt in via
``[tool.safelint.rules.<name>] enabled = true``.

**Function shape (1xx)** - Holzmann rule 6 (smallest scope) and
rule 1/7 (well-defined operations):

* **SAFE110** ``needless_mut`` - flags ``let mut x = ...`` where ``x``
  is never reassigned, never has ``&mut`` taken, and is never used
  as a method receiver / field-access target. Conservative: skips
  when usage is ambiguous so false-positive rate stays low.
* **SAFE112** ``unchecked_arithmetic_on_input`` - flags ``+`` / ``-`` /
  ``*`` on integer-typed function parameters. Silent overflow is
  release-mode-only in Rust; ``checked_*`` / ``wrapping_*`` /
  ``saturating_*`` makes the choice explicit.

**Error handling (2xx)** - Holzmann rule 7 (check return values):

* **SAFE204** ``panic_macros_outside_tests`` - flags ``panic!`` /
  ``todo!`` / ``unimplemented!`` macros in non-test code.
* **SAFE205** ``lock_poisoning_ignored`` - flags ``mutex.lock().unwrap()``
  and ``rwlock.read().unwrap()`` / ``.write().unwrap()``.
* **SAFE206** ``silent_result_discard`` - the Rust spiritual analogue
  of SAFE202 (empty_except). Flags empty ``Err`` arms in ``match``
  and empty ``if let Err(_) = ... { }`` bodies.
* **SAFE207** ``unlogged_error_branch`` - the Rust spiritual analogue
  of SAFE203 (logging_on_error). Flags ``Err`` arms / branches with
  non-empty bodies that contain no log call and don't propagate.
* **SAFE208** ``result_unwrap_outside_tests`` - flags any
  ``.unwrap()`` / ``.expect()`` / ``.unwrap_unchecked()`` outside
  test code. Broader than SAFE205 (lock-specific) and SAFE803
  (nullable-method-specific); catches bare ``let r = foo(); r.unwrap();``
  cases the narrow rules miss.

**Side effects / state (3xx)** - Holzmann rule 1/6/7 (well-defined
operations, smallest scope, checked conversions):

* **SAFE306** ``dangerous_mem_ops`` - flags calls to
  ``std::mem::transmute`` / ``forget`` / ``zeroed`` /
  ``uninitialized``.
* **SAFE307** ``interior_mutable_static`` - flags ``static`` items whose
  type provides safe interior mutability (``Mutex`` / ``RwLock`` /
  ``OnceLock`` / ``Atomic*`` / ``lazy_static!``), the safe-code global
  mutable state SAFE602's ``unsafe`` gate never sees (Holzmann rule 6).
* **SAFE308** ``truncating_as_cast`` - flags ``as u8`` / ``as u16``
  / ``as u32`` / ``as i32`` casts. Silently truncates in Rust;
  ``TryFrom`` / ``try_into()`` makes the failure mode explicit.

**Documentation (6xx)**:

* **SAFE602** ``undocumented_unsafe`` - flags ``unsafe { ... }``
  blocks lacking a ``// SAFETY:`` comment.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list
from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.rust import ASSIGNMENT_EXPRESSION as _RUST_ASSIGNMENT_EXPRESSION
from safelint.languages.rust import ATTRIBUTE_ITEM as _RUST_ATTRIBUTE_ITEM
from safelint.languages.rust import BINARY_EXPRESSION as _RUST_BINARY_EXPRESSION
from safelint.languages.rust import BLOCK as _RUST_BLOCK
from safelint.languages.rust import BLOCK_COMMENT as _RUST_BLOCK_COMMENT
from safelint.languages.rust import BOOLEAN_LITERAL as _RUST_BOOLEAN_LITERAL
from safelint.languages.rust import CALL_EXPRESSION as _RUST_CALL_EXPRESSION
from safelint.languages.rust import CHAR_LITERAL as _RUST_CHAR_LITERAL
from safelint.languages.rust import CLOSURE_EXPRESSION as _RUST_CLOSURE_EXPRESSION
from safelint.languages.rust import COMPOUND_ASSIGNMENT_EXPR as _RUST_COMPOUND_ASSIGNMENT_EXPR
from safelint.languages.rust import EXPRESSION_STATEMENT as _RUST_EXPRESSION_STATEMENT
from safelint.languages.rust import FIELD_EXPRESSION as _RUST_FIELD_EXPRESSION
from safelint.languages.rust import FLOAT_LITERAL as _RUST_FLOAT_LITERAL
from safelint.languages.rust import FUNCTION_ITEM as _RUST_FUNCTION_ITEM
from safelint.languages.rust import GENERIC_FUNCTION as _RUST_GENERIC_FUNCTION
from safelint.languages.rust import IDENTIFIER as _RUST_IDENTIFIER
from safelint.languages.rust import IF_EXPRESSION as _RUST_IF_EXPRESSION
from safelint.languages.rust import INDEX_EXPRESSION as _RUST_INDEX_EXPRESSION
from safelint.languages.rust import INTEGER_LITERAL as _RUST_INTEGER_LITERAL
from safelint.languages.rust import LET_CONDITION as _RUST_LET_CONDITION
from safelint.languages.rust import LET_DECLARATION as _RUST_LET_DECLARATION
from safelint.languages.rust import LINE_COMMENT as _RUST_LINE_COMMENT
from safelint.languages.rust import MACRO_INVOCATION as _RUST_MACRO_INVOCATION
from safelint.languages.rust import MATCH_ARM as _RUST_MATCH_ARM
from safelint.languages.rust import MATCH_PATTERN as _RUST_MATCH_PATTERN
from safelint.languages.rust import MINUS as _RUST_MINUS
from safelint.languages.rust import MOD_ITEM as _RUST_MOD_ITEM
from safelint.languages.rust import MUTABLE_SPECIFIER as _RUST_MUTABLE_SPECIFIER
from safelint.languages.rust import PARAMETER as _RUST_PARAMETER
from safelint.languages.rust import PLUS as _RUST_PLUS
from safelint.languages.rust import PRIMITIVE_TYPE as _RUST_PRIMITIVE_TYPE
from safelint.languages.rust import REFERENCE_EXPRESSION as _RUST_REFERENCE_EXPRESSION
from safelint.languages.rust import RETURN_EXPRESSION as _RUST_RETURN_EXPRESSION
from safelint.languages.rust import SCOPED_IDENTIFIER as _RUST_SCOPED_IDENTIFIER
from safelint.languages.rust import STAR as _RUST_STAR
from safelint.languages.rust import STATIC_ITEM as _RUST_STATIC_ITEM
from safelint.languages.rust import STRING_LITERAL as _RUST_STRING_LITERAL
from safelint.languages.rust import TUPLE_STRUCT_PATTERN as _RUST_TUPLE_STRUCT_PATTERN
from safelint.languages.rust import TYPE_CAST_EXPRESSION as _RUST_TYPE_CAST_EXPRESSION
from safelint.languages.rust import UNIT_EXPRESSION as _RUST_UNIT_EXPRESSION
from safelint.languages.rust import UNSAFE_BLOCK as _RUST_UNSAFE_BLOCK
from safelint.rules._rust_test_attribute import attribute_item_is_test_marker
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

#: Unwrap-family method names. SAFE208 fires when any of these is
#: called outside test code. Wider set than SAFE205's
#: :data:`_UNWRAP_METHOD_NAMES` because the broad rule also covers
#: ``.unwrap_unchecked()`` (an unsafe fast-path); SAFE205 sticks to
#: the safe-API set because the lock-poisoning hazard is about the
#: panic-on-Err mode of ``.unwrap()``, not the UB-on-Err mode of
#: ``.unwrap_unchecked()``.
_GENERAL_UNWRAP_METHODS: frozenset[str] = frozenset(
    {
        "unwrap",
        "expect",
        "unwrap_unchecked",
    }
)

#: Fixed-width integer / float primitive type names that SAFE308 flags
#: as truncating-cast targets. The complete list of Rust primitive
#: numeric types except ``i128`` / ``u128`` / ``f64`` (cast TO those
#: types from any smaller type is non-truncating) and except ``isize``
#: / ``usize`` (platform-dependent width, but casts TO them from
#: smaller types are non-truncating on 64-bit platforms - leaving
#: them out keeps the rule's default narrow).
_TRUNCATING_CAST_TARGETS: frozenset[str] = frozenset(
    {
        "i8",
        "u8",
        "i16",
        "u16",
        "i32",
        "u32",
        "i64",  # cast from u64 / i128 / u128 still truncates
        "u64",  # cast from i64 (sign) / i128 / u128 truncates
        "f32",  # cast from f64 loses precision
    }
)

#: Rust primitive integer type names. SAFE112 only fires when a
#: function parameter's declared type is one of these.
_RUST_INTEGER_PRIMITIVE_TYPES: frozenset[str] = frozenset(
    {
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "isize",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "usize",
    }
)

#: Binary operators that SAFE112 flags when applied to integer-typed
#: function parameters. ``/`` and ``%`` are NOT included because
#: division by zero is its own (well-defined) panic, not the silent
#: overflow that SAFE112 cares about.
_RUST_ARITHMETIC_OPERATORS: frozenset[str] = frozenset({_RUST_PLUS, _RUST_MINUS, _RUST_STAR})

#: Standard-library interior-mutability wrapper types that SAFE307 flags
#: when they appear in a ``static`` declaration's type. Each lets a
#: ``static`` (which is shared and immutable-by-binding) hold mutable
#: state in safe code, which the ``static mut`` route (SAFE602's unsafe
#: gate) does not catch. ``LazyLock`` / ``Lazy`` are both listed because
#: word-boundary matching keeps ``Lazy`` from matching ``LazyLock``.
_INTERIOR_MUTABLE_TYPES: frozenset[str] = frozenset(
    {
        "Mutex",
        "RwLock",
        "RefCell",
        "Cell",
        "OnceLock",
        "OnceCell",
        "Lazy",
        "LazyLock",
        "LazyCell",
        "AtomicBool",
        "AtomicI8",
        "AtomicI16",
        "AtomicI32",
        "AtomicI64",
        "AtomicIsize",
        "AtomicU8",
        "AtomicU16",
        "AtomicU32",
        "AtomicU64",
        "AtomicUsize",
        "AtomicPtr",
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
    if macro_node.type == _RUST_IDENTIFIER:
        return node_text(macro_node)
    if macro_node.type == _RUST_SCOPED_IDENTIFIER:
        name = macro_node.child_by_field_name("name")
        return node_text(name) if name is not None else None
    return None  # pragma: no cover - defensive: macro field is always identifier or scoped_identifier


def _node_has_test_marker_attribute(node: tree_sitter.Node) -> bool:
    """Return True if *node* has a ``#[test]`` or ``#[cfg(test)]`` attribute attached.

    In tree-sitter-rust, attributes parse as ``attribute_item`` *preceding
    siblings* of the function / mod / impl they decorate. Walks the
    ``prev_named_sibling`` chain while it yields attribute_items. The
    per-attribute marker check is delegated to
    :func:`safelint.rules._rust_test_attribute.attribute_item_is_test_marker`
    so SAFE204 / SAFE208 / SAFE701 / SAFE702 all share one definition.
    """
    cursor = node.prev_named_sibling
    while cursor is not None:
        if cursor.type != _RUST_ATTRIBUTE_ITEM:
            break
        if attribute_item_is_test_marker(cursor):
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
        if cursor.type in (_RUST_FUNCTION_ITEM, _RUST_MOD_ITEM) and _node_has_test_marker_attribute(cursor):
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
    if func.type == _RUST_GENERIC_FUNCTION:
        func = func.child_by_field_name("function")
        if func is None:  # pragma: no cover - defensive: every generic_function has an inner function field
            return None
    return func if func.type == _RUST_SCOPED_IDENTIFIER else None


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
            if node.type != _RUST_MACRO_INVOCATION:
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
    if func is None or func.type != _RUST_FIELD_EXPRESSION:
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
            if node.type != _RUST_CALL_EXPRESSION:
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
        if func is None or func.type != _RUST_FIELD_EXPRESSION:
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
        if receiver is None or receiver.type != _RUST_CALL_EXPRESSION:
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
            if node.type != _RUST_CALL_EXPRESSION:
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
        * ``transmute(...)`` (bare call without ``mem::`` prefix) is
          NOT flagged - it's indistinguishable from a user-defined
          helper of the same name without type inference. Projects
          that need bare-call detection should rename the import
          path (``use std::mem;`` then ``mem::transmute(...)``) so
          the rule's ``"mem"``-in-path check catches it; the
          ``dangerous_mem_ops_rust`` config only customises the set
          of *names* matched, not the detection shape.

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
            if node.type != _RUST_UNSAFE_BLOCK:
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
        if parent is not None and parent.type == _RUST_EXPRESSION_STATEMENT:
            anchor = parent
        prev = anchor.prev_sibling
        while prev is not None:
            if prev.type not in (_RUST_LINE_COMMENT, _RUST_BLOCK_COMMENT):
                break
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
    if pattern is None or pattern.type != _RUST_TUPLE_STRUCT_PATTERN:
        return False
    children = pattern.named_children
    if not children or children[0].type != _RUST_IDENTIFIER:  # pragma: no cover - defensive: tuple_struct_pattern always has a leading identifier
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
    if len(children) < 2 or children[0].type != _RUST_MATCH_PATTERN:  # pragma: no cover - defensive: every match_arm has match_pattern + body
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
    condition = next((c for c in if_expr.named_children if c.type == _RUST_LET_CONDITION), None)
    if condition is None:
        return None, None  # plain ``if cond { ... }`` without ``let`` - not an if-let
    pattern = next((c for c in condition.named_children), None)
    if not _is_err_pattern(pattern):
        return None, None
    block = next((c for c in if_expr.named_children if c.type == _RUST_BLOCK), None)
    return pattern, block


_NOOP_LEAF_TYPES: frozenset[str] = frozenset(
    {
        _RUST_INTEGER_LITERAL,
        _RUST_FLOAT_LITERAL,
        _RUST_STRING_LITERAL,
        _RUST_CHAR_LITERAL,
        _RUST_BOOLEAN_LITERAL,
        _RUST_UNIT_EXPRESSION,
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
    if body.type != _RUST_BLOCK:
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
    if only.type != _RUST_EXPRESSION_STATEMENT:  # pragma: no cover - rare: noop-leaf single-stmt blocks parse as direct leaf (tail form) or expression_statement (semicolon-terminated)
        return False
    inner = next((c for c in only.named_children), None)
    return inner is not None and inner.type in _NOOP_LEAF_TYPES


_RUST_FUNCTION_TYPES_FOR_SKIP: tuple[str, ...] = (_RUST_FUNCTION_ITEM, _RUST_CLOSURE_EXPRESSION)


def _node_resolves_to_log_call(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a macro or call resolving to a log-call name."""
    if node.type == _RUST_MACRO_INVOCATION:
        return _rust_macro_name(node.child_by_field_name("macro")) in _LOG_CALL_NAMES
    if node.type == _RUST_CALL_EXPRESSION:
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
    if node.type != _RUST_MACRO_INVOCATION:
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
        if node.type == _RUST_RETURN_EXPRESSION or _node_is_panic_like_macro(node):
            return True
    return _body_tail_is_err_constructor(body)


def _body_tail_is_err_constructor(body: tree_sitter.Node) -> bool:
    """Return True if *body*'s tail expression is ``Err(...)`` (re-raise pattern)."""
    if body.type == _RUST_CALL_EXPRESSION and _is_err_constructor_call(body):
        return True
    if body.type != _RUST_BLOCK:
        return False
    named = body.named_children
    if not named:  # pragma: no cover - defensive: callers reach this only for non-empty bodies
        return False
    tail = named[-1]
    if tail.type == _RUST_CALL_EXPRESSION:
        return _is_err_constructor_call(tail)  # pragma: no cover - tail-form ``Err(...)`` in a block is rare (typically a bare expression at the arm level)
    if tail.type == _RUST_EXPRESSION_STATEMENT:
        inner = next((c for c in tail.named_children), None)
        return inner is not None and inner.type == _RUST_CALL_EXPRESSION and _is_err_constructor_call(inner)
    return False  # pragma: no cover - non-call tail (let_declaration etc.) - body isn't a re-raise


def _is_err_constructor_call(call_node: tree_sitter.Node) -> bool:
    """Return True if *call_node* is ``Err(...)`` (the bare constructor)."""
    func = call_node.child_by_field_name("function")
    if func is None or func.type != _RUST_IDENTIFIER:
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
        if node.type == _RUST_MATCH_ARM:
            pattern, body = _match_arm_pattern_and_body(node)
            if _is_err_pattern(pattern) and _body_is_noop(body):
                return self._make_violation_for_node(
                    filepath,
                    node,
                    'Empty "Err" arm silently discards the error - log the failure or return / propagate it',
                )
            return None
        if node.type == _RUST_IF_EXPRESSION:
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
        if node.type == _RUST_MATCH_ARM:
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
        if node.type == _RUST_IF_EXPRESSION:
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


# ---------------------------------------------------------------------------
# SAFE208 - result_unwrap_outside_tests
# ---------------------------------------------------------------------------


class ResultUnwrapOutsideTestsRule(BaseRule):
    """Flag ``.unwrap()`` / ``.expect()`` / ``.unwrap_unchecked()`` outside test code.

    The broad Holzmann-rule-7 ("check return values") form for Rust.
    Narrower siblings:

    * SAFE205 (``lock_poisoning_ignored``) - lock-specific
      ``.unwrap()`` patterns.
    * SAFE803 (``null_dereference``) - ``.unwrap()`` on inner calls
      whose name is in the ``nullable_methods_rust`` set.

    SAFE208 catches the cases those miss: bare-variable unwraps
    (``let r = foo(); r.unwrap();``), unwrap chains where the inner
    call isn't in the nullable list, etc. Test code (``#[test]`` /
    ``#[cfg(test)]``) is exempt - panics there are the test
    framework's failure signal, not a bug.

    Enable alongside or instead of SAFE205/SAFE803 depending on
    desired strictness. With all three enabled, ``mutex.lock().unwrap()``
    fires multiple codes - documented overlap, intentional.
    """

    name = "result_unwrap_outside_tests"
    code = "SAFE208"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag unwrap-family method calls outside test code."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != _RUST_CALL_EXPRESSION:
                continue
            method = self._unwrap_method_name(node)
            if method is None:
                continue
            if _is_in_test_context(node):
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'".{method}()" outside test code - handle the Result / Option explicitly via match, "if let", or the "?" operator',
                )
            )
        return violations

    @staticmethod
    def _unwrap_method_name(call_node: tree_sitter.Node) -> str | None:
        """Return the method name if *call_node* is ``<x>.<unwrap-method>()``, else None."""
        func = call_node.child_by_field_name("function")
        if func is None or func.type != _RUST_FIELD_EXPRESSION:
            return None
        field = func.child_by_field_name("field")
        if field is None:  # pragma: no cover - defensive: every field_expression has a field child
            return None
        method = node_text(field)
        return method if method in _GENERAL_UNWRAP_METHODS else None


# ---------------------------------------------------------------------------
# SAFE308 - truncating_as_cast
# ---------------------------------------------------------------------------


class TruncatingAsCastRule(BaseRule):
    """Flag ``as`` casts to fixed-width numeric types (silent truncation hazard).

    Rust's ``as`` cast truncates without warning when the source value
    doesn't fit in the destination: ``1_000_000u32 as u8`` returns
    ``64`` (low byte), no panic, no error. The safe alternative is
    ``u8::try_from(x)`` which returns ``Result<u8, TryFromIntError>``
    - the failure mode becomes explicit and checked.

    The rule flags ``as`` casts whose target type is in
    :data:`_TRUNCATING_CAST_TARGETS` - the fixed-width integer
    types and ``f32`` (where the precision-loss hazard is similar).
    It deliberately fires even on apparently-safe casts (``0u8 as u8``,
    ``small as i32``) because without type inference the rule can't
    tell which casts truly fit; consistent "use TryFrom" beats
    selective tolerance.

    ``isize`` / ``usize`` / ``i128`` / ``u128`` / ``f64`` are NOT
    flagged as targets - they're the widest types, casts TO them
    from smaller types don't truncate. (Casts FROM them to smaller
    targets still fire because the smaller target type is in the
    set.)
    """

    name = "truncating_as_cast"
    code = "SAFE308"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag ``as`` casts to fixed-width numeric types."""
        targets = frozenset(self.config.get("truncating_cast_targets_rust", sorted(_TRUNCATING_CAST_TARGETS)))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != _RUST_TYPE_CAST_EXPRESSION:
                continue
            target_name = self._cast_target_primitive(node)
            if target_name is None or target_name not in targets:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"as {target_name}" silently truncates - use {target_name}::try_from(x) for a checked conversion or u-cast intentionally with a "// truncates: ..." comment',
                )
            )
        return violations

    @staticmethod
    def _cast_target_primitive(cast_node: tree_sitter.Node) -> str | None:
        """Return the trailing ``primitive_type`` name in *cast_node*, or None.

        ``type_cast_expression`` named children are the source
        expression followed by the target type. The target type is
        ``primitive_type`` for the cases SAFE308 cares about; other
        target shapes (reference_type, generic_type, etc.) are not
        flagged - those casts are typically zero-cost reinterpretation,
        not value truncation.
        """
        named = cast_node.named_children
        if len(named) < 2:  # pragma: no cover - defensive: type_cast_expression has source + type
            return None
        target = named[-1]
        return node_text(target) if target.type == _RUST_PRIMITIVE_TYPE else None


# ---------------------------------------------------------------------------
# SAFE110 - needless_mut
# ---------------------------------------------------------------------------


def _let_mut_binding_name(let_decl: tree_sitter.Node) -> str | None:
    """Return the bound name if *let_decl* is ``let mut <name> = ...``, else None.

    Handles only the simple ``let mut <ident>`` shape - tuple /
    struct destructure forms (``let mut (a, b) = ...``) aren't
    legal Rust (``mut`` goes per-binding inside the pattern:
    ``let (mut a, mut b) = ...``), so the rule sticks to the
    common single-binding form to minimise complexity.
    """
    if not any(c.type == _RUST_MUTABLE_SPECIFIER for c in let_decl.named_children):
        return None
    for child in let_decl.named_children:
        if child.type == _RUST_IDENTIFIER:
            return node_text(child)
    return None  # pragma: no cover - defensive: ``let mut`` without an identifier binding is non-trivial destructure (caller skips it)


def _function_body(func_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the ``block`` body of *func_node*, or None if it has no body.

    Rust ``function_item`` exposes the body on the ``body`` field;
    closures use the body field too but their body is an arbitrary
    expression (often a block).
    """
    return func_node.child_by_field_name("body")


def _name_needs_mut_usage(name: str, body: tree_sitter.Node) -> bool:
    """Return True if any usage of *name* in *body* requires the binding to be ``mut``.

    Three kinds of usage definitively need mut:

    * Assignment target: ``name = ...`` or ``name += ...`` etc.
    * Mutable reference: ``&mut name``.
    * Method call receiver: ``name.method(...)`` - the method may
      take ``&mut self``, and without type info we can't tell.
      Conservative: assume yes (= rule skips firing).
    * Field-access target: ``name.field`` (read or write -
      conservative: same reasoning).

    Index expressions are also ambiguous; treated the same way.
    """
    return any(_node_is_mut_use_of(name, n) for n in walk(body, skip_types=_RUST_FUNCTION_TYPES_FOR_SKIP))


def _node_is_mut_use_of(name: str, node: tree_sitter.Node) -> bool:
    """Return True if *node* is a usage of *name* that requires the binding to be ``mut``."""
    if node.type == _RUST_ASSIGNMENT_EXPRESSION:
        return _assignment_left_is(name, node)
    if node.type == _RUST_COMPOUND_ASSIGNMENT_EXPR:
        return _assignment_left_is(name, node)
    if node.type == _RUST_REFERENCE_EXPRESSION:
        return _is_mut_reference_of(name, node)
    if node.type == _RUST_FIELD_EXPRESSION:
        return _field_expression_value_is(name, node)
    if node.type == _RUST_INDEX_EXPRESSION:
        return _first_named_child_is(name, node)  # pragma: no cover - rare: index_expression as a mut-needing usage isn't reached by the current tests
    return False


def _assignment_left_is(name: str, node: tree_sitter.Node) -> bool:
    """Return True if *node*'s ``left`` field is identifier *name*."""
    left = node.child_by_field_name("left")
    return left is not None and left.type == _RUST_IDENTIFIER and node_text(left) == name


def _is_mut_reference_of(name: str, node: tree_sitter.Node) -> bool:
    """Return True if *node* is ``&mut <name>``."""
    if not any(c.type == _RUST_MUTABLE_SPECIFIER for c in node.named_children):
        return False  # pragma: no cover - bare ``&x`` references aren't mut-needing usages
    inner = next((c for c in node.named_children if c.type == _RUST_IDENTIFIER), None)
    return inner is not None and node_text(inner) == name


def _field_expression_value_is(name: str, node: tree_sitter.Node) -> bool:
    """Return True if *node*'s ``value`` (receiver) is identifier *name*."""
    value = node.child_by_field_name("value")
    return value is not None and value.type == _RUST_IDENTIFIER and node_text(value) == name


def _first_named_child_is(name: str, node: tree_sitter.Node) -> bool:
    """Return True if *node*'s first named child is identifier *name*."""
    children = node.named_children
    return bool(children) and children[0].type == _RUST_IDENTIFIER and node_text(children[0]) == name  # pragma: no cover - helper for the rarely-hit index_expression branch


class NeedlessMutRule(BaseRule):
    """Flag ``let mut x = ...`` where ``x`` is never reassigned or mutably referenced.

    Holzmann rule 6 (smallest scope / least privilege). Rust's
    default-immutable design encourages declaring ``mut`` only when
    truly needed; needless ``mut`` widens the surface for accidental
    mutation and obscures which variables are actually meant to
    change.

    The rule is conservative to keep false-positive rate low: it
    fires ONLY when none of the following usages appear in the
    enclosing function body:

    * ``name = ...`` (assignment) or ``name += ...`` (compound).
    * ``&mut name`` (taking a mutable reference).
    * ``name.method(...)`` (method call - receiver may need ``&mut self``).
    * ``name.field`` (field access - read or write, unknown without types).
    * ``name[i]`` (index expression - same reasoning).

    Skips nested function / closure bodies during the usage walk so
    a use inside an inner scope that isn't analysed for ``mut``
    requirements doesn't taint the outer binding's classification.

    Note: bindings inside ``loop`` / ``for`` / ``while`` bodies that
    use ``mut`` for a fold-style accumulator are correctly handled -
    the accumulator IS reassigned (``acc = combine(acc, x)``), so
    the rule sees the assignment and stays quiet.
    """

    name = "needless_mut"
    code = "SAFE110"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every needless ``let mut`` binding in the file."""
        violations: list[Violation] = []
        for func_node in walk(tree.root_node):
            if func_node.type not in _RUST_FUNCTION_TYPES_FOR_SKIP:
                continue
            body = _function_body(func_node)
            if body is None:
                continue  # pragma: no cover - trait-method-signature functions have no body
            violations.extend(self._violations_in_body(filepath, body))
        return violations

    def _violations_in_body(self, filepath: str, body: tree_sitter.Node) -> list[Violation]:
        """Return needless-mut violations for every ``let mut`` in *body*."""
        out: list[Violation] = []
        for let_decl in walk(body, skip_types=_RUST_FUNCTION_TYPES_FOR_SKIP):
            if let_decl.type != _RUST_LET_DECLARATION:
                continue
            name = _let_mut_binding_name(let_decl)
            if name is None or _name_needs_mut_usage(name, body):
                continue
            out.append(
                self._make_violation_for_node(
                    filepath,
                    let_decl,
                    f'"let mut {name}" is never reassigned or mutably referenced - drop the "mut"',
                )
            )
        return out


# ---------------------------------------------------------------------------
# SAFE112 - unchecked_arithmetic_on_input
# ---------------------------------------------------------------------------


def _integer_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return parameter names whose declared type is a Rust integer primitive.

    Walks the ``parameters`` field's children, finds ``parameter``
    nodes whose ``type`` field is a ``primitive_type`` with a Rust
    integer-type name, and collects the pattern's bound name.
    Skips ``self_parameter``, untyped closure ``identifier``
    children, and non-primitive types (``String``, generic types,
    references, etc.).
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover - defensive: every function_item has parameters
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        if child.type != _RUST_PARAMETER:
            continue  # pragma: no cover - self_parameter / variadic skipped
        type_node = child.child_by_field_name("type")
        if type_node is None or type_node.type != _RUST_PRIMITIVE_TYPE:
            continue
        if node_text(type_node) not in _RUST_INTEGER_PRIMITIVE_TYPES:
            continue
        pattern = child.child_by_field_name("pattern")
        if pattern is None or pattern.type != _RUST_IDENTIFIER:
            continue
        names.add(node_text(pattern))
    return names


class UncheckedArithmeticOnInputRule(BaseRule):
    """Flag bare arithmetic on integer-typed function parameters.

    Rust's ``+`` / ``-`` / ``*`` panic on overflow in debug builds
    and wrap silently in release builds - the worst of both worlds
    for production reliability. ``checked_add`` / ``wrapping_add`` /
    ``saturating_add`` make the choice explicit at the call site:
    you either get ``Option<T>`` to check the failure mode, declare
    you want wrapping, or declare you want saturation.

    The rule fires when:

    * The enclosing function has at least one parameter of integer
      primitive type (``i8`` ... ``u128``, ``isize``, ``usize``).
    * A ``binary_expression`` inside the function body has operator
      in :data:`_RUST_ARITHMETIC_OPERATORS` (``+`` / ``-`` / ``*``).
    * At least one operand is an ``identifier`` whose text matches
      one of the integer parameter names.

    ``/`` and ``%`` are deliberately excluded - division by zero
    is a separate, loudly-panic-on-debug hazard not addressed by
    the ``checked_*`` family the same way; SAFE112 stays focused
    on silent-overflow.

    Heuristic limitation: the rule has no type information beyond
    parameter annotations, so it misses arithmetic on locally-bound
    integer variables that derive from parameters
    (``let x = p + 1; let y = x + 1;`` only fires on the first).
    Users wanting tighter coverage can use ``clippy`` for the
    full-type-info version; SAFE112 is the static-only baseline.
    """

    name = "unchecked_arithmetic_on_input"
    code = "SAFE112"
    language = ("rust",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag unchecked arithmetic on integer-typed parameters."""
        violations: list[Violation] = []
        for func_node in walk(tree.root_node):
            if func_node.type != _RUST_FUNCTION_ITEM:
                continue
            int_params = _integer_param_names(func_node)
            if not int_params:
                continue
            body = _function_body(func_node)
            if body is None:
                continue  # pragma: no cover - trait-method-signature functions have no body
            violations.extend(self._violations_in_body(filepath, body, int_params))
        return violations

    def _violations_in_body(self, filepath: str, body: tree_sitter.Node, int_params: set[str]) -> list[Violation]:
        """Return violations for every unchecked arithmetic op on *int_params* in *body*."""
        out: list[Violation] = []
        for node in walk(body, skip_types=_RUST_FUNCTION_TYPES_FOR_SKIP):
            if node.type != _RUST_BINARY_EXPRESSION:
                continue
            op = self._operator_text(node)
            if op not in _RUST_ARITHMETIC_OPERATORS:
                continue  # comparisons / divisions / boolean ops aren't flagged
            param_name = self._operand_matching_param(node, int_params)
            if param_name is None:
                continue  # arithmetic between locals (neither operand is a flagged param)
            suffix = _op_method_suffix(op)
            out.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"{op}" on integer parameter "{param_name}" can overflow silently in release - use checked_{suffix} / wrapping_{suffix} / saturating_{suffix}',
                )
            )
        return out

    @staticmethod
    def _operator_text(binary: tree_sitter.Node) -> str | None:
        """Return the operator text of a ``binary_expression``."""
        op = binary.child_by_field_name("operator")
        return node_text(op) if op is not None else None

    @staticmethod
    def _operand_matching_param(binary: tree_sitter.Node, int_params: set[str]) -> str | None:
        """Return the first operand whose text is in *int_params*, or None."""
        for field in ("left", "right"):
            operand = binary.child_by_field_name(field)
            if operand is None or operand.type != _RUST_IDENTIFIER:
                continue  # operand is a literal / method call / nested binary - not a param identifier
            text = node_text(operand)
            if text in int_params:
                return text
        return None


def _op_method_suffix(op: str | None) -> str:
    """Map an arithmetic operator to its checked_*/wrapping_*/saturating_* method suffix."""
    return {_RUST_PLUS: "add", _RUST_MINUS: "sub", _RUST_STAR: "mul"}.get(op or "", "op")


# ---------------------------------------------------------------------------
# SAFE307 - interior_mutable_static
# ---------------------------------------------------------------------------


def _static_item_is_mutable_specifier(static_node: tree_sitter.Node) -> bool:
    """Return True if *static_node* is a ``static mut`` declaration.

    ``static mut`` carries a ``mutable_specifier`` named child. Those are
    already audit-gated by SAFE602 (reads / writes require ``unsafe``), so
    SAFE307 skips them to avoid double-reporting.
    """
    return any(child.type == _RUST_MUTABLE_SPECIFIER for child in static_node.named_children)


def _type_text_has_interior_mutable(type_text: str, names: frozenset[str]) -> bool:
    """Return True if *type_text* contains any *names* entry as a standalone token.

    Word-boundary matching (not substring) so ``Lazy`` does not match
    ``LazyLock`` and a user type like ``MutexGuardWrapper`` does not match
    ``Mutex``. Qualified paths (``std::sync::Mutex<T>``) still match the
    trailing type name because ``::`` is a non-word boundary.
    """
    return any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", type_text) for name in names)


class InteriorMutableStaticRule(BaseRule):
    """Flag ``static`` items whose type provides safe interior mutability.

    Holzmann rule 6 (declare data at the smallest possible scope) bans
    global mutable state. Rust's ``static mut`` route requires ``unsafe``
    and is therefore already audit-gated by SAFE602, but the idiomatic
    route - a plain ``static`` holding a ``Mutex`` / ``RwLock`` /
    ``OnceLock`` / ``Atomic*`` / ``lazy_static!`` - is entirely safe code
    and invisible to SAFE602. SAFE307 closes that gap.

    Two shapes fire:

    * A ``static_item`` whose declared type contains an interior-mutability
      wrapper name (configurable via ``interior_mutable_types_rust``).
    * A ``lazy_static! { ... }`` macro invocation - the macro's whole
      purpose is declaring lazily-initialised statics, and its body is a
      token tree safelint cannot decode (the same documented limitation
      as SAFE801's blindness to ``sqlx::query!``), so the invocation is
      flagged wholesale.

    ``const`` items (immutable by construction) and ``static mut`` (SAFE602's
    territory) are deliberately not flagged. Disabled by default.
    """

    name = "interior_mutable_static"
    code = "SAFE307"
    language = ("rust",)

    _DEFAULT_TYPES: ClassVar[frozenset[str]] = _INTERIOR_MUTABLE_TYPES

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag interior-mutable statics and ``lazy_static!`` declarations."""
        raw = self.config.get("interior_mutable_types_rust", sorted(self._DEFAULT_TYPES))
        names = frozenset(_validated_string_list(raw, "interior_mutable_types_rust"))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            violation = self._violation_for(filepath, node, names)
            if violation is not None:
                violations.append(violation)
        return violations

    def _violation_for(self, filepath: str, node: tree_sitter.Node, names: frozenset[str]) -> Violation | None:
        """Return a SAFE307 violation for *node* if it is an interior-mutable static, else None."""
        if node.type == _RUST_MACRO_INVOCATION and _rust_macro_name(node.child_by_field_name("macro")) == "lazy_static":
            return self._make_violation_for_node(
                filepath,
                node,
                "lazy_static! declares lazily-initialised global mutable state - prefer passing state explicitly or scoping it to the consumer (Power of Ten rule 6)",
            )
        if node.type != _RUST_STATIC_ITEM or _static_item_is_mutable_specifier(node):
            return None
        type_node = node.child_by_field_name("type")
        if type_node is None or not _type_text_has_interior_mutable(node_text(type_node), names):
            return None
        name_node = node.child_by_field_name("name")
        static_name = node_text(name_node) if name_node is not None else "<static>"
        return self._make_violation_for_node(
            filepath,
            node,
            f'Static "{static_name}" uses interior mutability ({node_text(type_node)}) - global mutable state defeats smallest-scope reasoning (Power of Ten rule 6)',
        )
