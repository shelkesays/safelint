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

from safelint.languages import c as _c
from safelint.languages import cpp as _cpp
from safelint.languages import go as _go
from safelint.languages import java as _java
from safelint.languages import javascript as _js
from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages import rust as _rust
from safelint.languages import typescript as _ts
from safelint.languages._node_utils import function_name_node, node_text, resolve_lang_name, walk
from safelint.rules.base import BaseRule, Suggestion


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


#: Advisory, informational-only fix (no TextEdits): the right rewrite is an
#: explicit loop / worklist, but the shape of that loop depends on the
#: function, so safelint only names the direction, never an edit.
_ITERATIVE_SUGGESTION = Suggestion(description="Convert the recursion to an explicit loop with a worklist / accumulator")


_PY_FUNCTION_TYPES = frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF})

_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": _PY_FUNCTION_TYPES,
    "javascript": _js.FUNCTION_TYPES,
    "typescript": _js.FUNCTION_TYPES,
    "java": _java.FUNCTION_TYPES,
    "rust": _rust.FUNCTION_TYPES,
    "go": _go.FUNCTION_TYPES,
    "php": _php.FUNCTION_TYPES,
    "c": _c.FUNCTION_TYPES,
    "cpp": _cpp.FUNCTION_TYPES,
}

#: The call-expression node type(s) per language. Most languages have a
#: single call node type; PHP spreads calls across three
#: (``function_call_expression`` for bare ``foo()``,
#: ``member_call_expression`` for ``$this->foo()``,
#: ``scoped_call_expression`` for ``self::foo()`` / ``static::foo()``), so
#: the value is a set. Constructor calls (``new_expression`` /
#: ``object_creation_expression``) are deliberately excluded - constructing
#: an instance is not a self-recursive *function* call in the sense rule 1
#: cares about.
_CALL_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.CALL}),
    "javascript": frozenset({_js.CALL_EXPRESSION}),
    "typescript": frozenset({_ts.CALL_EXPRESSION}),
    "rust": frozenset({_rust.CALL_EXPRESSION}),
    "java": frozenset({_java.METHOD_INVOCATION}),
    "go": frozenset({_go.CALL_EXPRESSION}),
    "php": frozenset({_php.FUNCTION_CALL_EXPRESSION, _php.MEMBER_CALL_EXPRESSION, _php.NULLSAFE_MEMBER_CALL_EXPRESSION, _php.SCOPED_CALL_EXPRESSION}),
    "c": frozenset({_c.CALL_EXPRESSION}),
    "cpp": frozenset({_cpp.CALL_EXPRESSION}),
}

#: Identifiers that name "the current object" per language. A call
#: ``self.foo()`` / ``this.foo()`` inside ``foo`` is self-recursion;
#: ``other.foo()`` is not, even though it shares the bareword name.
_SELF_RECEIVERS: dict[str, frozenset[str]] = {
    "python": frozenset({"self", "cls"}),
    "javascript": frozenset({_js.THIS}),
    "typescript": frozenset({_ts.THIS}),
    "rust": frozenset({"self"}),
    "cpp": frozenset({_cpp.THIS}),
}

#: Member-access node shape per language: ``(node_type, object_field,
#: name_field)``. Used to recognise self-qualified calls. Java is absent
#: because its ``method_invocation`` carries the receiver and method name
#: as fields on the call node itself, not via a nested member-access node.
_MEMBER_ACCESS: dict[str, tuple[str, str, str]] = {
    "python": (_py.ATTRIBUTE, "object", "attribute"),
    "javascript": (_js.MEMBER_EXPRESSION, "object", "property"),
    "typescript": (_ts.MEMBER_EXPRESSION, "object", "property"),
    "rust": (_rust.FIELD_EXPRESSION, "value", "field"),
    # C++ ``this->m()``: field_expression with ``argument`` = this, ``field`` = m.
    "cpp": (_cpp.FIELD_EXPRESSION, "argument", "field"),
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
    if callee.type == _py.IDENTIFIER:
        return node_text(callee) == func_name
    if lang == _cpp.EXTRA_NAME and callee.type == _cpp.QUALIFIED_IDENTIFIER:
        # C++ ``ns::f()`` / ``S::m()`` self-call - the trailing ``name`` is the
        # bareword; a match against the enclosing function name is a self-call
        # (the same name-based heuristic as the bare-identifier case).
        name = callee.child_by_field_name("name")
        return name is not None and node_text(name) == func_name
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
    return obj is None or obj.type == _java.THIS


def _go_receiver_name(func: tree_sitter.Node) -> str | None:
    """Return a Go method's receiver variable name, or None.

    For ``func (s *Svc) Walk()`` returns ``"s"`` - the user-chosen
    receiver identifier is Go's analogue of ``self`` / ``this``, so a
    ``s.Walk(...)`` call inside ``Walk`` is self-recursion. Returns None
    for plain functions (no receiver) and for methods with an unnamed
    receiver (``func (*Svc) Walk()`` - the receiver can't be referenced,
    so a receiver-qualified self-call is impossible).
    """
    if func.type != _go.METHOD_DECLARATION:
        return None
    receiver = func.child_by_field_name("receiver")
    if receiver is None:  # pragma: no cover - defensive: method_declaration always has a receiver
        return None
    for decl in receiver.named_children:
        if decl.type != _go.PARAMETER_DECLARATION:  # pragma: no cover - defensive: receiver list holds only a parameter_declaration
            continue
        ident = next((child for child in decl.named_children if child.type == _go.IDENTIFIER), None)
        if ident is not None:
            return node_text(ident)
    return None


def _go_call_targets_self(call_node: tree_sitter.Node, func_name: str, receiver_name: str | None, *, is_method: bool) -> bool:
    """Return True if a Go ``call_expression`` is a direct self-call.

    Plain functions self-recurse via a bare ``foo()`` whose callee
    identifier equals the function name. Methods self-recurse via a
    receiver-qualified ``s.Walk()`` whose selector operand matches the
    receiver name and field matches the method name. A bare same-named call
    inside a method is NOT recursion - it denotes a different package-level
    function, since a method must be called through its receiver. The
    ``is_method`` flag (not ``receiver_name is None``) distinguishes the two:
    a method with an UNNAMED receiver (``func (*Svc) Walk()``) has no
    receiver name yet must still not fire on a bare ``Walk()`` call.
    """
    callee = call_node.child_by_field_name("function")
    if callee is None:  # pragma: no cover - defensive: call_expression always has a function field
        return False
    if callee.type == _go.IDENTIFIER:
        return not is_method and node_text(callee) == func_name
    if callee.type == _go.SELECTOR_EXPRESSION:
        if receiver_name is None:
            return False
        operand = callee.child_by_field_name("operand")
        field = callee.child_by_field_name("field")
        return operand is not None and field is not None and node_text(operand) == receiver_name and node_text(field) == func_name
    return False


def _php_call_targets_self(call_node: tree_sitter.Node, func_name: str, *, is_method: bool) -> bool:
    """Return True if a PHP call node is a direct self-call to *func_name*.

    Fires for a bare ``foo()`` (``function_call_expression`` whose
    ``function`` field is a ``name`` matching the function), a
    ``$this->foo()`` (``member_call_expression`` whose object is ``$this``),
    or a ``self::foo()`` / ``static::foo()``
    (``scoped_call_expression`` whose scope is the ``self`` / ``static``
    ``relative_scope``). A call through any other object or class
    (``$other->foo()`` / ``Other::foo()``) is not self-recursion.

    Inside a class method (``is_method``), a bare ``foo()`` is NOT recursion:
    PHP resolves an unqualified call to a global / namespaced function, never
    to the enclosing method, so a method recurses only through
    ``$this->`` / ``self::`` / ``static::``.
    """
    if call_node.type == _php.FUNCTION_CALL_EXPRESSION:
        if is_method:
            return False
        callee = call_node.child_by_field_name("function")
        return callee is not None and callee.type == _php.NAME and node_text(callee) == func_name
    return _php_qualified_self_call(call_node, func_name)


def _php_qualified_self_call(call_node: tree_sitter.Node, func_name: str) -> bool:
    """Return True if a PHP ``$this->`` / ``self::`` / ``static::`` call targets *func_name*."""
    name = call_node.child_by_field_name("name")
    if name is None or node_text(name) != func_name:
        return False
    if call_node.type in (_php.MEMBER_CALL_EXPRESSION, _php.NULLSAFE_MEMBER_CALL_EXPRESSION):
        # ``$this->foo()`` and ``$this?->foo()`` both recurse - ``$this`` is
        # never null, so the nullsafe form still calls (and recurses into) foo.
        obj = call_node.child_by_field_name("object")
        return obj is not None and node_text(obj) == "$this"
    # scoped_call_expression: ``self::`` / ``static::`` recursion only.
    scope = call_node.child_by_field_name("scope")
    return scope is not None and scope.type == _php.RELATIVE_SCOPE and node_text(scope) in ("self", "static")


def _targets_self(call_node: tree_sitter.Node, func_name: str, lang: str, receiver_name: str | None, *, is_method: bool) -> bool:
    """Dispatch self-recursion detection to the per-language predicate."""
    if lang == "java":
        return _java_call_targets_self(call_node, func_name)
    if lang == "go":
        return _go_call_targets_self(call_node, func_name, receiver_name, is_method=is_method)
    if lang == "php":
        return _php_call_targets_self(call_node, func_name, is_method=is_method)
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
    return callee is not None and callee.type == _py.IDENTIFIER


def _java_arity_rules_out_self(call_node: tree_sitter.Node, func: tree_sitter.Node) -> bool:
    """Return True if argument count proves this Java call is a *different* overload.

    Java overloads by signature, and the convenience-overload-delegates-to-the-
    general-one pattern is what Commons Lang and Guava are built from::

        boolean[] add(boolean[] a, int i, boolean e) {
            return (boolean[]) add(a, i, Boolean.valueOf(e), Boolean.TYPE);
        }                        ^ four arguments, three parameters - a different method

    A call whose argument count differs from the enclosing method's parameter
    count cannot be a self-call, and deciding that needs no type resolution at
    all. Measured on Commons Lang this accounted for the overwhelming majority of
    SAFE105 findings, which were 51% of the project's default output.

    Varargs are the one case arity cannot settle: ``vg(String... s)`` has one
    parameter and accepts any number of arguments, so a mismatch proves nothing
    and the call stays reported. Same for a call that omits the argument list
    entirely, which should not occur but must not be read as arity zero.
    """
    params = func.child_by_field_name("parameters")
    args = call_node.child_by_field_name("arguments")
    if params is None or args is None:
        return False  # pragma: no cover - defensive: both fields are always present on these nodes
    if any(child.type == _java.SPREAD_PARAMETER for child in params.named_children):
        return False
    return len(args.named_children) != len(params.named_children)


def _rust_is_associated_fn(func: tree_sitter.Node) -> bool:
    """Return True if *func* is a Rust ``fn`` declared inside an ``impl`` or ``trait``.

    A bare ``name(..)`` inside an associated function can never be a self-call:
    reaching the method requires ``self.name()`` or ``Type::name(..)``, so the
    bare identifier always resolves to a free function or an imported item. This
    is the same reasoning the ``is_method`` flag already applies to Go and PHP
    methods, which Rust simply never got.
    """
    parent = func.parent
    if parent is None or parent.type != _rust.DECLARATION_LIST:
        return False
    grandparent = parent.parent
    return grandparent is not None and grandparent.type in (_rust.IMPL_ITEM, _rust.TRAIT_ITEM)


def _rust_locally_shadowed(func: tree_sitter.Node, func_name: str) -> bool:
    """Return True if *func*'s own body imports an item named *func_name*.

    ``use`` inside a function body rebinds the name for the rest of the block, so
    the bare identifier no longer refers to the enclosing function::

        fn symlink(src: u32, dst: u32) -> u32 {
            use std::os::unix::fs::symlink;   // shadows the fn name
            symlink(src, dst).unwrap()        // std's symlink, not recursion
        }

    This shape is in ripgrep (`crates/ignore/src/walk.rs`). Only the final
    segment is compared, because that is the name the import binds - the path it
    came from is irrelevant. Nested functions are skipped so an import inside one
    does not silence the outer function.
    """
    for node in walk(func, skip_types=(_rust.FUNCTION_ITEM,)):
        if node is func or node.type != _rust.USE_DECLARATION:
            continue
        if func_name in _rust_imported_names(node):
            return True
    return False


def _rust_imported_names(use_decl: tree_sitter.Node) -> set[str]:
    """Return every name a Rust ``use`` declaration binds in the current scope.

    Covers the three shapes that can bind a bare name: a plain or scoped path
    (``use p::q::name``), a brace list (``use p::{a, b}``, including a nested
    list), and an alias (``use p::x as name``), where the alias is what binds.
    Collecting the identifiers reachable without descending past an alias is
    enough - a superfluous name costs only a missed finding, never a false one.
    """
    return {name for node in walk(use_decl) if (name := _rust_bound_name(node)) is not None}


def _rust_bound_name(node: tree_sitter.Node) -> str | None:
    """Return the bare name *node* contributes to the enclosing ``use``, or None.

    A ``scoped_identifier`` binds its trailing ``name`` field; a bare
    ``identifier`` that is not part of one binds itself (a brace-list entry or an
    ``as`` alias).
    """
    if node.type == _rust.SCOPED_IDENTIFIER:
        name = node.child_by_field_name("name")
        return node_text(name) if name is not None else None
    if node.type == _rust.IDENTIFIER and node.parent is not None and node.parent.type != _rust.SCOPED_IDENTIFIER:
        return node_text(node)
    return None


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


def _bare_call_cannot_recurse(func: tree_sitter.Node, func_name: str, func_types: frozenset[str], lang: str) -> bool:
    """Return True if an unqualified call in *func*'s body cannot be a self-call.

    Three independent reasons, combined here rather than threaded through
    ``_targets_self`` - that dispatcher's Rust path takes no ``is_method``
    argument, so setting the flag there would be a silent no-op:

    * a same-named nested function rebinds the name (every language);
    * a Rust ``fn`` in an ``impl`` / ``trait`` is reachable only as
      ``self.name()`` or ``Type::name(..)``, never bare (#160);
    * a Rust function-local ``use`` rebinds the name for the block (#173).

    Qualified calls are unaffected in every case - ``self.name()`` still reports.
    """
    if func_name in _directly_nested_function_names(func, func_types):
        return True
    if lang != _rust.EXTRA_NAME:
        return False
    return _rust_is_associated_fn(func) or _rust_locally_shadowed(func, func_name)


def _is_self_call(
    call_node: tree_sitter.Node,
    func: tree_sitter.Node,
    func_name: str,
    lang: str,
    receiver_name: str | None,
    *,
    bare_cannot_recurse: bool,
    is_method: bool,
) -> bool:
    """Return True if *call_node* really is a self-call of *func*.

    The two exclusions run before the name match, because both decide the
    question without needing it:

    * an unqualified call where the name cannot denote this function
      (:func:`_bare_call_cannot_recurse`);
    * in Java, an argument count that does not fit this signature, which proves a
      different overload (:func:`_java_arity_rules_out_self`).
    """
    if bare_cannot_recurse and _call_is_bare(call_node, lang):
        return False
    if lang == _java.EXTRA_NAME and _java_arity_rules_out_self(call_node, func):
        return False
    return _targets_self(call_node, func_name, lang, receiver_name, is_method=is_method)


class NoRecursionRule(BaseRule):
    """Flag functions that call themselves directly (Power of Ten rule 1)."""

    name = "no_recursion"
    code = "SAFE105"
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _go.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every function whose body directly calls itself."""
        lang = resolve_lang_name(filepath)
        func_types = _FUNCTION_TYPES_BY_LANG[lang]
        call_types = _CALL_TYPES_BY_LANG[lang]
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in func_types:
                continue
            violations.extend(self._check_function(filepath, node, func_types, call_types, lang))
        return violations

    def _check_function(
        self,
        filepath: str,
        func: tree_sitter.Node,
        func_types: frozenset[str],
        call_types: frozenset[str],
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
        name_node = function_name_node(func, lang)
        if name_node is None:
            return []
        func_name = node_text(name_node)
        # Both Go and PHP name their method node ``method_declaration``. The
        # ``is_method`` flag suppresses bare-call self-recursion for methods
        # (a bare ``foo()`` denotes a package-level / global function, not the
        # method). Only Go carries a user-named receiver to resolve.
        is_method = func.type == _go.METHOD_DECLARATION and lang in (_go.EXTRA_NAME, _php.EXTRA_NAME)
        receiver_name = _go_receiver_name(func) if (is_method and lang == _go.EXTRA_NAME) else None
        bare_cannot_recurse = _bare_call_cannot_recurse(func, func_name, func_types, lang)
        violations: list[Violation] = []
        for node in walk(func, skip_types=tuple(func_types)):
            if node.type not in call_types:
                continue
            if not _is_self_call(node, func, func_name, lang, receiver_name, bare_cannot_recurse=bare_cannot_recurse, is_method=is_method):
                continue
            base = self._make_violation_for_node(
                filepath,
                node,
                f'Function "{func_name}" calls itself; recursion has no guaranteed stack bound (Power of Ten rule 1) - refactor to an explicit loop or worklist',
            )
            # Violation is frozen; attach the advisory suggestion via replace.
            violations.append(replace(base, suggestions=(_ITERATIVE_SUGGESTION,)))
        return violations
