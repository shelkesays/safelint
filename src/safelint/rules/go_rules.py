"""Go-idiom rules (Go-only), slotted into category bands per the SafeLint numbering policy.

Go's runtime, ``go vet``, and the compiler already catch many issues other
languages leave to safelint, so the Go-specific rule set is small and targets
patterns those tools miss:

* **SAFE209** ``empty_error_check`` - flags ``if err != nil {}`` with an empty
  or comment-only body: the error was checked and then silently swallowed.
  Go's analogue of Rust's SAFE206 (``silent_result_discard``). 2xx
  (error-handling) band. Disabled by default.
* **SAFE211** ``panic_calls_outside_tests`` - flags ``panic(...)`` in
  non-``_test.go`` files; production paths should return ``error`` values
  rather than unwinding the stack. Go's analogue of Rust's SAFE204
  (``panic_macros_outside_tests``). 2xx band. Disabled by default.

Both are off by default (opinionated / project-dependent) and read their
configurable lists from ``_go``-suffixed config keys, matching the
per-language config convention. SAFE210 is intentionally unused - the v1
Go-only set is kept minimal; a goroutine-leak or unchecked-type-assertion
rule can follow with demand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list
from safelint.languages._node_utils import node_text, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# ---------------------------------------------------------------------------
# SAFE209 - empty_error_check
# ---------------------------------------------------------------------------


def _nil_error_operator(condition: tree_sitter.Node, error_names: frozenset[str]) -> str | None:
    """Return ``"!="`` / ``"=="`` if *condition* compares an error name to ``nil``, else None.

    Matches a ``binary_expression`` with an ``!=`` or ``==`` operator where
    one operand is an ``identifier`` whose text is in *error_names* and the
    other is the ``nil`` literal. Operand order is not assumed (``err != nil``
    and ``nil != err`` both match). The operator is returned so the caller can
    pick the error-handling branch: ``!=`` puts it in the ``consequence``,
    ``==`` puts it in the ``else`` (``alternative``).
    """
    if condition.type != "binary_expression":
        return None
    operator = condition.child_by_field_name("operator")
    if operator is None:  # pragma: no cover - defensive: binary_expression always has an operator
        return None
    op_text = node_text(operator)
    if op_text not in ("!=", "=="):
        return None
    left = condition.child_by_field_name("left")
    right = condition.child_by_field_name("right")
    if left is None or right is None:  # pragma: no cover - defensive: binary_expression always has both
        return None
    if _is_err_nil_pair(left, right, error_names) or _is_err_nil_pair(right, left, error_names):
        return op_text
    return None


def _is_err_nil_pair(err_side: tree_sitter.Node, nil_side: tree_sitter.Node, error_names: frozenset[str]) -> bool:
    """Return True if *err_side* is a configured error name and *nil_side* is ``nil``."""
    return err_side.type == "identifier" and node_text(err_side) in error_names and nil_side.type == "nil"


def _block_is_empty(block: tree_sitter.Node | None) -> bool:
    """Return True if *block* contains no executable statements.

    A Go ``block`` wraps its statements in a ``statement_list`` child; an
    empty ``{}`` block has no such child, and a comment-only block carries
    only ``comment`` nodes. Treating "no ``statement_list``" as empty makes
    both the bare and comment-only forms fire (the error was checked and
    then ignored either way).
    """
    if block is None:  # pragma: no cover - defensive: if_statement always has a consequence block
        return True
    return not any(child.type == "statement_list" for child in block.named_children)


class EmptyErrorCheckRule(BaseRule):
    """Flag ``if err != nil {}`` blocks that check an error and then swallow it."""

    name = "empty_error_check"
    code = "SAFE209"
    language = ("go",)

    _DEFAULT_ERROR_NAMES: ClassVar[list[str]] = ["err"]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag an error nil-check whose error-handling branch is empty.

        The branch that handles the error depends on the operator: ``err
        != nil`` handles it in the ``consequence``, ``err == nil`` handles
        it in the ``else`` (``alternative``). Only that branch is checked
        for emptiness, so ``if err == nil { ... }`` (no else) and
        ``if err == nil { ... } else if ... {}`` never produce false
        positives - the error is handled elsewhere.
        """
        error_names = frozenset(_validated_string_list(self.config.get("error_names_go", self._DEFAULT_ERROR_NAMES), "error_names_go"))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "if_statement":
                continue
            error_block = self._error_branch(node, error_names)
            if error_block is not None and _block_is_empty(error_block):
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        "Error checked but not handled - the error-handling branch is empty; handle the error, wrap it, or return it",
                    )
                )
        return violations

    @staticmethod
    def _error_branch(if_node: tree_sitter.Node, error_names: frozenset[str]) -> tree_sitter.Node | None:
        """Return the ``block`` that should handle the error, or None if not an error nil-check.

        ``err != nil`` -> the ``consequence`` block. ``err == nil`` -> the
        ``alternative`` (else) block, and only when it is a plain ``block``
        (an else-if chain is an ``if_statement`` and means the error path is
        handled, so it never fires).
        """
        condition = if_node.child_by_field_name("condition")
        if condition is None:  # pragma: no cover - defensive: if_statement always has a condition
            return None
        operator = _nil_error_operator(condition, error_names)
        if operator is None:
            return None
        if operator == "!=":
            return if_node.child_by_field_name("consequence")
        alternative = if_node.child_by_field_name("alternative")
        return alternative if alternative is not None and alternative.type == "block" else None


# ---------------------------------------------------------------------------
# SAFE211 - panic_calls_outside_tests
# ---------------------------------------------------------------------------


class PanicCallsOutsideTestsRule(BaseRule):
    """Flag ``panic(...)`` calls in production (non-``_test.go``) files."""

    name = "panic_calls_outside_tests"
    code = "SAFE211"
    language = ("go",)

    _DEFAULT_PANIC_CALLS: ClassVar[list[str]] = ["panic"]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every configured panic-family call outside ``_test.go`` files.

        Go's test files end in ``_test.go``; a ``panic`` there is an
        acceptable test-failure signal, so the whole file is exempt - the
        same spirit as Rust's SAFE204 exempting ``#[test]`` / ``#[cfg(test)]``
        contexts.
        """
        if filepath.endswith("_test.go"):
            return []
        panic_calls = frozenset(_validated_string_list(self.config.get("panic_calls_go", self._DEFAULT_PANIC_CALLS), "panic_calls_go"))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "call_expression":
                continue
            function = node.child_by_field_name("function")
            if function is None or function.type != "identifier" or node_text(function) not in panic_calls:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"{node_text(function)}()" called outside a test - production code should return an error, not unwind the stack (Power of Ten rule 1)',
                )
            )
        return violations
