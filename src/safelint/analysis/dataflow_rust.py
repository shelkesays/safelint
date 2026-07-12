"""Intra-procedural taint analysis for Rust source.

Parallel to :mod:`safelint.analysis.dataflow` (Python),
:mod:`safelint.analysis.dataflow_javascript` (JS / TS), and
:mod:`safelint.analysis.dataflow_java` (Java). The analysis shape is
identical: parameters seed the tainted set; let bindings and
assignments propagate; sanitizer calls clear taint; source calls
inject taint; sinks reaching tainted arguments produce hits.

Per-Rust quirks worth calling out:

* ``let x = value`` is the binding form (``let_declaration``), not
  ``const`` / ``let`` like JavaScript. Tuple- and struct-destructuring
  patterns bind every contained name.
* ``x = y`` is ``assignment_expression``; ``x += y`` is
  ``compound_assignment_expr``.
* Method calls (``obj.method(...)``) parse as ``call_expression``
  whose ``function`` is a ``field_expression``. Qualified path calls
  (``std::fs::read(...)`` / ``Command::new(...)``) parse with
  ``function`` set to a ``scoped_identifier``. ``call_name`` resolves
  both shapes to the trailing bareword.
* Macros (``println!`` / ``format!`` / ``sqlx::query!``) parse as
  ``macro_invocation`` and are NOT modelled by this tracker; the macro
  body parses as a token tree, not an expression list, so we can't
  see argument flow inside it without a per-macro decoder. SAFE801
  macro-based sinks (``sqlx::query!``) are a known limitation
  documented in docs/configuration/rules.md.
* Reference / dereference (``&x`` / ``*x``) and the ``?`` operator
  parse through ``unary_expression`` / ``reference_expression`` /
  ``try_expression``; taint passes through them unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.rust import (
    ARRAY_EXPRESSION,
    ASSIGNMENT_EXPRESSION,
    ASYNC_BLOCK,
    AWAIT_EXPRESSION,
    BINARY_EXPRESSION,
    CALL_EXPRESSION,
    CAPTURED_PATTERN,
    COMPOUND_ASSIGNMENT_EXPR,
    FIELD_EXPRESSION,
    FIELD_PATTERN,
    IDENTIFIER,
    INDEX_EXPRESSION,
    LET_DECLARATION,
    MUT_PATTERN,
    PARENTHESIZED_EXPRESSION,
    RANGE_EXPRESSION,
    REF_PATTERN,
    REFERENCE_EXPRESSION,
    SHORTHAND_FIELD_IDENTIFIER,
    STRUCT_EXPRESSION,
    STRUCT_PATTERN,
    TRY_EXPRESSION,
    TUPLE_EXPRESSION,
    TUPLE_PATTERN,
    TUPLE_STRUCT_PATTERN,
    UNARY_EXPRESSION,
)
from safelint.languages.rust import FUNCTION_TYPES as _RUST_FUNCTION_TYPES


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter


# Composite expressions whose taint state is the OR of their named
# children. ``parenthesized_expression`` and ``unary_expression``
# (which covers ``&x``, ``*x``, ``!x``, ``-x``) are pure pass-throughs
# at the value level; ``try_expression`` (``foo()?``) carries through
# the underlying Result's Ok value, so taint propagates. Binary /
# range / await / async / reference / await each carry through any
# tainted operand.
_SPREADING_TYPES = frozenset(
    {
        BINARY_EXPRESSION,
        UNARY_EXPRESSION,
        REFERENCE_EXPRESSION,
        PARENTHESIZED_EXPRESSION,
        TRY_EXPRESSION,
        RANGE_EXPRESSION,
        AWAIT_EXPRESSION,
        ASYNC_BLOCK,
    }
)

# Container / aggregate literals that carry taint when any element is tainted.
# ``tuple_expression`` covers ``(a, b)``; ``array_expression`` covers
# ``[a, b]`` and ``[expr; N]``; ``struct_expression`` covers
# ``Foo { x, y }`` field literals.
_CONTAINER_TYPES = frozenset(
    {
        TUPLE_EXPRESSION,
        ARRAY_EXPRESSION,
        STRUCT_EXPRESSION,
    }
)


class RustTaintTracker:
    """Track tainted variable flow through a Rust function / closure body.

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
        for node in walk(root, skip_types=tuple(_RUST_FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        if node.type == LET_DECLARATION:
            self._visit_let(node)
        elif node.type == ASSIGNMENT_EXPRESSION:
            self._visit_assignment(node)
        elif node.type == COMPOUND_ASSIGNMENT_EXPR:
            self._visit_compound_assignment(node)
        elif node.type == CALL_EXPRESSION:
            self._visit_call(node)

    def _iter_pattern_identifiers(self, pattern: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
        """Yield each bare identifier inside *pattern*.

        Handles Rust destructuring shapes:

        * ``identifier`` / ``shorthand_field_identifier`` - leaf
          identifiers; the latter is emitted inside ``field_pattern``
          for the shorthand ``{ x }`` form where the field name IS the
          bound name.
        * ``mut_pattern`` / ``ref_pattern`` - ``let mut x`` / ``let ref x``.
        * ``tuple_pattern`` - ``let (a, b) = ...``.
        * ``tuple_struct_pattern`` - ``let Some(x) = ...``.
        * ``struct_pattern`` - ``let Foo { a, b } = ...``; recurses
          into each ``field_pattern`` child (the leading
          ``type_identifier`` carries the type name and is skipped
          because it isn't a binding).
        * ``field_pattern`` - aliased ``{ x: alias }`` has the binding
          on the ``pattern`` field; shorthand ``{ x }`` carries the
          binding as a ``shorthand_field_identifier`` named child.
        * ``captured_pattern`` - ``name @ pattern`` binds both
          ``name`` and any inner identifiers.
        * ``tuple_expression`` - Rust 1.59+ destructuring assignment
          ``(a, b) = ...;``. The LHS of ``assignment_expression`` is
          parsed as ``tuple_expression`` (not ``tuple_pattern``) since
          it's an l-value expression, not a binding pattern. Recurse
          the same way to surface the rebound identifiers.

        Wildcard ``_`` and type references inside patterns don't bind
        anything and are skipped naturally.
        """
        nested_types = (
            MUT_PATTERN,
            REF_PATTERN,
            TUPLE_PATTERN,
            TUPLE_EXPRESSION,  # destructuring assignment: ``(a, b) = ...``
            TUPLE_STRUCT_PATTERN,
            STRUCT_PATTERN,
            CAPTURED_PATTERN,
        )
        # Iterative DFS over the pattern shape; children pushed reversed to
        # preserve left-to-right yield order. ``field_pattern`` delegates to a
        # helper (which re-enters this method for its inner pattern). Bounded
        # by the pattern's nesting.
        stack = [pattern]
        while len(stack) > 0:
            current = stack.pop()
            ptype = current.type
            if ptype in (IDENTIFIER, SHORTHAND_FIELD_IDENTIFIER):
                yield current
            elif ptype in nested_types:
                stack.extend(reversed(current.named_children))
            elif ptype == FIELD_PATTERN:
                yield from self._iter_field_pattern_identifiers(current)

    def _iter_field_pattern_identifiers(self, pattern: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
        """Yield bound identifiers inside a ``field_pattern`` node.

        Aliased ``{ x: alias }`` carries the binding on the ``pattern``
        field; shorthand ``{ x }`` carries the binding as a
        ``shorthand_field_identifier`` named child.
        """
        inner = pattern.child_by_field_name("pattern")
        if inner is not None:
            yield from self._iter_pattern_identifiers(inner)
            return
        shorthand = next((c for c in pattern.named_children if c.type == SHORTHAND_FIELD_IDENTIFIER), None)
        if shorthand is not None:
            yield shorthand

    def _visit_let(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``let <pattern> = value``.

        Rust ``let`` declarations always have a ``pattern`` field; a
        ``value`` field is optional (``let x;`` without an initialiser
        is legal). When the initialiser is missing the bound names
        start untainted - call ``_update_name(..., is_tainted=False)``
        to clear any prior taint on shadowed names from outer scopes.
        """
        pattern = node.child_by_field_name("pattern")
        if pattern is None:  # pragma: no cover - defensive: every let_declaration has a pattern
            return
        value = node.child_by_field_name("value")
        is_tainted = self._is_tainted(value) if value is not None else False
        for ident in self._iter_pattern_identifiers(pattern):
            self._update_name(ident, is_tainted=is_tainted)

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value`` (assignment_expression)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive: valid assignments have both sides
            return
        is_tainted = self._is_tainted(right)
        for ident in self._iter_pattern_identifiers(left):
            self._update_name(ident, is_tainted=is_tainted)

    def _visit_compound_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x += value`` / ``x *= value`` etc."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive
            return
        if self._is_tainted(right):
            self._update_name(left, is_tainted=True)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink with tainted arguments."""
        name = call_name(node)
        if name not in self.sinks:
            return
        args_node = node.child_by_field_name("arguments")
        if not args_node:  # pragma: no cover - defensive: call_expression always has an arguments child
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(node, arg, name)

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == IDENTIFIER else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, *, is_tainted: bool) -> None:
        """Add or remove *target* from the tainted set if it carries a bare name."""
        if target.type not in (IDENTIFIER, SHORTHAND_FIELD_IDENTIFIER):
            return
        name = node_text(target)
        if is_tainted:
            self.tainted.add(name)
        else:
            self.tainted.discard(name)

    def _is_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* may carry tainted data.

        Iterative worklist with OR semantics (first tainted node wins).
        Per-node classification is split into :meth:`_node_directly_tainted`
        and :meth:`_taint_propagating_children`. Depth is bounded by the
        expression's nesting.
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
        if node_type == IDENTIFIER:
            return node_text(node) in self.tainted
        if node_type == CALL_EXPRESSION:
            return self._call_tainted(node)
        return False

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*.

        ``field_expression`` (``obj.field``) propagates its ``value`` receiver -
        the field is a name lookup, so receiver taint dominates.
        ``index_expression`` (``arr[i]``), spreading expressions, and
        containers propagate every named child: for indexing, both
        ``tainted_arr[clean_idx]`` and ``clean_arr[tainted_idx]`` are tainted
        (the selected element depends on the index). Everything else is a
        taint dead-end.
        """
        node_type = node.type
        if node_type == FIELD_EXPRESSION:
            obj = node.child_by_field_name("value")
            return [obj] if obj is not None else []
        if node_type == INDEX_EXPRESSION or node_type in _SPREADING_TYPES or node_type in _CONTAINER_TYPES:
            return list(node.named_children)
        return []

    def _call_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if this call produces a tainted value.

        Mirrors the Python / JS tracker's :meth:`_call_tainted` exactly -
        sanitizers clear, sources inject, unknowns either preserve or
        drop based on ``assume_taint_preserving``.

        For Rust, ``assume_taint_preserving=True`` must also flow taint
        through the *method receiver* on calls like ``tainted.trim()``
        / ``path.clone()`` / ``s.to_string()``: those return a value
        derived from the receiver but take zero positional arguments,
        so a positional-only inspection would silently mark them clean
        and miss real sinks (``cmd.arg(tainted.trim())``).
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
        # Method-call shape: ``call_expression.function`` is a
        # ``field_expression`` whose ``value`` is the receiver. Plain
        # function calls (``foo(x)``) have an ``identifier`` /
        # ``scoped_identifier`` function and no receiver to read.
        function = node.child_by_field_name("function")
        if function is not None and function.type == FIELD_EXPRESSION:
            receiver = function.child_by_field_name("value")
            if receiver is not None:
                candidates.append(receiver)
        return any(self._is_tainted(c) for c in candidates)
