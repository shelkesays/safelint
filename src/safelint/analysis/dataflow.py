"""Intra-procedural taint analysis using Tree-sitter.

The :class:`TaintTracker` walks a single function body and tracks which
variables carry data derived from tainted sources (function parameters,
configurable I/O calls). When a tainted value reaches a configurable
dangerous sink the hit is recorded in :attr:`TaintTracker.sink_hits`.

Design goals
------------
* Intra-procedural only - no cross-function call graph needed.
* Assignment propagation: ``x = tainted_y`` makes ``x`` tainted.
* Sanitizer calls clear taint: ``x = escape(tainted_y)`` → ``x`` clean.
* Source calls inject taint: ``x = input()`` → ``x`` tainted.
* f-strings, containers, and arithmetic operators spread taint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.analysis._taint_contract import PropertyContract, combine_status, identifier_tainted, set_status, value_status
from safelint.languages import python as _py
from safelint.languages._node_utils import call_has_arguments, call_name, node_text, walk


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter


_SPREADING_TYPES = frozenset(
    {
        _py.BINARY_OPERATOR,
        _py.BOOLEAN_OPERATOR,
        _py.UNARY_OPERATOR,
        _py.COMPARISON_OPERATOR,
        _py.CONDITIONAL_EXPRESSION,
    }
)

# Aggregate literals that carry taint when any element is tainted.
# ``expression_list`` is the *unparenthesised* tuple on the RHS of a
# destructuring assignment (``x, y = user_input, "k"`` parses its RHS as
# ``expression_list``, not ``tuple``). Without it that RHS reduced to
# "no propagating children" and both targets read clean - a false negative
# on the very common ``value, err = tainted, None`` shape. Like every other
# container here the whole RHS status is applied to every target, which
# over-approximates (``y`` is marked tainted too) in the conservative
# direction.
_CONTAINER_TYPES = frozenset({_py.LIST, _py.TUPLE, _py.SET, _py.EXPRESSION_LIST})

# Splat operators in call argument lists - ``foo(*args, **kwargs)``.
# Tree-sitter parses these as single-child wrapper nodes whose only
# named child is the operand.
_SPLAT_TYPES = frozenset({"list_splat", "dictionary_splat"})

# Destructure shapes recognised on the LHS of an assignment.
_PATTERN_TYPES = frozenset({_py.PATTERN_LIST, _py.TUPLE_PATTERN, _py.LIST_PATTERN, _py.LIST_SPLAT_PATTERN})


class TaintTracker:
    """Track tainted variable flow through a function body.

    Instantiate with the set of already-tainted parameter names, the sets of
    sink / sanitizer / source call names, then call ``visit(func_node)``.
    Results are in :attr:`sink_hits` as ``(call_node, var_name, sink_name)``
    triples - the call node is preserved (rather than just its line) so
    callers can position violations precisely with column ranges.
    """

    def __init__(
        self,
        params: set[str],
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
        *,
        assume_taint_preserving: bool = True,
        receiver_sinks: frozenset[str] = frozenset(),
        property_contract: PropertyContract | None = None,
    ) -> None:
        """Initialise tracker with tainted entry parameters and rule config.

        *assume_taint_preserving* controls how unknown function calls
        (i.e. calls whose name is in neither ``sources`` nor
        ``sanitizers``) propagate taint. The flag-name is literal:
        ``True`` is the more *conservative* posture (assume taint is
        preserved through unknown calls); ``False`` is the *less
        conservative* / weaker-detection posture (drop taint at every
        unknown call). See docs/configuration/rules.md for the full trade-off
        discussion.

        * ``True`` (default) - conservative / taint-preserving.
          Unknown calls propagate taint from any tainted argument:
          ``f(tainted)`` is treated as tainted. Matches the historical
          safelint behaviour and minimises false negatives at the cost
          of potential false positives in codebases with many
          "obviously safe" wrappers.
        * ``False`` - less conservative / taint-dropping. Unknown
          calls drop taint: ``f(tainted)`` is treated as clean. Fewer
          false positives but new false negatives where helper
          functions actually do flow tainted data through to a sink.
          Set this when your codebase uses many internal wrappers and
          you'd rather miss a taint flow than report a false positive.

        *property_contract* carries the opt-in property-typed sanitiser
        contract (:class:`PropertyContract`): a sanitiser establishes named
        safety properties (e.g. ``escape -> {html_escaped}``) and a sink
        requires one (e.g. ``execute -> sql_escaped``). A property-typed
        sanitiser clears a sink only when it establishes that sink's required
        property; the flat *sanitizers* list stays universal (clears every
        sink) for backward compatibility, and a sink with no declared property
        is cleared only by that flat list, never by a property-typed sanitiser.
        Defaults to an empty contract (inert).
        """
        self.contract = property_contract if property_contract is not None else PropertyContract()
        # ``tainted`` maps a tainted variable to the set of safety properties it is
        # already safe for (cleared by a property-typed sanitiser on its path);
        # absence = clean. Entry parameters are raw taint (nothing cleared).
        self.tainted: dict[str, frozenset[str]] = {p: frozenset() for p in params}
        self._properties = self.contract.all_properties()
        self.sinks = sinks
        self.sanitizers = sanitizers
        self.sources = sources
        self.assume_taint_preserving = assume_taint_preserving
        self.receiver_sinks = receiver_sinks
        self.sink_hits: list[tuple[tree_sitter.Node, str, str]] = []

    def visit(self, root: tree_sitter.Node) -> None:
        """Process every node under *root* for taint propagation.

        Skips descent into nested ``def`` / ``async def`` bodies - those are
        analysed separately by the caller for each function found, with their
        own parameter set. Without this guard, an inner function's body would
        be treated as part of the outer function's flow, leaking taint between
        scopes that don't actually share variables.
        """
        for node in walk(root, skip_types=(_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF)):
            if node.type == _py.ASSIGNMENT:
                self._visit_assignment(node)
            elif node.type == _py.AUGMENTED_ASSIGNMENT:
                self._visit_aug_assignment(node)
            elif node.type == _py.CALL:
                self._visit_call(node)

    def _iter_target_identifiers(self, target: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
        """Yield each bare identifier inside *target*.

        Handles destructuring: ``a, b = …``, ``(a, b) = …``, ``[a, b] = …``,
        and starred targets like ``a, *rest = …``. Subscript / attribute
        targets (``a[0] = …``, ``obj.x = …``) are not bare names and are
        skipped - TaintTracker only tracks identifiers.
        """
        # Iterative DFS over the destructuring shape; children are pushed
        # reversed so identifiers yield left-to-right. Depth is bounded by the
        # nesting of the destructuring target.
        stack = [target]
        while len(stack) > 0:
            current = stack.pop()
            if current.type == _py.IDENTIFIER:
                yield current
            elif current.type in _PATTERN_TYPES:
                stack.extend(reversed(current.named_children))

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value``, including destructuring and chains.

        Chained assignments (``a = b = value``) parse as nested ``assignment``
        nodes - we follow the chain to find the innermost real RHS, then mark
        every LHS target with the same taint state. Destructuring on any of
        those LHS targets is expanded via ``_iter_target_identifiers``.
        """
        targets: list[tree_sitter.Node] = []
        cursor = node
        # Bounded by the depth of nested ``assignment`` nodes in the parse
        # tree - finite by source structure, not by runtime data.
        while cursor is not None:
            if cursor.type != _py.ASSIGNMENT:
                break
            left = cursor.child_by_field_name("left")
            if left is not None:
                targets.append(left)
            cursor = cursor.child_by_field_name("right")
        if cursor is None or not targets:
            return
        status = value_status(self._is_tainted, self._properties, cursor)
        for target in targets:
            for ident in self._iter_target_identifiers(target):
                set_status(self.tainted, node_text(ident), status)

    def _visit_aug_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x += value`` (read-modify-write preserves x's taint)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or left.type != _py.IDENTIFIER:
            return
        combined = combine_status(self.tainted.get(node_text(left)), value_status(self._is_tainted, self._properties, right))
        set_status(self.tainted, node_text(left), combined)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink via a tainted argument or method receiver."""
        name = call_name(node)
        if name not in self.sinks:
            return
        required = self.contract.required_for(name)
        if self._record_arg_hits(node, name, required):
            return  # a tainted argument already reached the sink; receiver is redundant
        # Sink method on a tainted receiver (``request.execute()``) - the receiver
        # is itself a tainted value reaching the sink. Fires ONLY when the call has
        # no arguments: an argument-consuming sink's payload is its argument, so a
        # tainted receiver passed only constant arguments (``conn.execute("SELECT
        # 1")`` where ``conn`` is a tainted connection) is not injection.
        function = node.child_by_field_name("function")
        if function is not None and function.type == _py.ATTRIBUTE:
            receiver = function.child_by_field_name("object")
            if receiver is not None and self._is_tainted(receiver, required) and (name in self.receiver_sinks or not call_has_arguments(node)):
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

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == _py.IDENTIFIER else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _is_tainted(self, node: tree_sitter.Node, required_property: str | None = None) -> bool:
        """Return True if *node* may carry data still tainted for *required_property*.

        Single iterative worklist (no recursion): each node is reduced by
        :meth:`_taint_step` to ``(is_tainted_here, children_to_examine)``; the
        first tainted node short-circuits to ``True``. *required_property* is the
        safety property the target sink requires (``None`` when the sink declares
        none); it decides whether a property-typed sanitiser on the path clears.
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

        A tainted identifier terminates; a call is classified by
        :meth:`_classify_call`; an f-string yields its interpolated expressions as
        children; everything else yields its taint-propagating children. Calls and
        f-strings return children rather than re-entering :meth:`_is_tainted`, so
        the whole check stays a single worklist (no mutual recursion).
        """
        node_type = node.type
        if node_type == _py.IDENTIFIER:
            return identifier_tainted(self.tainted, node_text(node), required_property), []
        if node_type == _py.CALL:
            return self._classify_call(node, required_property)
        if node_type == _py.STRING:
            return False, [(child, required_property) for child in self._fstring_children(node)]
        return False, [(child, required_property) for child in self._taint_propagating_children(node)]

    @staticmethod
    def _fstring_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the interpolated expression nodes of *this* f-string only.

        ``skip_types`` prunes nested f-strings: an inner ``string`` is returned
        as a child (so the worklist pops it and enumerates its own
        interpolations next) rather than having its interpolations re-collected
        here. Without the prune each nesting level re-enumerated every deeper
        level, so a chain of N nested f-strings cost 2**N node visits on the
        exhaustive (untainted) path - measurably 1.3s at N=20.
        """
        return [inner for child in walk(node, skip_types=(_py.STRING,)) if child.type == _py.INTERPOLATION for inner in child.named_children]

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*.

        ``attribute`` (``obj.attr``), ``subscript`` (``obj[k]``), and
        ``keyword_argument`` (``foo(name=expr)``) each propagate exactly one
        field-named child - the receiver / base / value - so ``request.data``
        and ``request.GET["q"]`` stay tainted while the attribute-name and
        subscript-index (name lookups, not data) are ignored. Splats, f-string
        concat, containers, and spreading expressions propagate every named
        child. Everything else is a taint dead-end.
        """
        node_type = node.type
        # Plain if-branches (no per-call dict) to match the other trackers and
        # stay allocation-free in this worklist hot path: ``obj.attr`` propagates
        # its ``object``; ``obj[k]`` and ``foo(name=expr)`` propagate their
        # ``value`` (base array / keyword value).
        if node_type == _py.ATTRIBUTE:
            obj = node.child_by_field_name("object")
            return [obj] if obj is not None else []
        if node_type in (_py.SUBSCRIPT, _py.KEYWORD_ARGUMENT):
            value = node.child_by_field_name("value")
            return [value] if value is not None else []
        if node_type in _SPLAT_TYPES or node_type == _py.CONCATENATED_STRING or node_type in _CONTAINER_TYPES or node_type in _SPREADING_TYPES:
            return list(node.named_children)
        return []

    def _classify_call(self, node: tree_sitter.Node, required_property: str | None) -> tuple[bool, list[tuple[tree_sitter.Node, str | None]]]:
        """Classify a call for the worklist: ``(is_tainted_here, children_to_examine)``.

        A sanitiser that clears *required_property* short-circuits to
        ``(False, [])`` (its arguments are not followed); a source is
        ``(True, [])``. An unknown call under ``assume_taint_preserving`` returns
        ``(False, <arg / receiver nodes>)`` so the worklist drains them - taint
        flows through iff a child is tainted, realised without re-entering
        :meth:`_is_tainted`. The sanitiser check runs first, so
        ``escape(request.data)`` still clears (for the property escape covers).
        """
        name = call_name(node)
        # Flat ``sanitizers`` are universal (historical behaviour); the contract
        # adds property-typed sanitisers that clear only their sink's property.
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
        # Method-call shape: ``call.function`` is an ``attribute`` whose
        # ``object`` is the receiver. Plain calls (``foo(x)``) have an
        # ``identifier`` function and no receiver to read.
        function = node.child_by_field_name("function")
        if function is not None and function.type == _py.ATTRIBUTE:
            receiver = function.child_by_field_name("object")
            if receiver is not None:
                candidates.append(receiver)
        # An unknown call may transform or DECODE its inputs, so it cannot be
        # trusted to preserve a safety property a sanitiser established earlier
        # (``html_unescape(escape(u))`` is not html-safe). Drop the property for
        # the children: any taint reaching them re-taints the result for every
        # property. Raw taint still propagates as before.
        return False, [(child, None) for child in candidates]
