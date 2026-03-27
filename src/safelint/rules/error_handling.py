"""Error-handling rules: bare_except, empty_except, logging_on_error."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class BareExceptRule(BaseRule):
    """Reject bare ``except:`` clauses that silently catch SystemExit and KeyboardInterrupt."""

    name = "bare_except"
    code = "SAFE201"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag every except handler with no exception type specified."""
        return [
            self._v(filepath, handler.lineno, "Bare except clause - specify the exception type(s)")
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
            for handler in node.handlers
            if handler.type is None
        ]


class EmptyExceptRule(BaseRule):
    """Reject except blocks whose body is empty (silent failure)."""

    name = "empty_except"
    code = "SAFE202"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag every except handler with an empty body."""
        return [
            self._v(
                filepath,
                handler.lineno,
                "Empty except block - add error handling or a logging call",
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
            for handler in node.handlers
            if not handler.body
        ]


class LoggingOnErrorRule(BaseRule):
    """Require a logging call in every except block that does not simply re-raise."""

    name = "logging_on_error"
    code = "SAFE203"

    _LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})

    def _only_reraises(self, handler: ast.ExceptHandler) -> bool:
        """Return True when the handler body consists solely of a bare raise."""
        stmts = handler.body
        return len(stmts) == 1 and isinstance(stmts[0], ast.Raise) and stmts[0].exc is None

    def _has_log_call(self, handler: ast.ExceptHandler) -> bool:
        """Return True when the handler body contains at least one logging call."""
        for node in ast.walk(handler):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in self._LOG_METHODS:
                return True
            if isinstance(func, ast.Name) and func.id in self._LOG_METHODS:
                return True
        return False

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag except blocks that handle an error without any logging call."""
        return [
            self._v(
                filepath,
                handler.lineno,
                "Except block missing logging call - errors must be logged before being swallowed",
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
            for handler in node.handlers
            if handler.body and not self._only_reraises(handler) and not self._has_log_call(handler)
        ]
