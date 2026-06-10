"""no_recursion rule (SAFE105): flag direct self-recursive function calls.

Holzmann's Power-of-Ten rule 1 ("restrict all code to very simple control
flow constructs") bans recursion outright. The rationale: recursion plus the
absence of a guaranteed bound turns the call stack itself into an unbounded
resource, so worst-case stack depth (and therefore termination and memory
behaviour) cannot be proven by inspection. An explicit loop with a worklist
makes the bound visible.

Scope: **direct self-recursion only** - a function whose body contains a call
to its own name. Indirect / mutual recursion (``a`` calls ``b`` calls ``a``)
needs a call graph and is intentionally out of scope; a future rule may add
it. Anonymous functions (arrow functions, ``function`` expressions, lambdas)
have no name to match against, so a binding-level recursion such as
``const f = () => f()`` is a documented blind spot.

Cross-language: the per-function walk pattern mirrors ``complexity`` and the
other per-function rules - the outer walk finds every function-defining node
(including nested ones), and the inner walk is pruned at nested function
boundaries via ``skip_types`` so a nested helper sharing the outer function's
name is not misattributed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_PY_FUNCTION_TYPES = frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF})

_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": _PY_FUNCTION_TYPES,
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
    "rust": _RUST_FUNCTION_TYPES,
}

#: The call-expression node type per language. Constructor calls
#: (``new_expression`` / ``object_creation_expression``) are deliberately
#: excluded - constructing an instance is not a self-recursive *function*
#: call in the sense rule 1 cares about.
_CALL_TYPE_BY_LANG: dict[str, str] = {
    "python": "call",
    "javascript": "call_expression",
    "typescript": "call_expression",
    "rust": "call_expression",
    "java": "method_invocation",
}

#: Identifiers that name "the current object" per language. A call
#: ``self.foo()`` / ``this.foo()`` inside ``foo`` is self-recursion;
#: ``other.foo()`` is not, even though it shares the bareword name.
_SELF_RECEIVERS: dict[str, frozenset[str]] = {
    "python": frozenset({"self", "cls"}),
    "javascript": frozenset({"this"}),
    "typescript": frozenset({"this"}),
    "rust": frozenset({"self"}),
}

#: Member-access node shape per language: ``(node_type, object_field,
#: name_field)``. Used to recognise self-qualified calls. Java is absent
#: because its ``method_invocation`` carries the receiver and method name
#: as fields on the call node itself, not via a nested member-access node.
_MEMBER_ACCESS: dict[str, tuple[str, str, str]] = {
    "python": ("attribute", "object", "attribute"),
    "javascript": ("member_expression", "object", "property"),
    "typescript": ("member_expression", "object", "property"),
    "rust": ("field_expression", "value", "field"),
}


def _matches_self_qualified(callee: tree_sitter.Node, func_name: str, lang: str) -> bool:
    """Return True if *callee* is a ``self``/``this``-qualified access of *func_name*."""
    spec = _MEMBER_ACCESS.get(lang)
    if spec is None or callee.type != spec[0]:
        return False
    obj = callee.child_by_field_name(spec[1])
    name = callee.child_by_field_name(spec[2])
    if obj is None or name is None or node_text(name) != func_name:
        return False
    # ``self`` / ``this`` / ``cls`` parse as distinct node types across
    # languages (Python ``self`` is an ``identifier``; JS ``this`` and Rust
    # ``self`` are their own keyword node types), so match on the receiver's
    # source text rather than its node type. A non-self receiver
    # (``other.foo()``, ``foo.bar.baz()``) yields text outside the set and
    # is correctly skipped.
    return node_text(obj) in _SELF_RECEIVERS[lang]


def _call_targets_self(call_node: tree_sitter.Node, func_name: str, lang: str) -> bool:
    """Return True if *call_node* is a direct self-recursive call to *func_name* (non-Java)."""
    callee = call_node.child_by_field_name("function")
    if callee is None:
        return False
    if callee.type == "identifier":
        return node_text(callee) == func_name
    return _matches_self_qualified(callee, func_name, lang)


def _java_call_targets_self(call_node: tree_sitter.Node, func_name: str) -> bool:
    """Return True if a Java ``method_invocation`` is a self-call to *func_name*.

    Fires for a bare call (``foo()`` with no receiver) or an explicitly
    ``this``-qualified call (``this.foo()``). A call with any other
    receiver (``other.foo()``) is not self-recursion.
    """
    name = call_node.child_by_field_name("name")
    if name is None or node_text(name) != func_name:
        return False
    obj = call_node.child_by_field_name("object")
    return obj is None or obj.type == "this"


def _targets_self(call_node: tree_sitter.Node, func_name: str, lang: str) -> bool:
    """Dispatch self-recursion detection to the per-language predicate."""
    if lang == "java":
        return _java_call_targets_self(call_node, func_name)
    return _call_targets_self(call_node, func_name, lang)


class NoRecursionRule(BaseRule):
    """Flag functions that call themselves directly (Power of Ten rule 1)."""

    name = "no_recursion"
    code = "SAFE105"
    language = ("python", "javascript", "typescript", "java", "rust")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every function whose body directly calls itself."""
        lang = resolve_lang_name(filepath)
        func_types = _FUNCTION_TYPES_BY_LANG[lang]
        call_type = _CALL_TYPE_BY_LANG[lang]
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in func_types:
                continue
            violations.extend(self._check_function(filepath, node, func_types, call_type, lang))
        return violations

    def _check_function(
        self,
        filepath: str,
        func: tree_sitter.Node,
        func_types: frozenset[str],
        call_type: str,
        lang: str,
    ) -> list[Violation]:
        """Return one violation per direct self-call inside *func*.

        The inner walk is pruned at nested function boundaries so a nested
        helper sharing this function's name (or a closure that calls this
        function's name) is not attributed here.
        """
        name_node = func.child_by_field_name("name")
        if name_node is None:
            return []
        func_name = node_text(name_node)
        violations: list[Violation] = []
        for node in walk(func, skip_types=tuple(func_types)):
            if node.type != call_type:
                continue
            if _targets_self(node, func_name, lang):
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Function "{func_name}" calls itself; recursion has no guaranteed stack bound (Power of Ten rule 1) - refactor to an explicit loop or worklist',
                    )
                )
        return violations
