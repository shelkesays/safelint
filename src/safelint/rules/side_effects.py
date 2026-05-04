"""Side-effect rules: side_effects_hidden and side_effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, CALL, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


def _first_io_call(func_node: tree_sitter.Node, io_funcs: frozenset[str]) -> tree_sitter.Node | None:
    """Return the first I/O call inside *func_node* (skipping nested defs), or None."""
    for child in walk(func_node, skip_types=(FUNCTION_DEF, ASYNC_FUNCTION_DEF)):
        if child.type != CALL:
            continue
        name = call_name(child)
        if name and name in io_funcs:
            return child
    return None


class SideEffectsHiddenRule(BaseRule):
    """Reject functions with pure-sounding names that perform I/O."""

    name = "side_effects_hidden"
    code = "SAFE303"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag pure-named functions that contain I/O calls."""
        io_funcs: frozenset[str] = frozenset(self.config.get("io_functions", ["open", "print", "input"]))
        # Normalise both sides of the comparison so user-supplied prefixes
        # like ``["Get", "Calculate"]`` still match ``get_data`` / ``calculate_x``.
        pure_prefixes: tuple[str, ...] = tuple(p.lower() for p in self.config.get("pure_prefixes", []))

        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else ""
            name_lower = func_name.lower()
            if not any(name_lower.startswith(p) or name_lower == p.rstrip("_") for p in pure_prefixes):
                continue
            io_call = _first_io_call(node, io_funcs)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        io_call,
                        f'Function "{func_name}" looks pure but calls I/O primitive "{io_name}" - rename to signal intent or use dependency injection',
                    )
                )
        return violations


class SideEffectsRule(BaseRule):
    """Flag I/O primitives called inside any function not explicitly named for I/O."""

    name = "side_effects"
    code = "SAFE304"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions that hide side effects behind a non-I/O name."""
        io_funcs: frozenset[str] = frozenset(self.config.get("io_functions", ["open", "print", "input"]))
        # Lowercase BOTH sides so the substring check is genuinely
        # case-insensitive — mixed-case keywords in config (e.g. ``"Write"``)
        # still match camelCase function names like ``writeLog``.
        io_keywords: list[str] = [kw.lower() for kw in self.config.get("io_name_keywords", [])]

        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else ""
            name_lower = func_name.lower()
            if any(kw in name_lower for kw in io_keywords):
                continue
            io_call = _first_io_call(node, io_funcs)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        io_call,
                        f'Function "{func_name}" calls I/O primitive "{io_name}" - rename to signal intent or use dependency injection',
                    )
                )
        return violations
