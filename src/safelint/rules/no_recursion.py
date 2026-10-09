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

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, NamedTuple

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
    from collections.abc import Mapping

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

    A ``receiver_parameter`` (``void tick(Outer Outer.this, int n)``, Java 8's
    explicit-receiver form) is a named child of ``formal_parameters`` but is never
    passed at a call site, so counting it would make every self-call in such a
    method look like an arity mismatch and silence it.
    """
    params = func.child_by_field_name("parameters")
    args = call_node.child_by_field_name("arguments")
    if params is None or args is None:
        return False  # pragma: no cover - defensive: both fields are always present on these nodes
    if any(child.type == _java.SPREAD_PARAMETER for child in params.named_children):
        return False
    declared = [child for child in params.named_children if child.type != _java.RECEIVER_PARAMETER]
    return len(args.named_children) != len(declared)


def _java_positional_params(func: tree_sitter.Node) -> tuple[tuple[str | None, str | None], ...]:
    """Return ``(declared type, name)`` per positional parameter of a Java method.

    The explicit receiver (``void tick(Outer Outer.this, int n)``) is excluded, as
    it is never passed at a call site.
    """
    params = func.child_by_field_name("parameters")
    if params is None:
        return ()
    out: list[tuple[str | None, str | None]] = []
    for child in params.named_children:
        if child.type == _java.RECEIVER_PARAMETER:
            continue
        type_node = child.child_by_field_name("type")
        name_node = child.child_by_field_name("name")
        out.append((node_text(type_node) if type_node is not None else None, node_text(name_node) if name_node is not None else None))
    return tuple(out)


def _java_type_variables(func: tree_sitter.Node) -> frozenset[str]:
    """Return the type-variable names in scope for *func*: its own plus its type's.

    A parameter declared as a type variable accepts anything, so none of the
    argument-shape rules below can rule it out: ``<T> void f(T t)`` really does
    accept ``f((Object) x)``, with ``T`` inferred as ``Object``.
    """
    holders = (func, _java_enclosing_type(func))
    names: set[str] = set()
    for holder in holders:
        if holder is None:
            continue
        type_params = holder.child_by_field_name("type_parameters")
        if type_params is None:
            continue
        names |= {node_text(entry.child_by_field_name("name") or entry) for entry in type_params.named_children}
    return frozenset(names)


def _java_enclosing_type(func: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the class / interface / enum / record declaration *func* is declared in."""
    cur = func.parent
    while cur is not None:
        if cur.type in _java.TYPE_DECLARATION_TYPES:
            return cur
        cur = cur.parent
    return None


def _java_foreach_array_sources(func: tree_sitter.Node) -> dict[str, str]:
    """Map each for-each variable in *func* to the bare name it iterates over.

    ``for (final boolean element : array)`` records ``element -> array``. When
    ``array`` is the method's own array parameter, ``element`` has its element
    type, which is never assignable to the array type itself.
    """
    sources: dict[str, str] = {}
    for node in walk(func, skip_types=tuple(_java.FUNCTION_TYPES)):
        if node.type != _java.ENHANCED_FOR_STATEMENT:
            continue
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name is not None and value is not None and value.type == _java.IDENTIFIER:
            sources[node_text(name)] = node_text(value)
    return sources


def _collect_functions(
    root: tree_sitter.Node,
    func_types: frozenset[str],
    lang: str,
) -> tuple[tuple[tree_sitter.Node, ...], dict[int, dict[str, tuple[tuple[int, bool], ...]]]]:
    """Return the functions to check and, for Java, the per-type overload table.

    One walk serves both. Resolving an overload needs the sibling declarations, so
    the table must be complete before any function is checked, and re-walking the
    enclosing type per method would make the rule quadratic in the file; walking
    the tree a second time just to build it was measurably slower on Guava.
    """
    want_table = lang == _java.EXTRA_NAME
    funcs: list[tree_sitter.Node] = []
    table: dict[int, dict[str, list[tuple[int, bool]]]] = {}
    for node in walk(root):
        if node.type in func_types:
            funcs.append(node)
        if want_table and node.type == _java.METHOD_DECLARATION:
            _record_java_method(table, node)
    return tuple(funcs), {owner: {name: tuple(entries) for name, entries in names.items()} for owner, names in table.items()}


def _record_java_method(table: dict[int, dict[str, list[tuple[int, bool]]]], node: tree_sitter.Node) -> None:
    """Record *node*'s signature shape under its enclosing type and name."""
    name_node = node.child_by_field_name("name")
    owner = _java_enclosing_type(node)
    if name_node is None or owner is None:
        return
    table.setdefault(owner.id, {}).setdefault(node_text(name_node), []).append(_java_signature_shape(node))


def _java_signature_shape(func: tree_sitter.Node) -> tuple[int, bool]:
    """Return ``(positional parameter count, is varargs)`` for a Java method.

    Deliberately avoids resolving parameter types and names: this runs for every
    method in the file, and decoding the source text of each one showed up as the
    dominant cost of building the table.
    """
    params = func.child_by_field_name("parameters")
    if params is None:
        return (0, False)
    count = 0
    varargs = False
    for child in params.named_children:
        if child.type == _java.RECEIVER_PARAMETER:
            continue
        count += 1
        varargs = varargs or child.type == _java.SPREAD_PARAMETER
    return (count, varargs)


def _java_delegation_is_provable(call_node: tree_sitter.Node, facts: _FunctionFacts) -> bool:
    """Return True if *call_node* provably targets a method other than the enclosing one.

    Two independent facts, each decidable from the source text alone. Neither is a
    likelihood heuristic: each is a reason the enclosing method is not a candidate
    for this call at all, so suppressing cannot hide genuine recursion.

    * **An argument cast to ``Object`` against a non-``Object`` parameter.**
      ``remove((Object) array, index)`` inside ``remove(boolean[], int)``:
      ``Object`` is not assignable to ``boolean[]``.
    * **An element of the parameter at that same position.** ``append(lhs[i], ..)``
      inside ``append(Object[] lhs, ..)``, directly or via a for-each variable: an
      element type is never assignable to its own array type.

    A third condition was tried and withdrawn: "a varargs method loses to a
    same-named fixed-arity sibling at this argument count". JLS 15.12.2 does
    resolve phases 1 and 2 (no varargs) before phase 3, but a method is a
    *candidate* in those phases only if it is applicable, which needs the argument
    types to be compatible and not merely counted. With an incompatible sibling -
    ``j(int, int, int)`` beside ``j(String, String...)`` calling
    ``j(a, "b", "c")`` - phases 1 and 2 find nothing and phase 3 selects the
    varargs method, so that call is genuine recursion. Arity alone cannot
    establish applicability, so the condition is unsound and was removed.
    """
    args_node = call_node.child_by_field_name("arguments")
    if args_node is None:
        return False  # pragma: no cover - defensive: method_invocation always has arguments
    args = args_node.named_children
    params = facts.positional_params
    if len(args) != len(params):
        return False
    return any(_java_arg_rules_out_param(arg, params[index], facts.type_variables, facts.foreach_array_sources) for index, arg in enumerate(args))


def _java_arg_rules_out_param(
    arg: tree_sitter.Node,
    param: tuple[str | None, str | None],
    tvars: frozenset[str],
    foreach: Mapping[str, str],
) -> bool:
    """Return True if *arg* cannot be passed to *param*, so this is a different overload."""
    ptype, pname = param
    if ptype is None or ptype in tvars:
        return False
    if arg.type == _java.CAST_EXPRESSION:
        return _java_cast_rules_out_param(arg, ptype)
    if not ptype.endswith("[]") or pname is None:
        return False
    return _java_arg_is_element_of(arg, pname, foreach)


#: ``Object`` written both ways. A parameter declared ``java.lang.Object`` accepts
#: an ``(Object)`` cast, so comparing the raw source text would read the two
#: spellings as different types and silence a genuine self-call.
_JAVA_OBJECT_SPELLINGS = frozenset({"Object", "java.lang.Object"})


def _java_cast_rules_out_param(arg: tree_sitter.Node, ptype: str) -> bool:
    """Return True if *arg* is cast to ``Object`` and *ptype* is not ``Object``.

    Only this direction is decidable without a type hierarchy: a cast to a subtype
    of the parameter type is still applicable, so ``(String) o`` passed to a
    ``CharSequence`` parameter proves nothing.
    """
    cast_type = arg.child_by_field_name("type")
    if cast_type is None or node_text(cast_type) not in _JAVA_OBJECT_SPELLINGS:
        return False
    return ptype not in _JAVA_OBJECT_SPELLINGS


def _java_arg_is_element_of(arg: tree_sitter.Node, pname: str, foreach: Mapping[str, str]) -> bool:
    """Return True if *arg* is an element of the array parameter named *pname*.

    Either by index (``lhs[i]``) or through a for-each variable
    (``for (T e : lhs) f(e)``). Both have the element type, which is never
    assignable to the array type the parameter declares.
    """
    if arg.type == _java.ARRAY_ACCESS:
        base = arg.child_by_field_name("array")
        return base is not None and base.type == _java.IDENTIFIER and node_text(base) == pname
    return arg.type == _java.IDENTIFIER and foreach.get(node_text(arg)) == pname


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


def _rust_shadowed_spans(func: tree_sitter.Node, func_name: str) -> tuple[tuple[int, int], ...]:
    """Return the byte spans in which a function-local ``use`` rebinds *func_name*.

    ``use`` inside a function body rebinds the name, so the bare identifier no
    longer refers to the enclosing function::

        fn symlink(src: u32, dst: u32) -> u32 {
            use std::os::unix::fs::symlink;   // shadows the fn name
            symlink(src, dst).unwrap()        // std's symlink, not recursion
        }

    This shape is in ripgrep (`crates/ignore/src/walk.rs`). Only the final
    segment is compared, because that is the name the import binds - the path it
    came from is irrelevant. Nested functions are skipped so an import inside one
    does not silence the outer function.

    A ``use`` is an *item*, so it binds throughout its enclosing block regardless
    of position, but no further: an import in a nested block leaves the rest of
    the body alone. Returning that block's span rather than a function-wide
    boolean keeps a genuine recursive call outside the block reportable::

        fn walk(n: u32) -> u32 {
            { use std::fs::walk; let _ = walk; }
            walk(n - 1)                       // still recursion
        }
    """
    spans: list[tuple[int, int]] = []
    for node in walk(func, skip_types=(_rust.FUNCTION_ITEM,)):
        if node is func or node.type != _rust.USE_DECLARATION:
            continue
        if func_name not in _rust_imported_names(node):
            continue
        scope = _rust_enclosing_block(node)
        if scope is not None:
            spans.append((scope.start_byte, scope.end_byte))
    return tuple(spans)


def _rust_enclosing_block(use_decl: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the innermost ``block`` whose scope *use_decl* binds its names in."""
    parent = use_decl.parent
    while parent is not None:
        if parent.type == _rust.BLOCK:
            return parent
        parent = parent.parent
    return None  # pragma: no cover - defensive: a function-local `use` always sits in a block


def _node_within_spans(node: tree_sitter.Node, spans: tuple[tuple[int, int], ...]) -> bool:
    """Return True if *node* starts inside any of *spans*.

    Tree-sitter byte spans nest exactly, so a start byte inside a block's span is
    the same test as "is a descendant of that block".
    """
    return any(start <= node.start_byte < end for start, end in spans)


def _rust_imported_names(use_decl: tree_sitter.Node) -> set[str]:
    """Return every name a Rust ``use`` declaration binds in the current scope.

    The shape of the declaration decides, so this walks the structure rather than
    sweeping every identifier underneath it. A flat sweep over-collects the
    *path* segments, which silences genuine recursion in a function named after
    one of them::

        use a::b::{c};     // binds c only - NOT b
        use a::b::*;       // binds b's contents under their own names - not b
        use a::{b::c, d};  // binds c and d - not a, not b

    The rules, one per node kind:

    * a plain or scoped path (``use p::q``) binds its trailing segment;
    * ``use_wildcard`` (``use p::q::*``) binds nothing nameable - the imported
      names are whatever ``q`` contains, which is not in this file;
    * ``scoped_use_list`` (``use p::q::{..}``) binds only what its brace list
      says, with the path's trailing segment carried in for the ``self`` case;
    * ``self`` inside a brace list (``use p::q::{self, a}``) binds ``q``;
    * ``use_as_clause`` binds its ``alias`` and nothing else, so
      ``use other::bar as helper`` does not bind ``bar``.

    Unrecognised path kinds (``crate``, ``super``, a metavariable) contribute no
    name, which leaves the call reported - the safe direction for this rule.
    Iterative, not recursive: SAFE105 polices this codebase.
    """
    names: set[str] = set()
    # Each entry pairs a node with the path segment a ``self`` entry under it
    # would bind (None outside a braced list).
    stack: list[tuple[tree_sitter.Node, str | None]] = [(child, None) for child in use_decl.named_children]
    while len(stack) > 0:
        node, path_tail = stack.pop()
        if node.type == _rust.USE_WILDCARD:
            continue
        if node.type == _rust.SCOPED_USE_LIST:
            _rust_push_use_list(stack, node)
            continue
        if node.type == _rust.USE_LIST:
            stack.extend((entry, path_tail) for entry in node.named_children)
            continue
        name = _rust_use_entry_name(node, path_tail)
        if name is not None:
            names.add(name)
    return names


def _rust_use_entry_name(node: tree_sitter.Node, path_tail: str | None) -> str | None:
    """Return the name a leaf ``use`` entry binds, or None if it binds nothing nameable.

    An ``as`` clause binds its alias and nothing else; a ``self`` entry inside a
    braced list binds the path's trailing segment; anything else binds its own
    trailing segment.
    """
    if node.type == _rust.USE_AS_CLAUSE:
        return _rust_path_tail(node.child_by_field_name("alias"))
    if node.type == _rust.SELF:
        return path_tail
    return _rust_path_tail(node)


def _rust_push_use_list(stack: list[tuple[tree_sitter.Node, str | None]], scoped_use_list: tree_sitter.Node) -> None:
    """Queue a ``scoped_use_list``'s entries, carrying its path's trailing segment."""
    entries = scoped_use_list.child_by_field_name("list")
    if entries is None:
        return  # pragma: no cover - defensive: a scoped_use_list always has a list
    tail = _rust_path_tail(scoped_use_list.child_by_field_name("path"))
    stack.extend((entry, tail) for entry in entries.named_children)


def _rust_path_tail(node: tree_sitter.Node | None) -> str | None:
    """Return the trailing segment of a Rust path, or None if it is not a plain path."""
    if node is None:
        return None
    if node.type == _rust.SCOPED_IDENTIFIER:
        name = node.child_by_field_name("name")
        return node_text(name) if name is not None else None
    if node.type == _rust.IDENTIFIER:
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

    Two function-wide reasons, combined here rather than threaded through
    ``_targets_self`` - that dispatcher's Rust path takes no ``is_method``
    argument, so setting the flag there would be a silent no-op:

    * a same-named nested function rebinds the name (every language);
    * a Rust ``fn`` in an ``impl`` / ``trait`` is reachable only as
      ``self.name()`` or ``Type::name(..)``, never bare (#160).

    The third reason, a Rust function-local ``use`` (#173), is block-scoped rather
    than function-wide, so it is decided per call against
    :func:`_rust_shadowed_spans` instead of here.

    Qualified calls are unaffected in every case - ``self.name()`` still reports.
    """
    if func_name in _directly_nested_function_names(func, func_types):
        return True
    if lang != _rust.EXTRA_NAME:
        return False
    return _rust_is_associated_fn(func)


@dataclass(frozen=True, eq=False)
class _FunctionFacts:
    """Everything about the enclosing function a per-call decision needs.

    Every field is computed once per function, which keeps the per-call predicates
    to two arguments instead of eight and keeps the per-call work O(1) in the size
    of the body. ``eq=False`` so no ``__hash__`` is generated: one field is a
    mapping, and a frozen dataclass that looks hashable but raises on a mapping
    field is a trap this codebase has already been bitten by once.
    """

    node: tree_sitter.Node
    name: str
    lang: str
    receiver_name: str | None
    bare_cannot_recurse: bool
    shadowed_spans: tuple[tuple[int, int], ...]
    is_method: bool
    #: Java only: ``(parameter count, is varargs)`` for every same-named method in
    #: the enclosing type, including this one. Empty for other languages.
    sibling_arities: tuple[tuple[int, bool], ...] = ()
    is_varargs: bool = False
    #: Java only: the positional ``(declared type, name)`` of each parameter, the
    #: type variables in scope, and each for-each variable's source. All three are
    #: consulted per call, so they are resolved here rather than re-derived; the
    #: for-each map in particular needs a body walk.
    positional_params: tuple[tuple[str | None, str | None], ...] = ()
    type_variables: frozenset[str] = frozenset()
    foreach_array_sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def rival_arities(self) -> tuple[tuple[int, bool], ...]:
        """The same-named declarations in this type other than this method.

        One occurrence of this method's own shape is dropped rather than every
        matching one: ``f(int)`` and ``f(String)`` share the shape ``(1, False)``,
        so removing all of them would hide a genuine rival.
        """
        rivals = list(self.sibling_arities)
        own = (len(self.positional_params), self.is_varargs)
        if own in rivals:
            rivals.remove(own)
        return tuple(rivals)


def _is_self_call(call_node: tree_sitter.Node, facts: _FunctionFacts) -> bool:
    """Return True if *call_node* really is a self-call of the enclosing function.

    The two exclusions run before the name match, because both decide the
    question without needing it:

    * an unqualified call where the name cannot denote this function, either
      function-wide (:func:`_bare_call_cannot_recurse`) or only within the block
      an import shadows it in (:func:`_rust_shadowed_spans`);
    * in Java, an argument count that does not fit this signature, which proves a
      different overload (:func:`_java_arity_rules_out_self`).
    """
    if _bare_call_rules_out_self(call_node, facts):
        return False
    if facts.lang == _java.EXTRA_NAME and _java_rules_out_self(call_node, facts):
        return False
    return _targets_self(call_node, facts.name, facts.lang, facts.receiver_name, is_method=facts.is_method)


def _message_for(call_node: tree_sitter.Node, facts: _FunctionFacts) -> str:
    """Return the message for this call, hedged only when a rival overload could take it."""
    return _ambiguous_message(facts.name) if _java_rival_could_take_call(call_node, facts) else _certain_message(facts.name)


def _java_rival_could_take_call(call_node: tree_sitter.Node, facts: _FunctionFacts) -> bool:
    """Return True if a same-named sibling could accept this call's argument count.

    The question is per call, not per method: a type holding ``f(int)`` and
    ``f(int, int)`` has an overloaded name, but a one-argument call inside
    ``f(int)`` has only one candidate and so resolves with certainty. Hedging it
    would be over-correction in the other direction.
    """
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return False  # pragma: no cover - defensive: method_invocation always has arguments
    count = len(args.named_children)
    return any(_java_accepts_arity(shape, count) for shape in facts.rival_arities)


def _java_accepts_arity(shape: tuple[int, bool], arg_count: int) -> bool:
    """Return True if a method of *shape* can be invoked with *arg_count* arguments.

    *shape* is the ``(parameter count, is varargs)`` pair the overload table stores.
    A varargs method accepts anything from its fixed prefix upwards.
    """
    param_count, varargs = shape
    if varargs:
        return arg_count >= param_count - 1
    return arg_count == param_count


def _certain_message(func_name: str) -> str:
    """Build the message for a call that can only be a self-call."""
    return f'Function "{func_name}" calls itself; recursion has no guaranteed stack bound (Power of Ten rule 1) - refactor to an explicit loop or worklist'


def _ambiguous_message(func_name: str) -> str:
    """Build the message for a call whose target needs type information to resolve.

    When the enclosing type declares the name more than once, a same-arity call may
    reach a sibling overload instead of recursing. The argument-shape rules in
    :func:`_java_delegation_is_provable` settle the cases the source text settles;
    what is left needs the declared types of locals and fields, which means a
    classpath. Saying so is more useful than either asserting recursion that may
    not be there or dropping the finding - the latter would silence genuine
    recursion in any method that happens to be overloaded.

    Limitation: only declarations on the enclosing type are known. A same-named
    method **inherited** from a superclass can also win resolution, so the
    unhedged message means "no rival in this type", not "no rival anywhere";
    resolving that would need the supertype's source, which means a classpath.
    """
    return (
        f'Function "{func_name}" calls "{func_name}", which is overloaded in this type, so the target cannot be '
        f"resolved without type information; if it is this method, recursion has no guaranteed stack bound "
        f"(Power of Ten rule 1) - refactor to an explicit loop or worklist"
    )


def _sibling_arities(func: tree_sitter.Node, func_name: str, methods: dict[int, dict[str, tuple[tuple[int, bool], ...]]]) -> tuple[tuple[int, bool], ...]:
    """Return the same-named declarations in *func*'s enclosing type, or empty."""
    if not methods:
        return ()
    owner = _java_enclosing_type(func)
    if owner is None:
        return ()
    return methods.get(owner.id, {}).get(func_name, ())


def _java_is_varargs(func: tree_sitter.Node) -> bool:
    """Return True if *func*'s last parameter is a varargs (``T...``) parameter."""
    params = func.child_by_field_name("parameters")
    if params is None:
        return False
    return any(child.type == _java.SPREAD_PARAMETER for child in params.named_children)


def _build_function_facts(
    func: tree_sitter.Node,
    func_name: str,
    func_types: frozenset[str],
    lang: str,
    methods: dict[int, dict[str, tuple[tuple[int, bool], ...]]],
) -> _FunctionFacts:
    """Collect the per-function invariants the per-call predicates need."""
    # Both Go and PHP name their method node ``method_declaration``. The
    # ``is_method`` flag suppresses bare-call self-recursion for methods
    # (a bare ``foo()`` denotes a package-level / global function, not the
    # method). Only Go carries a user-named receiver to resolve.
    is_method = func.type == _go.METHOD_DECLARATION and lang in (_go.EXTRA_NAME, _php.EXTRA_NAME)
    java = _java_facts(func) if lang == _java.EXTRA_NAME else _NO_JAVA_FACTS
    return _FunctionFacts(
        node=func,
        name=func_name,
        lang=lang,
        receiver_name=_go_receiver_name(func) if (is_method and lang == _go.EXTRA_NAME) else None,
        bare_cannot_recurse=_bare_call_cannot_recurse(func, func_name, func_types, lang),
        shadowed_spans=_rust_shadowed_spans(func, func_name) if lang == _rust.EXTRA_NAME else (),
        is_method=is_method,
        sibling_arities=_sibling_arities(func, func_name, methods),
        is_varargs=_java_is_varargs(func) if lang == _java.EXTRA_NAME else False,
        positional_params=java.positional_params,
        type_variables=java.type_variables,
        foreach_array_sources=java.foreach_array_sources,
    )


class _JavaFacts(NamedTuple):
    """The Java-only half of :class:`_FunctionFacts`, resolved in one pass."""

    positional_params: tuple[tuple[str | None, str | None], ...]
    type_variables: frozenset[str]
    foreach_array_sources: Mapping[str, str]


_NO_JAVA_FACTS = _JavaFacts((), frozenset(), {})


def _java_facts(func: tree_sitter.Node) -> _JavaFacts:
    """Resolve the Java-only per-function facts for *func*.

    The for-each map needs a body walk, and it is consulted only for a parameter
    whose declared type is an array, so it is skipped entirely for the large
    majority of methods that declare none.
    """
    params = _java_positional_params(func)
    wants_foreach = any(ptype is not None and ptype.endswith("[]") for ptype, _ in params)
    return _JavaFacts(
        positional_params=params,
        type_variables=_java_type_variables(func),
        foreach_array_sources=_java_foreach_array_sources(func) if wants_foreach else {},
    )


def _java_rules_out_self(call_node: tree_sitter.Node, facts: _FunctionFacts) -> bool:
    """Return True if Java overload resolution cannot select the enclosing method."""
    if _java_arity_rules_out_self(call_node, facts.node):
        return True
    return _java_delegation_is_provable(call_node, facts)


def _bare_call_rules_out_self(call_node: tree_sitter.Node, facts: _FunctionFacts) -> bool:
    """Return True if *call_node* is unqualified and cannot denote the enclosing function."""
    if not _call_is_bare(call_node, facts.lang):
        return False
    return facts.bare_cannot_recurse or _node_within_spans(call_node, facts.shadowed_spans)


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
        # Java overload resolution needs the sibling declarations, so the per-type
        # method table has to be complete before the first function is checked.
        # Both it and the function list come out of a single tree walk.
        funcs, methods = _collect_functions(tree.root_node, func_types, lang)
        violations: list[Violation] = []
        for node in funcs:
            violations.extend(self._check_function(filepath, node, func_types, call_types, lang, methods))
        return violations

    def _check_function(
        self,
        filepath: str,
        func: tree_sitter.Node,
        func_types: frozenset[str],
        call_types: frozenset[str],
        lang: str,
        methods: dict[int, dict[str, tuple[tuple[int, bool], ...]]],
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
        facts = _build_function_facts(func, func_name, func_types, lang, methods)
        violations: list[Violation] = []
        for node in walk(func, skip_types=tuple(func_types)):
            if node.type not in call_types:
                continue
            if not _is_self_call(node, facts):
                continue
            base = self._make_violation_for_node(filepath, node, _message_for(node, facts))
            # Violation is frozen; attach the advisory suggestion via replace.
            violations.append(replace(base, suggestions=(_ITERATIVE_SUGGESTION,)))
        return violations
