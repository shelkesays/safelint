"""resource_lifecycle rule - tracked resource functions must be wrapped in cleanup-guaranteed scope.

Cross-language: Python requires a ``with`` block (context manager);
JavaScript requires a ``try { ... } finally { ... }`` somewhere up the
AST ancestor chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup  # ``_validated_string_list`` re-exported for backwards-compat
from safelint.languages._node_utils import call_name, resolve_lang_name, walk
from safelint.languages._node_utils import node_text as _node_text
from safelint.languages.go import FUNCTION_TYPES as _GO_FUNCTION_TYPES
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import CALL, WITH_ITEM
from safelint.rules.base import BaseRule


# ``_validated_string_list`` was historically defined in this module
# and re-exported because several rules import it from here. It now
# lives in ``safelint.core._validators`` so core/ and rules/ can
# share the helper without cross-rule imports. The line above keeps
# the old import path working - third-party rules / forks doing
# ``from safelint.rules.resource_lifecycle import _validated_string_list``
# don't break.


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _with_item_call(item: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the call node opened by *item*, unwrapping ``as_pattern`` if present."""
    value = item.child_by_field_name("value")
    # ``with_item`` always has a ``value`` field in valid Python; this is
    # a defensive guard against malformed AST.
    if value is None:  # pragma: no cover
        return None
    if value.type == "as_pattern" and value.named_children:
        value = value.named_children[0]
    return value if value.type == CALL else None


def _iter_with_items(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every ``with_item`` node in *tree* (Python).

    ``with_item`` only appears inside ``with_statement`` in tree-sitter-python,
    so a flat walk is sufficient.
    """
    for node in walk(tree.root_node):
        if node.type == WITH_ITEM:
            yield node


def _is_inside_try_finally(node: tree_sitter.Node) -> bool:
    """Return True if *node* has an enclosing guarding try/finally within the same function scope.

    Walks the parent chain (Tree-sitter Node exposes ``.parent``) and
    short-circuits on the first ``try_statement`` whose children include a
    ``finally_clause`` - *unless* the call we're checking sits inside that
    very ``finally_clause`` itself. A resource acquired inside the finally
    block has no subsequent finally to clean up *itself*, so the
    enclosing try/finally that the call lives inside does not count as
    guarding it. Multiple nested try-statements within the same function
    are tolerated: an outer ``try { ... } finally { ... }`` still counts
    as guarding a deeply-nested call inside that function - provided the
    call is not inside the outer finally.

    **Stops at function boundaries.** If the walk crosses a JavaScript
    function-defining node (``function_declaration``, ``arrow_function``,
    ``method_definition``, etc.) before finding a guarding ``try_statement``,
    the call is *not* guarded - the outer function's ``finally`` block
    runs when the *outer* function returns, not when the inner function
    is invoked later (e.g. via ``setTimeout(callback, 1000)``). Without
    this boundary check the rule would silently miss the most common
    leak pattern of all: an acquirer call inside a callback / arrow /
    method nested in an unrelated outer try/finally.

    Heuristic: the rule still doesn't verify that the ``finally`` block
    actually closes the resource - only that *some* finally exists in
    the same function scope. Catches the common "I opened a stream and
    forgot to handle cleanup at all" case while staying simple.
    False positives are possible for try-finally blocks that don't
    actually clean up; users with those patterns can suppress with
    ``// nosafe: SAFE401``.
    """
    prev = node
    cur = node.parent
    while cur is not None:
        if cur.type in _JS_FUNCTION_TYPES:
            # Walked out of the call's function scope without finding a
            # guarding try/finally - anything further up belongs to a
            # different function whose ``finally`` doesn't run when this
            # call eventually executes.
            return False
        # ``prev.type != "finally_clause"`` skips a try_statement whose
        # finally we just came out of - that finally is the *parent* of
        # the call, not a subsequent cleanup hook for it. Without this
        # check, ``try { ... } finally { fs.createReadStream(p); }``
        # would be silently accepted as "guarded" even though no
        # finally runs after the stream opens.
        if _try_statement_has_finally(cur) and prev.type != "finally_clause":
            return True
        prev = cur
        cur = cur.parent
    return False


def _try_statement_has_finally(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a ``try_statement`` with a ``finally_clause`` child."""
    if node.type != "try_statement":
        return False
    return any(child.type == "finally_clause" for child in node.named_children)


def _java_acquired_variable_name(call_node: tree_sitter.Node) -> str | None:
    """Return the simple identifier the acquirer call is assigned to, or None.

    Handles the assignment shapes a Java acquirer can sit inside:

    * ``Resource r = acquirer(...)`` (``variable_declarator`` parent inside a
      ``local_variable_declaration`` / field) - returns ``"r"``.
    * ``r = acquirer(...)`` (``assignment_expression`` parent, reassignment
      of a previously-declared variable) - returns ``"r"``.
    * ``BufferedReader br = new BufferedReader(new FileReader(path))``
      (the *inner* ``new FileReader`` is an argument to an *outer*
      ``object_creation_expression`` that is itself assigned) - returns
      ``"br"``. Closing the outer wrapper closes the inner resource per
      the JDK ``AutoCloseable`` / ``Closeable`` contract, so for cleanup
      purposes the inner acquirer shares the outer's variable handle.
      The recursion handles arbitrarily nested wrappers
      (``new A(new B(new C(stream)))``).

    Returns ``None`` for bare-expression acquirers (``new FileInputStream(p);``
    with no left-hand-side) - those can never be closed because there's no
    handle, so they're always leaks regardless of try/finally shape.

    The walk transparently skips ``parenthesized_expression`` and
    ``cast_expression`` wrappers so ``Resource r = (Resource) acquirer(...)``
    still resolves to ``"r"``.
    """
    # Peel outward: a wrapped acquirer (an argument to an enclosing
    # ``object_creation_expression``) shares the outer wrapper's handle, so we
    # re-resolve against the outer creation. Looping instead of recursing; the
    # outward walk is bounded by the finite parent chain (terminates at root),
    # and the per-step wrapper skip is delegated to ``_skip_wrapper_parents``.
    node = call_node
    while node is not None:
        cur = _skip_wrapper_parents(node.parent)
        if cur is None:  # pragma: no cover - defensive: walked off the tree root
            return None
        direct = _direct_assigned_name(cur)
        if direct is not None:
            return direct
        if cur.type == "argument_list" and cur.parent is not None and cur.parent.type == "object_creation_expression":
            node = cur.parent
            continue
        return None
    return None  # pragma: no cover - loop exits only via the returns above


def _skip_wrapper_parents(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Return the nearest ancestor of *node* (inclusive) that isn't a paren/cast wrapper.

    ``parenthesized_expression`` / ``cast_expression`` are transparent for
    cleanup purposes (``Resource r = (Resource) acquirer(...)``). Bounded by
    the finite parent chain.
    """
    cur = node
    while cur is not None:
        if cur.type not in ("parenthesized_expression", "cast_expression"):
            return cur
        cur = cur.parent
    return None  # node was None, or the wrapper chain ran off the tree root


def _direct_assigned_name(node: tree_sitter.Node) -> str | None:
    """Return the LHS identifier of *node* if it's a direct declarator / assignment, else None.

    Helper extracted from ``_java_acquired_variable_name`` to keep that
    function under the complexity threshold. ``node`` is the parent
    (after passthrough unwrap) of an acquirer call - we just need to
    pick off the two terminal cases.
    """
    if node.type == "variable_declarator":
        name_node = node.child_by_field_name("name")
        if name_node is not None and name_node.type == "identifier":
            return _node_text(name_node)
        return None  # pragma: no cover - defensive: declarator name is always an identifier in valid Java
    if node.type == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            return _node_text(left)
    return None


def _finally_closes_variable(finally_clause: tree_sitter.Node, var_name: str) -> bool:
    """Return True if the finally clause contains a ``var_name.close()`` invocation.

    Walks the finally clause body looking for a ``method_invocation`` whose
    ``object`` field is an ``identifier`` matching ``var_name`` and whose
    ``name`` field is ``close``. Stops descending into nested Java
    executable bodies covered by ``_JAVA_FUNCTION_TYPES`` (methods,
    constructors, lambdas, static initializers) so a nested
    ``close()`` on a captured copy doesn't spuriously satisfy the
    check.

    A consequence of pruning ``_JAVA_FUNCTION_TYPES``: a ``close()``
    invoked from inside an anonymous inner class declared in the
    finally (``new Runnable() { public void run() { x.close(); } }``)
    is NOT recognised because the walk yields the inner
    ``method_declaration`` but does not descend into its body. The
    same holds for closes routed through a lambda or static
    initializer. Users hitting this can suppress with
    ``// nosafe: SAFE401`` or restructure to call ``close()`` directly
    in the finally body (which is the idiomatic pattern anyway).

    **Strict matching trade-off.** A close routed through a helper -
    ``IOUtils.closeQuietly(var)`` (Apache Commons IO), ``closeAll()`` with
    no argument, ``Try.run(() -> var.close())`` - is NOT recognised here
    and would produce a false-positive SAFE401. The trade-off was accepted
    deliberately: the dominant real-world leak is ``finally { audit(); }``
    or similar where nothing closes the resource at all, and a strict
    matcher catches that without the cross-helper analysis that would
    otherwise be needed. Users hitting the helper-pattern false positive
    can suppress with ``// nosafe: SAFE401`` on the acquirer line, or
    refactor to the modern try-with-resources form.
    """
    for descendant in walk(finally_clause, skip_types=_JAVA_FUNCTION_TYPES):
        if descendant.type != "method_invocation":
            continue
        obj = descendant.child_by_field_name("object")
        if obj is None or obj.type != "identifier" or _node_text(obj) != var_name:
            continue
        name_node = descendant.child_by_field_name("name")
        if name_node is not None and _node_text(name_node) == "close":
            return True
    return False


def _is_inside_java_resource_guard(node: tree_sitter.Node) -> bool:
    """Return True if *node* has an enclosing Java resource-cleanup scope.

    Java has two idiomatic cleanup forms:

    * **try-with-resources** (``try (Resource r = ...) { ... }``): the JLS
      guarantees ``close()`` is called on the declared resource when the
      try block exits, including via exception. This is the modern
      preferred form for any ``AutoCloseable``. **Only resources declared
      in the header parens are auto-closed** - an inner ``new
      FileReader(...)`` inside the try body is NOT covered by the
      enclosing try-with-resources and would leak. To distinguish the
      two, the walk only accepts a ``try_with_resources_statement``
      ancestor when we reached it via the ``resource_specification``
      child (the header) - if we walked up through the ``block`` child
      (the body), the call is NOT in the header and isn't auto-closed.
    * **try { ... } finally { resource.close(); }**: the older manual
      form. The finally clause must contain a direct
      ``<acquired-var>.close()`` invocation; bare ``finally { audit(); }``
      blocks that perform other work but don't close the resource are
      treated as unguarded (see ``_finally_closes_variable`` for the
      helper-pattern trade-off).

    Walks the parent chain looking for either form, stopping at function
    boundaries (method_declaration, constructor_declaration,
    lambda_expression, static_initializer) so a resource acquired
    inside a lambda doesn't borrow the enclosing method's
    try-with-resources for safety.

    The ``prev.type != "finally_clause"`` guard mirrors the JS logic:
    a resource acquired inside the finally block of a try-statement
    isn't covered by *that* try's cleanup. tree-sitter-java doesn't
    use ``finally_clause`` as a child of try_with_resources_statement
    (auto-cleanup is implicit), so the guard only matters for the
    manual try/finally form.
    """
    var_name = _java_acquired_variable_name(node)
    prev = node
    cur = node.parent
    while cur is not None:
        if cur.type in _JAVA_FUNCTION_TYPES:
            return False
        if _java_ancestor_is_guard(cur, prev, var_name):
            return True
        prev = cur
        cur = cur.parent
    return False  # pragma: no cover - defensive: walks off the tree root


def _java_ancestor_is_guard(cur: tree_sitter.Node, prev: tree_sitter.Node, var_name: str | None) -> bool:
    """Return True if *cur* is a try ancestor that guards the acquirer.

    Two acceptances:

    * ``try_with_resources_statement`` reached via the ``resource_specification``
      child - meaning the acquirer call sat in the header parens, where the
      JLS guarantees ``close()``. A call reached via the ``block`` child is
      inside the body and is NOT auto-closed.
    * ``try_statement`` (manual try/finally) whose finally clause contains a
      ``<var_name>.close()`` invocation. The ``prev.type != "finally_clause"``
      guard skips a try whose finally we just walked out of - that finally
      doesn't run AFTER the acquirer if the acquirer lives inside it.
      ``var_name is None`` (bare-expression acquirers) always returns False
      from this branch because there's no handle to close.
    """
    if cur.type == "try_with_resources_statement" and prev.type == "resource_specification":
        return True
    if cur.type != "try_statement" or prev.type == "finally_clause" or var_name is None:
        return False
    finally_clause = next((c for c in cur.named_children if c.type == "finally_clause"), None)
    return finally_clause is not None and _finally_closes_variable(finally_clause, var_name)


def _go_acquired_variable_names(call_node: tree_sitter.Node) -> frozenset[str]:
    """Return the variable name(s) a Go acquirer call is assigned to.

    Handles the three assignment shapes an acquirer can sit in:

    * ``f, err := os.Open(p)`` (``short_var_declaration``) - the call is the
      ``right`` expression_list; the names come from the ``left`` list.
    * ``f = os.Open(p)`` (``assignment_statement``) - same ``left`` / ``right``
      shape.
    * ``var f = os.Open(p)`` (``var_spec``) - names are the spec's direct
      ``identifier`` children; the call lives in the trailing
      ``expression_list``.

    **Positional mapping:** when several calls share one statement
    (``a, b := os.Open(p1), os.Open(p2)``) and the LHS / RHS arities match,
    each call resolves to *only* its positional LHS variable - otherwise a
    ``defer a.Close()`` would wrongly mark ``b``'s acquirer guarded too.
    Multi-value single calls (``f, err := os.Open(p)``) keep returning all
    LHS names so either handle can satisfy the defer check.

    The blank identifier ``_`` is excluded (it discards the value, so there
    is no handle to close). Returns an empty set for a bare-expression
    acquirer (``os.Open(p)`` with no assignment) - no handle means it can
    never be deferred-closed, so it is always a leak.
    """
    rhs_list = call_node.parent
    if rhs_list is None or rhs_list.type != "expression_list":
        return frozenset()
    container = rhs_list.parent
    if container is None:  # pragma: no cover - defensive: expression_list always has a parent
        return frozenset()
    left_idents = _go_left_idents(container)
    if left_idents is None:
        return frozenset()
    positional = _go_positional_name(call_node, left_idents, rhs_list.named_children)
    if positional is not None:
        return positional
    return frozenset(t for t in (_node_text(n) for n in left_idents) if t != "_")


def _go_positional_name(call_node: tree_sitter.Node, left_idents: list[tree_sitter.Node], right_exprs: list[tree_sitter.Node]) -> frozenset[str] | None:
    """Return the positionally-matched LHS name set for *call_node*, or None to fall back.

    Only applies when several RHS calls share the statement and the LHS / RHS
    arities match (``a, b := f(), g()``); each call then maps to its own LHS
    variable. Returns None (caller falls back to all LHS names) for the
    single-call / mismatched-arity cases. A positional match onto ``_``
    yields an empty set (discarded handle).
    """
    if len(right_exprs) <= 1 or len(left_idents) != len(right_exprs):
        return None
    idx = next((i for i, expr in enumerate(right_exprs) if expr.id == call_node.id), None)
    if idx is None:  # pragma: no cover - defensive: call_node is one of rhs_list's children
        return frozenset()
    name = _node_text(left_idents[idx])
    return frozenset({name}) if name != "_" else frozenset()


def _go_left_idents(container: tree_sitter.Node) -> list[tree_sitter.Node] | None:
    """Return the ordered LHS ``identifier`` nodes of an assignment / ``var`` spec, or None.

    Order is preserved (including blank ``_``) so callers can map a RHS call
    to its positional LHS target. Returns None for any other container
    (e.g. a ``return`` statement) so a returned acquirer is treated as
    having no local handle.
    """
    if container.type in ("short_var_declaration", "assignment_statement"):
        left = container.child_by_field_name("left")
        return [c for c in left.named_children if c.type == "identifier"] if left is not None else []
    if container.type == "var_spec":
        return [c for c in container.named_children if c.type == "identifier"]
    return None


def _go_enclosing_function(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the nearest enclosing Go function / method / closure node, or None."""
    cur = node.parent
    while cur is not None:
        if cur.type in _GO_FUNCTION_TYPES:
            return cur
        cur = cur.parent
    return None  # pragma: no cover - defensive: acquirer calls always sit inside a function


# Go control-flow / closure node types that break the "runs on every exit
# path" guarantee for a ``defer``. A ``defer`` nested inside any of these is
# conditional and does not reliably close a resource acquired unconditionally.
_GO_NESTING_TYPES: frozenset[str] = frozenset(
    {
        "if_statement",
        "for_statement",
        "expression_switch_statement",
        "type_switch_statement",
        "select_statement",
        "communication_case",
        "expression_case",
        "type_case",
        "default_case",
        "func_literal",
    }
)


def _go_defer_closes(func_node: tree_sitter.Node, var_names: frozenset[str], acquirer: tree_sitter.Node) -> bool:
    """Return True if *func_node* defers a ``<var>.Close()`` that actually guards *acquirer*.

    Walks the function body for ``defer_statement`` nodes, pruning nested
    function / closure bodies (a ``defer`` inside an inner closure guards
    that closure's scope, not this one). A defer guards the acquirer only when:

    * it targets one of *var_names* in the ``defer f.Close()`` form (a defer
      routed through a wrapping closure is a documented blind spot), AND
    * it appears **after** the acquisition in source order - Go evaluates a
      deferred call's receiver immediately, so ``defer f.Close()`` written
      before ``f`` is assigned cannot close it, AND
    * it sits at the function's top level, not inside a conditional / loop /
      switch branch (see :data:`_GO_NESTING_TYPES`), so it runs on every exit
      path from the unconditional acquisition.
    """
    for node in walk(func_node, skip_types=tuple(_GO_FUNCTION_TYPES)):
        if node.type != "defer_statement" or not _go_defer_targets(node, var_names):
            continue
        if node.start_byte > acquirer.start_byte and _go_defer_is_unconditional(node, func_node):
            return True
    return False


def _go_defer_is_unconditional(defer_node: tree_sitter.Node, func_node: tree_sitter.Node) -> bool:
    """Return True if *defer_node* sits at *func_node*'s top level (no conditional ancestor).

    Walks the parent chain from the defer up to the function node; if it
    crosses any :data:`_GO_NESTING_TYPES` boundary the defer is conditional
    and does not run on every exit path.
    """
    cur = defer_node.parent
    while cur is not None:
        if cur.id == func_node.id:
            return True
        if cur.type in _GO_NESTING_TYPES:
            return False
        cur = cur.parent
    return True  # pragma: no cover - defensive: the defer always sits within func_node


def _go_defer_targets(defer_node: tree_sitter.Node, var_names: frozenset[str]) -> bool:
    """Return True if *defer_node* is a ``defer <var>.Close()`` for a name in *var_names*."""
    call = next((c for c in defer_node.named_children if c.type == "call_expression"), None)
    if call is None:
        return False
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "selector_expression":
        return False
    operand = fn.child_by_field_name("operand")
    field = fn.child_by_field_name("field")
    if operand is None or field is None or operand.type != "identifier":
        return False
    return _node_text(field) == "Close" and _node_text(operand) in var_names


class ResourceLifecycleRule(BaseRule):
    """Require tracked resource-acquisition calls to be wrapped in cleanup-guaranteed scope.

    Python: the call must appear inside a ``with`` statement (``with
    open(path) as f:``). Bare assignments without ``with`` fire even
    when paired with manual ``f.close()`` - Python's idiom is
    context-manager-first.

    JavaScript: the call must appear inside a ``try`` block whose
    ``try_statement`` has a ``finally_clause`` somewhere up the
    ancestor chain. Heuristic-only - the rule doesn't verify that the
    ``finally`` block actually closes the specific resource. Captures
    the most common "I created a stream and didn't handle cleanup at
    all" leak. JavaScript's newer ``using`` declarations (Stage 3 /
    Node 22+) aren't yet recognised as a safe form; for now, wrap
    inside ``try { ... } finally { ... }``.
    """

    name = "resource_lifecycle"
    code = "SAFE401"
    language = ("python", "javascript", "typescript", "java", "go")

    _DEFAULT_TRACKED_JAVASCRIPT: ClassVar[list[str]] = [
        # File / stream APIs.
        "createReadStream",
        "createWriteStream",
        "openSync",  # fs.openSync - returns a raw fd
        # Network / server.
        "createServer",
        "createConnection",  # net.createConnection / db drivers
        "connect",  # database drivers, sockets
        # Worker pools.
        "createWorker",
    ]

    _DEFAULT_TRACKED_JAVA: ClassVar[list[str]] = [
        # File / stream APIs via ``new`` - ``call_name`` on
        # ``object_creation_expression`` returns the simple class name.
        "FileInputStream",
        "FileOutputStream",
        "FileReader",
        "FileWriter",
        "BufferedReader",
        "BufferedWriter",
        "Scanner",
        "PrintWriter",
        "RandomAccessFile",
        # java.nio.file.Files static factory methods.
        "newBufferedReader",
        "newBufferedWriter",
        "newInputStream",
        "newOutputStream",
        # Network.
        "Socket",
        "ServerSocket",
        # JDBC.
        "getConnection",  # DriverManager.getConnection / DataSource.getConnection
        # NOT listed: ``FileChannel`` / bare ``open`` - ``call_name()`` strips
        # the receiver, and ``FileChannel`` doesn't expose a public constructor
        # (the standard acquirer is the static ``FileChannel.open(...)`` which
        # resolves to bare ``"open"``). A generic ``"open"`` entry would
        # over-match unrelated ``dialog.open()`` / ``editor.open()`` /
        # project-local helpers AND the intended ``FileChannel.open()``.
        # Java users who want ``FileChannel.open`` tracked can opt in via
        # ``[tool.safelint.rules.resource_lifecycle] tracked_functions_java
        # = ["FileInputStream", ..., "open"]`` (which fully replaces this
        # default list). The ``extend_tracked_functions`` config key is
        # Python-only; the Java path uses the ``tracked_functions_java``
        # per-language config which replaces rather than appends.
    ]

    _DEFAULT_TRACKED_GO: ClassVar[list[str]] = [
        # ``call_name`` strips the package / receiver, so each entry is the
        # bare method name. ``Open`` covers both ``os.Open`` and ``sql.Open``;
        # ``Create`` is ``os.Create``; ``Dial`` / ``Listen`` are the
        # ``net`` connection / listener acquirers. The safe form is a
        # ``defer <var>.Close()`` in the same function body.
        "Open",
        "Create",
        "Dial",
        "Listen",
    ]

    def _go_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the Go check: a tracked acquirer must be paired with ``defer <var>.Close()``.

        Go's idiom is ``f, err := os.Open(p); ... ; defer f.Close()`` - the
        deferred close runs on every exit path from the enclosing function.
        A tracked acquirer is clean when the function it lives in defers a
        ``Close()`` on one of the variables it was assigned to; otherwise it
        leaks. Bare-expression acquirers (no assignment) always fire - there
        is no handle to defer-close.
        """
        raw_tracked, error_key = resolve_lang_config_lookup(self.config, "tracked_functions", "go", default=self._DEFAULT_TRACKED_GO)
        tracked = frozenset(_validated_string_list(raw_tracked, error_key))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "call_expression":
                continue
            name = call_name(node)
            if not name or name not in tracked:
                continue
            message = self._go_leak_message(node, name)
            if message is not None:
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    @staticmethod
    def _go_leak_message(call_node: tree_sitter.Node, name: str) -> str | None:
        """Return the SAFE401 message for *call_node*, or None when it is properly guarded.

        Tailors the remediation to the acquirer shape: a bare-expression
        acquirer has no handle to close, so the message says to capture it
        first; a captured-but-unguarded handle just needs a `defer Close()`.
        """
        var_names = _go_acquired_variable_names(call_node)
        if not var_names:
            return f'"{name}()" acquires a resource but discards the handle - capture it (e.g. `f, err := {name}(...)`) and add `defer f.Close()` so it is released on every exit path'
        func = _go_enclosing_function(call_node)
        if func is not None and _go_defer_closes(func, var_names, call_node):
            return None
        return f'"{name}()" acquires a resource with no deferred close - add `defer <resource>.Close()` immediately after acquiring it (at the function\'s top level, after the acquisition)'

    @staticmethod
    def _python_collect_guarded(tree: tree_sitter.Tree, tracked: frozenset[str]) -> set[int]:
        """Return the set of start_byte values for tracked calls already inside a ``with`` block."""
        guarded: set[int] = set()
        for item in _iter_with_items(tree):
            call_node = _with_item_call(item)
            if call_node is None:
                continue
            name = call_name(call_node)
            if name and name in tracked:
                guarded.add(call_node.start_byte)
        return guarded

    def _python_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the Python-specific check (call must be inside a ``with`` block)."""
        base_tracked = _validated_string_list(self.config.get("tracked_functions", ["open"]), "tracked_functions")
        extra_tracked = _validated_string_list(self.config.get("extend_tracked_functions", []), "extend_tracked_functions")
        tracked: frozenset[str] = frozenset(base_tracked + extra_tracked)
        # cleanup_patterns has the same string-vs-list footgun as
        # tracked_functions - ``cleanup_patterns = "close"`` would coerce
        # to ``frozenset("close")`` = ``{'c','l','o','s','e'}`` and the
        # diagnostic text would render as ``c / e / l / o / s``. Validate
        # it the same way for consistency.
        cleanup_list = _validated_string_list(self.config.get("cleanup_patterns", ["close"]), "cleanup_patterns")
        cleanup: frozenset[str] = frozenset(cleanup_list)
        guarded = self._python_collect_guarded(tree, tracked)
        cleanup_str = " / ".join(sorted(cleanup))

        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != CALL:
                continue
            name = call_name(node)
            if not name or name not in tracked or node.start_byte in guarded:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"{name}()" called outside a with block - use a context manager or ensure {cleanup_str} is called on all exit paths',
                )
            )
        return violations

    def _javascript_check(self, filepath: str, tree: tree_sitter.Tree, lang_name: str) -> list[Violation]:
        """Run the JS-family (JavaScript / TypeScript) check (call must be inside ``try { ... } finally { ... }``).

        Walks both ``call_expression`` and ``new_expression`` - the runtime
        presets populate ``tracked_functions_javascript`` with constructor
        names (``Worker``, ``WebSocket``, ``MutationObserver``, ...) that
        are typically invoked via ``new``, so a call-only walk would
        miss exactly the cases the browser preset is designed to catch.
        ``call_name`` resolves both shapes - the rule layer doesn't need
        to branch.

        TypeScript inherits the JS tracked-functions list by default;
        users can set ``tracked_functions_typescript`` for TS-only
        overrides.
        """
        # JS-family (JS / TS): TypeScript inherits the JS list by default
        # via ``get_per_language_config``'s TS→JS fallback; users can
        # override per-language by setting ``tracked_functions_typescript``.
        raw_tracked, error_key = resolve_lang_config_lookup(
            self.config,
            "tracked_functions",
            lang_name,
            default=self._DEFAULT_TRACKED_JAVASCRIPT,
        )
        tracked_js = _validated_string_list(raw_tracked, error_key)
        tracked: frozenset[str] = frozenset(tracked_js)
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in ("call_expression", "new_expression"):
                continue
            name = call_name(node)
            if not name or name not in tracked:
                continue
            if _is_inside_try_finally(node):
                continue
            # Distinguish constructor invocations (``new Worker(...)``)
            # from plain calls (``createReadStream(...)``) in the
            # message. Reporting ``Worker()`` for ``new Worker(...)``
            # would be misleading - the user grep'ing for ``Worker(``
            # in the source wouldn't find the offending site.
            invocation = f"new {name}()" if node.type == "new_expression" else f"{name}()"
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"{invocation}" not wrapped in try/finally - guarantee cleanup with try {{ ... }} finally {{ ... }}',
                )
            )
        return violations

    def _java_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the Java check: call must be inside ``try-with-resources`` or ``try { ... } finally { ... }``.

        Walks both ``method_invocation`` and ``object_creation_expression``
        - tree-sitter-java's two call shapes. ``call_name`` normalises
        both: ``new FileInputStream(p)`` resolves to ``"FileInputStream"``,
        ``Files.newBufferedReader(p)`` resolves to ``"newBufferedReader"``.
        """
        raw_tracked, error_key = resolve_lang_config_lookup(
            self.config,
            "tracked_functions",
            "java",
            default=self._DEFAULT_TRACKED_JAVA,
        )
        tracked = frozenset(_validated_string_list(raw_tracked, error_key))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in ("method_invocation", "object_creation_expression"):
                continue
            name = call_name(node)
            if not name or name not in tracked:
                continue
            if _is_inside_java_resource_guard(node):
                continue
            # Use ``new Foo()`` only for constructor invocations to match
            # the source surface the user can grep for. ``Files.newBufferedReader``
            # via ``method_invocation`` renders as ``newBufferedReader()``.
            invocation = f"new {name}()" if node.type == "object_creation_expression" else f"{name}()"
            message = (
                f'"{invocation}" not wrapped in try-with-resources or try/finally; '
                f"declare it as ``try (var resource = {invocation}) {{ ... }}`` "
                "(try-with-resources; the JVM auto-closes the resource on exit), "
                "or guard with ``try {{ ... }} finally {{ resource.close(); }}``"
            )
            violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag unguarded calls to tracked resource-acquisition functions."""
        lang_name = resolve_lang_name(filepath)
        if lang_name == "python":
            return self._python_check(filepath, tree)
        if lang_name == "java":
            return self._java_check(filepath, tree)
        if lang_name == "go":
            return self._go_check(filepath, tree)
        return self._javascript_check(filepath, tree, lang_name)
