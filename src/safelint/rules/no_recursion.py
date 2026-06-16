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
boundaries via ``skip_types`` so calls *inside* a nested function body are not
attributed to the enclosing function. Name shadowing is handled separately: if
a function defines a same-named nested function, an unqualified call to that
name in the enclosing body resolves to the nested binding (not recursion), so
such bare calls are skipped while ``self``/``this``-qualified self-calls still
count.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.rules.base import BaseRule, Suggestion


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


#: Advisory, informational-only fix (no TextEdits): the right rewrite is an
#: explicit loop / worklist, but the shape of that loop depends on the
#: function, so safelint only names the direction, never an edit.
_ITERATIVE_SUGGESTION = Suggestion(description="Convert the recursion to an explicit loop with a worklist / accumulator")


_PY_FUNCTION_TYPES = frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF})

_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": _PY_FUNCTION_TYPES,
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
    "rust": _RUST_FUNCTION_TYPES,
    "go": _GO_FUNCTION_TYPES,
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
    "go": "call_expression",
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


def _go_receiver_name(func: tree_sitter.Node) -> str | None:
    """Return a Go method's receiver variable name, or None.

    For ``func (s *Svc) Walk()`` returns ``"s"`` - the user-chosen
    receiver identifier is Go's analogue of ``self`` / ``this``, so a
    ``s.Walk(...)`` call inside ``Walk`` is self-recursion. Returns None
    for plain functions (no receiver) and for methods with an unnamed
    receiver (``func (*Svc) Walk()`` - the receiver can't be referenced,
    so a receiver-qualified self-call is impossible).
    """
    if func.type != "method_declaration":
        return None
    receiver = func.child_by_field_name("receiver")
    if receiver is None:  # pragma: no cover - defensive: method_declaration always has a receiver
        return None
    for decl in receiver.named_children:
        if decl.type != "parameter_declaration":  # pragma: no cover - defensive: receiver list holds only a parameter_declaration
            continue
        ident = next((child for child in decl.named_children if child.type == "identifier"), None)
        if ident is not None:
            return node_text(ident)
    return None


def _go_call_targets_self(call_node: tree_sitter.Node, func_name: str, receiver_name: str | None) -> bool:
    """Return True if a Go ``call_expression`` is a direct self-call.

    Plain functions (``receiver_name is None``) self-recurse via a bare
    ``foo()`` whose callee identifier equals the function name. Methods
    self-recurse via a receiver-qualified ``s.Walk()`` whose selector
    operand matches the receiver name and field matches the method name.
    A bare same-named call inside a method is NOT recursion - it denotes a
    different package-level function, since a method must be called through
    its receiver.
    """
    callee = call_node.child_by_field_name("function")
    if callee is None:  # pragma: no cover - defensive: call_expression always has a function field
        return False
    if callee.type == "identifier":
        return receiver_name is None and node_text(callee) == func_name
    if callee.type == "selector_expression":
        if receiver_name is None:
            return False
        operand = callee.child_by_field_name("operand")
        field = callee.child_by_field_name("field")
        return operand is not None and field is not None and node_text(operand) == receiver_name and node_text(field) == func_name
    return False


def _targets_self(call_node: tree_sitter.Node, func_name: str, lang: str, receiver_name: str | None) -> bool:
    """Dispatch self-recursion detection to the per-language predicate."""
    if lang == "java":
        return _java_call_targets_self(call_node, func_name)
    if lang == "go":
        return _go_call_targets_self(call_node, func_name, receiver_name)
    return _call_targets_self(call_node, func_name, lang)


def _call_is_bare(call_node: tree_sitter.Node, lang: str) -> bool:
    """Return True if *call_node* is an unqualified call (no receiver / ``self`` / ``this``).

    A bare call resolves by name in the current scope, so it is the one a
    same-named nested function can shadow. ``self.foo()`` / ``this.foo()`` are
    *not* bare - they always denote the method, never a local binding.
    """
    if lang == "java":
        return call_node.child_by_field_name("object") is None
    callee = call_node.child_by_field_name("function")
    return callee is not None and callee.type == "identifier"


def _directly_nested_function_names(func: tree_sitter.Node, func_types: frozenset[str]) -> set[str]:
    """Return the names of functions defined directly inside *func*'s own body.

    The pruned walk yields each directly-nested function-definition node
    (without descending into it). A nested ``def``/``fn``/method whose name
    equals the enclosing function's rebinds that name in the enclosing scope,
    so an unqualified call to it inside the enclosing body resolves to the
    nested binding, not to recursion.
    """
    names: set[str] = set()
    for node in walk(func, skip_types=tuple(func_types)):
        if node is func or node.type not in func_types:
            continue
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            names.add(node_text(name_node))
    return names


class NoRecursionRule(BaseRule):
    """Flag functions that call themselves directly (Power of Ten rule 1)."""

    name = "no_recursion"
    code = "SAFE105"
    language = ("python", "javascript", "typescript", "java", "rust", "go")

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

        The inner walk is pruned at nested function boundaries so calls *inside*
        a nested function body are not attributed to this function. Name
        shadowing is also handled: if this function defines a same-named nested
        function, an unqualified call to that name in the body resolves to the
        nested binding (not recursion), so bare self-calls are skipped while
        ``self``/``this``-qualified ones still count.
        """
        name_node = func.child_by_field_name("name")
        if name_node is None:
            return []
        func_name = node_text(name_node)
        receiver_name = _go_receiver_name(func) if lang == "go" else None
        shadowed = func_name in _directly_nested_function_names(func, func_types)
        violations: list[Violation] = []
        for node in walk(func, skip_types=tuple(func_types)):
            if node.type != call_type:
                continue
            if shadowed and _call_is_bare(node, lang):
                continue
            if _targets_self(node, func_name, lang, receiver_name):
                base = self._make_violation_for_node(
                    filepath,
                    node,
                    f'Function "{func_name}" calls itself; recursion has no guaranteed stack bound (Power of Ten rule 1) - refactor to an explicit loop or worklist',
                )
                # Violation is frozen; attach the advisory suggestion via replace.
                violations.append(replace(base, suggestions=(_ITERATIVE_SUGGESTION,)))
        return violations
