"""Language-agnostic Tree-sitter node utility functions.

These helpers replace ast.walk(), node.lineno, node.name, etc. across all rules.
They work identically regardless of which language grammar was used to parse the tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    import tree_sitter


def walk(
    node: tree_sitter.Node,
    skip_types: Iterable[str] | None = None,
) -> Iterator[tree_sitter.Node]:
    """Yield every named node in the subtree rooted at *node*, depth-first.

    Anonymous tokens (punctuation, keyword tokens) are skipped - only the
    grammar's named nodes are yielded. This is the Tree-sitter analogue
    of the old ``ast.walk()``.

    Implemented iteratively (not recursively) to avoid Python's default
    recursion limit of 1000.

    ``skip_types`` opts into pruning: any descendant whose ``node.type`` is in
    the set has its subtree skipped. The starting *node* itself is always
    yielded even when its type matches - this is the natural shape for
    per-function rules that walk a function body but want to avoid descending
    into nested function definitions.
    """
    skip = frozenset(skip_types) if skip_types else frozenset()
    yield node
    stack: list[tree_sitter.Node] = list(reversed(node.named_children))
    while stack:  # nosafe: SAFE501
        current = stack.pop()
        yield current
        if current.type in skip:
            continue
        stack.extend(reversed(current.named_children))


def lineno(node: tree_sitter.Node) -> int:
    """Return the 1-based start line number of *node*.

    Tree-sitter uses 0-based row numbers. We add 1 to match Python convention
    and to stay compatible with the existing Violation.lineno field.
    """
    return node.start_point[0] + 1


def end_lineno(node: tree_sitter.Node) -> int:
    """Return the 1-based end line number of *node*."""
    return node.end_point[0] + 1


def column_start(node: tree_sitter.Node) -> int:
    """Return the 1-based start column of *node*.

    Tree-sitter reports 0-based columns; we add 1 to match safelint's
    1-based ``lineno`` convention. Editor adapters that need 0-based
    (e.g. LSP-style consumers) are expected to subtract 1 themselves.
    """
    return node.start_point[1] + 1


def column_end(node: tree_sitter.Node) -> int:
    """Return the 1-based end column of *node* (exclusive in Tree-sitter terms).

    Tree-sitter's ``end_point`` is *exclusive* - it points one past the
    last character of the node's span. Returning it as-is (after +1
    normalisation) gives a half-open ``[start, end)`` range that maps
    cleanly to LSP / VSCode ``Range`` semantics.
    """
    return node.end_point[1] + 1


def node_range(node: tree_sitter.Node) -> tuple[int, int, int, int]:
    """Return ``(start_line, end_line, column_start, column_end)`` for *node* - all 1-based.

    Convenience for rule code building :class:`~safelint.rules.base.Violation`
    objects: avoids the noisy ``node.start_point[0] + 1`` /
    ``node.start_point[1] + 1`` triplets at every call site.

    For multi-line constructs (function definitions, ``while`` loops,
    ``except`` clauses) ``end_line`` differs from ``start_line`` and
    ``column_end`` is the column on ``end_line`` (not on
    ``start_line``). Returning all four coordinates lets the caller
    populate ``Violation.end_lineno`` so editor / SARIF consumers
    can render the precise span instead of mis-applying
    ``column_end`` to ``start_line``.
    """
    return lineno(node), end_lineno(node), column_start(node), column_end(node)


def node_text(node: tree_sitter.Node) -> str:
    """Return the source text covered by *node* as a string.

    Returns an empty string if node.text is None (e.g., on error nodes).
    """
    return node.text.decode("utf-8") if node.text else ""


#: Tree-sitter node types that represent a function-call expression
#: across every registered language. Use ``node.type in CALL_TYPES``
#: instead of importing per-language constants when a rule needs to
#: walk calls without caring about source language.
#:
#: * Python: ``call``
#: * JavaScript / TypeScript: ``call_expression``
#: * Java: ``method_invocation`` (regular calls) and
#:   ``object_creation_expression`` (``new Foo(...)``)
CALL_TYPES: frozenset[str] = frozenset({"call", "call_expression", "method_invocation", "object_creation_expression"})


def resolve_lang_name(filepath: str) -> str:
    """Return the active language name for *filepath*, falling back to ``"python"``.

    The engine's dispatch loop only invokes rules whose ``language`` tuple
    matches the resolved language, so this helper always returns a known
    language inside engine-driven calls. The fallback exists for direct
    unit-test invocations of ``check_file`` that pass a placeholder
    filepath with no registered extension - historical tests assume the
    Python rule path, so default there.
    """
    # Local import to avoid a cycle: safelint.languages.__init__ imports
    # from this module via _types / language modules.
    from safelint.languages import get_language_for_file  # noqa: PLC0415

    lang = get_language_for_file(filepath)
    return lang.name if lang is not None else "python"


def _java_method_invocation_name(call_node: tree_sitter.Node) -> str | None:
    """Return the bare method name from a Java ``method_invocation`` node."""
    name_node = call_node.child_by_field_name("name")
    return node_text(name_node) if name_node and name_node.type == "identifier" else None


def _last_type_identifier(type_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the last ``type_identifier`` named child of *type_node*, or None."""
    last_id = None
    for child in type_node.named_children:
        if child.type == "type_identifier":
            last_id = child
    return last_id


def _java_object_creation_name(call_node: tree_sitter.Node) -> str | None:
    """Return the simple class name from a Java ``object_creation_expression``.

    Handles both ``new Foo(...)`` (``type_identifier``) and qualified
    ``new java.io.WriteStream(...)`` (``scoped_type_identifier`` - return
    the trailing identifier).
    """
    type_node = call_node.child_by_field_name("type")
    if type_node is None:
        return None
    if type_node.type == "type_identifier":
        return node_text(type_node)
    if type_node.type != "scoped_type_identifier":
        return None
    last_id = _last_type_identifier(type_node)
    return node_text(last_id) if last_id else None


def _python_js_call_name(call_node: tree_sitter.Node) -> str | None:
    """Return the bareword for a Python ``call`` or JS ``call_expression`` / ``new_expression``."""
    # ``call`` (Python) and ``call_expression`` (JS) expose the callee
    # via the ``function`` field; JS ``new_expression`` uses ``constructor``.
    func_node = call_node.child_by_field_name("function") or call_node.child_by_field_name("constructor")
    if func_node is None:
        return None
    if func_node.type == "identifier":
        return node_text(func_node)
    if func_node.type == "attribute":
        # Python: ``obj.method``. Property is the ``attribute`` field.
        attr_node = func_node.child_by_field_name("attribute")
        return node_text(attr_node) if attr_node else None
    if func_node.type == "member_expression":
        # JavaScript: ``obj.method`` (or ``new fs.WriteStream`` - same shape).
        # Property is the ``property`` field.
        prop_node = func_node.child_by_field_name("property")
        return node_text(prop_node) if prop_node else None
    return None


# Per-call-node-type dispatch: each entry returns the bareword name (or
# ``None``). Kept as a table so adding a new language's call shape is a
# one-line append, and ``call_name`` stays small (no growing chain of
# ``if`` branches that would trip the function-return-count guard).
_CALL_NAME_DISPATCH: dict[str, Callable[[tree_sitter.Node], str | None]] = {
    "method_invocation": _java_method_invocation_name,
    "object_creation_expression": _java_object_creation_name,
}


def call_name(call_node: tree_sitter.Node) -> str | None:
    """Return the bare callable name from a call node, or None if unresolvable.

    Handles call shapes across every registered language:

    * Python ``foo(...)``           - function field is ``identifier`` → ``"foo"``
    * Python ``obj.method(...)``    - function field is ``attribute``  → ``"method"``
    * JavaScript ``foo(...)``       - function field is ``identifier`` → ``"foo"``
    * JavaScript ``obj.method(...)`` - function field is ``member_expression`` → ``"method"``
    * JavaScript ``new Foo(...)``   - *constructor* field on ``new_expression``
      (instead of ``function``) → ``"Foo"`` for the identifier form,
      ``"WriteStream"`` for ``new fs.WriteStream(...)``.
    * Java ``foo(...)`` / ``obj.foo(...)`` - ``method_invocation`` node with
      a ``name`` field carrying the method identifier → ``"foo"``. The
      receiver lives on the ``object`` field, irrelevant for the bareword
      name extraction.
    * Java ``new Foo(...)`` - ``object_creation_expression`` node whose
      ``type`` field carries a ``type_identifier`` or
      ``scoped_type_identifier`` → ``"Foo"`` for the simple case,
      ``"WriteStream"`` for ``new java.io.WriteStream(...)``.

    Returns ``None`` for callees the rule layer can't resolve to a
    bareword (subscripted calls like ``x[0]()``, immediately-invoked
    function expressions, etc.) - rules that filter on call name then
    naturally skip those.

    Callers must pass the call node itself (not the function sub-node).
    """
    handler = _CALL_NAME_DISPATCH.get(call_node.type)
    if handler is not None:
        return handler(call_node)
    return _python_js_call_name(call_node)
