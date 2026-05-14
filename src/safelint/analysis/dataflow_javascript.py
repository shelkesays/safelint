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

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES


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
        "binary_expression",
        "unary_expression",
        "ternary_expression",
        "update_expression",
        "sequence_expression",
        "parenthesized_expression",
        "await_expression",
        "yield_expression",
        # TypeScript-only pass-through wrappers:
        "as_expression",
        "satisfies_expression",
        "non_null_expression",
        "type_assertion",
    }
)

# Container / aggregate literals that carry taint when any element is tainted.
_CONTAINER_TYPES = frozenset({"array", "object", "pair", "spread_element"})

# Member access shapes (``foo.bar`` / ``foo[idx]``) - taint flows from the
# receiver. ``optional_chain`` (``foo?.bar``) doesn't change the propagation
# direction, only the null-safety semantics - handled by SAFE803, not here.
_MEMBER_TYPES = frozenset({"member_expression", "subscript_expression"})


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

        Skips descent into nested function bodies - those are analysed
        separately by the caller for each function found, with their
        own parameter set.
        """
        for node in walk(root, skip_types=tuple(_JS_FUNCTION_TYPES)):
            self._visit_node(node)

    def _visit_node(self, node: tree_sitter.Node) -> None:
        """Dispatch *node* to the right per-shape handler."""
        if node.type == "assignment_expression":
            self._visit_assignment(node)
        elif node.type == "augmented_assignment_expression":
            self._visit_aug_assignment(node)
        elif node.type == "variable_declarator":
            self._visit_var_declarator(node)
        elif node.type in ("call_expression", "new_expression"):
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
        if target.type in ("identifier", "shorthand_property_identifier_pattern"):
            yield target
            return
        # ``array_pattern`` / ``object_pattern`` / ``rest_pattern`` all
        # bind every named child - same recursion shape, so a single
        # branch keeps cyclomatic complexity in check.
        if target.type in ("array_pattern", "object_pattern", "rest_pattern"):
            for child in target.named_children:
                yield from self._iter_target_identifiers(child)
            return
        # Patterns that bind through a *specific* field name. ``pair_pattern``
        # carries the bound alias on ``value`` (``{key: alias}``);
        # ``assignment_pattern`` carries the binding on ``left``
        # (``[a = 1]`` / ``function f(a = 1) {}`` - the ``right`` is
        # the default value, not a binding). Without ``assignment_pattern``
        # taint flowing into a destructuring target with a default would
        # silently drop on the floor.
        field_by_type = {"pair_pattern": "value", "assignment_pattern": "left"}
        field = field_by_type.get(target.type)
        if field is None:
            return
        inner = target.child_by_field_name(field)
        if inner is not None:
            yield from self._iter_target_identifiers(inner)

    def _visit_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x = value`` (assignment_expression)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive: valid assignments have both sides
            return
        is_tainted = self._is_tainted(right)
        for ident in self._iter_target_identifiers(left):
            self._update_name(ident, is_tainted=is_tainted)

    def _visit_aug_assignment(self, node: tree_sitter.Node) -> None:
        """Propagate taint through ``x += value``."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:  # pragma: no cover - defensive: valid aug-assignments have both sides
            return
        if self._is_tainted(right):
            self._update_name(left, is_tainted=True)

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
        is_tainted = self._is_tainted(value)
        for ident in self._iter_target_identifiers(name):
            self._update_name(ident, is_tainted=is_tainted)

    def _visit_call(self, node: tree_sitter.Node) -> None:
        """Check whether this call reaches a sink with tainted arguments."""
        name = call_name(node)
        if name not in self.sinks:
            return
        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(node, arg, name)

    def _record_sink_hit(self, call_node: tree_sitter.Node, arg_node: tree_sitter.Node, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == "identifier" else "<expr>"
        self.sink_hits.append((call_node, arg_name, sink))  # pragma: no branch

    def _update_name(self, target: tree_sitter.Node, *, is_tainted: bool) -> None:
        """Add or remove *target* from the tainted set if it carries a bare name."""
        if target.type not in ("identifier", "shorthand_property_identifier_pattern"):
            return
        name = node_text(target)
        if is_tainted:
            self.tainted.add(name)
        else:
            self.tainted.discard(name)

    def _is_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if *node* may carry tainted data."""
        node_type = node.type
        if node_type == "identifier":
            return node_text(node) in self.tainted
        if node_type in ("call_expression", "new_expression"):
            return self._call_tainted(node)
        if node_type == "template_string":
            return self._template_tainted(node)
        if node_type in _MEMBER_TYPES:
            obj = node.child_by_field_name("object")
            return self._is_tainted(obj) if obj is not None else False
        if node_type in _SPREADING_TYPES or node_type in _CONTAINER_TYPES:
            return any(self._is_tainted(child) for child in node.named_children)
        return False

    def _call_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if this call produces a tainted value.

        Mirrors the Python tracker's :meth:`_call_tainted` exactly -
        sanitizers clear, sources inject, unknowns either preserve or
        drop based on ``assume_taint_preserving``.
        """
        name = call_name(node)
        if name in self.sanitizers:
            return False
        if name in self.sources:
            return True
        if not self.assume_taint_preserving:
            return False
        args_node = node.child_by_field_name("arguments")
        if not args_node:  # pragma: no cover - defensive: every call_expression has an arguments child
            return False
        return any(self._is_tainted(arg) for arg in args_node.named_children)

    def _template_tainted(self, node: tree_sitter.Node) -> bool:
        """Return True if any ``${expr}`` substitution in a template string is tainted."""
        for child in walk(node):
            if child.type != "template_substitution":
                continue
            if any(self._is_tainted(inner) for inner in child.named_children):
                return True
        return False
