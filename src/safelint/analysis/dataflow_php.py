"""Intra-procedural taint analysis for PHP source.

Parallel to :mod:`safelint.analysis.dataflow` (Python),
:mod:`safelint.analysis.dataflow_javascript` (JS / TS),
:mod:`safelint.analysis.dataflow_java` (Java), :mod:`safelint.analysis.dataflow_rust`
(Rust), and :mod:`safelint.analysis.dataflow_go` (Go). The analysis shape is
identical: parameters seed the tainted set; assignments propagate; sanitizer
calls clear taint; source reads inject taint; sinks reaching tainted arguments
produce hits. All tree-walking is iterative (worklists), never recursive -
SAFE105 polices safelint's own source.

Per-PHP quirks worth calling out:

* **Superglobals are the dominant source.** Reading a key from ``$_GET`` /
  ``$_POST`` / ``$_REQUEST`` / ``$_COOKIE`` / ``$_SERVER`` / ``$_FILES`` /
  ``$_ENV`` (a ``subscript_expression`` whose base ``variable_name`` is one of
  these) yields attacker-controlled data. The source set therefore holds
  variable *names* (a read *shape*), not just call names - but a call name in
  the source set (e.g. ``getenv``) still injects taint via ``_call_tainted``.
* **Variables are ``variable_name`` nodes** whose text includes the ``$``
  (``$x``), so the tainted set holds ``"$x"`` strings.
* **Call shapes** span ``function_call_expression`` (``foo(...)``),
  ``member_call_expression`` (``$o->m(...)``),
  ``nullsafe_member_call_expression`` (``$o?->m(...)``), and
  ``scoped_call_expression`` (``C::m(...)``); ``call_name`` resolves the
  bareword. With ``assume_taint_preserving`` the receiver (``object`` field)
  also propagates, so ``$cmd->arg(trim($input))`` is caught.
* **Call arguments are wrapped in ``argument`` nodes**, so the taint walk
  treats ``argument`` as a pass-through to its inner expression.
* **String interpolation** (``"SELECT $x"`` - an ``encapsed_string`` with a
  ``variable_name`` child) and concatenation (``binary_expression`` with
  ``.``) both propagate operand taint.
* **Variable ``include`` / ``require``** with a tainted path are sinks in
  their own right (the file path is dynamic code loading).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.php import (
    ARGUMENT,
    ARRAY_CREATION_EXPRESSION,
    ARRAY_ELEMENT_INITIALIZER,
    ASSIGNMENT_EXPRESSION,
    AUGMENTED_ASSIGNMENT_EXPRESSION,
    BINARY_EXPRESSION,
    ENCAPSED_STRING,
    FUNCTION_CALL_EXPRESSION,
    INCLUDE_EXPRESSION,
    INCLUDE_ONCE_EXPRESSION,
    MEMBER_ACCESS_EXPRESSION,
    MEMBER_CALL_EXPRESSION,
    NULLSAFE_MEMBER_ACCESS_EXPRESSION,
    NULLSAFE_MEMBER_CALL_EXPRESSION,
    PARENTHESIZED_EXPRESSION,
    REQUIRE_EXPRESSION,
    REQUIRE_ONCE_EXPRESSION,
    SCOPED_CALL_EXPRESSION,
    SUBSCRIPT_EXPRESSION,
    UNARY_OP_EXPRESSION,
    VARIABLE_NAME,
)
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES


if TYPE_CHECKING:
    import tree_sitter


# PHP call node types whose result may carry taint / be a sink.
_PHP_CALL_TYPES = frozenset(
    {
        FUNCTION_CALL_EXPRESSION,
        MEMBER_CALL_EXPRESSION,
        NULLSAFE_MEMBER_CALL_EXPRESSION,
        SCOPED_CALL_EXPRESSION,
    }
)

# ``include`` / ``require`` family - a tainted path argument is a sink.
_PHP_INCLUDE_TYPES = frozenset(
    {
        INCLUDE_EXPRESSION,
        INCLUDE_ONCE_EXPRESSION,
        REQUIRE_EXPRESSION,
        REQUIRE_ONCE_EXPRESSION,
    }
)

# Expressions whose taint state is the OR of their named children.
# ``binary_expression`` covers ``.`` string concatenation and ``+``;
# ``unary_op_expression`` covers ``!x`` / ``-x``; ``parenthesized_expression``
# is a pure pass-through; ``encapsed_string`` carries interpolated variables.
_SPREADING_TYPES = frozenset(
    {
        BINARY_EXPRESSION,
        UNARY_OP_EXPRESSION,
        PARENTHESIZED_EXPRESSION,
        ENCAPSED_STRING,
    }
)

# Array literals carry taint when any element is tainted.
_CONTAINER_TYPES = frozenset({ARRAY_CREATION_EXPRESSION})


class PhpTaintTracker:
    """Track tainted variable flow through a PHP function / script-scope body.

    Mirrors the public surface of :class:`safelint.analysis.dataflow.TaintTracker`
    so :class:`~safelint.rules.dataflow.TaintedSinkRule` can dispatch on the
    active language without behavioural divergence at the call site. Results are
    in :attr:`sink_hits` as ``(call_node, var_name, sink_name)`` triples.
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
        analysed separately by the caller with their own parameter set. When
        *root* is the program node this analyses the script's top-level scope
        (common in PHP), and the function bodies are pruned out.
        """
        for node in walk(root, skip_types=tuple(_PHP_FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        node_type = node.type
        if node_type in (ASSIGNMENT_EXPRESSION, AUGMENTED_ASSIGNMENT_EXPRESSION):
            self._visit_assignment(node)
        elif node_type in _PHP_CALL_TYPES:
            self._visit_call(node)
        elif node_type in _PHP_INCLUDE_TYPES:
            self._visit_include(node)

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``$x = value`` / ``$x .= value``.

        A compound assignment (``$x .= $y`` / ``$x += $y``) is a
        read-modify-write, so a clean RHS must not clear ``$x``'s prior taint.
        A plain ``=`` is a fresh write that overwrites. The target is either a
        bare ``$x`` or a subscript ``$arr[...]`` (whose base array takes the
        taint).
        """
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive: both sides always present
            return
        target = self._assignment_target_name(left)
        if target is None:
            return
        keep_existing = node.type == AUGMENTED_ASSIGNMENT_EXPRESSION
        self._update_name(target, is_tainted=self._is_tainted(right), keep_existing=keep_existing)

    @staticmethod
    def _assignment_target_name(left: tree_sitter.Node) -> str | None:
        """Return the bound variable name for an assignment LHS, or None.

        ``$x`` -> ``"$x"``; ``$arr[...]`` -> the base array name ``"$arr"`` (a
        tainted element taints the array for the conservative model); other
        shapes (property writes etc.) are not tracked.
        """
        if left.type == VARIABLE_NAME:
            return node_text(left)
        if left.type == SUBSCRIPT_EXPRESSION:
            base = left.named_children[0] if left.named_children else None
            if base is not None and base.type == VARIABLE_NAME:
                return node_text(base)
        return None

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink with tainted arguments."""
        name = call_name(node)
        if name not in self.sinks:
            return
        args_node = node.child_by_field_name("arguments")
        if args_node is None:  # pragma: no cover - defensive: call nodes always have an arguments child
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(node, arg, name)

    def _visit_include(self, node: tree_sitter.Node) -> None:
        """Flag a tainted path flowing into ``include`` / ``require`` (dynamic file load)."""
        sink = node.type.removesuffix("_expression")
        for child in node.named_children:
            if self._is_tainted(child):
                self._record_sink_hit(node, child, sink)
                return

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        self.sink_hits.append((call_node, self._arg_display_name(arg_node), sink))

    @staticmethod
    def _arg_display_name(arg_node: tree_sitter.Node) -> str:
        """Return the variable name of an argument for the message, or ``"<expr>"``."""
        target = arg_node
        if arg_node.type == ARGUMENT and arg_node.named_children:
            target = arg_node.named_children[0]
        return node_text(target) if target.type == VARIABLE_NAME else "<expr>"

    def _update_name(self, name: str, *, is_tainted: bool, keep_existing: bool = False) -> None:
        """Add or remove *name* from the tainted set.

        With *keep_existing* (a compound read-modify-write assignment) a clean
        RHS leaves the name's prior taint untouched rather than clearing it.
        """
        if not name:  # pragma: no cover - defensive: callers pass non-empty names
            return
        if is_tainted:
            self.tainted.add(name)
        elif not keep_existing:
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
        if node_type == VARIABLE_NAME:
            return node_text(node) in self.tainted
        if node_type == SUBSCRIPT_EXPRESSION:
            return self._subscript_is_source(node)
        if node_type in _PHP_CALL_TYPES:
            return self._call_tainted(node)
        return False

    def _subscript_is_source(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* reads a key from a superglobal source (``$_GET['x']``).

        A subscript on a tainted *array* (``$tainted['k']``) is handled by the
        propagation path (the base is in the tainted set); this only flags the
        direct superglobal-read source shape.
        """
        base = node.named_children[0] if node.named_children else None
        return base is not None and base.type == VARIABLE_NAME and node_text(base) in self.sources

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*.

        ``argument`` is a pass-through wrapper around a call argument;
        ``member_access_expression`` / ``nullsafe_member_access_expression``
        (``$obj->prop``) propagate the receiver; ``subscript_expression``
        propagates its base array; spreading expressions and array literals
        propagate every named child. Everything else is a taint dead-end.
        """
        node_type = node.type
        if node_type in (MEMBER_ACCESS_EXPRESSION, NULLSAFE_MEMBER_ACCESS_EXPRESSION):
            obj = node.child_by_field_name("object")
            return [obj] if obj is not None else []
        if node_type == SUBSCRIPT_EXPRESSION:
            base = node.named_children[0] if node.named_children else None
            return [base] if base is not None else []
        if node_type in (ARGUMENT, ARRAY_ELEMENT_INITIALIZER) or node_type in _SPREADING_TYPES or node_type in _CONTAINER_TYPES:
            return list(node.named_children)
        return []

    def _call_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if this call produces a tainted value.

        Sanitizers clear, call-name sources inject, unknowns either preserve
        or drop based on ``assume_taint_preserving``. When preserving, both
        the positional arguments and the method receiver (the ``object`` field
        of a member / nullsafe / scoped call) are inspected, so
        ``trim($input)`` and ``$input->raw()`` stay tainted.
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
        receiver = node.child_by_field_name("object")
        if receiver is not None:
            candidates.append(receiver)
        return any(self._is_tainted(c) for c in candidates)
