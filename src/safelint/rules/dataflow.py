"""Dataflow hybrid rules: tainted_sink, return_value_ignored, null_dereference."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.analysis.dataflow import TaintTracker
from safelint.analysis.dataflow_javascript import JsTaintTracker
from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
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


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
}

# Python parameter shapes — kept in sync with the same set in
# safelint.rules.max_arguments to avoid drift.
_PY_PARAM_TYPES = frozenset(
    {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }
)

# JavaScript parameter shapes inside ``formal_parameters``.
_JS_PARAM_TYPES = frozenset(
    {
        "identifier",
        "assignment_pattern",
        "rest_pattern",
        "object_pattern",
        "array_pattern",
    }
)


def _python_param_node_name(child: tree_sitter.Node) -> str:
    """Return the bare identifier name carried by a Python parameter node, or ``""``."""
    if child.type == "identifier":
        return node_text(child)
    if child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
        # Splat parameters always have an identifier child in valid Python;
        # the empty-children branch is defensive against malformed AST.
        inner = child.named_children[0] if child.named_children else None  # pragma: no branch
        return node_text(inner) if inner else ""  # pragma: no cover
    name_node = child.child_by_field_name("name")
    return node_text(name_node) if name_node else ""  # pragma: no cover


def _python_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names for *func_node* (Python), excluding self / cls."""
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover — defensive: valid Python functions always have a parameters list
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        if child.type not in _PY_PARAM_TYPES:
            continue
        name = _python_param_node_name(child)
        if name and name not in ("self", "cls"):
            names.add(name)
    return names


def _javascript_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names for *func_node* (JavaScript).

    Destructured params (``function f({a, b})``, ``function f([x, y])``)
    contribute every bound name to the taint set — the destructured
    fields are themselves tainted entry points. Rest params (``...args``)
    contribute the rest variable name.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover — defensive: arrow functions and named functions both expose ``parameters``
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        if child.type not in _JS_PARAM_TYPES:
            continue
        names.update(_javascript_collect_names(child))
    return names


_JS_NAME_LEAF_TYPES = frozenset({"identifier", "shorthand_property_identifier_pattern"})
_JS_DESTRUCTURE_CONTAINER_TYPES = frozenset({"array_pattern", "object_pattern", "rest_pattern"})


def _javascript_collect_names(node: tree_sitter.Node) -> set[str]:
    """Walk a JS parameter / pattern node and collect every bound identifier name.

    Dispatches by node-type bucket — leaf identifiers, container patterns
    (array / object / rest), assignment patterns (``b = 5``), and pair
    patterns (``{key: alias}``) — into small helpers so this function
    stays under the cyclomatic-complexity cap.
    """
    if node.type in _JS_NAME_LEAF_TYPES:
        return {node_text(node)}
    if node.type in _JS_DESTRUCTURE_CONTAINER_TYPES:
        return _collect_from_container_pattern(node)
    if node.type == "assignment_pattern":
        return _collect_from_assignment_pattern(node)
    if node.type == "pair_pattern":
        return _collect_from_pair_pattern(node)
    return set()


def _collect_from_container_pattern(node: tree_sitter.Node) -> set[str]:
    """Collect bound names from ``[a, b]`` / ``{a, b}`` / ``...rest`` patterns."""
    names: set[str] = set()
    for c in node.named_children:
        names.update(_javascript_collect_names(c))
    return names


def _collect_from_assignment_pattern(node: tree_sitter.Node) -> set[str]:
    """Collect bound names from ``b = 5`` (default-value parameter)."""
    target = node.named_children[0] if node.named_children else None  # pragma: no branch
    return _javascript_collect_names(target) if target else set()  # pragma: no cover — defensive


def _collect_from_pair_pattern(node: tree_sitter.Node) -> set[str]:
    """Collect the bound name from ``{key: alias}`` (alias is bound, not key)."""
    value = node.child_by_field_name("value")
    return _javascript_collect_names(value) if value else set()  # pragma: no branch


class TaintedSinkRule(BaseRule):
    """Track user-controlled inputs flowing into dangerous sinks."""

    name = "tainted_sink"
    code = "SAFE801"
    language = ("python", "javascript")

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

    def _resolve_assume_taint_preserving(self) -> bool:
        """Read and validate the ``assume_taint_preserving`` config knob.

        Strict isinstance check: ``bool(...)`` would treat a TOML typo
        like ``assume_taint_preserving = "false"`` (string) as truthy
        and silently flip the rule into the opposite mode. Surface the
        typo as a clear ``TypeError`` instead.
        """
        value = self.config.get("assume_taint_preserving", True)
        if not isinstance(value, bool):
            msg = f"tainted_sink.assume_taint_preserving must be a bool, got {type(value).__name__}"
            raise TypeError(msg)
        return value

    def _python_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run Python taint analysis on every function in *tree*."""
        sinks = frozenset(self.config.get("sinks", self._DEFAULT_SINKS))
        sanitizers = frozenset(self.config.get("sanitizers", self._DEFAULT_SANITIZERS))
        sources = frozenset(self.config.get("sources", self._DEFAULT_SOURCES))
        assume = self._resolve_assume_taint_preserving()
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            params = _python_param_names(node)
            tracker = TaintTracker(params, sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        return violations

    def _javascript_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run JavaScript taint analysis on every function in *tree*."""
        sinks = frozenset(self.config.get("sinks_javascript", []))
        sanitizers = frozenset(self.config.get("sanitizers_javascript", []))
        sources = frozenset(self.config.get("sources_javascript", []))
        assume = self._resolve_assume_taint_preserving()
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in _JS_FUNCTION_TYPES:
                continue
            params = _javascript_param_names(node)
            tracker = JsTaintTracker(params, sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        return violations

    def _format_hits(self, filepath: str, hits: list[tuple[tree_sitter.Node, str, str]]) -> list[Violation]:
        """Convert tracker hits to Violations — same message format for both languages."""
        return [
            self._make_violation_for_node(
                filepath,
                call_node,
                f'Tainted variable "{var}" flows into dangerous sink "{sink}" - sanitize input before use',
            )
            for call_node, var, sink in hits
        ]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run taint analysis on every function in *tree*, dispatching on language."""
        lang_name = resolve_lang_name(filepath)
        if lang_name == "javascript":
            return self._javascript_check(filepath, tree)
        return self._python_check(filepath, tree)


class ReturnValueIgnoredRule(BaseRule):
    """Flag calls to error-signalling functions whose return value is discarded.

    Cross-language: walks ``expression_statement`` nodes (same name in
    both grammars) and checks whether the bare statement is a call. The
    flagged-calls list is per-language so ``write`` can have different
    semantics in Python (``file.write``) vs JavaScript (``stream.write``,
    ``fs.writeFile``).
    """

    name = "return_value_ignored"
    code = "SAFE802"
    language = ("python", "javascript")

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
        lang_name = resolve_lang_name(filepath)
        flagged = frozenset(self.config.get("flagged_calls", self._DEFAULT_FLAGGED)) if lang_name == "python" else frozenset(self.config.get("flagged_calls_javascript", []))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != EXPRESSION_STATEMENT:
                continue
            named = node.named_children
            if not named or named[0].type not in CALL_TYPES:
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


def _null_dereference_message(method: str, lang_name: str) -> str:
    """Build the language-specific SAFE803 violation message.

    Python uses ``None`` / ``is not None``; JavaScript uses
    ``null`` / ``undefined`` and the optional-chaining (``?.``) idiom
    that's the modern guard. The two-form JS message also surfaces the
    loose ``!= null`` check because it's the explicit alternative that
    catches both ``null`` and ``undefined`` (the strict ``!== null``
    misses ``undefined``).
    """
    if lang_name == "javascript":
        return f'Result of "{method}()" is immediately dereferenced without a null check - guard with optional chaining ("result?.field") or "if (result != null)"'
    return f'Result of "{method}()" is immediately dereferenced without a None check - guard with "if result is not None"'


class NullDereferenceRule(BaseRule):
    """Flag chained attribute or subscript access on calls that can return None."""

    name = "null_dereference"
    code = "SAFE803"
    language = ("python", "javascript")

    _DEFAULT_NULLABLE_PYTHON: ClassVar[frozenset[str]] = frozenset(
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

    def _python_deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> str | None:
        """Return the method name if *node* is an unsafe Python dereference, else None."""
        if node.type not in (ATTRIBUTE, SUBSCRIPT):
            return None
        # attribute → field "object", subscript → field "value"
        field_name = "object" if node.type == ATTRIBUTE else "value"
        obj = node.child_by_field_name(field_name)
        if obj is None or obj.type != CALL:
            return None
        name = call_name(obj)
        return name if name and name in nullable else None

    def _javascript_deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> str | None:
        """Return the method name if *node* is an unsafe JavaScript dereference, else None.

        ``foo?.bar`` (optional chaining) is null-safe by construction —
        any ``optional_chain`` child token in the member / subscript
        node means the rule should NOT fire.
        """
        if node.type not in ("member_expression", "subscript_expression"):
            return None
        # Optional chaining is the safe form — skip it entirely.
        if any(c.type == "optional_chain" for c in node.children):
            return None
        obj = node.child_by_field_name("object")
        if obj is None or obj.type != "call_expression":
            return None
        name = call_name(obj)
        return name if name and name in nullable else None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag immediate dereferences on nullable-returning calls.

        Per-language message: Python users get the ``None`` / ``is not None``
        idiom; JavaScript users get the null-or-undefined hazard surfaced
        with optional chaining (``result?.field`` — the modern guard) and
        the loose ``!= null`` form (which catches both ``null`` and
        ``undefined``) as the explicit alternative. Same per-language
        wording pattern as ``EmptyExceptRule`` / ``LoggingOnErrorRule``
        / ``UnboundedLoopsRule``.
        """
        lang_name = resolve_lang_name(filepath)
        if lang_name == "python":
            nullable = self._DEFAULT_NULLABLE_PYTHON | frozenset(self.config.get("nullable_methods", []))
            deref_hit = self._python_deref_hit
        else:
            nullable = frozenset(self.config.get("nullable_methods_javascript", []))
            deref_hit = self._javascript_deref_hit
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            method = deref_hit(node, nullable)
            if method is not None:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        _null_dereference_message(method, lang_name),
                    )
                )
        return violations
