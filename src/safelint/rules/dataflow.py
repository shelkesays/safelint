"""Dataflow hybrid rules: tainted_sink, return_value_ignored, null_dereference."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.analysis.dataflow import TaintTracker
from safelint.languages._node_utils import call_name, lineno, node_text, walk
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
        inner = child.named_children[0] if child.named_children else None
        return node_text(inner) if inner else ""
    name_node = child.child_by_field_name("name")
    return node_text(name_node) if name_node else ""


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
    ) -> list[Violation]:
        """Run taint analysis on a single function and return violations."""
        params = _param_names(func_node)
        tracker = TaintTracker(params, sinks, sanitizers, sources)
        tracker.visit(func_node)
        return [
            self._make_violation(
                filepath,
                line_num,
                f'Tainted variable "{var}" flows into dangerous sink "{sink}" - sanitize input before use',
            )
            for line_num, var, sink in tracker.sink_hits
        ]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run taint analysis on every function in *tree*."""
        sinks = frozenset(self.config.get("sinks", self._DEFAULT_SINKS))
        sanitizers = frozenset(self.config.get("sanitizers", self._DEFAULT_SANITIZERS))
        sources = frozenset(self.config.get("sources", self._DEFAULT_SOURCES))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                violations.extend(self._check_func(filepath, node, sinks, sanitizers, sources))
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
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
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

    def _deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> tuple[int, str] | None:
        """Return (lineno, method) if *node* is an unsafe chained dereference."""
        if node.type not in (ATTRIBUTE, SUBSCRIPT):
            return None
        # attribute → field "object", subscript → field "value"
        field_name = "object" if node.type == ATTRIBUTE else "value"
        obj = node.child_by_field_name(field_name)
        if obj is None or obj.type != CALL:
            return None
        name = call_name(obj)
        if name and name in nullable:
            return lineno(node), name
        return None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag immediate dereferences on nullable-returning calls."""
        extra: frozenset[str] = frozenset(self.config.get("nullable_methods", []))
        nullable = self._DEFAULT_NULLABLE | extra
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            result = self._deref_hit(node, nullable)
            if result:
                line_num, method = result
                violations.append(
                    self._make_violation(
                        filepath,
                        line_num,
                        f'Result of "{method}()" is immediately dereferenced without a None check - guard with "if result is not None"',
                    )
                )
        return violations
