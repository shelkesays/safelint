"""Error-handling rules: bare_except, empty_except, logging_on_error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, lineno, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    ATTRIBUTE,
    CALL,
    EXCEPT_CLAUSE,
    FUNCTION_DEF,
    IDENTIFIER,
    RAISE_STATEMENT,
    TUPLE,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _iter_except_clauses(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every ``except_clause`` node in *tree*."""
    # except_clauses only appear inside try_statements in tree-sitter-python,
    # so a flat walk suffices; no need to filter by parent.
    for node in walk(tree.root_node):
        if node.type == EXCEPT_CLAUSE:
            yield node


def _except_body(except_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the body block of *except_node*, or None if it has no body.

    The first branch (body field present) hits in normal code; the
    fallback (last named child) is defensive for AST shapes where the
    field isn't directly populated. Empty children should never happen
    in valid Python (an except always has a body or a single ``pass``).
    """
    body_node = except_node.child_by_field_name("body")
    if body_node is not None:
        return body_node
    named = except_node.named_children
    return named[-1] if named else None  # pragma: no cover


def _has_typed_exception(except_node: tree_sitter.Node) -> bool:
    """Return True when the except clause specifies one or more exception types."""
    # ``except ValueError as e:`` puts the type inside an ``as_pattern`` named child.
    return any(c.type in (IDENTIFIER, ATTRIBUTE, TUPLE, "as_pattern") for c in except_node.named_children)


class BareExceptRule(BaseRule):
    """Reject bare ``except:`` clauses that silently catch SystemExit and KeyboardInterrupt."""

    name = "bare_except"
    code = "SAFE201"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every except handler with no exception type specified."""
        return [
            self._make_violation(
                filepath,
                lineno(clause),
                "Bare except clause - specify the exception type(s)",
            )
            for clause in _iter_except_clauses(tree)
            if not _has_typed_exception(clause)
        ]


class EmptyExceptRule(BaseRule):
    """Reject except blocks whose body is empty (silent failure)."""

    name = "empty_except"
    code = "SAFE202"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every except handler with an empty body."""
        return [
            self._make_violation(
                filepath,
                lineno(clause),
                "Empty except block - add error handling or a logging call",
            )
            for clause in _iter_except_clauses(tree)
            if (body := _except_body(clause)) is None or not body.named_children
        ]


class LoggingOnErrorRule(BaseRule):
    """Require a logging call in every except block that does not simply re-raise."""

    name = "logging_on_error"
    code = "SAFE203"

    _LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})

    def _only_reraises(self, except_node: tree_sitter.Node) -> bool:
        """Return True when the handler body is just a bare ``raise``."""
        body_node = _except_body(except_node)
        # Defensive — ``_except_body`` only returns None for malformed AST
        # that this rule can't sensibly classify anyway.
        if body_node is None:  # pragma: no cover
            return False
        stmts = body_node.named_children
        if len(stmts) != 1 or stmts[0].type != RAISE_STATEMENT:
            return False
        return not stmts[0].named_children

    def _has_log_call(self, except_node: tree_sitter.Node) -> bool:
        """Return True when the handler body contains at least one logging call.

        Walks only the body block (skipping the exception-type spec) and
        prunes nested ``def`` / ``async def`` so a logging call inside an
        inner function definition — which the except handler never actually
        executes — does not count as logging the caught error.
        """
        body = _except_body(except_node)
        if body is None:  # pragma: no cover
            return False
        return any(call_name(node) in self._LOG_METHODS for node in walk(body, skip_types=(FUNCTION_DEF, ASYNC_FUNCTION_DEF)) if node.type == CALL)

    def _is_unlogged(self, except_node: tree_sitter.Node) -> bool:
        """Return True when this except clause swallows an error without logging."""
        body_node = _except_body(except_node)
        # Empty body (no named children) means this rule's job is done by
        # ``empty_except`` (SAFE202); skip here. ``body_node is None`` is
        # the same defensive case as elsewhere.
        if body_node is None or not body_node.named_children:  # pragma: no branch
            return False
        return not self._only_reraises(except_node) and not self._has_log_call(except_node)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag except blocks that handle an error without any logging call."""
        return [
            self._make_violation(
                filepath,
                lineno(clause),
                "Except block missing logging call - errors must be logged before being swallowed",
            )
            for clause in _iter_except_clauses(tree)
            if self._is_unlogged(clause)
        ]
