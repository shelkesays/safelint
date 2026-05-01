"""Intra-procedural taint analysis using Tree-sitter.

The :class:`TaintTracker` walks a single function body and tracks which
variables carry data derived from tainted sources (function parameters,
configurable I/O calls). When a tainted value reaches a configurable
dangerous sink the hit is recorded in :attr:`TaintTracker.sink_hits`.

Design goals
------------
* Intra-procedural only — no cross-function call graph needed.
* Assignment propagation: ``x = tainted_y`` makes ``x`` tainted.
* Sanitizer calls clear taint: ``x = escape(tainted_y)`` → ``x`` clean.
* Source calls inject taint: ``x = input()`` → ``x`` tainted.
* f-strings, containers, and arithmetic operators spread taint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, lineno, node_text, walk
from safelint.languages.python import (
    ANNOTATED_ASSIGNMENT,
    ASSIGNMENT,
    AUGMENTED_ASSIGNMENT,
    BINARY_OPERATOR,
    BOOLEAN_OPERATOR,
    CALL,
    COMPARISON_OPERATOR,
    CONCATENATED_STRING,
    CONDITIONAL_EXPRESSION,
    IDENTIFIER,
    INTERPOLATION,
    LIST,
    SET,
    STRING,
    TUPLE,
    UNARY_OPERATOR,
)


if TYPE_CHECKING:
    import tree_sitter


_SPREADING_TYPES = frozenset(
    {
        BINARY_OPERATOR,
        BOOLEAN_OPERATOR,
        UNARY_OPERATOR,
        COMPARISON_OPERATOR,
        CONDITIONAL_EXPRESSION,
    }
)

_CONTAINER_TYPES = frozenset({LIST, TUPLE, SET})


class TaintTracker:
    """Track tainted variable flow through a function body.

    Instantiate with the set of already-tainted parameter names, the sets of
    sink / sanitizer / source call names, then call ``visit(func_node)``.
    Results are in :attr:`sink_hits` as ``(lineno, var_name, sink_name)`` triples.
    """

    def __init__(
        self,
        params: set[str],
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
    ) -> None:
        """Initialise tracker with tainted entry parameters and rule config."""
        self.tainted: set[str] = set(params)
        self.sinks = sinks
        self.sanitizers = sanitizers
        self.sources = sources
        self.sink_hits: list[tuple[int, str, str]] = []

    def visit(self, root: tree_sitter.Node) -> None:
        """Process every node under *root* for taint propagation.

        Iterative walk; bound is the finite node count of *root*'s subtree.
        """
        stack: list[tree_sitter.Node] = [root]
        while stack:  # nosafe: SAFE501
            node = stack.pop()
            if node.type == ASSIGNMENT:
                self._visit_assignment(node)
            elif node.type == AUGMENTED_ASSIGNMENT:
                self._visit_aug_assignment(node)
            elif node.type == ANNOTATED_ASSIGNMENT:
                self._visit_ann_assignment(node)
            elif node.type == CALL:
                self._visit_call(node)
            stack.extend(reversed(node.children))

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value``."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left and right:
            self._update_name(left, is_tainted=self._is_tainted(right))

    def _visit_aug_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x += value``."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left and right and self._is_tainted(right):
            self._update_name(left, is_tainted=True)

    def _visit_ann_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x: T = value``."""
        value = node.child_by_field_name("right")
        if not value:
            return
        if node.named_children:
            target = node.named_children[0]
            self._update_name(target, is_tainted=self._is_tainted(value))

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink with tainted arguments."""
        name = call_name(node)
        if name not in self.sinks:
            return
        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(lineno(node), arg, name)

    def _record_sink_hit(self, line_num: int, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == IDENTIFIER else "<expr>"
        self.sink_hits.append((line_num, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, *, is_tainted: bool) -> None:
        """Add or remove *target* from the tainted set if it is a bare identifier."""
        if target.type != IDENTIFIER:
            return
        name = node_text(target)
        if is_tainted:
            self.tainted.add(name)
        else:
            self.tainted.discard(name)

    def _is_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* may carry tainted data."""
        node_type = node.type
        if node_type == IDENTIFIER:
            return node_text(node) in self.tainted
        if node_type == CALL:
            return self._call_tainted(node)
        if node_type == STRING:
            return self._fstring_tainted(node)
        if node_type == CONCATENATED_STRING or node_type in _CONTAINER_TYPES or node_type in _SPREADING_TYPES:
            return any(self._is_tainted(child) for child in node.named_children)
        return False

    def _call_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if this call produces a tainted value."""
        name = call_name(node)
        if name in self.sanitizers:
            return False
        if name in self.sources:
            return True
        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return False
        return any(self._is_tainted(arg) for arg in args_node.named_children)

    def _fstring_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if any interpolated expression in an f-string is tainted."""
        return any(self._is_tainted(inner) for child in walk(node) if child.type == INTERPOLATION for inner in child.named_children)
