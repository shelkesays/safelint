"""Side-effect rules: side_effects_hidden and side_effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, lineno, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, CALL, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class SideEffectsHiddenRule(BaseRule):
    """Reject functions with pure-sounding names that perform I/O."""

    name = "side_effects_hidden"
    code = "SAFE303"

    def _first_io_call(self, func_node: tree_sitter.Node, io_funcs: frozenset[str]) -> tree_sitter.Node | None:
        """Return the first I/O call node found inside *func_node*, or None."""
        for child in walk(func_node):
            if child.type != CALL:
                continue
            name = call_name(child)
            if name and name in io_funcs:
                return child
        return None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag pure-named functions that contain I/O calls."""
        io_funcs: frozenset[str] = frozenset(self.config.get("io_functions", ["open", "print", "input"]))
        pure_prefixes: tuple[str, ...] = tuple(self.config.get("pure_prefixes", []))

        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else ""
            name_lower = func_name.lower()
            if not any(name_lower.startswith(p) or name_lower == p.rstrip("_") for p in pure_prefixes):
                continue
            io_call = self._first_io_call(node, io_funcs)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(io_call),
                        f'Function "{func_name}" looks pure but calls I/O primitive "{io_name}" - rename to signal intent or use dependency injection',
                    )
                )
        return violations


class SideEffectsRule(BaseRule):
    """Flag I/O primitives called inside any function not explicitly named for I/O."""

    name = "side_effects"
    code = "SAFE304"

    def _first_io_call(self, func_node: tree_sitter.Node, io_funcs: frozenset[str]) -> tree_sitter.Node | None:
        """Return the first I/O call node found inside *func_node*, or None."""
        for child in walk(func_node):
            if child.type != CALL:
                continue
            name = call_name(child)
            if name and name in io_funcs:
                return child
        return None

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions that hide side effects behind a non-I/O name."""
        io_funcs: frozenset[str] = frozenset(self.config.get("io_functions", ["open", "print", "input"]))
        io_keywords: list[str] = self.config.get("io_name_keywords", [])

        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else ""
            if any(kw in func_name for kw in io_keywords):
                continue
            io_call = self._first_io_call(node, io_funcs)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(io_call),
                        f'Function "{func_name}" calls I/O primitive "{io_name}" - rename to signal intent or use dependency injection',
                    )
                )
        return violations
