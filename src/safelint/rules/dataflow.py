"""Dataflow hybrid rules: tainted_sink, return_value_ignored, null_dereference."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.analysis.dataflow import TaintTracker
from safelint.analysis.dataflow_c import CTaintTracker
from safelint.analysis.dataflow_go import GoTaintTracker
from safelint.analysis.dataflow_java import JavaTaintTracker
from safelint.analysis.dataflow_javascript import JsTaintTracker
from safelint.analysis.dataflow_php import PhpTaintTracker
from safelint.analysis.dataflow_rust import RustTaintTracker
from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
from safelint.languages.c import FUNCTION_TYPES as _C_FUNCTION_TYPES
from safelint.languages.go import FUNC_LITERAL as _GO_FUNC_LITERAL
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.go import IDENTIFIER as _GO_IDENTIFIER
from safelint.languages.go import PARAMETER_DECLARATION as _GO_PARAMETER_DECLARATION
from safelint.languages.go import VARIADIC_PARAMETER_DECLARATION as _GO_VARIADIC_PARAMETER_DECLARATION
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    ATTRIBUTE,
    CALL,
    EXPRESSION_STATEMENT,
    FUNCTION_DEF,
    SUBSCRIPT,
)
from safelint.languages.rust import CLOSURE_EXPRESSION as _RUST_CLOSURE
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Callable

    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
    "rust": _RUST_FUNCTION_TYPES,
    "go": _GO_FUNCTION_TYPES,
    "php": _PHP_FUNCTION_TYPES,
    "c": _C_FUNCTION_TYPES,
}


def _c_function_declarator(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Unwrap pointer / array declarators to the ``function_declarator``, or None (bounded loop)."""
    cur = node
    for _ in range(16):
        if cur is None or cur.type == "function_declarator":
            return cur
        cur = cur.child_by_field_name("declarator")
    return None


def _c_param_identifier(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Unwrap a parameter's declarator to its name ``identifier``, or None (bounded loop)."""
    cur = node
    for _ in range(16):
        if cur is None or cur.type == "identifier":
            return cur
        cur = cur.child_by_field_name("declarator")
    return None


def _c_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names for a C ``function_definition``.

    Parameters nest under ``function_declarator.parameters`` (the function's own
    declarator may be wrapped in a ``pointer_declarator`` for a pointer-returning
    function). Each ``parameter_declaration``'s declarator names one parameter,
    unwrapping pointer / array layers; ``void`` and unnamed prototype parameters
    contribute nothing. ``argv`` enters tainted this way.
    """
    func_decl = _c_function_declarator(func_node.child_by_field_name("declarator"))
    params_node = func_decl.child_by_field_name("parameters") if func_decl is not None else None
    if params_node is None:
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        ident = _c_param_identifier(child.child_by_field_name("declarator"))
        if ident is not None:
            names.add(node_text(ident))
    return names


def _php_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names (``$x`` form) for a PHP function / method / closure.

    Reads the ``parameters`` field (``formal_parameters``). Each
    ``simple_parameter`` / ``variadic_parameter`` / ``property_promotion_parameter``
    wraps a ``variable_name`` whose text (including the ``$``) is the bound
    name. PHP has no ``self`` / ``cls`` convention, so every parameter seeds
    the tainted set. Closure ``use (...)`` captures are a documented v1
    limitation (not seeded).
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover - defensive: valid PHP functions always have a parameters list
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        if child.type not in ("simple_parameter", "variadic_parameter", "property_promotion_parameter"):
            continue
        var = next((c for c in child.named_children if c.type == "variable_name"), None)
        if var is not None:
            names.add(node_text(var))
    return names


# Pass-through wrappers in the JS / TS grammar: nodes whose *runtime
# value* is identical to their inner expression. SAFE803 must peel
# these to see whether the underlying expression is a nullable call -
# without it, TypeScript authors writing ``(foo() as Bar).baz``,
# ``(foo())!.baz``, or ``(foo()).baz`` would slip past the check
# even though the underlying call IS nullable. Mirrors the TS subset
# of ``_SPREADING_TYPES`` in ``analysis/dataflow_javascript.py``;
# kept narrower (no binary / unary / ternary) because for SAFE803
# we only care about pure pass-throughs, not full taint propagation.
def _peel_js_passthrough(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Descend through TS / JS pass-through wrappers, returning the inner expression.

    Handles ``type_assertion`` (TS angle-bracket cast ``<Foo>x``)
    specially because the type comes first and the expression second;
    every other pass-through wrapper has the expression as the first
    named child. AST depth is bounded by Tree-sitter's own depth cap, so
    the loop terminates without an explicit counter.
    """
    while node is not None:
        if node.type not in _JS_PASSTHROUGH_WRAPPER_TYPES or not node.named_children:
            break
        node = node.named_children[1] if node.type == "type_assertion" and len(node.named_children) >= 2 else node.named_children[0]
    return node


_JS_PASSTHROUGH_WRAPPER_TYPES = frozenset(
    {
        "parenthesized_expression",
        "as_expression",
        "satisfies_expression",
        "non_null_expression",
        # ``<Foo>x`` - older TS angle-bracket cast syntax, equivalent
        # to ``as`` but discouraged in TSX (collides with JSX). Plain
        # TS files still use it; SAFE803 must peel it the same as the
        # ``as`` cast or ``(call as Foo)!.bar`` would only be partly
        # handled.
        "type_assertion",
    }
)

# Java pass-through wrappers analogous to the JS / TS set above. Both
# ``parenthesized_expression`` and ``cast_expression`` have the same
# runtime value as their inner expression, so SAFE803 must peel them
# before checking whether the underlying receiver is a nullable call.
# Without these, ``((Foo) map.get(k)).bar`` would slip past the check.
_JAVA_PASSTHROUGH_WRAPPER_TYPES = frozenset(
    {
        "parenthesized_expression",
        "cast_expression",
    }
)


_RUST_PASSTHROUGH_WRAPPER_TYPES = frozenset(
    {
        "parenthesized_expression",
        "reference_expression",  # ``&x`` / ``&mut x``
        "try_expression",  # ``foo()?`` propagates Ok inside the Result
    }
)


def _peel_rust_passthrough(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Descend through Rust pass-through wrappers, returning the inner expression.

    Mirrors :func:`_peel_js_passthrough` and :func:`_peel_java_passthrough`
    for Rust's reference / parenthesis / try-operator shapes. The loop
    is bounded by tree depth.
    """
    while node is not None:
        if node.type not in _RUST_PASSTHROUGH_WRAPPER_TYPES or not node.named_children:
            break
        node = node.named_children[0]
    return node


def _peel_java_passthrough(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Descend through Java pass-through wrappers, returning the inner expression.

    ``cast_expression`` exposes the expression on its ``value`` field
    (the type is on the ``type`` field). ``parenthesized_expression``
    is a single-child wrapper. The loop is bounded by Tree-sitter's
    own depth cap.
    """
    while node is not None:
        if node.type not in _JAVA_PASSTHROUGH_WRAPPER_TYPES:
            break
        if node.type == "cast_expression":
            inner = node.child_by_field_name("value")
        elif node.named_children:
            inner = node.named_children[0]
        else:  # pragma: no cover - defensive: passthrough wrappers always have a child in valid Java
            return node
        if inner is None:  # pragma: no cover - defensive: cast_expression.value is always present in valid Java
            return node
        node = inner
    return node


# Python parameter shapes - kept in sync with the same set in
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

# JavaScript / TypeScript parameter shapes inside ``formal_parameters``.
#
# JavaScript-only shapes appear bare in JS source:
# ``identifier`` (``x``), ``assignment_pattern`` (``x = 5``),
# ``rest_pattern`` (``...args``), ``object_pattern`` /
# ``array_pattern`` (destructuring).
#
# TypeScript wraps each parameter in a typed-parameter wrapper:
# ``required_parameter`` (``x: number``), ``optional_parameter``
# (``x?: number``), ``rest_parameter`` (``...args: number[]``). The
# inner binding pattern is the first named child; the type annotation
# is the second child. ``_javascript_collect_names`` recurses into
# these wrappers via the unwrap step in :func:`_collect_from_ts_param_wrapper`.
_JS_PARAM_TYPES = frozenset(
    {
        # JavaScript shapes
        "identifier",
        "assignment_pattern",
        "rest_pattern",
        "object_pattern",
        "array_pattern",
        # TypeScript wrapper shapes
        "required_parameter",
        "optional_parameter",
        "rest_parameter",
    }
)
_TS_PARAM_WRAPPER_TYPES = frozenset({"required_parameter", "optional_parameter", "rest_parameter"})


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
    if params_node is None:  # pragma: no cover - defensive: valid Python functions always have a parameters list
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
    contribute every bound name to the taint set - the destructured
    fields are themselves tainted entry points. Rest params (``...args``)
    contribute the rest variable name.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover - defensive: arrow functions and named functions both expose ``parameters``
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
    """Walk a JS / TS parameter / pattern node and collect every bound identifier name.

    Dispatches by node-type bucket - leaf identifiers, container patterns
    (array / object / rest), assignment patterns (``b = 5``), pair
    patterns (``{key: alias}``), and TS typed-parameter wrappers
    (``required_parameter`` / ``optional_parameter`` / ``rest_parameter``)
    - into small helpers so this function stays under the
    cyclomatic-complexity cap.
    """
    # TypeScript typed-parameter wrappers: ``required_parameter``,
    # ``optional_parameter``, ``rest_parameter``. The inner binding
    # pattern is the first named child; the type annotation (if any)
    # is the second. Recurse into the inner binding pattern. ``or set()``
    # handles the (defensive) case of a wrapper with no named children.
    while node.type in _TS_PARAM_WRAPPER_TYPES:
        if not node.named_children:
            return set()
        node = node.named_children[0]
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
    return _javascript_collect_names(target) if target else set()  # pragma: no cover - defensive


def _collect_from_pair_pattern(node: tree_sitter.Node) -> set[str]:
    """Collect the bound name from ``{key: alias}`` (alias is bound, not key)."""
    value = node.child_by_field_name("value")
    return _javascript_collect_names(value) if value else set()  # pragma: no branch


def _java_formal_param_name(child: tree_sitter.Node) -> str | None:
    """Return the bound name for a Java ``formal_parameter`` (``Type name``), or None."""
    name_node = child.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":
        return None
    return node_text(name_node)


def _java_spread_param_name(child: tree_sitter.Node) -> str | None:
    """Return the bound name for a Java ``spread_parameter`` (varargs ``T... args``).

    ``spread_parameter`` wraps a ``variable_declarator`` with the
    binding name on the ``name`` field; the variadic ellipsis is
    anonymous.
    """
    decl = next((c for c in child.named_children if c.type == "variable_declarator"), None)
    if decl is None:  # pragma: no cover - defensive: valid Java field/local always has a declarator
        return None
    name_node = decl.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":  # pragma: no cover - defensive: declarator name is always an identifier
        return None
    return node_text(name_node)


def _rust_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names for *func_node* (Rust function or closure).

    Rust functions expose ``parameters`` (the ``(...)`` container);
    closures expose ``closure_parameters`` (the ``|...|`` container).
    Each container holds:

    * ``parameter`` nodes - typed params with a ``pattern`` field
      carrying the binding. Tuple / struct destructuring on the
      pattern is expanded so every bound name enters the tainted set.
    * ``identifier`` nodes - bare names in untyped closure params
      (``|x, y| ...``); contribute the name directly.
    * ``self_parameter`` - the ``self`` / ``&self`` / ``&mut self``
      receiver; ALWAYS skipped because ``self`` is the bound name and
      shouldn't be treated as an untrusted input.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover - defensive: valid Rust functions/closures always have a parameters list
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        names.update(_rust_single_param_names(child))
    return names


def _rust_single_param_names(child: tree_sitter.Node) -> set[str]:
    """Return the bound names contributed by a single Rust param-list entry."""
    if child.type == "self_parameter":
        return set()
    if child.type == "identifier":
        return {node_text(child)}
    if child.type == "parameter":
        pattern = child.child_by_field_name("pattern")
        return _rust_collect_pattern_names(pattern) if pattern is not None else set()
    return set()


_RUST_RECURSIVE_PATTERN_TYPES = frozenset({"mut_pattern", "ref_pattern", "tuple_pattern", "tuple_struct_pattern", "struct_pattern", "captured_pattern"})


def _rust_collect_pattern_names(node: tree_sitter.Node) -> set[str]:
    """Walk a Rust parameter pattern and collect every bound identifier name.

    Mirrors :class:`~safelint.analysis.dataflow_rust.RustTaintTracker._iter_pattern_identifiers`
    but returns a flat set rather than yielding nodes - cheaper for
    parameter seeding where positional info isn't needed.
    """
    # Iterative DFS over the pattern shape; ``field_pattern`` delegates to a
    # helper. Bounded by the pattern's nesting.
    names: set[str] = set()
    stack = [node]
    while len(stack) > 0:
        current = stack.pop()
        if current.type in ("identifier", "shorthand_field_identifier"):
            names.add(node_text(current))
        elif current.type in _RUST_RECURSIVE_PATTERN_TYPES:
            stack.extend(current.named_children)
        elif current.type == "field_pattern":
            names.update(_rust_field_pattern_names(current))
    return names


def _rust_field_pattern_names(node: tree_sitter.Node) -> set[str]:
    """Return the bound name(s) inside a single ``field_pattern`` node."""
    inner = node.child_by_field_name("pattern")
    if inner is not None:
        return _rust_collect_pattern_names(inner)
    shorthand = next((c for c in node.named_children if c.type == "shorthand_field_identifier"), None)
    return {node_text(shorthand)} if shorthand is not None else set()


def _java_lambda_enclosing_tainted(lambda_node: tree_sitter.Node, cache: dict[int, set[str]]) -> set[str]:
    """Return the enclosing function's final tainted set for *lambda_node*.

    Walks the parent chain looking for the nearest function-defining
    ancestor (including outer ``lambda_expression`` nodes), then returns
    that scope's cached tainted set. The cache is populated in pass 1 for
    non-lambda functions and incrementally in pass 2 for outer lambdas
    encountered before inner ones (preorder walk guarantees this).

    Over-approximation: returns the enclosing's *full* tainted set
    regardless of where the lambda sits textually. A local that becomes
    tainted AFTER the lambda is constructed will still appear in the
    lambda's seed - safer than the alternative (missing real bugs) and
    practically rare. Returns an empty set when the parent chain has
    no function ancestor (shouldn't happen in valid Java).
    """
    cur = lambda_node.parent
    while cur is not None:
        if cur.type in _JAVA_FUNCTION_TYPES:
            return cache.get(cur.id, set())
        cur = cur.parent
    return set()  # pragma: no cover - defensive: a lambda in valid Java always has an enclosing function


def _rust_closure_enclosing_tainted(closure_node: tree_sitter.Node, cache: dict[int, set[str]]) -> set[str]:
    """Return the enclosing function / closure's final tainted set for *closure_node*.

    Rust closures capture by reference / value from the enclosing scope,
    so a closure body referencing a tainted local like ``cmd.arg(input)``
    must see ``input`` as tainted even when ``input`` is bound on the
    outer function's parameters or `let` bindings, not on the closure's
    own parameter list. Mirrors the Java lambda approach: walk parents
    to the nearest ``function_item`` or outer ``closure_expression`` and
    return that scope's cached tainted set.

    Same over-approximation as the Java variant: the enclosing's full
    tainted set is returned without regard to textual position, so a
    local that becomes tainted only after the closure is constructed
    still appears in its seed. Trade-off favours not missing real
    sinks; the alternative is unsound. Empty set when no function
    ancestor is found (a closure outside any function isn't valid Rust;
    defensive).
    """
    cur = closure_node.parent
    while cur is not None:
        if cur.type in _RUST_FUNCTION_TYPES:
            return cache.get(cur.id, set())
        cur = cur.parent
    return set()  # pragma: no cover - defensive: a closure in valid Rust always has an enclosing function


def _go_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names for *func_node* (Go function / method / closure).

    Reads the ``parameters`` field (the ``(...)`` list); a single
    ``parameter_declaration`` can bind several names (``a, b int``), and
    ``variadic_parameter_declaration`` binds one (``args ...T``). The
    method receiver lives on the separate ``receiver`` field, never inside
    ``parameters``, so it is excluded structurally - the receiver is the
    method's ``self`` analogue, not an untrusted input.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover - defensive: valid Go functions always have a parameters list
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        if child.type not in (_GO_PARAMETER_DECLARATION, _GO_VARIADIC_PARAMETER_DECLARATION):
            continue
        names.update(node_text(g) for g in child.named_children if g.type == _GO_IDENTIFIER)
    return names


def _go_closure_enclosing_tainted(closure_node: tree_sitter.Node, cache: dict[int, set[str]]) -> set[str]:
    """Return the enclosing function / closure's final tainted set for *closure_node*.

    Go ``func_literal`` closures capture variables from the enclosing
    scope, so a closure body referencing a tainted local must see it as
    tainted even when the local is bound on an outer function. Mirrors
    the Java lambda / Rust closure approach: walk parents to the nearest
    enclosing Go function node and return that scope's cached tainted set.
    The same over-approximation applies (the enclosing's full tainted set
    is returned regardless of textual position).
    """
    cur = closure_node.parent
    while cur is not None:
        if cur.type in _GO_FUNCTION_TYPES:
            return cache.get(cur.id, set())
        cur = cur.parent
    return set()  # pragma: no cover - defensive: a closure in valid Go always has an enclosing function


def _java_param_names(func_node: tree_sitter.Node) -> set[str]:
    """Return all parameter names for *func_node* (Java).

    Java has three formal parameter shapes inside ``formal_parameters``:

    * ``formal_parameter`` - the standard ``Type name`` form, including
      annotated parameters (``@Valid @RequestBody Foo arg``). The
      binding name is on the ``name`` field; the type lives on the
      ``type`` field; annotations live inside the ``modifiers`` child.
    * ``spread_parameter`` - varargs ``T... args``. The binding name
      is on the ``variable_declarator`` child's ``name`` field.
    * ``receiver_parameter`` - ``Foo this`` (rare; explicit-self
      method-on-self idiom). The receiver isn't a bound name the way
      ``self`` / ``cls`` aren't bound names in Python; explicitly
      skipped.

    Lambda parameters have three shapes:

    * ``formal_parameters`` for typed lambdas (``(String a, int b) -> ...``)
    * ``inferred_parameters`` for untyped multi-arg lambdas (``(a, b) -> ...``)
    * **bare ``identifier``** for untyped single-arg lambdas (``a -> ...``).
      In this shape ``params_node`` IS the identifier itself, not a
      container; ``params_node.named_children`` is empty. The early
      ``identifier``-shape branch below seeds the single parameter
      directly, otherwise common Java stream patterns like
      ``list.stream().filter(u -> dangerous(u))`` would silently
      fail to seed ``u`` as tainted and SAFE801 would miss sinks
      reachable through the lambda body.

    Constructor parameters (``constructor_declaration``) share the
    ``formal_parameters`` shape with methods, so the same extraction
    works without special-casing.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:  # pragma: no cover - defensive
        return set()
    # Untyped single-arg lambda: ``params_node`` IS the bare
    # ``identifier`` (no wrapping container). Seed the one bound
    # name directly before falling through to the container path.
    if params_node.type == "identifier":
        return {node_text(params_node)}
    extractors: dict[str, Callable[[tree_sitter.Node], str | None]] = {
        "formal_parameter": _java_formal_param_name,
        "spread_parameter": _java_spread_param_name,
        # ``inferred_parameters`` body (lambda ``(a, b) -> ...``) lists
        # the parameter identifiers directly as named children. ``node_text``
        # returns ``""`` (falsy) for malformed AST; the ``if name is not None``
        # guard below still admits the empty string, which is harmless for
        # the tainted set lookup.
        "identifier": node_text,
    }
    names: set[str] = set()
    for child in params_node.named_children:
        extract = extractors.get(child.type)
        if extract is None:  # pragma: no cover - defensive: receiver_parameter etc. unrelated to taint seeds
            continue
        name = extract(child)
        if name is not None:
            names.add(name)
    return names


class TaintedSinkRule(BaseRule):
    """Track user-controlled inputs flowing into dangerous sinks."""

    name = "tainted_sink"
    code = "SAFE801"
    language = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c")

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

    def _javascript_check(self, filepath: str, tree: tree_sitter.Tree, lang_name: str) -> list[Violation]:
        """Run JS-family (JavaScript or TypeScript) taint analysis on every function in *tree*.

        TypeScript inherits the JavaScript sink / sanitizer / source
        lists by default - same runtime, same threat surface. Users
        can override with ``sinks_typescript`` etc. when they want
        different behaviour for ``.ts`` files.
        """
        sinks_raw, sinks_key = resolve_lang_config_lookup(self.config, "sinks", lang_name, default=[])
        sinks = frozenset(_validated_string_list(sinks_raw, sinks_key))
        sanitizers_raw, sanitizers_key = resolve_lang_config_lookup(self.config, "sanitizers", lang_name, default=[])
        sanitizers = frozenset(_validated_string_list(sanitizers_raw, sanitizers_key))
        sources_raw, sources_key = resolve_lang_config_lookup(self.config, "sources", lang_name, default=[])
        sources = frozenset(_validated_string_list(sources_raw, sources_key))
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

    def _java_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run Java taint analysis on every method / constructor / lambda in *tree*.

        Two-pass walk so lambdas inherit the enclosing function's FULL
        tainted set (params plus locals tainted by the body), not just
        its params. Pass 1 analyses every non-lambda function and
        caches its final tainted set; pass 2 walks lambdas in tree
        order (preorder, so outer lambdas resolve before inner ones)
        and seeds each lambda's tracker with own-params plus the
        enclosing scope's cached tainted set.

        Java's framework preset (``[tool.safelint.java] framework =
        "spring-boot"``) overrides the default ``sinks_java`` /
        ``sources_java`` lists in :mod:`safelint.core.config` to add
        Spring-aware patterns (for example, ``executeQuery`` /
        ``queryForObject`` on ``JdbcTemplate`` and ``getForObject`` /
        ``postForObject`` on ``RestTemplate`` as sinks). The preset
        does NOT extend ``sanitizers_java`` - context-specific output
        encoders (Spring's ``HtmlUtils.htmlEscape``, Apache Commons
        ``escapeHtml*`` / ``escapeXml``, OWASP ``forHtml`` /
        ``forJavaScript`` / ``forCssString``) are deliberately
        excluded from the global sanitizer set because they only
        clear taint for their own output context; including them
        would create false negatives like ``jdbc.query(... +
        htmlEscape(input))`` where HTML encoding doesn't quote SQL
        metacharacters. The vanilla-Java preset uses conservative
        stdlib defaults; both presets share the same narrow
        ``sanitizers_java`` baseline (``sanitize`` / ``validate`` /
        ``quote`` / ``escape``).
        """
        sinks_raw, sinks_key = resolve_lang_config_lookup(self.config, "sinks", "java", default=[])
        sinks = frozenset(_validated_string_list(sinks_raw, sinks_key))
        sanitizers_raw, sanitizers_key = resolve_lang_config_lookup(self.config, "sanitizers", "java", default=[])
        sanitizers = frozenset(_validated_string_list(sanitizers_raw, sanitizers_key))
        sources_raw, sources_key = resolve_lang_config_lookup(self.config, "sources", "java", default=[])
        sources = frozenset(_validated_string_list(sources_raw, sources_key))
        assume = self._resolve_assume_taint_preserving()
        violations: list[Violation] = []
        # Pass 1: analyse non-lambda functions; cache final tainted set
        # keyed by ``node.id`` (the tree-sitter-stable identifier;
        # ``id(wrapper)`` differs across wrapper accesses).
        tainted_cache: dict[int, set[str]] = {}
        for node in walk(tree.root_node):
            if node.type not in _JAVA_FUNCTION_TYPES or node.type == "lambda_expression":
                continue
            tracker = JavaTaintTracker(_java_param_names(node), sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            tainted_cache[node.id] = set(tracker.tainted)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        # Pass 2: lambdas, seeded with enclosing function's final tainted.
        for node in walk(tree.root_node):
            if node.type != "lambda_expression":
                continue
            seed = _java_param_names(node) | _java_lambda_enclosing_tainted(node, tainted_cache)
            tracker = JavaTaintTracker(seed, sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            tainted_cache[node.id] = set(tracker.tainted)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        return violations

    def _rust_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run Rust taint analysis on every function / closure in *tree*.

        Rust's threat surface differs meaningfully from the other
        languages: there is no ``eval`` / ``Function(code)``; the
        dynamic-execution sinks reduce to ``Command`` (shell), database
        crate calls (sqlx / diesel / rusqlite / postgres), and FFI
        (``libloading`` / extern fn invocation). Defaults focus on the
        stdlib shape; downstream projects extend via
        ``sinks_rust`` / ``sanitizers_rust`` / ``sources_rust``.

        Two passes - mirrors the Java lambda handling. Pass 1 analyses
        ``function_item`` nodes and caches each function's final tainted
        set. Pass 2 analyses ``closure_expression`` nodes seeded with
        the enclosing scope's tainted names so a captured tainted local
        (``iter.for_each(|_| cmd.arg(input))``) reaches the sink check
        instead of being treated as an unrelated free variable.
        """
        sinks_raw, sinks_key = resolve_lang_config_lookup(self.config, "sinks", "rust", default=[])
        sinks = frozenset(_validated_string_list(sinks_raw, sinks_key))
        sanitizers_raw, sanitizers_key = resolve_lang_config_lookup(self.config, "sanitizers", "rust", default=[])
        sanitizers = frozenset(_validated_string_list(sanitizers_raw, sanitizers_key))
        sources_raw, sources_key = resolve_lang_config_lookup(self.config, "sources", "rust", default=[])
        sources = frozenset(_validated_string_list(sources_raw, sources_key))
        assume = self._resolve_assume_taint_preserving()
        violations: list[Violation] = []
        # Pass 1: ``function_item`` nodes. Cache the final tainted set
        # keyed by ``node.id`` (tree-sitter-stable across wrapper accesses;
        # ``id(wrapper)`` is not).
        tainted_cache: dict[int, set[str]] = {}
        for node in walk(tree.root_node):
            if node.type != _RUST_CLOSURE and node.type in _RUST_FUNCTION_TYPES:
                tracker = RustTaintTracker(_rust_param_names(node), sinks, sanitizers, sources, assume_taint_preserving=assume)
                tracker.visit(node)
                tainted_cache[node.id] = set(tracker.tainted)
                violations.extend(self._format_hits(filepath, tracker.sink_hits))
        # Pass 2: ``closure_expression`` nodes, seeded with the
        # enclosing scope's final tainted set so captures are visible.
        # Preorder walk processes outer closures before inner ones, so
        # nested closures inherit transitively via the cache.
        for node in walk(tree.root_node):
            if node.type != _RUST_CLOSURE:
                continue
            seed = _rust_param_names(node) | _rust_closure_enclosing_tainted(node, tainted_cache)
            tracker = RustTaintTracker(seed, sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            tainted_cache[node.id] = set(tracker.tainted)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        return violations

    def _go_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run Go taint analysis on every function / method / closure in *tree*.

        Go's threat surface is shell execution (``os/exec`` ``Command`` /
        ``CommandContext``), raw SQL (``database/sql`` ``Query`` /
        ``QueryRow`` / ``Exec``), and plugin loading (``plugin.Open``).
        Sources are request / environment accessors (``os.Getenv``,
        ``r.FormValue`` / ``r.PostFormValue`` / ``r.FormFile``).

        Two passes mirror the Java / Rust closure handling. Pass 1
        analyses ``function_declaration`` / ``method_declaration`` nodes
        and caches each one's final tainted set. Pass 2 analyses
        ``func_literal`` closures seeded with the enclosing scope's
        tainted names so a captured tainted local reaching a sink inside
        the closure is still caught.
        """
        sinks_raw, sinks_key = resolve_lang_config_lookup(self.config, "sinks", "go", default=[])
        sinks = frozenset(_validated_string_list(sinks_raw, sinks_key))
        sanitizers_raw, sanitizers_key = resolve_lang_config_lookup(self.config, "sanitizers", "go", default=[])
        sanitizers = frozenset(_validated_string_list(sanitizers_raw, sanitizers_key))
        sources_raw, sources_key = resolve_lang_config_lookup(self.config, "sources", "go", default=[])
        sources = frozenset(_validated_string_list(sources_raw, sources_key))
        assume = self._resolve_assume_taint_preserving()
        violations: list[Violation] = []
        tainted_cache: dict[int, set[str]] = {}
        # Pass 1: named functions and methods (not closures).
        for node in walk(tree.root_node):
            if node.type not in _GO_FUNCTION_TYPES or node.type == _GO_FUNC_LITERAL:
                continue
            tracker = GoTaintTracker(_go_param_names(node), sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            tainted_cache[node.id] = set(tracker.tainted)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        # Pass 2: closures, seeded with the enclosing scope's tainted set.
        for node in walk(tree.root_node):
            if node.type != _GO_FUNC_LITERAL:
                continue
            seed = _go_param_names(node) | _go_closure_enclosing_tainted(node, tainted_cache)
            tracker = GoTaintTracker(seed, sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            tainted_cache[node.id] = set(tracker.tainted)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        return violations

    def _php_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run PHP taint analysis on the script top-level scope and every function.

        PHP's threat surface is the classic web-taint flow: superglobal sources
        (``$_GET`` / ``$_POST`` / ...) into command execution (``exec`` /
        ``system`` / ``shell_exec`` / ``proc_open``), code execution
        (``eval``), deserialisation (``unserialize``), raw SQL (``->query`` /
        ``mysqli_query``), and dynamic ``include`` / ``require``.

        A first pass analyses the script's top-level scope (PHP code commonly
        lives outside any function), then each function / method / closure is
        analysed with its own parameters seeded. The top-level pass uses an
        empty seed; superglobal sources taint structurally regardless.
        """
        sinks_raw, sinks_key = resolve_lang_config_lookup(self.config, "sinks", "php", default=[])
        sinks = frozenset(_validated_string_list(sinks_raw, sinks_key))
        sanitizers_raw, sanitizers_key = resolve_lang_config_lookup(self.config, "sanitizers", "php", default=[])
        sanitizers = frozenset(_validated_string_list(sanitizers_raw, sanitizers_key))
        sources_raw, sources_key = resolve_lang_config_lookup(self.config, "sources", "php", default=[])
        sources = frozenset(_validated_string_list(sources_raw, sources_key))
        assume = self._resolve_assume_taint_preserving()
        violations: list[Violation] = []
        # Top-level (script) scope - ``visit`` prunes function bodies, which
        # are analysed separately below.
        top = PhpTaintTracker(set(), sinks, sanitizers, sources, assume_taint_preserving=assume)
        top.visit(tree.root_node)
        violations.extend(self._format_hits(filepath, top.sink_hits))
        for node in walk(tree.root_node):
            if node.type not in _PHP_FUNCTION_TYPES:
                continue
            tracker = PhpTaintTracker(_php_param_names(node), sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        return violations

    def _c_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run C taint analysis: seed each function's parameters and track to sinks.

        C executable code lives only inside functions, so there is no top-level
        pass (unlike PHP). ``argv`` and other parameters seed the tainted set;
        call-based sources (``getenv`` / ``fgets`` / ``scanf`` / ``read`` /
        ``recv``) inject taint inside the body, and the classic command-exec /
        unbounded-copy sinks (``system`` / ``strcpy`` / ``sprintf`` / ...) are
        flagged when reached by a tainted argument.
        """
        sinks_raw, sinks_key = resolve_lang_config_lookup(self.config, "sinks", "c", default=[])
        sinks = frozenset(_validated_string_list(sinks_raw, sinks_key))
        sanitizers_raw, sanitizers_key = resolve_lang_config_lookup(self.config, "sanitizers", "c", default=[])
        sanitizers = frozenset(_validated_string_list(sanitizers_raw, sanitizers_key))
        sources_raw, sources_key = resolve_lang_config_lookup(self.config, "sources", "c", default=[])
        sources = frozenset(_validated_string_list(sources_raw, sources_key))
        assume = self._resolve_assume_taint_preserving()
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in _C_FUNCTION_TYPES:
                continue
            tracker = CTaintTracker(_c_param_names(node), sinks, sanitizers, sources, assume_taint_preserving=assume)
            tracker.visit(node)
            violations.extend(self._format_hits(filepath, tracker.sink_hits))
        return violations

    def _format_hits(self, filepath: str, hits: list[tuple[tree_sitter.Node, str, str]]) -> list[Violation]:
        """Convert tracker hits to Violations - same message format for both languages."""
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
        # JS / TS share a checker that needs the language name; the rest take
        # ``(filepath, tree)`` and dispatch through the table (single return,
        # Python is the fallback).
        if lang_name in ("javascript", "typescript"):
            return self._javascript_check(filepath, tree, lang_name)
        checks = {
            "java": self._java_check,
            "rust": self._rust_check,
            "go": self._go_check,
            "php": self._php_check,
            "c": self._c_check,
        }
        return checks.get(lang_name, self._python_check)(filepath, tree)


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
    language = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c")

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
        if lang_name == "python":
            flagged = frozenset(self.config.get("flagged_calls", self._DEFAULT_FLAGGED))
        else:
            # JS-family (JS / TS) inherits via TS→JS fallback in
            # ``get_per_language_config``; Java has its own dedicated set.
            raw, error_key = resolve_lang_config_lookup(self.config, "flagged_calls", lang_name, default=[])
            flagged = frozenset(_validated_string_list(raw, error_key))
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
    misses ``undefined``). Java uses ``null`` (no ``undefined`` axis)
    and the standard guards are ``if (result != null)`` or wrapping
    the call in ``Optional.ofNullable(...)``.
    """
    if lang_name in ("javascript", "typescript"):
        return f'Result of "{method}()" is immediately dereferenced without a null check - guard with optional chaining ("result?.field") or "if (result != null)"'
    if lang_name == "java":
        return f'Result of "{method}()" is immediately dereferenced without a null check - guard with "if (result != null)" or wrap in Optional.ofNullable(...)'
    if lang_name == "rust":
        return f'Result of "{method}()" is immediately unwrapped without an Option/Result check - guard with "if let Some(x) = ..." / "match" or propagate with "?"'
    if lang_name == "php":
        return f'Result of "{method}()" is immediately dereferenced without a null check - guard with the nullsafe operator ("$result?->field") or "if ($result !== null)"'
    return f'Result of "{method}()" is immediately dereferenced without a None check - guard with "if result is not None"'


class NullDereferenceRule(BaseRule):
    """Flag chained attribute or subscript access on calls that can return None."""

    name = "null_dereference"
    code = "SAFE803"
    language = ("python", "javascript", "typescript", "java", "rust", "php")

    _RUST_UNWRAP_METHODS: ClassVar[frozenset[str]] = frozenset(
        {
            "unwrap",
            "unwrap_unchecked",
            "expect",
            "unwrap_err",
            "expect_err",
        }
    )

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

    _JAVA_DEREF_RECEIVER_FIELDS: ClassVar[dict[str, str]] = {
        # The Tree-sitter field name to look up for "the value being
        # dereferenced" depends on the chained-access shape:
        # ``field_access`` exposes the receiver as ``object``;
        # ``array_access`` exposes it as ``array``;
        # ``method_invocation`` exposes the receiver of a chained call
        # as ``object`` (``foo.bar()`` - ``bar`` is the ``name`` field;
        # ``foo`` is the ``object`` field).
        "field_access": "object",
        "array_access": "array",
        "method_invocation": "object",
    }

    def _java_deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> str | None:
        """Return the method name if *node* is an unsafe Java dereference, else None.

        Java's chained-access shapes (the Java equivalents of JS's
        ``member_expression`` / ``subscript_expression``):

        * ``field_access`` - ``obj.field`` (Map.get(k).field is the
          classic SAFE803 case, Map.get returns null on miss).
        * ``array_access`` - ``arr[i]`` (``getList()[0]`` would surface here).
        * ``method_invocation`` with chained receiver - ``map.get(k).toString()``
          is a method-invocation node whose ``object`` field is itself
          the nullable call. The most natural Java SAFE803 case.

        Java pass-through wrappers (``parenthesized_expression``,
        ``cast_expression``) are peeled by :func:`_peel_java_passthrough`
        so ``((Foo) map.get(k)).bar`` is recognised. Java does NOT
        have an optional-chaining operator analogous to JS's ``?.`` -
        the only safe guard is an explicit ``!= null`` check or
        ``Optional.ofNullable(...)``. So unlike the JS branch there's
        no ``optional_chain`` early-out.
        """
        receiver_field = self._JAVA_DEREF_RECEIVER_FIELDS.get(node.type)
        if receiver_field is None:
            return None
        obj = _peel_java_passthrough(node.child_by_field_name(receiver_field))
        if obj is None or obj.type != "method_invocation":
            return None
        name = call_name(obj)
        return name if name and name in nullable else None

    def _rust_deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> str | None:
        """Return the method name if *node* is an unsafe Rust unwrap, else None.

        Rust has no ``null`` - the nullable / fallible analogues are
        ``Option<T>`` and ``Result<T, E>``. The hazardous pattern is
        ``some_call().unwrap()`` (or ``.expect("...")``) where the
        inner call returns one of these types: ``unwrap`` panics on
        ``None`` / ``Err``, exactly the SAFE803 hazard adapted for
        Rust's type system.

        Detection shape:

        1. *node* is a ``call_expression``.
        2. Its ``function`` is a ``field_expression`` whose ``field``
           is one of :attr:`_RUST_UNWRAP_METHODS`.
        3. The ``value`` of that ``field_expression`` (the receiver
           that's being unwrapped) is itself a ``call_expression``
           whose resolved ``call_name`` is in *nullable*.

        Pass-through wrappers between the unwrap-target and the
        inner call are peeled via :func:`_peel_rust_passthrough` so
        ``(map.get(&k)).unwrap()`` and ``(&map.get(&k)).unwrap()``
        both fire.
        """
        if node.type != "call_expression":
            return None
        func = node.child_by_field_name("function")
        if func is None or func.type != "field_expression":
            return None
        field = func.child_by_field_name("field")
        if field is None or node_text(field) not in self._RUST_UNWRAP_METHODS:
            return None
        receiver = _peel_rust_passthrough(func.child_by_field_name("value"))
        if receiver is None or receiver.type != "call_expression":
            return None
        name = call_name(receiver)
        return name if name and name in nullable else None

    _PHP_RECEIVER_CALL_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "function_call_expression",
            "member_call_expression",
            "nullsafe_member_call_expression",
            "scoped_call_expression",
        }
    )

    def _php_deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> str | None:
        """Return the method name if *node* is an unsafe PHP dereference, else None.

        Fires when a plain ``->`` chain (``member_call_expression`` /
        ``member_access_expression``) is rooted in a nullable-returning call:
        ``$repo->find($id)->getName()`` dereferences the result of ``find()``
        (which returns null on a miss) without a guard. The nullsafe forms
        (``nullsafe_member_call_expression`` / ``nullsafe_member_access_expression``,
        the ``?->`` operator) are the safe idiom and are excluded by node type,
        exactly like JS optional chaining (``?.``).
        """
        if node.type not in ("member_call_expression", "member_access_expression"):
            return None
        obj = node.child_by_field_name("object")
        if obj is None or obj.type not in self._PHP_RECEIVER_CALL_TYPES:
            return None
        name = call_name(obj)
        return name if name and name in nullable else None

    def _javascript_deref_hit(self, node: tree_sitter.Node, nullable: frozenset[str]) -> str | None:
        """Return the method name if *node* is an unsafe JavaScript dereference, else None.

        ``foo?.bar`` (optional chaining) is null-safe by construction -
        any ``optional_chain`` child token in the member / subscript
        node means the rule should NOT fire.

        TS / JS routinely wrap the callee in zero-runtime-cost
        annotations that the rule must peel before checking whether
        ``obj`` is a call:

        * ``parenthesized_expression`` - ``(foo()).bar``
        * ``as_expression`` - ``(foo() as Bar).baz``
        * ``satisfies_expression`` - ``(foo() satisfies Bar).baz``
        * ``non_null_expression`` - ``foo()!.bar`` (the ``!``
          is a compile-time annotation that says "trust me, it's
          not null" but provides zero runtime safety)

        All four are pass-through wrappers - runtime value is
        identical to the inner expression - so SAFE803 must still
        fire when the underlying call IS nullable. Peel them in a
        loop because TS authors freely combine them
        (``(foo() as Bar)!.baz``).
        """
        if node.type not in ("member_expression", "subscript_expression"):
            return None
        # Optional chaining is the safe form - skip it entirely.
        if any(c.type == "optional_chain" for c in node.children):
            return None
        obj = _peel_js_passthrough(node.child_by_field_name("object"))
        if obj is None or obj.type != "call_expression":
            return None
        name = call_name(obj)
        return name if name and name in nullable else None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag immediate dereferences on nullable-returning calls.

        Per-language message: Python users get the ``None`` / ``is not None``
        idiom; JavaScript users get the null-or-undefined hazard surfaced
        with optional chaining (``result?.field`` - the modern guard) and
        the loose ``!= null`` form (which catches both ``null`` and
        ``undefined``) as the explicit alternative. Same per-language
        wording pattern as ``EmptyExceptRule`` / ``LoggingOnErrorRule``
        / ``UnboundedLoopsRule``.
        """
        lang_name = resolve_lang_name(filepath)
        if lang_name == "python":
            nullable = self._DEFAULT_NULLABLE_PYTHON | frozenset(self.config.get("nullable_methods", []))
            deref_hit = self._python_deref_hit
        elif lang_name == "java":
            raw, error_key = resolve_lang_config_lookup(self.config, "nullable_methods", "java", default=[])
            nullable = frozenset(_validated_string_list(raw, error_key))
            deref_hit = self._java_deref_hit
        elif lang_name == "rust":
            raw, error_key = resolve_lang_config_lookup(self.config, "nullable_methods", "rust", default=[])
            nullable = frozenset(_validated_string_list(raw, error_key))
            deref_hit = self._rust_deref_hit
        elif lang_name == "php":
            raw, error_key = resolve_lang_config_lookup(self.config, "nullable_methods", "php", default=[])
            nullable = frozenset(_validated_string_list(raw, error_key))
            deref_hit = self._php_deref_hit
        else:
            # JS-family (JS / TS): TypeScript inherits the JS list by default.
            raw, error_key = resolve_lang_config_lookup(self.config, "nullable_methods", lang_name, default=[])
            nullable = frozenset(_validated_string_list(raw, error_key))
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
