"""max_arguments rule - argument count (excluding self/cls) must not exceed max_args."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation

_SPLAT_PARAM_TYPES = frozenset({"list_splat_pattern", "dictionary_splat_pattern"})

_COUNTED_PARAM_TYPES = frozenset(
    {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
    }
    | _SPLAT_PARAM_TYPES
)


def _param_identifier(child: tree_sitter.Node) -> str | None:
    """Return the bare identifier name for a counted parameter node, else None."""
    if child.type == "identifier":
        return node_text(child)
    if child.type in _SPLAT_PARAM_TYPES:
        # `*args` / `**kwargs` carry their identifier as the first named child.
        inner = child.named_children[0] if child.named_children else None
        return node_text(inner) if inner else None
    name_node = child.child_by_field_name("name")
    return node_text(name_node) if name_node else None


def _count_args(func_node: tree_sitter.Node) -> tuple[int, str | None]:
    """Return (count, first_param_name) for *func_node*.

    ``first_param_name`` is used to detect and skip ``self`` / ``cls``.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:
        return 0, None
    counted = [c for c in params_node.named_children if c.type in _COUNTED_PARAM_TYPES]
    first_name = _param_identifier(counted[0]) if counted else None
    return len(counted), first_name


class MaxArgumentsRule(BaseRule):
    """Reject functions whose argument count (excluding self/cls) exceeds the limit."""

    name = "max_arguments"
    code = "SAFE103"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function with more arguments than max_args."""
        max_args: int = self.config.get("max_args", 7)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            count, first_name = _count_args(node)
            if first_name in ("self", "cls"):
                count -= 1
            if count > max_args:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" has {count} arguments (max {max_args})',
                    )
                )
        return violations
