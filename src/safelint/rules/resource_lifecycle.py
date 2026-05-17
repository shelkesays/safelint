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

    Handles two assignment shapes:

    * ``Resource r = acquirer(...)`` (``variable_declarator`` parent inside a
      ``local_variable_declaration`` / field) - returns ``"r"``.
    * ``r = acquirer(...)`` (``assignment_expression`` parent, reassignment
      of a previously-declared variable) - returns ``"r"``.

    Returns ``None`` for bare-expression acquirers (``new FileInputStream(p);``
    with no left-hand-side) - those can never be closed because there's no
    handle, so they're always leaks regardless of try/finally shape.

    The walk transparently skips ``parenthesized_expression`` and
    ``cast_expression`` wrappers so ``Resource r = (Resource) acquirer(...)``
    still resolves to ``"r"``.
    """
    cur = call_node.parent
    while cur is not None and cur.type in ("parenthesized_expression", "cast_expression"):
        cur = cur.parent
    if cur is None:
        return None
    if cur.type == "variable_declarator":
        name_node = cur.child_by_field_name("name")
        if name_node is not None and name_node.type == "identifier":
            return _node_text(name_node)
        return None
    if cur.type == "assignment_expression":
        left = cur.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            return _node_text(left)
    return None


def _finally_closes_variable(finally_clause: tree_sitter.Node, var_name: str) -> bool:
    """Return True if the finally clause contains a ``var_name.close()`` invocation.

    Walks the finally clause body looking for a ``method_invocation`` whose
    ``object`` field is an ``identifier`` matching ``var_name`` and whose
    ``name`` field is ``close``. Stops descending into nested function /
    lambda / class bodies so a nested ``close()`` on a captured copy doesn't
    spuriously satisfy the check.

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
        # try-with-resources only auto-closes resources declared in
        # the header (the ``resource_specification`` child). A call
        # reached via the ``block`` child is inside the body and is
        # NOT auto-closed by the enclosing try-with-resources -
        # treat it like any other unguarded acquirer.
        if cur.type == "try_with_resources_statement" and prev.type == "resource_specification":
            return True
        if cur.type == "try_statement" and prev.type != "finally_clause" and var_name is not None:
            finally_clause = next((c for c in cur.named_children if c.type == "finally_clause"), None)
            if finally_clause is not None and _finally_closes_variable(finally_clause, var_name):
                return True
        prev = cur
        cur = cur.parent
    return False


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
    language = ("python", "javascript", "typescript", "java")

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
        # Concurrent / IO channels via constructor / factory names only.
        # NOT listed: bare ``open`` - ``call_name()`` strips the receiver,
        # so a generic ``"open"`` entry would match ``dialog.open()`` /
        # ``editor.open()`` / project-local helpers AND the intended
        # ``FileChannel.open()``. Java users who need ``FileChannel.open``
        # tracked can override via
        # ``[tool.safelint.rules.resource_lifecycle] tracked_functions_java
        # = ["FileChannel", "FileInputStream", ..., "open"]`` (which fully
        # replaces this default list). The ``extend_tracked_functions``
        # config key is Python-only; the Java path uses the
        # ``tracked_functions_java`` per-language config which replaces
        # rather than appends.
        "FileChannel",
    ]

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
                f'"{invocation}" not wrapped in try-with-resources or try/finally - '
                f"declare in ``try (... = {invocation})`` for automatic cleanup, "
                "or guard with ``try {{ ... }} finally {{ ... }}``"
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
        return self._javascript_check(filepath, tree, lang_name)
