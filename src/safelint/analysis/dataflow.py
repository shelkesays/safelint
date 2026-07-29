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

from safelint.languages import python as _py
from safelint.languages._node_utils import call_name, node_text, walk


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

_CONTAINER_TYPES = frozenset({_py.LIST, _py.TUPLE, _py.SET})

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
        """
        self.tainted: set[str] = set(params)
        self.sinks = sinks
        self.sanitizers = sanitizers
        self.sources = sources
        self.assume_taint_preserving = assume_taint_preserving
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
            elif node.type == _py.ANNOTATED_ASSIGNMENT:
                self._visit_ann_assignment(node)
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
        is_tainted = self._is_tainted(cursor)
        for target in targets:
            for ident in self._iter_target_identifiers(target):
                self._update_name(ident, is_tainted=is_tainted)

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
        """Check whether this call reaches a sink via a tainted argument or method receiver."""
        name = call_name(node)
        if name not in self.sinks:
            return
        if self._record_arg_hits(node, name):
            return  # a tainted argument already reached the sink; receiver is redundant
        # Else, a sink method on a tainted receiver (``request.execute()``) - the
        # receiver is itself a tainted value reaching the sink with no arguments.
        function = node.child_by_field_name("function")
        if function is not None and function.type == _py.ATTRIBUTE:
            receiver = function.child_by_field_name("object")
            if receiver is not None and self._is_tainted(receiver):
                self._record_sink_hit(node, receiver, name)

    def _record_arg_hits(self, node: tree_sitter.Node, name: str) -> bool:
        """Record one sink hit per tainted positional argument; return True if any fired."""
        args_node = node.child_by_field_name("arguments")
        if args_node is None:
            return False
        fired = False
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(node, arg, name)
                fired = True
        return fired

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == _py.IDENTIFIER else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, *, is_tainted: bool) -> None:
        """Add or remove *target* from the tainted set if it is a bare identifier."""
        if target.type != _py.IDENTIFIER:
            return
        name = node_text(target)
        if is_tainted:
            self.tainted.add(name)
        else:
            self.tainted.discard(name)

    def _is_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* may carry tainted data.

        Iterative worklist with OR semantics: taint propagates up from any
        tainted leaf, so the first tainted node short-circuits to ``True``.
        Per-node classification is split into :meth:`_node_directly_tainted`
        (leaf check) and :meth:`_taint_propagating_children` (which children to
        enqueue). Depth is bounded by the expression's nesting.
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
        if node_type == _py.IDENTIFIER:
            return node_text(node) in self.tainted
        if node_type == _py.CALL:
            return self._call_tainted(node)
        if node_type == _py.STRING:
            return self._fstring_tainted(node)
        return False

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
        # Local, single-use lookup for the one-field-child shapes above.
        single_field_child = {
            _py.ATTRIBUTE: "object",
            _py.SUBSCRIPT: "value",
            "keyword_argument": "value",
        }
        node_type = node.type
        field = single_field_child.get(node_type)
        if field is not None:
            child = node.child_by_field_name(field)
            return [child] if child is not None else []
        if node_type in _SPLAT_TYPES or node_type == _py.CONCATENATED_STRING or node_type in _CONTAINER_TYPES or node_type in _SPREADING_TYPES:
            return list(node.named_children)
        return []

    def _call_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if this call produces a tainted value.

        Unknown calls (neither sanitizer nor source) consult
        ``assume_taint_preserving``: when True, the call's result is
        tainted iff any argument **or the method receiver** is tainted;
        when False, the result is always clean. Reading the receiver is
        what makes ``request.GET.get("q")`` / ``tainted.strip()`` stay
        tainted - those return a value derived from the receiver but take
        no tainted positional args, so a positional-only check would miss
        them. Mirrors the Java / Rust / Go / PHP trackers. The sanitizer
        check runs first, so ``escape(request.data)`` still clears.
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
        # Method-call shape: ``call.function`` is an ``attribute`` whose
        # ``object`` is the receiver. Plain calls (``foo(x)``) have an
        # ``identifier`` function and no receiver to read.
        function = node.child_by_field_name("function")
        if function is not None and function.type == _py.ATTRIBUTE:
            receiver = function.child_by_field_name("object")
            if receiver is not None:
                candidates.append(receiver)
        return any(self._is_tainted(c) for c in candidates)

    def _fstring_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if any interpolated expression in an f-string is tainted."""
        return any(self._is_tainted(inner) for child in walk(node) if child.type == _py.INTERPOLATION for inner in child.named_children)
