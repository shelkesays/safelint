"""max_arguments rule - argument count must not exceed max_args."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
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

_COUNTED_PARAM_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": _PY_COUNTED_PARAM_TYPES,
    "javascript": _JS_COUNTED_PARAM_TYPES,
    "typescript": _TS_COUNTED_PARAM_TYPES,
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
    # Every function definition has a parameters list (possibly empty).
    # This guard fires only on malformed AST that Tree-sitter produced
    # with errors, in which case zero args is a safe answer.
    if params_node is None:  # pragma: no cover
        return 0, None
    counted_types = _COUNTED_PARAM_TYPES_BY_LANG[lang_name]
    counted = [c for c in params_node.named_children if c.type in counted_types]
    first_name: str | None = None
    if counted and lang_name == "python":
        first_name = _python_param_identifier(counted[0])
    return len(counted), first_name


class MaxArgumentsRule(BaseRule):
    """Reject functions whose argument count exceeds the limit.

    Python: ``self`` / ``cls`` are excluded from the count (the rule fires
    when a method has more than *max_args* "real" parameters). JavaScript
    has no equivalent convention, so every parameter counts.
    """

    name = "max_arguments"
    code = "SAFE103"
    language = ("python", "javascript", "typescript")

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
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Function "{func_name}" has {count} arguments (max {max_args})',
                    )
                )
        return violations
