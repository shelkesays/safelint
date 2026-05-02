"""State & purity rules: global_state and global_mutation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import (
    ANNOTATED_ASSIGNMENT,
    ASSIGNMENT,
    ASYNC_FUNCTION_DEF,
    AUGMENTED_ASSIGNMENT,
    CLASS_DEF,
    FUNCTION_DEF,
    GLOBAL_STATEMENT,
    IDENTIFIER,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _func_name(func_node: tree_sitter.Node) -> str:
    """Return the declared name of *func_node*, or ``"<anonymous>"``."""
    name_node = func_node.child_by_field_name("name")
    return node_text(name_node) if name_node else "<anonymous>"


def _iter_functions(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every function (sync or async) definition in *tree*."""
    for node in walk(tree.root_node):
        if node.type in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
            yield node


# Class bodies are their own scope: a `global X` declared inside a nested
# class belongs to that class body, not the enclosing function. Same for
# nested function definitions. Stop the per-function walk at any of these.
_NESTED_SCOPE_TYPES = (FUNCTION_DEF, ASYNC_FUNCTION_DEF, CLASS_DEF)


def _iter_global_statements(func_node: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
    """Yield every ``global X, Y`` statement found inside *func_node*.

    Stops at nested function definitions: a ``global`` declared in an inner
    function belongs to that inner function's scope, not the outer one's.
    """
    for child in walk(func_node, skip_types=_NESTED_SCOPE_TYPES):
        if child.type == GLOBAL_STATEMENT:
            yield child


def _global_identifiers(global_stmt: tree_sitter.Node) -> list[tree_sitter.Node]:
    """Return the identifier nodes named in a ``global`` statement."""
    return [c for c in global_stmt.named_children if c.type == IDENTIFIER]


def _assignment_target(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the bare identifier target of *node* if it is one, else None."""
    if node.type in (ASSIGNMENT, AUGMENTED_ASSIGNMENT):
        left = node.child_by_field_name("left")
        return left if left is not None and left.type == IDENTIFIER else None
    if node.type == ANNOTATED_ASSIGNMENT and node.named_children:
        target = node.named_children[0]
        # Subscript / attribute targets like ``a[0]: int = …`` exist in valid
        # Python but aren't relevant to the global-mutation rule (which
        # cares about bare identifier targets only).
        return target if target.type == IDENTIFIER else None  # pragma: no cover
    return None


class GlobalStateRule(BaseRule):
    """Reject use of the ``global`` keyword inside functions."""

    name = "global_state"
    code = "SAFE301"

    def _violations_for_func(self, filepath: str, func: tree_sitter.Node) -> list[Violation]:
        """Return one violation per ``global`` statement inside *func*."""
        func_name = _func_name(func)
        return [
            self._make_violation(
                filepath,
                lineno(stmt),
                f'Function "{func_name}" declares global: {", ".join(node_text(c) for c in _global_identifiers(stmt))} - use dependency injection instead',
            )
            for stmt in _iter_global_statements(func)
        ]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function that declares a global variable."""
        violations: list[Violation] = []
        for func in _iter_functions(tree):
            violations.extend(self._violations_for_func(filepath, func))
        return violations


class GlobalMutationRule(BaseRule):
    """Reject functions that declare globals and then write to them."""

    name = "global_mutation"
    code = "SAFE302"

    @staticmethod
    def _collect_global_names(func_node: tree_sitter.Node) -> set[str]:
        """Return all names declared via ``global`` inside *func_node*."""
        return {node_text(ident) for stmt in _iter_global_statements(func_node) for ident in _global_identifiers(stmt)}

    @staticmethod
    def _mutating_assignments(
        func_node: tree_sitter.Node,
        global_names: set[str],
    ) -> list[tuple[int, str]]:
        """Return (lineno, name) for each write to a declared global in *func_node*.

        Stops at nested defs — assignments inside inner functions belong to
        their own scope and must not be attributed to the outer function.
        """
        results: list[tuple[int, str]] = []
        for node in walk(func_node, skip_types=_NESTED_SCOPE_TYPES):
            target = _assignment_target(node)
            if target is not None and node_text(target) in global_names:
                results.append((lineno(node), node_text(target)))
        return results

    def _violations_for_func(self, filepath: str, func: tree_sitter.Node) -> list[Violation]:
        """Return violations for global writes inside *func*."""
        global_names = self._collect_global_names(func)
        if not global_names:
            return []
        func_name = _func_name(func)
        return [
            self._make_violation(
                filepath,
                line_num,
                f'Function "{func_name}" writes to global "{name}" - globals must not be mutated',
            )
            for line_num, name in self._mutating_assignments(func, global_names)
        ]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every write to a declared global variable inside a function."""
        violations: list[Violation] = []
        for func in _iter_functions(tree):
            violations.extend(self._violations_for_func(filepath, func))
        return violations
