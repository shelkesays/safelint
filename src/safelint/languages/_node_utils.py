"""Language-agnostic Tree-sitter node utility functions.

These helpers replace ast.walk(), node.lineno, node.name, etc. across all rules.
They work identically regardless of which language grammar was used to parse the tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    import tree_sitter


def walk(
    node: tree_sitter.Node,
    skip_types: Iterable[str] | None = None,
) -> Iterator[tree_sitter.Node]:
    """Yield every named node in the subtree rooted at *node*, depth-first.

    Anonymous tokens (punctuation, keyword tokens) are skipped — only the
    grammar's named nodes are yielded. This is the Tree-sitter analogue
    of the old ``ast.walk()``.

    Implemented iteratively (not recursively) to avoid Python's default
    recursion limit of 1000.

    ``skip_types`` opts into pruning: any descendant whose ``node.type`` is in
    the set has its subtree skipped. The starting *node* itself is always
    yielded even when its type matches — this is the natural shape for
    per-function rules that walk a function body but want to avoid descending
    into nested function definitions.
    """
    skip = frozenset(skip_types) if skip_types else frozenset()
    yield node
    stack: list[tree_sitter.Node] = list(reversed(node.named_children))
    while stack:  # nosafe: SAFE501
        current = stack.pop()
        yield current
        if current.type in skip:
            continue
        stack.extend(reversed(current.named_children))


def lineno(node: tree_sitter.Node) -> int:
    """Return the 1-based start line number of *node*.

    Tree-sitter uses 0-based row numbers. We add 1 to match Python convention
    and to stay compatible with the existing Violation.lineno field.
    """
    return node.start_point[0] + 1


def end_lineno(node: tree_sitter.Node) -> int:
    """Return the 1-based end line number of *node*."""
    return node.end_point[0] + 1


def column_start(node: tree_sitter.Node) -> int:
    """Return the 1-based start column of *node*.

    Tree-sitter reports 0-based columns; we add 1 to match safelint's
    1-based ``lineno`` convention. Editor adapters that need 0-based
    (e.g. LSP-style consumers) are expected to subtract 1 themselves.
    """
    return node.start_point[1] + 1


def column_end(node: tree_sitter.Node) -> int:
    """Return the 1-based end column of *node* (exclusive in Tree-sitter terms).

    Tree-sitter's ``end_point`` is *exclusive* — it points one past the
    last character of the node's span. Returning it as-is (after +1
    normalisation) gives a half-open ``[start, end)`` range that maps
    cleanly to LSP / VSCode ``Range`` semantics.
    """
    return node.end_point[1] + 1


def node_range(node: tree_sitter.Node) -> tuple[int, int, int]:
    """Return ``(lineno, column_start, column_end)`` for *node* — all 1-based.

    Convenience for rule code building :class:`~safelint.rules.base.Violation`
    objects: avoids the noisy ``node.start_point[0] + 1`` /
    ``node.start_point[1] + 1`` triplets at every call site. Multi-line
    nodes report only the start line — column_end refers to the end
    column on whatever line that is, matching Tree-sitter's convention
    of treating column_end as the column on the end_point's row.
    """
    return lineno(node), column_start(node), column_end(node)


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
