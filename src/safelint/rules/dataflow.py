"""Dataflow hybrid rules: tainted_sink, return_value_ignored, null_dereference.

These rules combine structural AST analysis with lightweight intra-procedural
dataflow tracking to find bugs that pure pattern matching cannot catch.

All three are **disabled by default** - enable them in ``.safelint.yaml``
under ``rules.<name>.enabled: true``.
"""

from __future__ import annotations

import ast

from safelint.analysis.dataflow import TaintTracker
from safelint.rules.base import BaseRule, Violation

# ---------------------------------------------------------------------------
# TaintedSinkRule
# ---------------------------------------------------------------------------


class TaintedSinkRule(BaseRule):
    """Track user-controlled inputs flowing into dangerous sinks.

    Algorithm (intra-procedural taint analysis):

    1. Mark every function parameter as tainted at function entry.
    2. Walk the function body; propagate taint through assignments,
       augmented assignments, f-strings, containers, and arithmetic.
    3. Configurable "source" calls (e.g. ``input()``) inject fresh taint.
    4. Configurable "sanitizer" calls (e.g. ``escape()``) clear taint.
    5. When a tainted value reaches a configurable "sink" call
       (e.g. ``eval``, ``exec``, ``subprocess.run``), emit a violation.
    """

    name = "tainted_sink"
    code = "SAFE801"

    _DEFAULT_SINKS: list[str] = [
        "eval",
        "exec",
        "compile",
        "system",
        "popen",
        "Popen",
        "run",
        "call",
        "check_output",
        "execute",
    ]
    _DEFAULT_SANITIZERS: list[str] = [
        "escape",
        "sanitize",
        "clean",
        "validate",
        "quote",
        "encode",
        "bleach",
    ]
    _DEFAULT_SOURCES: list[str] = [
        "input",
        "readline",
        "recv",
        "recvfrom",
        "read",
    ]

    def _param_names(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        """Return all parameter names, excluding self / cls."""
        args = func.args
        all_args = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
        if args.vararg:
            all_args.append(args.vararg)
        if args.kwarg:
            all_args.append(args.kwarg)
        return {a.arg for a in all_args if a.arg not in ("self", "cls")}

    def _check_func(
        self,
        filepath: str,
        func: ast.FunctionDef | ast.AsyncFunctionDef,
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
    ) -> list[Violation]:
        """Run taint analysis on a single function and return violations."""
        params = self._param_names(func)
        tracker = TaintTracker(params, sinks, sanitizers, sources)
        tracker.visit(func)
        return [
            self._v(
                filepath,
                lineno,
                f'Tainted variable "{var}" flows into dangerous sink "{sink}"'
                " - sanitize input before use",
            )
            for lineno, var, sink in tracker.sink_hits
        ]

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Run taint analysis on every function in *tree*."""
        sinks = frozenset(self.config.get("sinks", self._DEFAULT_SINKS))
        sanitizers = frozenset(self.config.get("sanitizers", self._DEFAULT_SANITIZERS))
        sources = frozenset(self.config.get("sources", self._DEFAULT_SOURCES))
        violations: list[Violation] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                violations.extend(self._check_func(filepath, node, sinks, sanitizers, sources))
        return violations


# ---------------------------------------------------------------------------
# ReturnValueIgnoredRule
# ---------------------------------------------------------------------------


class ReturnValueIgnoredRule(BaseRule):
    """Flag calls to error-signalling functions whose return value is discarded.

    Detects bare ``ast.Expr`` statements (expression used as statement) whose
    value is a call to a configured function.  Ignoring the return value of
    ``subprocess.run``, ``os.write``, socket ``send``, etc. silently swallows
    errors and violates the Holzmann "check return value" rule.
    """

    name = "return_value_ignored"
    code = "SAFE802"

    _DEFAULT_FLAGGED: list[str] = [
        "run",
        "call",
        "check_output",
        "write",
        "send",
        "sendall",
        "sendfile",
        "seek",
        "truncate",
        "remove",
        "unlink",
        "rename",
        "replace",
        "makedirs",
        "mkdir",
        "rmdir",
    ]

    def _ignored_call_name(self, node: ast.Expr, flagged: frozenset[str]) -> str | None:
        """Return the call name if this Expr discards a flagged return value."""
        if not isinstance(node.value, ast.Call):
            return None
        name = self._call_name(node.value.func)
        return name if name in flagged else None

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag bare calls whose return value is discarded."""
        flagged = frozenset(self.config.get("flagged_calls", self._DEFAULT_FLAGGED))
        violations: list[Violation] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Expr):
                continue
            name = self._ignored_call_name(node, flagged)
            if name:
                violations.append(
                    self._v(
                        filepath,
                        node.lineno,
                        f'Return value of "{name}" is discarded'
                        " - check the result or assign it to a named variable",
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# NullDereferenceRule
# ---------------------------------------------------------------------------


class NullDereferenceRule(BaseRule):
    """Flag chained attribute or subscript access on calls that can return None.

    Detects patterns like ``config.get("key").strip()`` where a method known
    to sometimes return ``None`` is immediately dereferenced without a guard.
    This pattern raises ``AttributeError`` at runtime when the key is absent.

    Detection strategy: AST pattern matching on ``ast.Attribute(value=ast.Call)``
    and ``ast.Subscript(value=ast.Call)`` nodes where the inner call's method
    name is in the configured ``nullable_methods`` set.
    """

    name = "null_dereference"
    code = "SAFE803"

    _DEFAULT_NULLABLE: frozenset[str] = frozenset(
        [
            "get",  # dict.get() → None when key absent
            "pop",  # dict.pop(key, None)
            "find",  # str.find() → -1 (often misused as Optional)
            "next",  # next(iterator, None)
            "first",  # common ORM / queryset pattern
            "one_or_none",  # SQLAlchemy
            "scalar",  # SQLAlchemy session.scalar()
            "scalar_one_or_none",  # SQLAlchemy
            "fetchone",  # DB-API cursor.fetchone()
        ]
    )

    def _deref_hit(self, node: ast.AST, nullable: frozenset[str]) -> tuple[int, str] | None:
        """Return (lineno, method) if *node* is an unsafe chained dereference."""
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call):
            name = self._call_name(node.value.func)
            if name in nullable:
                return node.lineno, name
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call):
            name = self._call_name(node.value.func)
            if name in nullable:
                return node.lineno, name
        return None

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag immediate dereferences on nullable-returning calls."""
        extra: frozenset[str] = frozenset(self.config.get("nullable_methods", []))
        nullable = self._DEFAULT_NULLABLE | extra
        violations: list[Violation] = []
        for node in ast.walk(tree):
            result = self._deref_hit(node, nullable)
            if result:
                lineno, method = result
                violations.append(
                    self._v(
                        filepath,
                        lineno,
                        f'Result of "{method}()" is immediately dereferenced'
                        ' without a None check - guard with "if result is not None"',
                    )
                )
        return violations
