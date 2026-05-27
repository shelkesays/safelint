"""Rust-idiom rules: SAFE204 / SAFE205 / SAFE306 / SAFE602.

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
* **SAFE306** ``dangerous_mem_ops`` (side effects) - flags calls to
  ``std::mem::transmute``, ``std::mem::forget``, ``std::mem::zeroed``,
  and ``std::mem::uninitialized``. All four have safer Rust idioms.
* **SAFE602** ``undocumented_unsafe`` (documentation) - flags
  ``unsafe { ... }`` blocks that lack a ``// SAFETY:`` comment on a
  preceding line documenting the safety invariants.

All four are disabled by default; opt in via
``[tool.safelint.rules.<name>] enabled = true``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.languages._node_utils import node_text, walk
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _rust_macro_name(macro_node: tree_sitter.Node) -> str | None:
    """Return the bareword macro name from a Rust ``macro_invocation`` ``macro`` field.

    Bare ``panic!`` resolves to ``"panic"``; scoped ``std::panic!``
    also resolves to ``"panic"`` (trailing identifier extracted).
    """
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
        return None
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
                continue
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
            return None
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
