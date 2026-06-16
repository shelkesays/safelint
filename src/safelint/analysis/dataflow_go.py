"""Intra-procedural taint analysis for Go source.

Parallel to :mod:`safelint.analysis.dataflow` (Python),
:mod:`safelint.analysis.dataflow_javascript` (JS / TS),
:mod:`safelint.analysis.dataflow_java` (Java), and
:mod:`safelint.analysis.dataflow_rust` (Rust). The analysis shape is
identical: parameters seed the tainted set; bindings and assignments
propagate; sanitizer calls clear taint; source calls inject taint;
sinks reaching tainted arguments produce hits.

Per-Go quirks worth calling out:

* Three binding / assignment shapes carry taint:
  ``short_var_declaration`` (``x := value``), ``assignment_statement``
  (``x = value``), and ``var_spec`` (``var x = value``). The first two
  expose ``left`` / ``right`` ``expression_list`` fields; ``var_spec``
  lists the bound identifiers directly with a trailing
  ``expression_list``. Multiple-assignment (``a, b := f(), g()``) pairs
  positionally when both sides have equal arity; otherwise every bound
  name takes the OR of the right-hand expressions (covers
  ``f, err := os.Open(p)`` where one call yields several values).
* Method calls (``recv.Method(...)``) and package calls
  (``pkg.Fn(...)``) both parse as ``call_expression`` whose ``function``
  is a ``selector_expression``; ``call_name`` resolves the trailing
  ``field`` bareword. With ``assume_taint_preserving`` the receiver
  (``operand`` of the selector) also propagates taint, so
  ``cmd.Arg(input.Trim())`` is caught.
* ``selector_expression`` used as a value (``r.Body``) propagates the
  operand's taint. ``index_expression`` (``arr[i]``) and string concat
  (``binary_expression`` with ``+``) propagate every operand.
* The blank identifier ``_`` never enters the tainted set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES


if TYPE_CHECKING:
    import tree_sitter


# Expressions whose taint state is the OR of their named children.
# ``binary_expression`` covers ``+`` string concatenation (Go's only
# taint-spreading binary op of interest, but any operand carrying taint
# taints the result); ``unary_expression`` covers ``&x`` / ``*x`` / ``!x``;
# ``parenthesized_expression`` is a pure pass-through.
_SPREADING_TYPES = frozenset(
    {
        "binary_expression",
        "unary_expression",
        "parenthesized_expression",
    }
)

# Composite literals (``T{...}`` / ``[]T{...}`` / ``map[K]V{...}``) carry
# taint when any element is tainted.
_CONTAINER_TYPES = frozenset({"composite_literal"})


class GoTaintTracker:
    """Track tainted variable flow through a Go function / method / closure body.

    Mirrors the public surface of :class:`safelint.analysis.dataflow.TaintTracker`
    so :class:`~safelint.rules.dataflow.TaintedSinkRule` can dispatch on
    the active language without behavioural divergence at the call site.
    Results are in :attr:`sink_hits` as ``(call_node, var_name, sink_name)``
    triples.
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
        """Process every node under *root* for taint propagation.

        Skips descent into nested function / closure bodies - those are
        analysed separately by the caller for each function found, with
        their own parameter set.
        """
        for node in walk(root, skip_types=tuple(_GO_FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        node_type = node.type
        if node_type in ("short_var_declaration", "assignment_statement"):
            self._visit_assignment(node)
        elif node_type == "var_spec":
            self._visit_var_spec(node)
        elif node_type == "call_expression":
            self._visit_call(node)

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x := value`` / ``x = value`` (left / right lists)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive: both sides always present
            return
        name_nodes = [c for c in left.named_children if c.type == "identifier"]
        self._propagate(name_nodes, list(right.named_children))

    def _visit_var_spec(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``var x = value`` (identifiers + trailing expression_list)."""
        name_nodes = [c for c in node.named_children if c.type == "identifier"]
        rhs_list = next((c for c in node.named_children if c.type == "expression_list"), None)
        rhs = list(rhs_list.named_children) if rhs_list is not None else []
        self._propagate(name_nodes, rhs)

    def _propagate(self, name_nodes: list[tree_sitter.Node], rhs_exprs: list[tree_sitter.Node]) -> None:
        """Set taint on each bound name from the right-hand expressions.

        Equal arity pairs positionally (``a, b := x, y``); otherwise each
        name takes the OR of all right-hand expressions, which covers the
        common ``f, err := os.Open(p)`` shape where a single call produces
        several values.
        """
        if len(name_nodes) == len(rhs_exprs):
            for name_node, rhs in zip(name_nodes, rhs_exprs, strict=True):
                self._update_name(name_node, is_tainted=self._is_tainted(rhs))
            return
        any_tainted = any(self._is_tainted(rhs) for rhs in rhs_exprs)
        for name_node in name_nodes:
            self._update_name(name_node, is_tainted=any_tainted)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink with tainted arguments."""
        name = call_name(node)
        if name not in self.sinks:
            return
        args_node = node.child_by_field_name("arguments")
        if args_node is None:  # pragma: no cover - defensive: call_expression always has an arguments child
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(node, arg, name)

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == "identifier" else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, *, is_tainted: bool) -> None:
        """Add or remove *target* from the tainted set if it is a non-blank bare name."""
        if target.type != "identifier":  # pragma: no cover - defensive: callers pre-filter to identifier nodes
            return
        name = node_text(target)
        if name == "_":
            return
        if is_tainted:
            self.tainted.add(name)
        else:
            self.tainted.discard(name)

    def _is_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* may carry tainted data.

        Iterative worklist with OR semantics (first tainted node wins).
        Depth is bounded by the expression's nesting.
        """
        stack = [node]
        while len(stack) > 0:
            current = stack.pop()
            if self._node_directly_tainted(current):
                return True
            stack.extend(self._taint_propagating_children(current))
        return False

    def _node_directly_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* is a leaf that itself carries taint."""
        node_type = node.type
        if node_type == "identifier":
            return node_text(node) in self.tainted
        if node_type == "call_expression":
            return self._call_tainted(node)
        return False

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*.

        ``selector_expression`` (``obj.field`` as a value) propagates its
        ``operand`` receiver - the field is a name lookup, so receiver
        taint dominates. ``index_expression`` (``arr[i]``), spreading
        expressions, and composite literals propagate every named child.
        Everything else is a taint dead-end.
        """
        node_type = node.type
        if node_type == "selector_expression":
            operand = node.child_by_field_name("operand")
            return [operand] if operand is not None else []
        if node_type == "index_expression" or node_type in _SPREADING_TYPES or node_type in _CONTAINER_TYPES:
            return list(node.named_children)
        return []

    def _call_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if this call produces a tainted value.

        Mirrors the other trackers' :meth:`_call_tainted`: sanitizers
        clear, sources inject, unknowns either preserve or drop based on
        ``assume_taint_preserving``. When preserving, both the positional
        arguments and the method receiver (the selector's ``operand``)
        are inspected, so ``input.Trim()`` / ``strings.TrimSpace(input)``
        stay tainted and reach the sink check.
        """
        name = call_name(node)
        if name in self.sanitizers:
            return False
        if name in self.sources:
            return True
        if not self.assume_taint_preserving:
            return False
        candidates: list[tree_sitter.Node] = []
        args_node = node.child_by_field_name("arguments")
        if args_node is not None:
            candidates.extend(args_node.named_children)
        function = node.child_by_field_name("function")
        if function is not None and function.type == "selector_expression":
            receiver = function.child_by_field_name("operand")
            if receiver is not None:
                candidates.append(receiver)
        return any(self._is_tainted(c) for c in candidates)
