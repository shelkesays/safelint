"""max_arguments rule - argument count must not exceed max_args."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import function_name_node, node_text, resolve_lang_name, walk
from safelint.languages.c import FUNCTION_TYPES as _C_FUNCTION_TYPES
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.go import IDENTIFIER as _GO_IDENTIFIER
from safelint.languages.go import PARAMETER_DECLARATION as _GO_PARAMETER_DECLARATION
from safelint.languages.go import VARIADIC_PARAMETER_DECLARATION as _GO_VARIADIC_PARAMETER_DECLARATION
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
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

_PY_SPLAT_PARAM_TYPES = frozenset({"list_splat_pattern", "dictionary_splat_pattern"})

_PY_COUNTED_PARAM_TYPES = frozenset(
    {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
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
        "identifier",
        "assignment_pattern",
        "rest_pattern",
        "object_pattern",
        "array_pattern",
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
        "required_parameter",
        "optional_parameter",
        "rest_parameter",
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
        "formal_parameter",
        "spread_parameter",
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
        "parameter",
        "identifier",
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
        "simple_parameter",
        "variadic_parameter",
        "property_promotion_parameter",
    }
)

_COUNTED_PARAM_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": _PY_COUNTED_PARAM_TYPES,
    "javascript": _JS_COUNTED_PARAM_TYPES,
    "typescript": _TS_COUNTED_PARAM_TYPES,
    "java": _JAVA_COUNTED_PARAM_TYPES,
    "rust": _RUST_COUNTED_PARAM_TYPES,
    "php": _PHP_COUNTED_PARAM_TYPES,
    # C: each ``parameter_declaration`` is one parameter. ``int f(void)`` has a
    # single ``void`` parameter_declaration; counting it as one never produces a
    # false positive at the default max of 7, so it is not special-cased.
    "c": frozenset({"parameter_declaration"}),
}


def _python_param_identifier(child: tree_sitter.Node) -> str | None:
    """Return the bare identifier name for a Python parameter node, else None.

    Used to detect and skip ``self`` / ``cls`` - which JavaScript doesn't have.
    """
    if child.type == "identifier":
        return node_text(child)
    if child.type in _PY_SPLAT_PARAM_TYPES:
        # `*args` / `**kwargs` carry their identifier as the first named child.
        inner = child.named_children[0] if child.named_children else None
        return node_text(inner) if inner else None
    name_node = child.child_by_field_name("name")
    return node_text(name_node) if name_node else None


def _count_args(func_node: tree_sitter.Node, lang_name: str) -> tuple[int, str | None]:
    """Return (count, first_param_name) for *func_node*.

    *first_param_name* is meaningful for Python (used to detect and skip
    ``self`` / ``cls``); JavaScript callers ignore it. Both languages
    expose the parameter list through ``func_node.child_by_field_name("parameters")``.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None and lang_name == "c":
        # C nests the parameter list under the ``function_declarator``
        # (``func_node.declarator.parameters``), not directly on the
        # ``function_definition`` like the other languages.
        decl = func_node.child_by_field_name("declarator")
        params_node = decl.child_by_field_name("parameters") if decl is not None else None
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
    if params_node.type == "identifier":
        return 1
    if params_node.type == "inferred_parameters":
        return sum(1 for c in params_node.named_children if c.type == "identifier")
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
        if child.type not in (_GO_PARAMETER_DECLARATION, _GO_VARIADIC_PARAMETER_DECLARATION):
            continue
        names = sum(1 for g in child.named_children if g.type == _GO_IDENTIFIER)
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
    language = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c")

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
