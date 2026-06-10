"""Intra-procedural taint analysis for Java source.

Parallel to :mod:`safelint.analysis.dataflow_javascript` (JS / TS) and
:mod:`safelint.analysis.dataflow` (Python). The analysis shape matches
both - parameters seed the tainted set; assignments and local-variable
declarations propagate; sanitizer calls clear taint; source calls
inject taint; sinks reaching tainted arguments produce hits - but
Java's node-type vocabulary differs enough that keeping a dedicated
module is cleaner than threading ``lang_name`` through every helper.

Design goals
------------
* Intra-procedural only - no cross-function call graph needed.
* Variable declarations (``Foo x = y;``) and assignment expressions
  (``x = y``) both propagate taint.
* Method-call return values can be tainted: sources inject taint;
  sanitizers clear it; unknown calls preserve or drop based on the
  ``assume_taint_preserving`` knob (same posture as Python / JS).
* Cast expressions (``(Foo) x``) and parenthesised expressions are
  pass-throughs - taint flows through them unchanged.
* String concatenation propagates taint (Java ``+`` on Strings is a
  ``binary_expression`` whose taint state is the OR of its operands).
* Java 21+ string templates: tree-sitter-java does not yet expose
  the template-substitution shape uniformly, so the tracker treats
  every ``string_literal`` as untainted regardless of nested
  template markers. Conservative: a future grammar upgrade can lift
  this without re-architecting the rule.
* Constructor calls (``new Foo(x)``) participate in the sink check
  the same way method invocations do - ``ProcessBuilder`` is a
  common Java sink that's only ever invoked via ``new``.

Java does *not* have JS-style destructuring assignment, so the
``_iter_target_identifiers`` shape is much simpler than the JS
tracker - Java assignment LHS is always either a bare identifier,
a field access, or an array access; only the identifier case binds
a name into the tainted set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES


if TYPE_CHECKING:
    import tree_sitter


# Composite expressions whose taint state is the OR of their named children.
# Mirrors ``_SPREADING_TYPES`` in the Python / JS trackers.
#
# ``binary_expression``: covers Java string concatenation via ``+`` -
# ``"hello " + tainted`` keeps the result tainted. Numeric ``+`` /
# ``-`` / etc. also pass taint through, which is the conservative
# choice (untainted numeric operands don't generate spurious hits).
#
# ``cast_expression`` (``(Foo) x``) is a zero-runtime-cost pass-through -
# the cast doesn't sanitise anything, so taint must flow. Without this
# entry, ``Runtime.exec((String) userInput)`` would silently drop the
# taint marker before hitting the sink.
#
# ``parenthesized_expression`` is the formatting wrapper; same
# rationale as JS - peel through redundant parens without losing
# taint state.
#
# ``ternary_expression`` (Java's ``? :``) takes taint from either
# branch. ``unary_expression`` (``-x``, ``!flag``) and
# ``update_expression`` (``++i``, ``i--``) propagate from their
# single operand.
_SPREADING_TYPES = frozenset(
    {
        "binary_expression",
        "unary_expression",
        "ternary_expression",
        "update_expression",
        "parenthesized_expression",
        "cast_expression",
        "instanceof_expression",  # pattern variables introduced by ``x instanceof Foo f`` are unhandled today; the expression itself is boolean
    }
)

# Container / aggregate literals that carry taint when any element is tainted.
# Java's analogue of JS's ``array``: an inline array creation. Other
# aggregate literals (``Map.of(...)``, ``List.of(...)``) are method
# invocations, handled by the call-tainted path.
_CONTAINER_TYPES = frozenset(
    {
        "array_creation_expression",
        "array_initializer",
    }
)

# Member access shapes - taint flows from the receiver. Java splits
# what JS calls ``member_expression`` / ``subscript_expression`` into
# ``field_access`` (``obj.foo``) and ``array_access`` (``arr[i]``).
_MEMBER_TYPES = frozenset({"field_access", "array_access"})

# Call shapes - Java's two flavours. Both feed the sink check and
# taint propagation; ``call_name`` already normalises both
# (returning ``"foo"`` for both ``foo(...)`` / ``obj.foo(...)`` and
# ``new Foo(...)``).
_CALL_TYPES = frozenset({"method_invocation", "object_creation_expression"})


def _is_compound_assignment(node: tree_sitter.Node) -> bool:
    """Return True if *node* is an ``assignment_expression`` with a compound operator.

    tree-sitter-java emits the operator as an anonymous middle child of
    ``assignment_expression``. The plain assignment uses ``=``; compound
    forms use ``+=`` / ``-=`` / ``*=`` / ``/=`` / ``%=`` / ``|=`` /
    ``&=`` / ``^=`` / ``<<=`` / ``>>=`` / ``>>>=``. Any non-``=``
    operator means the LHS's existing value is read AND combined with
    the RHS, so the LHS keeps its prior taint regardless of RHS state.
    """
    for child in node.children:
        if not child.is_named:
            return child.type != "="
    return False  # pragma: no cover - defensive: every assignment_expression has an operator token


class JavaTaintTracker:
    """Track tainted variable flow through a Java method / constructor / lambda body.

    Mirrors the public surface of
    :class:`safelint.analysis.dataflow.TaintTracker` (Python) and
    :class:`safelint.analysis.dataflow_javascript.JsTaintTracker` (JS / TS)
    so :class:`~safelint.rules.dataflow.TaintedSinkRule` can dispatch
    on the active language without behavioural divergence at the call
    site. Results land in :attr:`sink_hits` as ``(call_node, var_name,
    sink_name)`` triples.
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

        Skips descent into nested function-defining nodes - those are
        analysed separately by the caller for each method / constructor /
        lambda / static initialiser found, with their own parameter set.
        """
        for node in walk(root, skip_types=tuple(_JAVA_FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        if node.type == "assignment_expression":
            self._visit_assignment(node)
        elif node.type == "variable_declarator":
            self._visit_var_declarator(node)
        elif node.type == "enhanced_for_statement":
            self._visit_enhanced_for(node)
        elif node.type in _CALL_TYPES:
            # Treat ``new Foo(tainted)`` the same as ``Foo(tainted)`` for
            # taint tracking - both feed the sink check via ``call_name``.
            self._visit_call(node)

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value`` (assignment_expression).

        Java's assignment LHS shapes:

        * ``identifier`` - bare local / parameter / field name binding
        * ``field_access`` - ``obj.field = v`` (we don't track fields)
        * ``array_access`` - ``arr[i] = v`` (we don't track element bindings)

        Only the identifier case updates the tainted set; field /
        array writes don't change *which names* carry taint.

        Compound assignments (``+=`` / ``-=`` / ``|=`` etc.) preserve
        the LHS's existing taint: ``sql += " suffix"`` keeps ``sql``
        tainted even if the RHS is clean, since the new value still
        contains the original tainted contents. Detected by inspecting
        the operator token (the anonymous middle child).

        Chained assignments ``a = b = expr`` are an ``assignment_expression``
        whose ``right`` is another ``assignment_expression``. The
        innermost RHS taint flows through every LHS in the chain; we
        recurse on the nested assignment first so ``b`` is updated,
        then resolve the chained RHS's taint via
        ``_assignment_chain_tainted`` for the outer ``a``.
        """
        # Collect the chain of nested ``assignment_expression`` nodes
        # (``a = b = expr`` -> ``[a, b]``) then process innermost-first so each
        # LHS sees the resolved RHS taint - the iterative form of the original
        # recurse-on-right. Bounded by the depth of the assignment chain.
        chain: list[tree_sitter.Node] = []
        cur: tree_sitter.Node | None = node
        while cur is not None:
            if cur.type != "assignment_expression":
                break
            chain.append(cur)
            cur = cur.child_by_field_name("right")
        for assign in reversed(chain):
            left = assign.child_by_field_name("left")
            right = assign.child_by_field_name("right")
            if left is None or right is None:  # pragma: no cover - defensive: valid assignments have both sides
                continue
            if left.type != "identifier":
                continue
            rhs_tainted = self._assignment_chain_tainted(right)
            if _is_compound_assignment(assign) and self._name_is_tainted(left):
                rhs_tainted = True
            self._update_name(left, is_tainted=rhs_tainted)

    def _assignment_chain_tainted(self, node: tree_sitter.Node) -> bool:
        """Return the innermost-RHS taint state for a (possibly chained) assignment RHS."""
        cur = node
        while cur.type == "assignment_expression":
            inner = cur.child_by_field_name("right")
            if inner is None:  # pragma: no cover - defensive: valid assignment always has right
                return False
            cur = inner
        return self._is_tainted(cur)

    def _name_is_tainted(self, name_node: tree_sitter.Node) -> bool:
        """Return True if *name_node* is an identifier that's currently tainted."""
        return name_node.type == "identifier" and node_text(name_node) in self.tainted

    def _visit_enhanced_for(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``for (T x : tainted_iterable) { ... }``.

        Java's enhanced-for binds each element of the iterable to a
        fresh local, so a tainted iterable taints the loop variable.
        Without this, ``for (String arg : args) { exec(arg); }`` with
        tainted ``args`` would silently miss SAFE801 because the loop
        variable was never added to the tainted set.

        tree-sitter-java's ``enhanced_for_statement`` exposes ``name``
        (the loop variable identifier) and ``value`` (the iterable
        expression). Only identifier-shaped loop variables are
        tracked - destructuring isn't a Java feature, so this covers
        every case.
        """
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        if name_node is None or value_node is None:  # pragma: no cover - defensive: enhanced_for always has both
            return
        if name_node.type != "identifier":  # pragma: no cover - defensive: name field is always identifier in valid Java
            return
        self._update_name(name_node, is_tainted=self._is_tainted(value_node))

    def _visit_var_declarator(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``Type x = value;``.

        ``variable_declarator`` is the per-binding node inside a
        ``local_variable_declaration`` (``Foo x = y;``) or a
        ``field_declaration`` (class-scope; included for completeness,
        though field-level taint would need cross-scope analysis we
        don't do today). Field names are ``name`` (the LHS identifier)
        and ``value`` (the RHS expression).

        Multi-binding ``int x = a, y = b;`` produces multiple
        ``variable_declarator`` siblings; each is visited
        independently by the engine's top-level walk.
        """
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name is None or value is None:
            # No initialiser: ``int x;`` - the binding starts untainted,
            # nothing to record.
            return
        if name.type != "identifier":  # pragma: no cover - defensive: variable_declarator name is always an identifier in valid Java
            return
        is_tainted = self._is_tainted(value)
        self._update_name(name, is_tainted=is_tainted)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink with tainted inputs.

        For Java ``method_invocation`` sinks, taint may arrive either via
        an explicit argument or via the *receiver object* itself. The
        canonical case is ``url.openStream()`` where the URL was built
        from user input - the call has zero arguments but the receiver
        carries the taint. Same posture for the sink check as for the
        result-taint check in ``_call_tainted``: receiver counts as
        an input for method invocations only (constructor calls via
        ``object_creation_expression`` have no receiver).
        """
        name = call_name(node)
        if name not in self.sinks:
            return
        self._record_tainted_arg_hits(node, name)
        if node.type == "method_invocation":
            obj = node.child_by_field_name("object")
            if obj is not None and self._is_tainted(obj):
                self._record_sink_hit(node, obj, name)

    def _record_tainted_arg_hits(self, call_node: tree_sitter.Node, sink_name: str) -> None:
        """Record one sink hit per tainted argument on *call_node*."""
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:  # pragma: no cover - defensive: method_invocation always carries an arguments node
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(call_node, arg, sink_name)

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == "identifier" else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))

    def _update_name(self, target: tree_sitter.Node, *, is_tainted: bool) -> None:
        """Add or remove *target* (an ``identifier``) from the tainted set."""
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
        if node_type == "identifier":
            return node_text(node) in self.tainted
        if node_type in _CALL_TYPES:
            return self._call_tainted(node)
        return False

    @staticmethod
    def _taint_propagating_children(node: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Return the child nodes through which taint can flow into *node*.

        Member access (``field_access`` / ``array_access``) propagates its
        receiver; spreading expressions and containers propagate every named
        child. Everything else is a taint dead-end.
        """
        node_type = node.type
        if node_type in _MEMBER_TYPES:
            obj = node.child_by_field_name("object" if node_type == "field_access" else "array")
            return [obj] if obj is not None else []
        if node_type in _SPREADING_TYPES or node_type in _CONTAINER_TYPES:
            return list(node.named_children)
        return []

    def _call_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if this call produces a tainted value.

        Mirrors the Python / JS trackers' ``_call_tainted`` with one
        Java-specific extension: for ``method_invocation``, the
        *receiver object* is treated as an input alongside the
        explicit arguments when applying ``assume_taint_preserving``.
        Without this, ``String s = input.trim();`` would silently drop
        the taint marker because ``trim()`` has zero arguments even
        though the receiver ``input`` IS tainted - a common Java
        false-negative pattern. Constructor calls
        (``object_creation_expression``) have no receiver and only
        consult arguments.

        Sanitizers clear regardless of input taint state; sources
        inject regardless of input taint state; unknowns either
        preserve (default ``assume_taint_preserving=True``) or drop
        (``False``) based on any input.
        """
        name = call_name(node)
        if name in self.sanitizers:
            return False
        if name in self.sources:
            return True
        if not self.assume_taint_preserving:
            return False
        args_node = node.child_by_field_name("arguments")
        if args_node and any(self._is_tainted(arg) for arg in args_node.named_children):
            return True
        if node.type == "method_invocation":
            obj = node.child_by_field_name("object")
            if obj is not None and self._is_tainted(obj):
                return True
        return False
