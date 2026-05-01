"""Language-agnostic Tree-sitter node utility functions.

These helpers replace ast.walk(), node.lineno, node.name, etc. across all rules.
They work identically regardless of which language grammar was used to parse the tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter


def walk(node: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
    """Yield every node in the subtree rooted at *node*, depth-first.

    This replaces ``ast.walk(tree)`` from the old code.
    Usage: ``for node in walk(tree.root_node): ...``

    Implemented iteratively (not recursively) to avoid Python's default
    recursion limit of 1000. ast.walk() is also iterative for the same
    reason. A recursive implementation will crash with RecursionError on
    large or deeply nested source files.
    """
    stack = [node]
    while stack:  # nosafe: SAFE501
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def lineno(node: tree_sitter.Node) -> int:
    """Return the 1-based start line number of *node*.

    Tree-sitter uses 0-based row numbers. We add 1 to match Python convention
    and to stay compatible with the existing Violation.lineno field.
    """
    return node.start_point[0] + 1


def end_lineno(node: tree_sitter.Node) -> int:
    """Return the 1-based end line number of *node*."""
    return node.end_point[0] + 1


def node_text(node: tree_sitter.Node) -> str:
    """Return the source text covered by *node* as a string.

    Returns an empty string if node.text is None (e.g., on error nodes).
    """
    return node.text.decode("utf-8") if node.text else ""


def call_name(call_node: tree_sitter.Node) -> str | None:
    """Return the bare callable name from a ``call`` node, or None if unresolvable.

    Handles two forms:
    - ``foo(...)``         → returns ``"foo"``
    - ``obj.method(...)``  → returns ``"method"``

    This replaces ``BaseRule._call_name(node.func)`` from the old code.
    Callers must pass the call node itself (not the function sub-node).
    """
    func_node = call_node.child_by_field_name("function")
    if func_node is None:
        return None
    if func_node.type == "identifier":
        return node_text(func_node)
    if func_node.type == "attribute":
        attr_node = func_node.child_by_field_name("attribute")
        return node_text(attr_node) if attr_node else None
    return None
