"""resource_lifecycle rule - tracked resource functions must use context managers."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.languages._node_utils import call_name, resolve_lang_name, walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import CALL, WITH_ITEM
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _validated_string_list(value: object, key_name: str) -> list[str]:
    """Validate that *value* is a list/tuple of strings, return it as a list.

    Raises :class:`TypeError` if *value* is anything else — including a bare
    ``str``, which Python would otherwise silently coerce into a list of
    individual characters via ``list(...)``. The early raise turns a typo
    like ``tracked_functions = "open"`` (note the missing brackets) into a
    clear error rather than a tracker that mysteriously matches single
    letters.
    """
    if not isinstance(value, (list, tuple)):
        msg = f"{key_name} must be a list of strings, got {type(value).__name__}"
        raise TypeError(msg)
    non_strings = [item for item in value if not isinstance(item, str)]
    if non_strings:
        bad = ", ".join(f"{type(item).__name__}({item!r})" for item in non_strings)
        msg = f"{key_name} must contain only strings — got: {bad}"
        raise TypeError(msg)
    # Both checks above guarantee every element is a str; the list
    # comprehension is a typing-only re-narrowing for ty/mypy.
    return [item for item in value if isinstance(item, str)]


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
    ``finally_clause`` — *unless* the call we're checking sits inside that
    very ``finally_clause`` itself. A resource acquired inside the finally
    block has no subsequent finally to clean up *itself*, so the
    enclosing try/finally that the call lives inside does not count as
    guarding it. Multiple nested try-statements within the same function
    are tolerated: an outer ``try { ... } finally { ... }`` still counts
    as guarding a deeply-nested call inside that function — provided the
    call is not inside the outer finally.

    **Stops at function boundaries.** If the walk crosses a JavaScript
    function-defining node (``function_declaration``, ``arrow_function``,
    ``method_definition``, etc.) before finding a guarding ``try_statement``,
    the call is *not* guarded — the outer function's ``finally`` block
    runs when the *outer* function returns, not when the inner function
    is invoked later (e.g. via ``setTimeout(callback, 1000)``). Without
    this boundary check the rule would silently miss the most common
    leak pattern of all: an acquirer call inside a callback / arrow /
    method nested in an unrelated outer try/finally.

    Heuristic: the rule still doesn't verify that the ``finally`` block
    actually closes the resource — only that *some* finally exists in
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
            # guarding try/finally — anything further up belongs to a
            # different function whose ``finally`` doesn't run when this
            # call eventually executes.
            return False
        # ``prev.type != "finally_clause"`` skips a try_statement whose
        # finally we just came out of — that finally is the *parent* of
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


class ResourceLifecycleRule(BaseRule):
    """Require tracked resource-acquisition calls to be wrapped in cleanup-guaranteed scope.

    Python: the call must appear inside a ``with`` statement (``with
    open(path) as f:``). Bare assignments without ``with`` fire even
    when paired with manual ``f.close()`` — Python's idiom is
    context-manager-first.

    JavaScript: the call must appear inside a ``try`` block whose
    ``try_statement`` has a ``finally_clause`` somewhere up the
    ancestor chain. Heuristic-only — the rule doesn't verify that the
    ``finally`` block actually closes the specific resource. Captures
    the most common "I created a stream and didn't handle cleanup at
    all" leak. JavaScript's newer ``using`` declarations (Stage 3 /
    Node 22+) aren't yet recognised as a safe form; for now, wrap
    inside ``try { ... } finally { ... }``.
    """

    name = "resource_lifecycle"
    code = "SAFE401"
    language = ("python", "javascript")

    _DEFAULT_TRACKED_JAVASCRIPT: ClassVar[list[str]] = [
        # File / stream APIs.
        "createReadStream",
        "createWriteStream",
        "openSync",  # fs.openSync — returns a raw fd
        # Network / server.
        "createServer",
        "createConnection",  # net.createConnection / db drivers
        "connect",  # database drivers, sockets
        # Worker pools.
        "createWorker",
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
        # tracked_functions — ``cleanup_patterns = "close"`` would coerce
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

    def _javascript_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the JavaScript-specific check (call must be inside ``try { ... } finally { ... }``).

        Walks both ``call_expression`` and ``new_expression`` — the runtime
        presets populate ``tracked_functions_javascript`` with constructor
        names (``Worker``, ``WebSocket``, ``MutationObserver``, ...) that
        are typically invoked via ``new``, so a call-only walk would
        miss exactly the cases the browser preset is designed to catch.
        ``call_name`` resolves both shapes — the rule layer doesn't need
        to branch.
        """
        tracked_js = _validated_string_list(
            self.config.get("tracked_functions_javascript", self._DEFAULT_TRACKED_JAVASCRIPT),
            "tracked_functions_javascript",
        )
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
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"{name}()" not wrapped in try/finally - guarantee cleanup with try {{ ... }} finally {{ ... }}',
                )
            )
        return violations

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag unguarded calls to tracked resource-acquisition functions."""
        lang_name = resolve_lang_name(filepath)
        if lang_name == "python":
            return self._python_check(filepath, tree)
        return self._javascript_check(filepath, tree)
