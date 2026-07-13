"""max_arguments rule - argument count must not exceed max_args."""

from __future__ import annotations

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
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF}),
    "javascript": _js.FUNCTION_TYPES,
    "typescript": _js.FUNCTION_TYPES,
    "java": _java.FUNCTION_TYPES,
    "rust": _rust.FUNCTION_TYPES,
    "go": _go.FUNCTION_TYPES,
    "php": _php.FUNCTION_TYPES,
    "c": _c.FUNCTION_TYPES,
    "cpp": _cpp.FUNCTION_TYPES,
}

_PY_SPLAT_PARAM_TYPES = frozenset({_py.LIST_SPLAT_PATTERN, _py.DICTIONARY_SPLAT_PATTERN})

_PY_COUNTED_PARAM_TYPES = frozenset(
    {
        _py.IDENTIFIER,
        _py.TYPED_PARAMETER,
        _py.DEFAULT_PARAMETER,
        _py.TYPED_DEFAULT_PARAMETER,
    }
    | _PY_SPLAT_PARAM_TYPES
)

# JavaScript ``formal_parameters`` children that count toward the limit.
# ``identifier``: bare param. ``assignment_pattern``: ``b = 5`` default value.
# ``rest_pattern``: ``...args``. ``object_pattern`` / ``array_pattern``:
# destructured params (each destructured group counts as one - that's
# the whole *point* of using a config object, so the count stays low).
_JS_COUNTED_PARAM_TYPES = frozenset(
    {
        _js.IDENTIFIER,
        _js.ASSIGNMENT_PATTERN,
        _js.REST_PATTERN,
        _js.OBJECT_PATTERN,
        _js.ARRAY_PATTERN,
    }
)

# TypeScript wraps each formal parameter in a typed wrapper node:
# ``required_parameter`` (``x: number``), ``optional_parameter``
# (``x?: number``), ``rest_parameter`` (``...args: number[]``). The
# bare JS shapes don't appear in TS source. Note: ``type_parameters``
# (the ``<T, U>`` generic list) is a SEPARATE child of the function
# declaration, NOT inside ``formal_parameters``, so generic type
# parameters are correctly excluded from the count without any
# additional handling.
_TS_COUNTED_PARAM_TYPES = frozenset(
    {
        _ts.REQUIRED_PARAMETER,
        _ts.OPTIONAL_PARAMETER,
        _ts.REST_PARAMETER,
    }
)

# Java ``formal_parameters`` children that count toward the limit.
# ``formal_parameter``: the standard ``Type name`` shape, including
# annotated parameters like ``@Valid @RequestBody Foo arg`` (annotations
# live inside the formal_parameter, not as siblings). ``spread_parameter``:
# varargs ``T... args``. ``receiver_parameter`` (``Foo this``, rare
# method-on-self idiom) is deliberately excluded - it's an explicit form
# of the implicit receiver, analogous to Python's ``self`` / ``cls``, and
# should not count toward user-facing argument count.
_JAVA_COUNTED_PARAM_TYPES = frozenset(
    {
        _java.FORMAL_PARAMETER,
        _java.SPREAD_PARAMETER,
    }
)

# Rust ``function_item`` has a ``parameters`` container whose children
# are ``parameter`` (typed: ``name: Type``) or ``self_parameter`` (``self``
# / ``&self`` / ``&mut self``). The self forms are deliberately excluded -
# they're the explicit method-receiver, analogous to Python's ``self`` /
# ``cls`` and Java's ``receiver_parameter``, and shouldn't count as a
# user-facing argument. Closures (``closure_expression``) expose a
# ``closure_parameters`` container whose children are bare ``identifier``
# nodes for untyped closures (``|x, y| ...``) or ``parameter`` nodes for
# typed closures (``|x: i32, y: i32| ...``); ``identifier`` is in the
# counted set so untyped closure arity is captured.
_RUST_COUNTED_PARAM_TYPES = frozenset(
    {
        _rust.PARAMETER,
        _rust.IDENTIFIER,
    }
)

# PHP ``formal_parameters`` children that count toward the limit.
# ``simple_parameter``: ``$a`` / ``int $b = 1`` (typed and/or defaulted).
# ``variadic_parameter``: ``...$args``. ``property_promotion_parameter``:
# a constructor-promoted property (``private int $x``) - a real
# constructor parameter, so it counts. PHP has no ``self`` / ``cls``
# convention, so every parameter counts; the field name is ``parameters``
# (same as Python / JS), so PHP routes through the generic counting path.
_PHP_COUNTED_PARAM_TYPES = frozenset(
    {
        _php.SIMPLE_PARAMETER,
        _php.VARIADIC_PARAMETER,
        _php.PROPERTY_PROMOTION_PARAMETER,
    }
)

_COUNTED_PARAM_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": _PY_COUNTED_PARAM_TYPES,
    "javascript": _JS_COUNTED_PARAM_TYPES,
    "typescript": _TS_COUNTED_PARAM_TYPES,
    "java": _JAVA_COUNTED_PARAM_TYPES,
    "rust": _RUST_COUNTED_PARAM_TYPES,
    "php": _PHP_COUNTED_PARAM_TYPES,
    # C is counted by ``_count_c_args`` (it unwraps the declarator and treats a
    # lone ``void`` as zero), so it has no entry here.
}


def _python_param_identifier(child: tree_sitter.Node) -> str | None:
    """Return the bare identifier name for a Python parameter node, else None.

    Used to detect and skip ``self`` / ``cls`` - which JavaScript doesn't have.
    """
    if child.type == _py.IDENTIFIER:
        return node_text(child)
    if child.type in _PY_SPLAT_PARAM_TYPES:
        # `*args` / `**kwargs` carry their identifier as the first named child.
        inner = child.named_children[0] if child.named_children else None
        return node_text(inner) if inner else None
    name_node = child.child_by_field_name("name")
    return node_text(name_node) if name_node else None


def _is_c_void_param(param: tree_sitter.Node) -> bool:
    """Return True if *param* is a lone ``void`` (``int f(void)`` - zero arguments).

    A ``void`` parameter has a ``primitive_type`` child whose text is ``void``
    and no declarator (an actual ``void *`` argument carries a
    ``pointer_declarator``, so it is not matched).
    """
    return param.child_by_field_name("declarator") is None and any(c.type == _c.PRIMITIVE_TYPE and node_text(c) == "void" for c in param.named_children)


def _count_cpp_lambda_args(lambda_node: tree_sitter.Node) -> int:
    """Count the parameters of a C++ ``lambda_expression``.

    A lambda nests its parameters under an ``abstract_function_declarator``
    child (there is no ``declarator`` field, unlike a ``function_definition``),
    so the C declarator-chain unwrap in :func:`_count_c_args` would miss them
    and count every lambda as zero. A parameterless lambda (``[]{...}`` or
    ``[](){...}``) has no parameter list and counts as zero.
    """
    afd = next((c for c in lambda_node.named_children if c.type == _cpp.ABSTRACT_FUNCTION_DECLARATOR), None)
    params_node = afd.child_by_field_name("parameters") if afd is not None else None
    if params_node is None:
        return 0
    return len([c for c in params_node.named_children if c.type in (_cpp.PARAMETER_DECLARATION, _c.VARIADIC_PARAMETER, _cpp.OPTIONAL_PARAMETER_DECLARATION)])


def _c_function_params_node(func_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Unwrap the declarator chain to the ``function_declarator``'s parameter list, or None.

    The function's own declarator may be wrapped in a ``pointer_declarator`` for a
    pointer-returning function (``char *foo(...)``), so the chain is unwrapped to
    the ``function_declarator`` first (bounded loop; never recurses).
    """
    decl = func_node.child_by_field_name("declarator")
    for _ in range(16):
        if decl is None or decl.type == _c.FUNCTION_DECLARATOR:
            break
        decl = decl.child_by_field_name("declarator")
    return decl.child_by_field_name("parameters") if decl is not None and decl.type == _c.FUNCTION_DECLARATOR else None


def _count_c_args(func_node: tree_sitter.Node) -> int:
    """Count C / C++ parameters, treating a lone ``void`` as zero.

    Parameters nest under ``function_declarator.parameters`` (resolved by
    :func:`_c_function_params_node`). ``int f(void)`` is C's spelling for *no*
    parameters and counts as zero. A C++ ``lambda_expression`` uses a different
    shape and is delegated to :func:`_count_cpp_lambda_args`.
    """
    if func_node.type == _cpp.LAMBDA_EXPRESSION:
        return _count_cpp_lambda_args(func_node)
    params_node = _c_function_params_node(func_node)
    if params_node is None:  # pragma: no cover - defensive: a function_definition always has a parameter list
        return 0
    # ``variadic_parameter`` is the ``...`` ellipsis - a real parameter slot, so
    # ``int log(int a, ...)`` counts as 2 (omitting it leaves the count one short).
    # ``optional_parameter_declaration`` is a C++ default-valued parameter
    # (``int b = 5``) - still a real parameter slot, counted like the lambda path.
    params = [c for c in params_node.named_children if c.type in (_c.PARAMETER_DECLARATION, _c.VARIADIC_PARAMETER, _cpp.OPTIONAL_PARAMETER_DECLARATION)]
    if len(params) == 1 and _is_c_void_param(params[0]):
        return 0
    return len(params)


def _count_args(func_node: tree_sitter.Node, lang_name: str) -> tuple[int, str | None]:
    """Return (count, first_param_name) for *func_node*.

    *first_param_name* is meaningful for Python (used to detect and skip
    ``self`` / ``cls``); JavaScript callers ignore it. Both languages
    expose the parameter list through ``func_node.child_by_field_name("parameters")``.
    """
    if lang_name in (_c.EXTRA_NAME, _cpp.EXTRA_NAME):
        # C / C++ nest parameters under the ``function_declarator`` (which may itself
        # be wrapped in a ``pointer_declarator`` for a pointer-returning
        # function), and ``int f(void)`` is the spelling for *zero* parameters.
        # ``_count_c_args`` handles both; the generic ``parameters``-field path
        # below would miss the wrapped declarator and miscount the lone ``void``.
        return _count_c_args(func_node), None
    params_node = func_node.child_by_field_name("parameters")
    # Every function definition has a parameters list (possibly empty).
    # This guard fires only on malformed AST that Tree-sitter produced
    # with errors, in which case zero args is a safe answer.
    if params_node is None:  # pragma: no cover
        return 0, None
    if lang_name == "java":
        return _count_java_args(params_node), None
    if lang_name == "go":
        return _count_go_args(params_node), None
    counted_types = _COUNTED_PARAM_TYPES_BY_LANG[lang_name]
    counted = [c for c in params_node.named_children if c.type in counted_types]
    first_name: str | None = None
    if counted and lang_name == "python":
        first_name = _python_param_identifier(counted[0])
    return len(counted), first_name


def _count_java_args(params_node: tree_sitter.Node) -> int:
    """Count Java parameters across all three lambda + standard shapes.

    tree-sitter-java exposes the ``parameters`` field with three distinct
    node types depending on the surface syntax:

    * ``formal_parameters`` - standard method / constructor / lambda with
      typed params (``(String a, int b) -> ...``). Children are
      ``formal_parameter`` or ``spread_parameter`` nodes.
    * ``inferred_parameters`` - untyped multi-arg lambda (``(a, b) -> ...``).
      Children are bare ``identifier`` nodes.
    * ``identifier`` - untyped single-arg lambda (``a -> ...``). The
      ``parameters`` field IS the identifier itself, no container node.

    Without the inferred_parameters / bare-identifier branches, the rule
    silently treats untyped lambdas as zero-arg and misses
    over-argument lambdas like
    ``(a, b, c, d, e, f, g, h) -> ...`` that are increasingly common
    in stream / reactive pipelines.
    """
    if params_node.type == _java.IDENTIFIER:
        return 1
    if params_node.type == _java.INFERRED_PARAMETERS:
        return sum(1 for c in params_node.named_children if c.type == _java.IDENTIFIER)
    return sum(1 for c in params_node.named_children if c.type in _JAVA_COUNTED_PARAM_TYPES)


def _count_go_args(params_node: tree_sitter.Node) -> int:
    """Count Go parameters, counting *names* not declarations.

    A single Go ``parameter_declaration`` can bind several names sharing
    one type (``a, b int`` is two parameters, one declaration), so the
    count is the number of bound identifiers, not the number of
    declarations. ``variadic_parameter_declaration`` (``args ...T``) binds
    one name. An unnamed parameter (``func f(int, string)`` - legal in Go
    function types / signatures) has no identifier child and counts as one.

    The method receiver is NOT counted: it lives on the declaration's
    separate ``receiver`` field, never inside the ``parameters`` field this
    helper is handed, so it is excluded structurally (Go's analogue of
    Python ``self`` / Java ``receiver_parameter``).
    """
    total = 0
    for child in params_node.named_children:
        if child.type not in (_go.PARAMETER_DECLARATION, _go.VARIADIC_PARAMETER_DECLARATION):
            continue
        names = sum(1 for g in child.named_children if g.type == _go.IDENTIFIER)
        total += names or 1
    return total


class MaxArgumentsRule(BaseRule):
    """Reject functions whose argument count exceeds the limit.

    Python: ``self`` / ``cls`` are excluded from the count (the rule fires
    when a method has more than *max_args* "real" parameters). JavaScript
    has no equivalent convention, so every parameter counts.
    """

    name = "max_arguments"
    code = "SAFE103"
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _go.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function with more arguments than max_args."""
        max_args: int = self.config.get("max_args", 7)
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            count, first_name = _count_args(node, lang_name)
            if first_name in ("self", "cls"):
                count -= 1
            if count > max_args:
                name_node = function_name_node(node, lang_name)
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Function "{func_name}" has {count} arguments (max {max_args})',
                    )
                )
        return violations
