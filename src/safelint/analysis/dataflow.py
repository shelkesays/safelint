"""Intra-procedural taint analysis via AST NodeVisitor.

The :class:`TaintTracker` walks a single function body and tracks which
variables carry data derived from tainted sources (function parameters,
configurable I/O calls).  When a tainted value reaches a configurable
dangerous sink the hit is recorded in :attr:`TaintTracker.sink_hits`.

Design goals
------------
* Intra-procedural only — no cross-function call graph needed.
* Assignment propagation: ``x = tainted_y`` makes ``x`` tainted.
* Sanitizer calls clear taint: ``x = escape(tainted_y)`` → ``x`` clean.
* Source calls inject taint: ``x = input()`` → ``x`` tainted.
* f-strings, containers, and arithmetic operators spread taint.
* Nesting depth ≤ 2 in every method (safelint-compatible).
"""

from __future__ import annotations

import ast

# ---------------------------------------------------------------------------
# Module-level helper (no self dependency, so top-level is cleaner)
# ---------------------------------------------------------------------------


def _call_name(func: ast.expr) -> str | None:
    """Return the bare callable name from a Call's func node, or None."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# ---------------------------------------------------------------------------
# TaintTracker
# ---------------------------------------------------------------------------


class TaintTracker(ast.NodeVisitor):
    """Track tainted variable flow through a function body.

    Instantiate with the set of already-tainted parameter names, the sets of
    sink / sanitizer / source call names, then call ``visit(func_node)``.
    Results are in :attr:`sink_hits` as ``(lineno, var_name, sink_name)``
    triples.
    """

    # AST expression types whose sub-names propagate taint.
    _SPREADING: tuple[type[ast.expr], ...] = (
        ast.BinOp,
        ast.BoolOp,
        ast.UnaryOp,
        ast.Compare,
        ast.IfExp,
    )
    # Literal container types that propagate element taint.
    _CONTAINERS: tuple[type[ast.expr], ...] = (ast.List, ast.Tuple, ast.Set)

    def __init__(
        self,
        params: set[str],
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
    ) -> None:
        """Initialise tracker with tainted entry parameters and rule config."""
        self.tainted: set[str] = set(params)
        self.sinks = sinks
        self.sanitizers = sanitizers
        self.sources = sources
        # (lineno, variable_name_or_expr, sink_name)
        self.sink_hits: list[tuple[int, str, str]] = []

    # ------------------------------------------------------------------
    # Taint propagation helpers — each ≤ depth 1
    # ------------------------------------------------------------------

    def _name_tainted(self, node: ast.Name) -> bool:
        """Return True if this Name references a tainted variable."""
        return node.id in self.tainted

    def _call_tainted(self, node: ast.Call) -> bool:
        """Return True if this Call produces a tainted value."""
        name = _call_name(node.func)
        if name in self.sanitizers:
            return False
        if name in self.sources:
            return True
        return any(self._is_tainted(a) for a in node.args)

    def _fstring_tainted(self, node: ast.JoinedStr) -> bool:
        """Return True if any interpolated value in an f-string is tainted."""
        return any(
            self._is_tainted(v.value)
            for v in node.values
            if isinstance(v, ast.FormattedValue)
        )

    def _container_tainted(self, node: ast.expr) -> bool:
        """Return True if any element of a list/tuple/set literal is tainted."""
        elts: list[ast.expr] = getattr(node, "elts", [])
        return any(self._is_tainted(e) for e in elts)

    def _spreading_tainted(self, node: ast.expr) -> bool:
        """Return True if any Name inside a spreading expression is tainted."""
        tainted_names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        return bool(self.tainted & tainted_names)

    def _is_tainted(self, node: ast.expr) -> bool:  # noqa: PLR0911
        """Return True if *node* may carry tainted data."""
        if isinstance(node, ast.Name):
            return self._name_tainted(node)
        if isinstance(node, ast.Call):
            return self._call_tainted(node)
        if isinstance(node, ast.JoinedStr):
            return self._fstring_tainted(node)
        if isinstance(node, self._CONTAINERS):
            return self._container_tainted(node)
        if isinstance(node, self._SPREADING):
            return self._spreading_tainted(node)
        return False

    # ------------------------------------------------------------------
    # Assignment visitors — propagate taint to LHS names
    # ------------------------------------------------------------------

    def _update_name(self, target: ast.expr, is_tainted: bool) -> None:
        """Add or remove *target* from the tainted set."""
        if not isinstance(target, ast.Name):
            return
        if is_tainted:
            self.tainted.add(target.id)
        else:
            self.tainted.discard(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Propagate taint through plain assignment."""
        is_tainted = self._is_tainted(node.value)
        for target in node.targets:
            self._update_name(target, is_tainted)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        """Propagate taint through augmented assignment (+=, |=, …)."""
        if self._is_tainted(node.value):
            self._update_name(node.target, True)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        """Propagate taint through annotated assignment."""
        if node.value and self._is_tainted(node.value):
            self._update_name(node.target, True)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Call visitor — detect tainted args at dangerous sinks
    # ------------------------------------------------------------------

    def _record_sink_hit(self, lineno: int, arg: ast.expr, sink: str) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        name = arg.id if isinstance(arg, ast.Name) else "<expr>"
        self.sink_hits.append((lineno, name, sink))

    def _check_call_args(self, node: ast.Call, sink: str) -> None:
        """Record a hit for each tainted positional argument to *sink*."""
        for arg in node.args:
            if self._is_tainted(arg):
                self._record_sink_hit(node.lineno, arg, sink)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Check whether this Call reaches a sink with tainted arguments."""
        name = _call_name(node.func)
        if name in self.sinks:
            self._check_call_args(node, name)
        self.generic_visit(node)
