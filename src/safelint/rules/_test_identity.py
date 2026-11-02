"""Shared recognition of what each language calls a test.

``test_functions_only`` scopes SAFE601 to tests, so it needs to know which
functions are tests. Only three languages say so with a name:

* **Python, PHP, C / C++** - a name prefix (``test_foo``), which
  ``test_function_prefixes`` already covers.
* **JavaScript, TypeScript, Go** - the body is a callback handed to a
  registration call, so it has no name of its own::

      it("rejects a short password", () => { ... })        // Jest / Vitest
      t.Run("short password", func(t *testing.T) { ... })  // Go subtest

* **Rust, Java** - an attribute or annotation marks the function, and the name
  is free prose: ``#[test] fn empty_input_is_zero()``,
  ``@Test void shouldRejectShortPassword()``. Rust's dominant idiom also puts
  those tests inside the production file, under ``#[cfg(test)] mod tests``, so
  the file is not a test file either.

Reading test identity from the name alone therefore turned the option off for
five of the nine languages rather than scoping it (#222 for the JS family). This
module owns the other two routes:

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
* :func:`marked_as_test` - is this function marked as a test by an attribute or
  annotation? Unlike the other two routes this one does not care where the
  function lives: ``#[test]`` and ``@Test`` are unambiguous wherever they
  appear, which is what lets Rust's colocated tests be found inside a
  production file.

Lives in ``rules/`` beside :mod:`rules._test_files` as a private shared helper
so the vocabulary has one definition rather than one per rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from safelint.languages import go as _go
from safelint.languages import java as _java
from safelint.languages import javascript as _js
from safelint.languages import rust as _rust
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
    developer looking for a test by the wrong name. An interpolated template
    literal counts as computed; a plain one (no ``${...}``) is a usable title.
    """
    arguments = call_node.child_by_field_name("arguments")
    if arguments is None:  # pragma: no cover - defensive: a call always has an arguments field
        return None
    first = next((child for child in arguments.named_children if not child.is_extra), None)
    if first is None or first.type not in _TITLE_TYPES_BY_LANG[lang_name]:
        return None
    if any(child.type == _js.TEMPLATE_SUBSTITUTION for child in first.named_children):
        # ``it(`case ${name} runs`, ...)`` is a computed title like any other:
        # printing it verbatim puts a literal ``${name}`` in the finding and
        # sends the reader looking for a test by a name that does not exist.
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


#: Names that match a test-name prefix but are not test cases, per language.
#:
#: Go's ``TestMain(m *testing.M)`` is the package's setup harness: the toolchain
#: calls it instead of running the tests directly, and it ends in ``m.Run()``.
#: It matches the ``Test`` prefix, takes no ``*testing.T`` and has nothing to
#: assert, so without this it reported on every Go package that has one. The
#: ``m.Run()`` call cannot excuse it either - the delegation guard needs a
#: callback argument, and ``m.Run()`` takes none.
_NOT_TEST_CASES_BY_LANG: dict[str, frozenset[str]] = {"go": frozenset({"TestMain"})}


#: Node types that carry a test marker for *func_node*, per language. Rust puts
#: its attributes on preceding siblings (``#[test]`` then ``fn``); Java nests
#: its annotations in the method's own ``modifiers`` child.
_MARKER_LANGUAGES: frozenset[str] = frozenset({"rust", "java"})


def marked_as_test(func_node: tree_sitter.Node, lang_name: str, markers: frozenset[str]) -> bool:
    """Return True when an attribute or annotation marks *func_node* as a test.

    Deliberately independent of the file: ``#[test]`` and ``@Test`` say "this is
    a test case" wherever they appear, and Rust's convention is to put them in
    the production file under ``#[cfg(test)] mod tests``. Requiring a test
    *file* as well would leave Rust's dominant idiom unreachable.

    ``#[cfg(test)]`` is NOT a marker here, although
    :mod:`rules._rust_test_attribute` counts it as one for its own two callers.
    The question there is "is this file or node in test context"; the question
    here is "is this function a test case", and a ``#[cfg(test)] fn helper()``
    is test support, not a test.
    """
    if not markers or lang_name not in _MARKER_LANGUAGES:
        return False
    if lang_name == "rust":
        return any(name in markers for name in _rust_attribute_names(func_node))
    return any(name in markers for name in _java_annotation_names(func_node))


def _rust_attribute_names(func_node: tree_sitter.Node) -> set[str]:
    """Return the names of the attributes attached to a Rust function item.

    Attributes are preceding siblings, and they stack: ``#[test]`` followed by
    ``#[should_panic]`` are two ``attribute_item`` nodes before the
    ``function_item``, so the walk continues past the first one it sees. It also
    walks past comments, which tree-sitter puts in the same sibling chain.
    """
    names: set[str] = set()
    sibling = func_node.prev_named_sibling
    while sibling is not None:
        # Comments are extra nodes and sit in the sibling chain, so
        # ``#[ignore] // flaky`` or a comment line above ``fn`` would otherwise
        # end the walk before ``#[test]`` is reached and silently drop the test.
        if sibling.is_extra:
            sibling = sibling.prev_named_sibling
            continue
        if sibling.type != _rust.ATTRIBUTE_ITEM:
            break
        name = _marker_name(_rust_attribute_path(sibling))
        if name is not None:
            names.add(name)
        sibling = sibling.prev_named_sibling
    return names


def _rust_attribute_path(attribute_item: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the path node naming the attribute inside an ``attribute_item``.

    Two hops: the item wraps an ``attribute``, whose first named child is the
    path (``identifier`` for ``#[test]``, ``scoped_identifier`` for
    ``#[tokio::test]``). Reading the ``attribute`` node's own text instead would
    give ``tokio::test`` for the qualified form, which matches no configured
    bareword - the same two-hop descent ``rules/_rust_test_attribute.py`` makes.
    """
    attribute = next((child for child in attribute_item.named_children if child.type == _rust.ATTRIBUTE), None)
    if attribute is None:  # pragma: no cover - defensive: every attribute_item wraps an attribute
        return None
    children = attribute.named_children
    return children[0] if children else None


def _java_annotation_names(func_node: tree_sitter.Node) -> set[str]:
    """Return the names of the annotations on a Java method declaration.

    Both annotation shapes count: the bare ``marker_annotation`` (``@Test``) and
    the ``annotation`` that takes arguments (``@ValueSource(...)``), because
    ``@ParameterizedTest`` is one and its ``@ValueSource`` sibling is the other.
    """
    modifiers = next((child for child in func_node.named_children if child.type == _java.MODIFIERS), None)
    if modifiers is None:
        return set()
    names: set[str] = set()
    for child in modifiers.named_children:
        if child.type not in (_java.MARKER_ANNOTATION, _java.ANNOTATION):
            continue
        name = _marker_name(child.child_by_field_name("name"))
        if name is not None:
            names.add(name)
    return names


def _marker_name(node: tree_sitter.Node | None) -> str | None:
    """Return the bareword name of an attribute or annotation node.

    A qualified marker keeps only its trailing segment, so ``#[tokio::test]``
    reads as ``test`` and ``@org.junit.jupiter.api.Test`` as ``Test``; a user
    configuring ``test_markers_rust`` should not have to enumerate every
    framework's path, and the trailing name is what identifies the marker.
    """
    if node is None:
        return None
    trailing = node.child_by_field_name("name")
    return node_text(trailing if trailing is not None else node)


def is_harness(lang_name: str, func_name: str) -> bool:
    """Return True when *func_name* matches a test prefix but is not a test case.

    See :data:`_NOT_TEST_CASES_BY_LANG`. Deliberately a fixed list rather than a
    config key: the names come from a language's own testing toolchain, not from
    anything a project chooses.
    """
    return func_name in _NOT_TEST_CASES_BY_LANG.get(lang_name, frozenset())
