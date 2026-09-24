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

from safelint.analysis._taint_contract import PropertyContract, assignment_sink_name, combine_status, identifier_tainted, set_status, value_status
from safelint.languages import c as _c
from safelint.languages import cpp as _cpp
from safelint.languages._node_utils import call_has_arguments, call_name, node_text, walk


if TYPE_CHECKING:
    import tree_sitter


# Expressions whose taint state is the OR of their named children.
_SPREADING_TYPES = frozenset(
    {
        _c.BINARY_EXPRESSION,
        _c.UNARY_EXPRESSION,
        _c.PARENTHESIZED_EXPRESSION,
        _c.POINTER_EXPRESSION,  # ``*p`` / ``&p``
        _c.COMMA_EXPRESSION,
        _c.CONDITIONAL_EXPRESSION,  # ``cond ? tainted : clean`` - either branch taints
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


#: Node kinds the declarator descent can step into: the name itself, or a
#: wrapper that nests another declarator inside it. Used only for
#: ``reference_declarator``, which carries no ``declarator`` field to follow.
_DESCENDABLE_DECLARATORS = frozenset(
    {
        _c.IDENTIFIER,
        _c.POINTER_DECLARATOR,
        _c.ARRAY_DECLARATOR,
        _c.FUNCTION_DECLARATOR,
        _c.PARENTHESIZED_DECLARATOR,
        _cpp.REFERENCE_DECLARATOR,
        _cpp.QUALIFIED_IDENTIFIER,
        _cpp.FIELD_IDENTIFIER,
    }
)


def _declarator_identifier(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Return the name ``identifier`` from a declarator, unwrapping pointer / array layers.

    Bounded iterative descent of the ``declarator`` field (never recursion -
    SAFE105 polices this codebase).
    """
    cur = node
    for _ in range(16):
        if cur is None:  # pragma: no cover - defensive: declarator chains always bottom out in an identifier
            return None
        if cur.type == _c.IDENTIFIER:
            return cur
        nxt = cur.child_by_field_name("declarator")
        if nxt is None and cur.type == _cpp.REFERENCE_DECLARATOR:
            # C++ ``T& r`` / ``T&& r``: tree-sitter-cpp gives
            # ``reference_declarator`` NO ``declarator`` field - the name is a
            # plain named child. Without this the descent bottomed out at None
            # and ``const std::string& r = tainted;`` bound no name at all, so
            # the reference silently read clean at every later sink.
            #
            # Pick the first child that can actually continue the descent
            # rather than child 0 blindly: every shape observed today puts the
            # identifier first, but an attribute or type child appearing ahead
            # of it would otherwise end the walk on a node with no name.
            nxt = next((child for child in cur.named_children if child.type in _DESCENDABLE_DECLARATORS), None)
        cur = nxt
    return None  # pragma: no cover - defensive: 16-deep declarator nesting does not occur


#: Assignment-target node types whose property name can name a sink, mapped to
#: the field holding that name.
_ASSIGNMENT_SINK_FIELDS: dict[str, str] = {_c.FIELD_EXPRESSION: "field"}


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
        receiver_sinks: frozenset[str] = frozenset(),
        property_contract: PropertyContract | None = None,
    ) -> None:
        """Initialise tracker with tainted entry parameters and rule config.

        This base class is the **C** tracker: method-receiver taint is off (in C,
        ``req->callback()`` invokes a function pointer whose result need not derive
        from the struct, so treating the receiver as a taint input is a false
        positive). :class:`CppTaintTracker` overrides :meth:`_cpp_method_receiver`
        to enable receiver taint for C++.
        """
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
        """Process every node under *root* for taint propagation (nested functions skipped)."""
        for node in walk(root, skip_types=tuple(_c.FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        node_type = node.type
        if node_type == _c.INIT_DECLARATOR:
            self._visit_init_declarator(node)
        elif node_type == _c.ASSIGNMENT_EXPRESSION:
            self._check_assignment_sink(node)
            self._visit_assignment(node)
        elif node_type == _c.CALL_EXPRESSION:
            self._visit_call(node)

    def _visit_init_declarator(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``T x = value;`` (declarator name <- value taint)."""
        value = node.child_by_field_name("value")
        if value is None:  # pragma: no cover - defensive: an init_declarator always has a value field
            return
        name_node = _declarator_identifier(node.child_by_field_name("declarator"))
        if name_node is not None:
            self._update_name(name_node, value_status(self._is_tainted, self._properties, value))

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value`` / ``x += value`` (compound keeps prior taint)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or left.type != _c.IDENTIFIER:
            return
        operator = node.child_by_field_name("operator")
        keep_existing = operator is not None and node_text(operator) != "="
        self._update_name(left, value_status(self._is_tainted, self._properties, right), keep_existing=keep_existing)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink via a tainted argument or (C++) receiver."""
        name = call_name(node)
        if name not in self.sinks:
            return
        required = self.contract.required_for(name)
        if self._record_arg_hits(node, name, required):
            return  # a tainted argument already reached the sink; receiver is redundant
        # Else, a sink C++ method on a tainted receiver (``req->execute()``); None
        # in C. Fires ONLY when the call has no arguments: an argument-consuming
        # sink's payload is its argument, so a tainted receiver passed only constant
        # arguments (``req->execute("SELECT 1")``) is not injection.
        receiver = self._cpp_method_receiver(node)
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

    def _check_assignment_sink(self, node: tree_sitter.Node) -> None:
        """Record a hit when a tainted value is WRITTEN to a sink-named property.

        Writing the property is the injection, so the assignment target is
        matched against the same sink list as a callee, honouring the same
        sanitiser and property-typed contract. Non-sink targets are ignored, so
        ordinary property writes are unaffected.
        """
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:
            return
        for target in self._sink_assignment_targets(left):
            sink = assignment_sink_name(target, _ASSIGNMENT_SINK_FIELDS)
            if sink is not None and sink in self.sinks and self._is_tainted(right, self.contract.required_for(sink)):
                self._record_sink_hit(node, right, sink)

    @staticmethod
    def _sink_assignment_targets(left: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the assignment targets to test against the sink list."""
        return [left]

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == _c.IDENTIFIER else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, status: frozenset[str] | None, *, keep_existing: bool = False) -> None:
        """Record taint *status* for identifier *target* (``None`` clears).

        No ``_`` blank-identifier skip: unlike Go / Python, C has no blank
        identifier, so a variable legitimately named ``_`` is tracked normally.
        With *keep_existing* (a compound read-modify-write assignment) the prior
        taint is OR-combined with *status* rather than overwritten.
        """
        if target.type != _c.IDENTIFIER:  # pragma: no cover - callers pre-filter to identifier nodes
            return
        name = node_text(target)
        if keep_existing:
            status = combine_status(self.tainted.get(name), status)
        set_status(self.tainted, name, status)

    def _is_tainted(self, node: tree_sitter.Node, required_property: str | None = None) -> bool:
        """Return True if *node* may carry data still tainted for *required_property*.

        Fully iterative (no recursion - the analysis-module guideline): each
        worklist node is reduced by ``_taint_step`` to ``(tainted_here, children
        to examine)``. A sanitizer call clears (no children); a source call
        taints; an unknown call under ``assume_taint_preserving`` taints iff one
        of its arguments is tainted, so those arguments stay on the worklist.
        *required_property* is the property the target sink requires (``None`` when
        it declares none) and decides whether a property-typed sanitiser clears.
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
        """Reduce one worklist node to ``(is_tainted_here, children_to_examine)``."""
        node_type = node.type
        if node_type == _c.IDENTIFIER:
            return identifier_tainted(self.tainted, node_text(node), required_property), []
        if node_type == _c.CALL_EXPRESSION:
            return self._classify_call(node, required_property)
        return False, [(child, required_property) for child in self._taint_propagating_children(node)]

    def _classify_call(self, node: tree_sitter.Node, required_property: str | None) -> tuple[bool, list[tuple[tree_sitter.Node, str | None]]]:
        """Classify a call: ``(is_source, args_to_descend_into)``.

        A sanitizer that clears *required_property* -> ``(False, [])`` (its
        arguments are not followed). A source taints -> ``(True, [])``; the
        sanitiser check runs first. An unknown call propagates only under
        ``assume_taint_preserving``, in which case its argument nodes - plus the
        method receiver for a C++ member call - are returned for the worklist to
        examine; otherwise it clears.
        """
        name = call_name(node)
        if name in self.sanitizers or self.contract.clears(name, required_property):
            return False, []
        if name in self.sources:
            return True, []
        if not self.assume_taint_preserving:
            return False, []
        args_node = node.child_by_field_name("arguments")
        candidates: list[tree_sitter.Node] = list(args_node.named_children) if args_node is not None else []
        receiver = self._cpp_method_receiver(node)
        if receiver is not None:
            candidates.append(receiver)
        # An unknown call may transform or DECODE its inputs, so it cannot be
        # trusted to preserve a safety property a sanitiser established earlier
        # (``html_unescape(escape(u))`` is not html-safe). Drop the property for
        # the children: any taint reaching them re-taints the result for every
        # property. Raw taint still propagates as before.
        return False, [(child, None) for child in candidates]

    def _cpp_method_receiver(self, node: tree_sitter.Node) -> tree_sitter.Node | None:  # noqa: ARG002 - overridden by CppTaintTracker
        """Return the method-call receiver, or None. C has none (see class docstring)."""
        return None

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*."""
        node_type = node.type
        if node_type == _c.SUBSCRIPT_EXPRESSION:
            argument = node.child_by_field_name("argument")
            return [argument] if argument is not None else []
        if node_type == _c.FIELD_EXPRESSION:
            argument = node.child_by_field_name("argument")
            return [argument] if argument is not None else []
        if node_type == _c.CAST_EXPRESSION:
            # ``(T)expr`` - propagate the operand, never the type_descriptor.
            return [c for c in node.named_children if c.type != _c.TYPE_DESCRIPTOR]
        if node_type == _c.ASSIGNMENT_EXPRESSION:
            # An inline ``(x = rhs)`` carries its RHS's value into the sink.
            return _assignment_propagating_children(node)
        if node_type in _SPREADING_TYPES:
            return list(node.named_children)
        return []


class CppTaintTracker(CTaintTracker):
    """C++ variant of :class:`CTaintTracker` with method-receiver taint enabled.

    tree-sitter-cpp shares C's ``call_expression`` shapes, so the whole tracker is
    inherited; only the method-call receiver differs. A C++ member call
    ``obj.method()`` / ``ptr->method()`` is a ``field_expression`` whose
    ``argument`` is the receiver, so ``req.body()`` / ``req->param("q")`` stay
    tainted. In C the same shape is a function-POINTER call (``req->callback()``)
    whose result need not derive from the struct, which is why the C base returns
    no receiver.
    """

    def _cpp_method_receiver(self, node: tree_sitter.Node) -> tree_sitter.Node | None:
        function = node.child_by_field_name("function")
        if function is None or function.type != _c.FIELD_EXPRESSION:
            return None
        return function.child_by_field_name("argument")
