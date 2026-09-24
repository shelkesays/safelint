r"""Intra-procedural taint analysis for JavaScript (Node) source.

Parallel to :mod:`safelint.analysis.dataflow` (Python). The shape of the
analysis matches - parameters seed the tainted set; assignments and
``const`` / ``let`` / ``var`` declarations propagate; sanitizer calls clear
taint; source calls inject taint; sinks reaching tainted arguments produce
hits - but the per-language node-type vocabulary differs enough that
keeping a separate module is cleaner than threading ``lang_name`` through
every helper.

Design goals
------------
* Intra-procedural only - no cross-function call graph needed.
* Variable declarations (``const x = y``) and assignment expressions
  (``x = y``) both propagate taint.
* Destructuring (``const [a, b] = arr``, ``const {x, y} = obj``,
  ``const {a: alias} = obj``, ``const [a, ...rest] = arr``) taints
  every bound name when the RHS is tainted.
* Sanitizer calls clear taint; source calls inject taint.
* Template strings (``\`prefix ${expr}\```) carry taint when any
  ``${...}`` substitution is tainted.
* ``foo(...args)`` spread + container literals propagate taint
  between operands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.analysis._taint_contract import PropertyContract, combine_status, identifier_tainted, set_status, value_status
from safelint.languages import javascript as _js
from safelint.languages._node_utils import call_has_arguments, call_name, node_text, walk


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter


# Composite expressions whose taint state is the OR of their named children.
# Mirrors ``_SPREADING_TYPES`` in the Python tracker. ``await_expression``
# and ``yield_expression`` are included so awaited / yielded values
# propagate taint - e.g. ``const x = await transform(input);`` keeps
# ``x`` tainted when ``input`` is and ``transform`` is taint-preserving.
#
# TypeScript adds four compile-time-only wrappers - all zero-runtime-
# cost annotations whose runtime value is identical to the inner
# expression. Without these entries, ``eval(userInput as string)``
# would silently slip past SAFE801 because the tracker would drop
# taint on the cast.
#
#   * ``as_expression`` - ``x as Foo``
#   * ``satisfies_expression`` - ``x satisfies Foo``
#   * ``non_null_expression`` - ``x!``
#   * ``type_assertion`` - ``<Foo>x`` (older TS angle-bracket cast
#     syntax; equivalent to ``as`` but discouraged in TSX files
#     because it collides with JSX. Still legal in plain TS - taint
#     must propagate through it the same as through ``as_expression``)
_SPREADING_TYPES = frozenset(
    {
        _js.BINARY_EXPRESSION,
        _js.UNARY_EXPRESSION,
        _js.TERNARY_EXPRESSION,
        _js.UPDATE_EXPRESSION,
        _js.SEQUENCE_EXPRESSION,
        _js.PARENTHESIZED_EXPRESSION,
        _js.AWAIT_EXPRESSION,
        _js.YIELD_EXPRESSION,
        # TypeScript-only pass-through wrappers:
        _js.AS_EXPRESSION,
        _js.SATISFIES_EXPRESSION,
        _js.NON_NULL_EXPRESSION,
        _js.TYPE_ASSERTION,
    }
)

# Container / aggregate literals that carry taint when any element is tainted.
_CONTAINER_TYPES = frozenset({_js.ARRAY, _js.OBJECT, _js.PAIR, _js.SPREAD_ELEMENT})

# Member access shapes (``foo.bar`` / ``foo[idx]``) - taint flows from the
# receiver. ``optional_chain`` (``foo?.bar``) doesn't change the propagation
# direction, only the null-safety semantics - handled by SAFE803, not here.
_MEMBER_TYPES = frozenset({_js.MEMBER_EXPRESSION, _js.SUBSCRIPT_EXPRESSION})

#: Destructuring-pattern node types that bind through a *specific* field.
#: ``pair_pattern`` carries the bound alias on ``value`` (``{key: alias}``);
#: ``assignment_pattern`` carries the binding on ``left`` (``[a = 1]`` -
#: ``right`` is the default value, not a binding).
_PATTERN_BINDING_FIELD = {_js.PAIR_PATTERN: "value", _js.ASSIGNMENT_PATTERN: "left"}

#: Destructuring-pattern node types whose every named child is a binding.
_PATTERN_CONTAINER_TYPES = frozenset({_js.ARRAY_PATTERN, _js.OBJECT_PATTERN, _js.REST_PATTERN})


def _destructure_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
    """Return the binding sub-nodes of a destructuring pattern *node*.

    Containers (``array_pattern`` / ``object_pattern`` / ``rest_pattern``)
    yield every named child; field-binding patterns (``pair_pattern`` /
    ``assignment_pattern``) yield the single binding child. Anything else
    binds nothing.
    """
    if node.type in _PATTERN_CONTAINER_TYPES:
        return list(node.named_children)
    field = _PATTERN_BINDING_FIELD.get(node.type)
    if field is None:
        return []
    inner = node.child_by_field_name(field)
    return [inner] if inner is not None else []


def _assignment_sink_name(target: tree_sitter.Node) -> str | None:
    """Return the property name an assignment writes to, or None.

    ``el.innerHTML = x`` exposes it on the ``property`` field; the equivalent
    ``el["innerHTML"] = x`` puts it in the ``index`` string, whose quotes are
    stripped so both spellings resolve to the same configurable name.
    """
    if target.type == _js.MEMBER_EXPRESSION:
        prop = target.child_by_field_name("property")
        return node_text(prop) if prop is not None and prop.type == _js.PROPERTY_IDENTIFIER else None
    if target.type == _js.SUBSCRIPT_EXPRESSION:
        index = target.child_by_field_name("index")
        if index is not None and index.type == _js.STRING:
            return node_text(index).strip("\"'`")
    return None


class JsTaintTracker:
    """Track tainted variable flow through a JavaScript function body.

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
        receiver_sinks: frozenset[str] = frozenset(),
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
        self.receiver_sinks = receiver_sinks
        self.sink_hits: list[tuple[tree_sitter.Node, str, str]] = []

    def visit(self, root: tree_sitter.Node) -> None:
        """Process every node under *root* for taint propagation.

        Skips descent into nested function bodies - those are analysed
        separately by the caller for each function found, with their
        own parameter set.
        """
        for node in walk(root, skip_types=tuple(_js.FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        if node.type == _js.ASSIGNMENT_EXPRESSION:
            self._visit_assignment(node)
        elif node.type == _js.AUGMENTED_ASSIGNMENT_EXPRESSION:
            self._visit_aug_assignment(node)
        elif node.type == _js.VARIABLE_DECLARATOR:
            self._visit_var_declarator(node)
        elif node.type in (_js.CALL_EXPRESSION, _js.NEW_EXPRESSION):
            # Treat ``new Foo(tainted)`` the same as ``Foo(tainted)`` for
            # taint tracking - the default JS sinks list includes ``Function``,
            # which is canonically invoked via ``new Function(code)``.
            # ``call_name`` resolves both shapes.
            self._visit_call(node)

    def _iter_target_identifiers(self, target: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
        """Yield each bare identifier inside *target*.

        Handles JS destructuring shapes:

        * ``[a, b]``               - ``array_pattern``
        * ``{a, b}``               - ``object_pattern`` with
          ``shorthand_property_identifier_pattern`` children
        * ``{key: alias}``         - ``object_pattern`` with
          ``pair_pattern`` children (the alias is bound, not the key)
        * ``[a, ...rest]``         - ``rest_pattern`` wraps the inner name
        * ``[a = 1, b]``           - ``assignment_pattern`` wraps the
          binding name on the ``left`` field; the default value on
          ``right`` is irrelevant to which name gets bound.

        ``shorthand_property_identifier_pattern`` is treated as an
        identifier shape - it carries the bound name directly in its
        text. Subscript / member targets (``arr[0] = …``, ``obj.x = …``)
        aren't bare names and are skipped.
        """
        # Iterative DFS over the destructuring shape; bounded by its nesting.
        # Per-node child selection is delegated to ``_destructure_children`` so
        # this loop stays flat (children pushed reversed to preserve
        # left-to-right yield order).
        stack = [target]
        while len(stack) > 0:
            current = stack.pop()
            if current.type in (_js.IDENTIFIER, _js.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN):
                yield current
            else:
                stack.extend(reversed(_destructure_children(current)))

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value`` (assignment_expression)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive: valid assignments have both sides
            return
        self._check_assignment_sink(node, left, right)
        status = value_status(self._is_tainted, self._properties, right)
        for ident in self._iter_target_identifiers(left):
            self._update_name(ident, status)

    def _check_assignment_sink(self, node: tree_sitter.Node, left: tree_sitter.Node, right: tree_sitter.Node) -> None:
        """Record a hit when a tainted value is WRITTEN to a sink-named property.

        Some JavaScript sinks are assigned to rather than called - ``innerHTML``
        is the canonical one, and it ships in the default ``sinks_javascript``.
        The call-based hit recorder never saw ``element.innerHTML = tainted``,
        so the shipped default could only ever fire on an ``innerHTML(...)``
        call, a shape that does not occur in real code. Writing to the property
        IS the injection, so the assignment target is checked against the same
        sink list, honouring the same property-typed contract as a call.
        """
        sink = _assignment_sink_name(left)
        if sink is None or sink not in self.sinks:
            return
        if self._is_tainted(right, self.contract.required_for(sink)):
            self._record_sink_hit(node, right, sink)

    def _visit_aug_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x += value``."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is not None and right is not None:
            # ``el.innerHTML += tainted`` appends attacker data to the sink just
            # as surely as a plain assignment does.
            self._check_assignment_sink(node, left, right)
        if left is None or right is None:  # pragma: no cover - defensive: valid aug-assignments have both sides
            return
        self._update_name(left, value_status(self._is_tainted, self._properties, right), keep_existing=True)

    def _visit_var_declarator(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``const x = value`` / ``let`` / ``var``.

        ``variable_declarator`` is the per-binding node inside a
        ``lexical_declaration`` (``const`` / ``let``) or
        ``variable_declaration`` (``var``). Field names are ``name``
        (the LHS) and ``value`` (the RHS).
        """
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name is None or value is None:
            return
        status = value_status(self._is_tainted, self._properties, value)
        for ident in self._iter_target_identifiers(name):
            self._update_name(ident, status)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink via a tainted argument or method receiver."""
        name = call_name(node)
        if name not in self.sinks:
            return
        required = self.contract.required_for(name)
        if self._record_arg_hits(node, name, required):
            return  # a tainted argument already reached the sink; receiver is redundant
        # Else, a sink method on a tainted receiver (``req.exec()`` / ``new
        # req.Sink()``). Fires ONLY when the call has no arguments: an
        # argument-consuming sink's payload is its argument, so a tainted receiver
        # passed only constant arguments (``conn.query("SELECT 1")``) is not injection.
        receiver = self._method_receiver(node)
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
        arg_name = node_text(arg_node) if arg_node.type == _js.IDENTIFIER else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))  # pragma: no branch

    def _update_name(self, target: tree_sitter.Node, status: frozenset[str] | None, *, keep_existing: bool = False) -> None:
        """Record taint *status* for *target* if it carries a bare name (``None`` clears)."""
        if target.type not in (_js.IDENTIFIER, _js.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN):
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

        Calls and template strings return children rather than re-entering
        :meth:`_is_tainted`, so the whole check stays a single worklist.
        """
        node_type = node.type
        if node_type == _js.IDENTIFIER:
            return identifier_tainted(self.tainted, node_text(node), required_property), []
        if node_type in (_js.CALL_EXPRESSION, _js.NEW_EXPRESSION):
            return self._classify_call(node, required_property)
        if node_type == _js.TEMPLATE_STRING:
            return False, [(child, required_property) for child in self._template_children(node)]
        return False, [(child, required_property) for child in self._taint_propagating_children(node)]

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*.

        Member access propagates its ``object`` receiver; spreading
        expressions and containers propagate every named child. Everything
        else is a taint dead-end.
        """
        if node.type in _MEMBER_TYPES:
            obj = node.child_by_field_name("object")
            return [obj] if obj is not None else []
        if node.type in _SPREADING_TYPES or node.type in _CONTAINER_TYPES:
            return list(node.named_children)
        return []

    def _classify_call(self, node: tree_sitter.Node, required_property: str | None) -> tuple[bool, list[tuple[tree_sitter.Node, str | None]]]:
        """Classify a call for the worklist: ``(is_tainted_here, children_to_examine)``.

        A sanitiser that clears *required_property* short-circuits to
        ``(False, [])``; a source is ``(True, [])``. An unknown call under
        ``assume_taint_preserving`` returns ``(False, <arg / receiver nodes>)`` so
        the worklist drains them (``req.query.get("q")`` / ``tainted.trim()`` stay
        tainted via the receiver). The sanitiser check runs first, so
        ``escape(req.data)`` still clears (for the property escape covers).
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
        receiver = self._method_receiver(node)
        if receiver is not None:
            candidates.append(receiver)
        # An unknown call may transform or DECODE its inputs, so it cannot be
        # trusted to preserve a safety property a sanitiser established earlier
        # (``html_unescape(escape(u))`` is not html-safe). Drop the property for
        # the children: any taint reaching them re-taints the result for every
        # property. Raw taint still propagates as before.
        return False, [(child, None) for child in candidates]

    @staticmethod
    def _method_receiver(node: tree_sitter.Node) -> tree_sitter.Node | None:
        """Return the receiver object of a method call / member construction, or None.

        Covers both ``call_expression`` (callee on the ``function`` field) and
        ``new_expression`` (callee on the ``constructor`` field), so
        ``req.query.get("q")`` and ``new req.Factory()`` both expose ``req``.
        """
        callee = node.child_by_field_name("function") or node.child_by_field_name("constructor")
        if callee is None or callee.type != _js.MEMBER_EXPRESSION:
            return None
        return callee.child_by_field_name("object")

    @staticmethod
    def _template_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the ``${expr}`` substitutions of *this* template string only.

        ``skip_types`` prunes nested template strings: an inner template is
        returned as a child (the worklist pops it and enumerates its own
        substitutions next) rather than having them re-collected here. Without
        the prune each nesting level re-enumerated every deeper level, so N
        nested templates cost 2**N node visits on the exhaustive (untainted)
        path. Same fix as the Python tracker's ``_fstring_children``.
        """
        return [inner for child in walk(node, skip_types=(_js.TEMPLATE_STRING,)) if child.type == _js.TEMPLATE_SUBSTITUTION for inner in child.named_children]
