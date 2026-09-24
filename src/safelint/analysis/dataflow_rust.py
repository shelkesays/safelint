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

from safelint.analysis._taint_contract import AssignmentShapes, PropertyContract, SinkKinds, combine_status, identifier_tainted, iter_assignment_writes, set_status, value_status
from safelint.languages import rust as _rust
from safelint.languages._node_utils import call_has_arguments, call_name, node_text, walk


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
        _rust.BINARY_EXPRESSION,
        _rust.UNARY_EXPRESSION,
        _rust.REFERENCE_EXPRESSION,
        _rust.PARENTHESIZED_EXPRESSION,
        _rust.TRY_EXPRESSION,
        _rust.RANGE_EXPRESSION,
        _rust.AWAIT_EXPRESSION,
        _rust.ASYNC_BLOCK,
    }
)

# Container / aggregate literals that carry taint when any element is tainted.
# ``tuple_expression`` covers ``(a, b)``; ``array_expression`` covers
# ``[a, b]`` and ``[expr; N]``; ``struct_expression`` covers
# ``Foo { x, y }`` field literals.
_CONTAINER_TYPES = frozenset(
    {
        _rust.TUPLE_EXPRESSION,
        _rust.ARRAY_EXPRESSION,
        _rust.STRUCT_EXPRESSION,
    }
)


#: Node types this language uses for assignment targets. The traversal that
#: consumes them lives in ``_taint_contract`` and is shared by every tracker.
_ASSIGNMENT_SHAPES = AssignmentShapes(
    fields={_rust.FIELD_EXPRESSION: ("field", False)},
    chains=frozenset({_rust.ASSIGNMENT_EXPRESSION}),
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
        sink_kinds: SinkKinds | None = None,
        property_contract: PropertyContract | None = None,
    ) -> None:
        """Initialise tracker with tainted entry parameters and rule config."""
        self.contract = property_contract if property_contract is not None else PropertyContract()
        self.tainted: dict[str, frozenset[str]] = {p: frozenset() for p in params}
        self._properties = self.contract.all_properties()
        self.sinks = sinks
        self.sanitizers = sanitizers
        self.sources = sources
        self.assume_taint_preserving = assume_taint_preserving
        self.sink_kinds = sink_kinds if sink_kinds is not None else SinkKinds()
        self.sink_hits: list[tuple[tree_sitter.Node, str, str]] = []

    def visit(self, root: tree_sitter.Node) -> None:
        """Process every node under *root* for taint propagation.

        Skips descent into nested function / closure bodies - those are
        analysed separately by the caller for each function found, with
        their own parameter set.
        """
        for node in walk(root, skip_types=tuple(_rust.FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        if node.type == _rust.LET_DECLARATION:
            self._visit_let(node)
        elif node.type == _rust.ASSIGNMENT_EXPRESSION:
            self._check_assignment_sink(node)
            self._visit_assignment(node)
        elif node.type == _rust.COMPOUND_ASSIGNMENT_EXPR:
            self._check_assignment_sink(node)
            self._visit_compound_assignment(node)
        elif node.type == _rust.CALL_EXPRESSION:
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
            _rust.MUT_PATTERN,
            _rust.REF_PATTERN,
            _rust.TUPLE_PATTERN,
            _rust.TUPLE_EXPRESSION,  # destructuring assignment: ``(a, b) = ...``
            _rust.TUPLE_STRUCT_PATTERN,
            _rust.STRUCT_PATTERN,
            _rust.CAPTURED_PATTERN,
        )
        # Iterative DFS over the pattern shape; children pushed reversed to
        # preserve left-to-right yield order. ``field_pattern`` delegates to a
        # helper (which re-enters this method for its inner pattern). Bounded
        # by the pattern's nesting.
        stack = [pattern]
        while len(stack) > 0:
            current = stack.pop()
            ptype = current.type
            if ptype in (_rust.IDENTIFIER, _rust.SHORTHAND_FIELD_IDENTIFIER):
                yield current
            elif ptype in nested_types:
                stack.extend(reversed(current.named_children))
            elif ptype == _rust.FIELD_PATTERN:
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
        shorthand = next((c for c in pattern.named_children if c.type == _rust.SHORTHAND_FIELD_IDENTIFIER), None)
        if shorthand is not None:
            yield shorthand

    def _visit_let(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``let <pattern> = value``.

        Rust ``let`` declarations always have a ``pattern`` field; a
        ``value`` field is optional (``let x;`` without an initialiser
        is legal). When the initialiser is missing the bound names
        start untainted - a ``None`` status clears any prior taint on
        shadowed names from outer scopes.
        """
        pattern = node.child_by_field_name("pattern")
        if pattern is None:  # pragma: no cover - defensive: every let_declaration has a pattern
            return
        value = node.child_by_field_name("value")
        status = value_status(self._is_tainted, self._properties, value) if value is not None else None
        for ident in self._iter_pattern_identifiers(pattern):
            self._update_name(ident, status)

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value`` (assignment_expression)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive: valid assignments have both sides
            return
        status = value_status(self._is_tainted, self._properties, right)
        for ident in self._iter_pattern_identifiers(left):
            self._update_name(ident, status)

    def _visit_compound_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x += value`` / ``x *= value`` etc."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive
            return
        self._update_name(left, value_status(self._is_tainted, self._properties, right), keep_existing=True)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink via a tainted argument or method receiver."""
        name = call_name(node)
        if name not in self.sinks:
            return
        required = self.contract.required_for(name)
        if self._record_arg_hits(node, name, required):
            return  # a tainted argument already reached the sink; receiver is redundant
        # Else, a sink method on a tainted receiver (``tainted.execute()``): the
        # field-expression value is itself a tainted value reaching the sink. Fires
        # ONLY when the call has no arguments: an argument-consuming sink's payload
        # is its argument, so a tainted receiver passed only constant arguments
        # (``conn.query("SELECT 1")``) is not injection.
        function = node.child_by_field_name("function")
        if function is not None and function.type == _rust.FIELD_EXPRESSION:
            receiver = function.child_by_field_name("value")
            if receiver is not None and self._is_tainted(receiver, required) and (name in self.sink_kinds.receiver or not call_has_arguments(node)):
                self._record_sink_hit(node, receiver, name)

    def _record_arg_hits(self, node: tree_sitter.Node, name: str, required: str | None) -> bool:
        """Record one sink hit per tainted positional argument; return True if any fired."""
        args_node = node.child_by_field_name("arguments")
        if args_node is None:
            return False
        fired = False
        for arg in args_node.named_children:
            if self._is_tainted(arg, required):
                self._record_sink_hit(node, arg, name)
                fired = True
        return fired

    def _check_assignment_sink(self, node: tree_sitter.Node) -> None:
        """Record a hit when a tainted value is WRITTEN to a sink-named property.

        Writing the property is the injection, so the target is matched against
        ``assignment_sinks`` with the same sanitiser and property-typed contract
        as a call. The traversal (parenthesised targets, unpacking, chained
        right-hand sides) is shared - only ``_ASSIGNMENT_SHAPES`` differs here.
        """
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:
            return
        for sink, value in iter_assignment_writes(left, right, _ASSIGNMENT_SHAPES):
            if sink in self.sink_kinds.assignment and self._is_tainted(value, self.contract.required_for(sink)):
                self._record_sink_hit(node, value, sink)

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == _rust.IDENTIFIER else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, status: frozenset[str] | None, *, keep_existing: bool = False) -> None:
        """Record taint *status* for *target* if it carries a bare name (``None`` clears)."""
        if target.type not in (_rust.IDENTIFIER, _rust.SHORTHAND_FIELD_IDENTIFIER):
            return
        name = node_text(target)
        if keep_existing:
            status = combine_status(self.tainted.get(name), status)
        set_status(self.tainted, name, status)

    def _is_tainted(self, node: tree_sitter.Node, required_property: str | None = None) -> bool:
        """Return True if *node* may carry data still tainted for *required_property*.

        Single iterative worklist (no recursion): each node is reduced by
        :meth:`_taint_step` to ``(is_tainted_here, children_to_examine)``; the
        first tainted node short-circuits. *required_property* is the property the
        target sink requires (``None`` when it declares none) and decides whether a
        property-typed sanitiser on the path clears.
        """
        stack: list[tuple[tree_sitter.Node, str | None]] = [(node, required_property)]
        while len(stack) > 0:
            current, prop = stack.pop()
            terminal, children = self._taint_step(current, prop)
            if terminal:
                return True
            stack.extend(children)
        return False

    def _taint_step(self, node: tree_sitter.Node, required_property: str | None) -> tuple[bool, list[tuple[tree_sitter.Node, str | None]]]:
        """Reduce *node* to ``(is_tainted_here, children_to_examine)`` for the worklist.

        A call is classified by :meth:`_classify_call`, which returns children
        rather than re-entering :meth:`_is_tainted`, keeping the check a single
        worklist.
        """
        node_type = node.type
        if node_type == _rust.IDENTIFIER:
            return identifier_tainted(self.tainted, node_text(node), required_property), []
        if node_type == _rust.CALL_EXPRESSION:
            return self._classify_call(node, required_property)
        return False, [(child, required_property) for child in self._taint_propagating_children(node)]

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
        if node_type == _rust.FIELD_EXPRESSION:
            obj = node.child_by_field_name("value")
            return [obj] if obj is not None else []
        if node_type == _rust.INDEX_EXPRESSION or node_type in _SPREADING_TYPES or node_type in _CONTAINER_TYPES:
            return list(node.named_children)
        return []

    def _classify_call(self, node: tree_sitter.Node, required_property: str | None) -> tuple[bool, list[tuple[tree_sitter.Node, str | None]]]:
        """Classify a call for the worklist: ``(is_tainted_here, children_to_examine)``.

        A sanitiser that clears *required_property* short-circuits to
        ``(False, [])``; a source is ``(True, [])``; the sanitiser check runs
        first. An unknown call under ``assume_taint_preserving`` returns
        ``(False, <arg / receiver nodes>)`` so the worklist drains them - the
        receiver keeps ``tainted.trim()`` / ``path.clone()`` / ``s.to_string()``
        tainted even with zero positional arguments (``cmd.arg(tainted.trim())``).
        """
        name = call_name(node)
        if name in self.sanitizers or self.contract.clears(name, required_property):
            return False, []
        if name in self.sources:
            return True, []
        if not self.assume_taint_preserving:
            return False, []
        candidates: list[tree_sitter.Node] = []
        args_node = node.child_by_field_name("arguments")
        if args_node is not None:
            candidates.extend(args_node.named_children)
        # Method-call shape: ``call_expression.function`` is a
        # ``field_expression`` whose ``value`` is the receiver. Plain
        # function calls (``foo(x)``) have an ``identifier`` /
        # ``scoped_identifier`` function and no receiver to read.
        function = node.child_by_field_name("function")
        if function is not None and function.type == _rust.FIELD_EXPRESSION:
            receiver = function.child_by_field_name("value")
            if receiver is not None:
                candidates.append(receiver)
        # An unknown call may transform or DECODE its inputs, so it cannot be
        # trusted to preserve a safety property a sanitiser established earlier
        # (``html_unescape(escape(u))`` is not html-safe). Drop the property for
        # the children: any taint reaching them re-taints the result for every
        # property. Raw taint still propagates as before.
        return False, [(child, None) for child in candidates]
