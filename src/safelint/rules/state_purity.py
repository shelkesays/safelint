"""State & purity rules: global_state and global_mutation."""

from __future__ import annotations

import ast

from safelint.rules.base import BaseRule, Violation


class GlobalStateRule(BaseRule):
    """Reject use of the ``global`` keyword inside functions."""

    name = "global_state"
    code = "SAFE301"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag any function that declares a global variable."""
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            global_nodes = [c for c in ast.walk(node) if isinstance(c, ast.Global)]
            for global_node in global_nodes:
                names = ", ".join(global_node.names)
                violations.append(
                    self._v(
                        filepath,
                        global_node.lineno,
                        f'Function "{node.name}" declares global: {names}'
                        " - use dependency injection instead",
                    )
                )
        return violations


class GlobalMutationRule(BaseRule):
    """Reject functions that declare globals and then write to them.

    Extends ``global_state`` by catching the actual write, not just the
    declaration. A function that says ``global x`` and then assigns ``x = …``
    is mutating shared state, which is the Holzmann no-go.
    """

    name = "global_mutation"
    code = "SAFE302"

    def _mutating_assignments(self, func: ast.AST, global_names: set[str]) -> list[tuple[int, str]]:
        """Return ``(lineno, name)`` for each write to a declared global in *func*."""
        results = []
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                targets: list[ast.expr] = node.targets
                lineno = node.lineno
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
                lineno = node.lineno
            else:
                continue
            results.extend(
                (lineno, target.id)
                for target in targets
                if isinstance(target, ast.Name) and target.id in global_names
            )
        return results

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Flag every write to a declared global variable inside a function."""
        violations = []
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            global_names: set[str] = {
                name
                for node in ast.walk(func)
                if isinstance(node, ast.Global)
                for name in node.names
            }
            if not global_names:
                continue
            for lineno, name in self._mutating_assignments(func, global_names):
                violations.append(
                    self._v(
                        filepath,
                        lineno,
                        f'Function "{func.name}" writes to global "{name}"'
                        " - globals must not be mutated",
                    )
                )
        return violations
