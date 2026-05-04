"""Dataflow hybrid rules: tainted_sink, return_value_ignored, null_dereference."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.analysis.dataflow import TaintTracker
from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    ATTRIBUTE,
    CALL,
    EXPRESSION_STATEMENT,
    FUNCTION_DEF,
    SUBSCRIPT,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_ALL_PARAM_TYPES = frozenset(
    {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }
)


def _param_node_name(child: tree_sitter.Node) -> str:
    """Return the bare identifier name carried by a parameter node, or ``""``."""
    if child.type == "identifier":
        return node_text(child)
    if child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
        # Splat parameters always have an identifier child in valid Python;
        # the empty-children branch is defensive against malformed AST.
        inner = child.named_children[0] if child.named_children else None  # pragma: no branch
        return node_text(inner) if inner else ""  # pragma: no cover
    name_node = child.child_by_field_name("name")
    return node_text(name_node) if name_node else ""  # pragma: no cover


def _param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names for *func_node*, excluding self / cls."""
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        if child.type not in _ALL_PARAM_TYPES:
            continue
        name = _param_node_name(child)
        if name and name not in ("self", "cls"):
            names.add(name)
    return names


class TaintedSinkRule(BaseRule):
    """Track user-controlled inputs flowing into dangerous sinks."""

    name = "tainted_sink"
    code = "SAFE801"

    _DEFAULT_SINKS: ClassVar[list[str]] = [
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
    _DEFAULT_SANITIZERS: ClassVar[list[str]] = [
        "escape",
        "sanitize",
        "clean",
        "validate",
        "quote",
        "encode",
        "bleach",
    ]
    _DEFAULT_SOURCES: ClassVar[list[str]] = [
        "input",
        "readline",
        "recv",
        "recvfrom",
        "read",
    ]

    def _check_func(
        self,
        filepath: str,
        func_node: tree_sitter.Node,
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
        *,
        assume_taint_preserving: bool,
    ) -> list[Violation]:
        """Run taint analysis on a single function and return violations."""
        params = _param_names(func_node)
        tracker = TaintTracker(params, sinks, sanitizers, sources, assume_taint_preserving=assume_taint_preserving)
        tracker.visit(func_node)
        return [
            self._make_violation_for_node(
                filepath,
                call_node,
                f'Tainted variable "{var}" flows into dangerous sink "{sink}" - sanitize input before use',
            )
            for call_node, var, sink in tracker.sink_hits
        ]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run taint analysis on every function in *tree*."""
        sinks = frozenset(self.config.get("sinks", self._DEFAULT_SINKS))
        sanitizers = frozenset(self.config.get("sanitizers", self._DEFAULT_SANITIZERS))
        sources = frozenset(self.config.get("sources", self._DEFAULT_SOURCES))
        # Default ``True`` matches the historical behaviour — unknown calls
        # propagate taint from any tainted argument. Set to ``False`` for a
        # stricter analysis that drops taint at every unknown call (cleaner
        # but generates false negatives in codebases with many wrapper
        # functions). See CONFIGURATION.md for guidance.
        assume_taint_preserving = bool(self.config.get("assume_taint_preserving", True))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                violations.extend(self._check_func(filepath, node, sinks, sanitizers, sources, assume_taint_preserving=assume_taint_preserving))
        return violations


class ReturnValueIgnoredRule(BaseRule):
    """Flag calls to error-signalling functions whose return value is discarded."""

    name = "return_value_ignored"
    code = "SAFE802"

    _DEFAULT_FLAGGED: ClassVar[list[str]] = [
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

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag bare calls whose return value is discarded."""
        flagged = frozenset(self.config.get("flagged_calls", self._DEFAULT_FLAGGED))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != EXPRESSION_STATEMENT:
                continue
            named = node.named_children
            if not named or named[0].type != CALL:
                continue
            call_node = named[0]
            name = call_name(call_node)
            if name and name in flagged:
                # Anchor on call_node, not the wrapping expression_statement,
                # so the range matches the call itself rather than including
                # trailing newline / semicolon tokens that the parent picks up.
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        call_node,
                        f'Return value of "{name}" is discarded - check the result or assign it to a named variable',
                    )
                )
        return violations


class NullDereferenceRule(BaseRule):
    """Flag chained attribute or subscript access on calls that can return None."""

    name = "null_dereference"
    code = "SAFE803"

    _DEFAULT_NULLABLE: ClassVar[frozenset[str]] = frozenset(
        {
            "get",
            "pop",
            "find",
            "next",
            "first",
            "one_or_none",
            "scalar",
            "scalar_one_or_none",
            "fetchone",
        }
    )

    def _deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> str | None:
        """Return the method name if *node* is an unsafe chained dereference, else None.

        The caller already has the *node* in scope, so returning just the
        method name is enough — the node carries its own position info
        for column-precise diagnostics.
        """
        if node.type not in (ATTRIBUTE, SUBSCRIPT):
            return None
        # attribute → field "object", subscript → field "value"
        field_name = "object" if node.type == ATTRIBUTE else "value"
        obj = node.child_by_field_name(field_name)
        if obj is None or obj.type != CALL:
            return None
        name = call_name(obj)
        if name and name in nullable:
            return name
        return None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag immediate dereferences on nullable-returning calls."""
        extra: frozenset[str] = frozenset(self.config.get("nullable_methods", []))
        nullable = self._DEFAULT_NULLABLE | extra
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            method = self._deref_hit(node, nullable)
            if method is not None:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Result of "{method}()" is immediately dereferenced without a None check - guard with "if result is not None"',
                    )
                )
        return violations
