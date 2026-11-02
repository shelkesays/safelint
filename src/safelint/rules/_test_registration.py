"""Shared recognition of tests whose body is passed to a registration call.

Python, Java, Rust, PHP and C declare a test as a named function, so a name
prefix identifies it. JavaScript, TypeScript and Go do not: the body is a
callback handed to a registration function.

    it("rejects a short password", () => { ... })   // Jest / Vitest / Mocha
    t.Run("short password", func(t *testing.T) { ... })  // Go subtest

Both forms are anonymous, so ``test_functions_only`` used to skip every one of
them: for the JS family the option did not scope SAFE601 to tests, it turned
the rule off for them (#222). This module answers the two questions that costs:

* :func:`describe_function` - is this function a registered test, and what
  should the finding call it? An anonymous callback reported as
  ``Function "<anonymous>"`` at a line number is hard to place; the
  registration call's first string argument is the test's own title, which is
  what the developer searches for.
* :func:`registers_tests` - does this function *register* tests rather than be
  one? A Go table-driven ``TestFoo`` whose assertions all live in ``t.Run``
  subtests asserts nothing in its own body, and the assertion counters stop at
  nested functions by design (they must, or an outer function would be
  credited for a closure's asserts). Without this question the parent reports
  as assertion-free while every one of its subtests asserts. The same answer
  covers a Mocha / Jest ``describe`` block.

Lives in ``rules/`` beside :mod:`rules._test_files` as a private shared helper
so the registration vocabulary has one definition rather than one per rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from safelint.languages import go as _go
from safelint.languages import javascript as _js
from safelint.languages._node_utils import CALL_TYPES, node_text, walk


if TYPE_CHECKING:
    import tree_sitter


#: Node type holding a call's arguments, per language. Only the languages whose
#: tests are registered through a callback appear here; everywhere else a
#: function is recognised as a test by its name alone and these lookups are
#: skipped entirely.
_ARGUMENT_LIST_BY_LANG: dict[str, str] = {
    "javascript": _js.ARGUMENTS,
    "typescript": _js.ARGUMENTS,
    "go": _go.ARGUMENT_LIST,
}

#: Node types that carry a name inside a callee chain, per language. Matching is
#: against the chain rather than the resolved call name because ``call_name``
#: keeps only the trailing bareword: ``it.only(...)`` resolves to ``"only"`` and
#: ``t.test(...)`` to ``"test"``, so neither a modifier form nor a receiver form
#: can be recognised from that name alone.
_CALLEE_NAME_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "javascript": frozenset({_js.IDENTIFIER, _js.PROPERTY_IDENTIFIER}),
    "typescript": frozenset({_js.IDENTIFIER, _js.PROPERTY_IDENTIFIER}),
    "go": frozenset({_go.IDENTIFIER, _go.FIELD_IDENTIFIER}),
}

#: String-literal node types whose text is a test title, per language.
_TITLE_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "javascript": frozenset({_js.STRING, _js.TEMPLATE_STRING}),
    "typescript": frozenset({_js.STRING, _js.TEMPLATE_STRING}),
    "go": frozenset({_go.INTERPRETED_STRING_LITERAL, _go.RAW_STRING_LITERAL}),
}

#: Quote characters stripped from a title literal's text. ``node_text`` returns
#: the literal including its delimiters, and Go's raw strings use backticks.
_QUOTES = "\"'`"


class TestSubject(NamedTuple):
    """How to describe a function in a finding, and whether it is a test.

    *label* is the complete subject of the message (``Function "parse"`` or
    ``Test "rejects a short password"``), so the message formatter stays a
    single owner of the wording and does not re-decide which noun to use.

    *is_registered_test* says the function was passed to a configured
    registration call. It is what lets ``test_functions_only`` keep a callback
    that no name prefix could ever match.
    """

    label: str
    is_registered_test: bool


def describe_function(func_node: tree_sitter.Node, lang_name: str, registration_calls: frozenset[str], func_name: str) -> TestSubject:
    """Return how to label *func_node* and whether it is a registered test.

    A registered test with a resolvable title is labelled by that title; one
    whose title is computed (Go's table-driven ``t.Run(c.name, ...)``) keeps the
    function label, because inventing a name for it would be worse than saying
    it is anonymous.
    """
    call = _enclosing_call(func_node, lang_name)
    if call is None or not (_callee_names(call, lang_name) & registration_calls):
        return TestSubject(f'Function "{func_name}"', is_registered_test=False)
    title = _first_title_argument(call, lang_name)
    if title is None:
        return TestSubject(f'Function "{func_name}"', is_registered_test=True)
    return TestSubject(f'Test "{title}"', is_registered_test=True)


def registers_tests(func_node: tree_sitter.Node, lang_name: str, registration_calls: frozenset[str], function_types: frozenset[str]) -> bool:
    """Return True when *func_node*'s own body registers tests through a callback.

    Such a function delegates its assertions to the callbacks it registers, and
    each of those is checked on its own merit, so reporting the parent as well
    would be a false positive on exactly the two shapes the ecosystem
    recommends: Go's table-driven subtests and a ``describe`` block.

    The walk prunes nested function bodies, so the registration call is found
    at the parent's own level while the callback's contents stay out of it.
    """
    if not registration_calls or lang_name not in _ARGUMENT_LIST_BY_LANG:
        return False
    for node in walk(func_node, skip_types=tuple(function_types)):
        if node is func_node or node.type not in CALL_TYPES:
            continue
        if not (_callee_names(node, lang_name) & registration_calls):
            continue
        if _has_function_argument(node, function_types):
            return True
    return False


def _enclosing_call(func_node: tree_sitter.Node, lang_name: str) -> tree_sitter.Node | None:
    """Return the call that takes *func_node* as a direct argument, or None."""
    argument_list = _ARGUMENT_LIST_BY_LANG.get(lang_name)
    if argument_list is None:
        return None
    parent = func_node.parent
    if parent is None or parent.type != argument_list:
        return None
    call = parent.parent
    if call is None or call.type not in CALL_TYPES:
        return None
    return call


def _callee_names(call_node: tree_sitter.Node, lang_name: str) -> set[str]:
    """Return every name in *call_node*'s callee chain.

    Collecting the whole chain is what covers all four registration shapes with
    one test: the bare ``it(...)``, the modifier ``it.only(...)`` /
    ``test.skip(...)``, the parametrised ``it.each(table)(...)`` (whose callee
    is itself a call), and Go's ``t.Run(...)`` receiver form.

    The pruning matters: ``it.each(cases)(...)`` has the table *inside* the
    callee, so without it a variable named ``test`` in that table would read as
    a registration name.
    """
    callee = call_node.child_by_field_name("function")
    if callee is None:  # pragma: no cover - defensive: a call always has a function field
        return set()
    name_types = _CALLEE_NAME_TYPES_BY_LANG[lang_name]
    pruned = (_ARGUMENT_LIST_BY_LANG[lang_name],)
    return {node_text(node) for node in walk(callee, skip_types=pruned) if node.type in name_types}


def _first_title_argument(call_node: tree_sitter.Node, lang_name: str) -> str | None:
    """Return the unquoted text of *call_node*'s first argument when it is a string.

    Only the first argument, because that is where every framework in scope puts
    the title. A computed title yields None rather than the expression's source
    text, which would read as a quoted literal in the message and send the
    developer looking for a test by the wrong name.
    """
    arguments = call_node.child_by_field_name("arguments")
    if arguments is None:  # pragma: no cover - defensive: a call always has an arguments field
        return None
    first = next((child for child in arguments.named_children if not child.is_extra), None)
    if first is None or first.type not in _TITLE_TYPES_BY_LANG[lang_name]:
        return None
    return node_text(first).strip(_QUOTES)


def _has_function_argument(call_node: tree_sitter.Node, function_types: frozenset[str]) -> bool:
    """Return True if *call_node* is passed a function as one of its arguments.

    Guards :func:`registers_tests` against crediting a call that merely shares a
    registration name: ``t.Run`` with no callback registers no subtest, and a
    production ``runner.test(value)`` is not a ``describe`` block.
    """
    arguments = call_node.child_by_field_name("arguments")
    if arguments is None:  # pragma: no cover - defensive: a call always has an arguments field
        return False
    return any(child.type in function_types for child in arguments.named_children)
