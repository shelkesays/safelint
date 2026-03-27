"""Side-effect rules: side_effects_hidden and side_effects."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class SideEffectsHiddenRule(BaseRule):
    """Reject functions with pure-sounding names that perform I/O.

    A function named ``calculate_total`` or ``get_user`` implies referential
    transparency. If it calls ``open()``, ``print()``, or similar primitives
    it is hiding a side effect, which is a Holzmann core risk.
    """

    name = "side_effects_hidden"
    code = "SAFE303"

    def _first_io_call(self, func_node: ast.AST, io_funcs: frozenset[str]) -> ast.Call | None:
        """Return the first I/O call node found inside *func_node*, or None."""
        for child in ast.walk(func_node):
            if not isinstance(child, ast.Call):
                continue
            call_name = self._call_name(child.func)
            if call_name and call_name in io_funcs:
                return child
        return None

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag pure-named functions that contain I/O calls."""
        io_funcs: frozenset[str] = frozenset(
            self.config.get("io_functions", ["open", "print", "input"])
        )
        pure_prefixes: tuple[str, ...] = tuple(self.config.get("pure_prefixes", []))

        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name_lower = node.name.lower()
            if not any(
                name_lower.startswith(p) or name_lower == p.rstrip("_") for p in pure_prefixes
            ):
                continue
            io_call = self._first_io_call(node, io_funcs)
            if io_call:
                violations.append(
                    self._v(
                        filepath,
                        io_call.lineno,
                        f'Function "{node.name}" looks pure but calls I/O primitive'
                        f' "{self._call_name(io_call.func)}"'
                        " - rename to signal intent or use dependency injection",
                    )
                )
        return violations


class SideEffectsRule(BaseRule):
    """Flag I/O primitives called inside any function not explicitly named for I/O."""

    name = "side_effects"
    code = "SAFE304"

    def _first_io_call(self, func_node: ast.AST, io_funcs: frozenset[str]) -> ast.Call | None:
        """Return the first I/O call node found inside *func_node*, or None."""
        for child in ast.walk(func_node):
            if not isinstance(child, ast.Call):
                continue
            call_name = self._call_name(child.func)
            if call_name and call_name in io_funcs:
                return child
        return None

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag functions that hide side effects behind a non-I/O name."""
        io_funcs: frozenset[str] = frozenset(
            self.config.get("io_functions", ["open", "print", "input"])
        )
        io_keywords: list[str] = self.config.get("io_name_keywords", [])

        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(kw in node.name for kw in io_keywords):
                continue
            io_call = self._first_io_call(node, io_funcs)
            if io_call:
                violations.append(
                    self._v(
                        filepath,
                        io_call.lineno,
                        f'Function "{node.name}" calls I/O primitive'
                        f' "{self._call_name(io_call.func)}"'
                        " - rename to signal intent or use dependency injection",
                    )
                )
        return violations
