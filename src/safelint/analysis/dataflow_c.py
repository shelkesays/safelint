"""Intra-procedural taint analysis for C source.

Parallel to :mod:`safelint.analysis.dataflow` (Python) and the JS / Java /
Rust / Go trackers. The analysis shape is identical: parameters seed the
tainted set; declarations and assignments propagate; sanitizer calls clear
taint; source calls inject taint; sinks reaching tainted arguments produce
hits.

Per-C quirks worth calling out:

* Two binding shapes carry taint: ``init_declarator`` (``char *p =
  getenv(...)`` - a ``declarator`` field naming the variable, possibly wrapped
  in ``pointer_declarator`` / ``array_declarator``, plus a ``value`` field) and
  ``assignment_expression`` (``x = ...`` / ``x += ...`` - ``left`` / ``right`` /
  ``operator`` fields). A compound assignment (``+=`` etc.) is read-modify-write
  and ORs with the name's prior taint.
* ``argv`` enters tainted through function-parameter seeding;
  ``subscript_expression`` (``argv[1]``) propagates its ``argument`` (the array),
  so an indexed read of a tainted array stays tainted.
* ``cast_expression`` (``(char *)x``), ``parenthesized_expression``,
  ``pointer_expression`` (``*p``), unary / binary expressions, and
  ``field_expression`` (``s.field`` / ``p->field``) all pass taint through.
* Unlike Go / Python, C has no blank identifier, so a variable named ``_`` is
  tracked like any other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.c import (
    ASSIGNMENT_EXPRESSION,
    BINARY_EXPRESSION,
    CALL_EXPRESSION,
    CAST_EXPRESSION,
    COMMA_EXPRESSION,
    CONDITIONAL_EXPRESSION,
    FIELD_EXPRESSION,
    IDENTIFIER,
    INIT_DECLARATOR,
    PARENTHESIZED_EXPRESSION,
    POINTER_EXPRESSION,
    SUBSCRIPT_EXPRESSION,
    TYPE_DESCRIPTOR,
    UNARY_EXPRESSION,
)
from safelint.languages.c import FUNCTION_TYPES as _C_FUNCTION_TYPES


if TYPE_CHECKING:
    import tree_sitter


# Expressions whose taint state is the OR of their named children.
_SPREADING_TYPES = frozenset(
    {
        BINARY_EXPRESSION,
        UNARY_EXPRESSION,
        PARENTHESIZED_EXPRESSION,
        POINTER_EXPRESSION,  # ``*p`` / ``&p``
        COMMA_EXPRESSION,
        CONDITIONAL_EXPRESSION,  # ``cond ? tainted : clean`` - either branch taints
    }
)


def _assignment_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
    """Return the children whose taint flows into an inline ``assignment_expression``'s value.

    ``(cmd = argv[1])`` used directly as a sink argument has the value of its RHS,
    so the RHS is followed. A compound assignment (``cmd += argv[1]``) reads the
    prior LHS as well, so both sides are followed in that case.
    """
    right = node.child_by_field_name("right")
    children = [right] if right is not None else []
    operator = node.child_by_field_name("operator")
    if operator is not None and node_text(operator) != "=":
        left = node.child_by_field_name("left")
        if left is not None:
            children.append(left)
    return children


def _declarator_identifier(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Return the name ``identifier`` from a declarator, unwrapping pointer / array layers.

    Bounded iterative descent of the ``declarator`` field (never recursion -
    SAFE105 polices this codebase).
    """
    cur = node
    for _ in range(16):
        if cur is None:  # pragma: no cover - defensive: declarator chains always bottom out in an identifier
            return None
        if cur.type == IDENTIFIER:
            return cur
        cur = cur.child_by_field_name("declarator")
    return None  # pragma: no cover - defensive: 16-deep declarator nesting does not occur


class CTaintTracker:
    """Track tainted variable flow through a C function body.

    Mirrors the public surface of :class:`safelint.analysis.dataflow.TaintTracker`
    so :class:`~safelint.rules.dataflow.TaintedSinkRule` can dispatch on the
    active language without behavioural divergence. Results are in
    :attr:`sink_hits` as ``(call_node, var_name, sink_name)`` triples.
    """

    def __init__(
        self,
        params: set[str],
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
        *,
        assume_taint_preserving: bool = True,
    ) -> None:
        """Initialise tracker with tainted entry parameters and rule config."""
        self.tainted: set[str] = set(params)
        self.sinks = sinks
        self.sanitizers = sanitizers
        self.sources = sources
        self.assume_taint_preserving = assume_taint_preserving
        self.sink_hits: list[tuple[tree_sitter.Node, str, str]] = []

    def visit(self, root: tree_sitter.Node) -> None:
        """Process every node under *root* for taint propagation (nested functions skipped)."""
        for node in walk(root, skip_types=tuple(_C_FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        node_type = node.type
        if node_type == INIT_DECLARATOR:
            self._visit_init_declarator(node)
        elif node_type == ASSIGNMENT_EXPRESSION:
            self._visit_assignment(node)
        elif node_type == CALL_EXPRESSION:
            self._visit_call(node)

    def _visit_init_declarator(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``T x = value;`` (declarator name <- value taint)."""
        value = node.child_by_field_name("value")
        if value is None:  # pragma: no cover - defensive: an init_declarator always has a value field
            return
        name_node = _declarator_identifier(node.child_by_field_name("declarator"))
        if name_node is not None:
            self._update_name(name_node, is_tainted=self._is_tainted(value))

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value`` / ``x += value`` (compound keeps prior taint)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or left.type != IDENTIFIER:
            return
        operator = node.child_by_field_name("operator")
        keep_existing = operator is not None and node_text(operator) != "="
        self._update_name(left, is_tainted=self._is_tainted(right), keep_existing=keep_existing)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink with tainted arguments."""
        name = call_name(node)
        if name not in self.sinks:
            return
        args_node = node.child_by_field_name("arguments")
        if args_node is None:  # pragma: no cover - defensive: call_expression always has arguments
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(node, arg, name)

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == IDENTIFIER else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, *, is_tainted: bool, keep_existing: bool = False) -> None:
        """Add or remove *target* from the tainted set if it is a bare name.

        No ``_`` blank-identifier skip: unlike Go / Python, C has no blank
        identifier, so a variable legitimately named ``_`` is tracked normally.
        """
        if target.type != IDENTIFIER:  # pragma: no cover - callers pre-filter to identifier nodes
            return
        name = node_text(target)
        if is_tainted:
            self.tainted.add(name)
        elif not keep_existing:
            self.tainted.discard(name)

    def _is_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* may carry tainted data (iterative worklist, OR semantics).

        Fully iterative (no recursion - the analysis-module guideline): each
        worklist node is reduced by ``_taint_step`` to ``(tainted_here, children
        to examine)``. A sanitizer call clears (no children); a source call
        taints; an unknown call under ``assume_taint_preserving`` taints iff one
        of its arguments is tainted, so those arguments stay on the worklist.
        """
        stack = [node]
        while len(stack) > 0:
            terminal, children = self._taint_step(stack.pop())
            if terminal:
                return True
            stack.extend(children)
        return False

    def _taint_step(self, node: tree_sitter.Node) -> tuple[bool, list[tree_sitter.Node]]:
        """Reduce one worklist node to ``(is_tainted_here, children_to_examine)``."""
        node_type = node.type
        if node_type == IDENTIFIER:
            return node_text(node) in self.tainted, []
        if node_type == CALL_EXPRESSION:
            return self._classify_call(node)
        return False, self._taint_propagating_children(node)

    def _classify_call(self, node: tree_sitter.Node) -> tuple[bool, list[tree_sitter.Node]]:
        """Classify a call: ``(is_source, args_to_descend_into)``.

        A sanitizer clears -> ``(False, [])`` (its arguments are not followed).
        A source taints -> ``(True, [])``. An unknown call propagates only under
        ``assume_taint_preserving``, in which case its argument nodes are
        returned for the worklist to examine; otherwise it clears.
        """
        name = call_name(node)
        if name in self.sanitizers:
            return False, []
        if name in self.sources:
            return True, []
        if not self.assume_taint_preserving:
            return False, []
        args_node = node.child_by_field_name("arguments")
        if args_node is None:  # pragma: no cover - defensive: a call_expression always has an arguments child
            return False, []
        return False, list(args_node.named_children)

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*."""
        node_type = node.type
        if node_type == SUBSCRIPT_EXPRESSION:
            argument = node.child_by_field_name("argument")
            return [argument] if argument is not None else []
        if node_type == FIELD_EXPRESSION:
            argument = node.child_by_field_name("argument")
            return [argument] if argument is not None else []
        if node_type == CAST_EXPRESSION:
            # ``(T)expr`` - propagate the operand, never the type_descriptor.
            return [c for c in node.named_children if c.type != TYPE_DESCRIPTOR]
        if node_type == ASSIGNMENT_EXPRESSION:
            # An inline ``(x = rhs)`` carries its RHS's value into the sink.
            return _assignment_propagating_children(node)
        if node_type in _SPREADING_TYPES:
            return list(node.named_children)
        return []
