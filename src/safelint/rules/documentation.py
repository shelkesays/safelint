"""documentation rule - functions should contain at least ``min_assertions`` assertions (heuristic)."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from safelint.core._validators import _validated_bool, _validated_string_list, resolve_lang_config_lookup
from safelint.languages import c as _c
from safelint.languages import cpp as _cpp
from safelint.languages import go as _go
from safelint.languages import java as _java
from safelint.languages import javascript as _js
from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages import rust as _rust
from safelint.languages import typescript as _ts
from safelint.languages._node_utils import CALL_TYPES, call_name, function_name_node, node_text, resolve_lang_name, walk
from safelint.rules._test_files import _DEFAULT_TEST_DIRS, _is_test_file
from safelint.rules._test_identity import describe_function, marked_as_test, registers_tests
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules._test_identity import TestSubject
    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF}),
    "javascript": _js.FUNCTION_TYPES,
    "typescript": _js.FUNCTION_TYPES,
    "java": _java.FUNCTION_TYPES,
    "rust": _rust.FUNCTION_TYPES,
    "go": _go.FUNCTION_TYPES,
    "php": _php.FUNCTION_TYPES,
    "c": _c.FUNCTION_TYPES,
    "cpp": _cpp.FUNCTION_TYPES,
}


class _AssertionSpec(NamedTuple):
    """The resolved per-language vocabulary an assertion counter matches against.

    *calls* are bareword call names (the receiver is already stripped by
    ``call_name``). *receivers* match a call by its receiver instead, which is
    how Go covers testify: ``assert`` and ``require`` expose dozens of
    assertion functions each, and listing every one of them in ``assertion_calls_go``
    would be a maintenance burden that still went stale. Empty for every other
    language, where name matching alone is enough.
    """

    calls: frozenset[str]
    receivers: frozenset[str]


class _FileScope(NamedTuple):
    """Everything resolved once per file, so no per-function work repeats it.

    Carried as one value because the per-function check needs all of it and
    threading the pieces individually would push the helper past the argument
    limit the project holds itself to.

    *scoped* is ``test_functions_only``. *file_is_test* is only meaningful when
    *scoped*; it gates the two identity routes that need the function to live in
    a test file (a name prefix, a registration callback) and not the marker
    route, which stands on its own.
    """

    lang_name: str
    function_types: frozenset[str]
    scoped: bool
    file_is_test: bool
    prefixes: tuple[str, ...]
    markers: frozenset[str]
    assertions: _AssertionSpec
    registrations: frozenset[str]
    minimum: int


def _python_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], assertion_calls: frozenset[str], minimum: int) -> int:
    """Count assertions in the Python function body, stopping at *minimum*.

    Two recognised forms, OR'd together:

    * **Built-in ``assert`` keyword**: ``assert x > 0`` parses as
      ``assert_statement`` - the original, always-counted form.
    * **Assertion method calls**: unittest / Django ``TestCase`` bodies
      assert via method calls (``self.assertEqual(...)`` /
      ``self.assertRaises(...)``), and pytest via ``pytest.raises(...)`` /
      ``pytest.warns(...)``. The rule counts *calls* matching the
      configured ``assertion_calls`` set; ``call_name`` strips the
      receiver (``self.assertEqual`` and ``pytest.raises`` resolve to
      ``"assertEqual"`` / ``"raises"``). Without this, every
      unittest-style test reads as assertion-less and forces a file-wide
      SAFE601 ignore.

    Matching is deliberately by call NAME only (receiver stripped), the
    same allowlist approach as the other languages' detectors and
    ``tainted_sink.sanitizers`` - and what lets a *bare* project helper
    (``verify_invariant(x)``) count when added to ``assertion_calls``.
    Requiring a specific receiver (``self`` / ``pytest``) to reduce the
    name-collision false-negative (a production call literally named
    ``fail`` / ``raises`` credited as an assertion) would break that
    configurability and newly false-positive on assertions written with
    an unrecognised receiver, so it is intentionally not done;
    ``test_functions_only`` scopes the rule to test functions instead.

    Skips nested function bodies so the outer function isn't credited
    for asserts that live inside an inner ``def``. Counting stops as
    soon as *minimum* is reached - the rule only needs to know whether
    the threshold is met, not the exact total of a heavily-asserted body.
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node:
            continue
        is_assert = c.type == _py.ASSERT_STATEMENT or (c.type in CALL_TYPES and call_name(c) in assertion_calls)
        if not is_assert:
            continue
        count += 1
        if count >= minimum:
            return count
    return count


def _java_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], assertion_calls: frozenset[str], minimum: int) -> int:
    """Count assertions in the Java method body, stopping at *minimum*.

    Two recognised forms, OR'd together:

    * **Built-in ``assert`` keyword** (Java 1.4+): ``assert x > 0;`` /
      ``assert x > 0 : "x positive";`` parses as ``assert_statement``,
      identical in spirit to Python's ``assert``.
    * **JUnit / AssertJ / Hamcrest assertion method calls**: ``assertEquals(x, y)``,
      ``assertThat(x).isEqualTo(y)``, ``assertNotNull(x)``, ``assertThrows(...)``,
      ``fail("...")``. The rule looks for *calls* matching the configured
      ``assertion_calls_java`` set; ``call_name`` already strips the
      receiver (``Assertions.assertEquals`` and ``assertEquals``
      both resolve to ``"assertEquals"``).

    Skips nested function bodies (inner class methods, lambdas) so the
    outer method isn't credited for asserts that live in a closure body.
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node:
            continue
        is_assert = c.type == _java.ASSERT_STATEMENT or (c.type in CALL_TYPES and call_name(c) in assertion_calls)
        if not is_assert:
            continue
        count += 1
        if count >= minimum:
            return count
    return count


def _rust_macro_name(macro_node: tree_sitter.Node) -> str | None:
    """Return the bareword macro name from a Rust ``macro_invocation`` ``macro`` field.

    The ``macro`` field is one of:

    * ``identifier`` - bare ``assert!`` / ``debug_assert_eq!``. Return as-is.
    * ``scoped_identifier`` - qualified ``std::assert!`` / ``core::panic!``.
      Return the trailing identifier (``"assert"`` / ``"panic"``) so that
      ``assertion_calls_rust`` can use bareword names without needing the
      caller to list every plausible qualifier.

    Returns ``None`` for shapes the rule can't resolve (an empty
    scoped_identifier with no trailing name etc.); the caller's filter
    naturally skips those.
    """
    if macro_node.type == _rust.IDENTIFIER:
        return node_text(macro_node)
    if macro_node.type == _rust.SCOPED_IDENTIFIER:
        name = macro_node.child_by_field_name("name")
        return node_text(name) if name is not None else None
    return None


def _rust_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], assertion_calls: frozenset[str], minimum: int) -> int:
    """Count assertion macros in the Rust function body, stopping at *minimum*.

    Rust expresses assertions exclusively through macros (``assert!``,
    ``assert_eq!``, ``assert_ne!``, ``debug_assert!``, etc.), NOT
    function calls. tree-sitter-rust parses these as
    ``macro_invocation`` with a ``macro`` field carrying the bareword
    or qualified macro name.

    Skips nested function / closure bodies so the outer function
    isn't credited for asserts that live in a closure body.
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node or c.type != _rust.MACRO_INVOCATION:
            continue
        macro = c.child_by_field_name("macro")
        if macro is None:
            continue
        name = _rust_macro_name(macro)
        if name is None or name not in assertion_calls:
            continue
        count += 1
        if count >= minimum:
            return count
    return count


def _go_receiver_name(call_node: tree_sitter.Node) -> str | None:
    """Return the receiver bareword of a Go method or package call, or None.

    ``assert.Equal(t, a, b)`` has its callee on a ``selector_expression`` whose
    ``operand`` is the receiver (``assert``) and whose ``field`` is the method
    (``Equal``). Only an identifier operand is returned: a chained or indexed
    receiver (``s.deps.assert.Equal``) is not a package-qualified assertion
    helper, and treating its trailing name as one would credit arbitrary method
    calls.
    """
    callee = call_node.child_by_field_name("function")
    if callee is None or callee.type != _go.SELECTOR_EXPRESSION:
        return None
    operand = callee.child_by_field_name("operand")
    if operand is None or operand.type not in (_go.IDENTIFIER, _go.PACKAGE_IDENTIFIER):
        return None
    return node_text(operand)


def _go_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], spec: _AssertionSpec, minimum: int) -> int:
    """Count assertions in the Go function body, stopping at *minimum*.

    Go has no assertion keyword and no production assertion idiom; a test fails
    by calling a failure method on its ``*testing.T`` / ``B`` / ``F``
    (``t.Fatalf("...")``, ``t.Errorf("...")``), so those names make up
    ``assertion_calls_go``.

    Testify is matched by RECEIVER instead. ``assert`` and ``require`` each
    expose dozens of assertion functions (``Equal``, ``NoError``, ``Len``,
    ``ErrorIs``, ...), so a name list would be long, would go stale against the
    library, and would collide with ordinary method names. ``assertion_receivers_go``
    says "any call on this package counts", which is both shorter and more
    accurate.

    Skips nested function / closure bodies, so a table-driven test is not
    credited for the asserts inside its subtests; the delegation guard in
    :func:`registers_tests` is what keeps that parent from reporting.
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node or c.type not in CALL_TYPES:
            continue
        if call_name(c) not in spec.calls and _go_receiver_name(c) not in spec.receivers:
            continue
        count += 1
        if count >= minimum:
            return count
    return count


def _javascript_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], assertion_calls: frozenset[str], minimum: int) -> int:
    """Count calls to configured assertion functions, stopping at *minimum*.

    JS doesn't have a built-in ``assert`` keyword (``assert`` is just a
    function from the ``assert`` module). The rule looks for *calls* to
    any name in *assertion_calls* - covering Node's ``assert(...)`` /
    ``assert.equal(...)`` and test-framework idioms like
    ``expect(x).toBe(y)`` (Jest, where ``expect`` is the call name) and
    ``console.assert(...)``.
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node or c.type not in CALL_TYPES:
            continue
        name = call_name(c)
        if not name or name not in assertion_calls:
            continue
        count += 1
        if count >= minimum:
            return count
    return count


class MissingAssertionsRule(BaseRule):
    """Warn when a function has fewer than ``min_assertions`` assertions (disabled by default).

    Python: counts the AST ``assert_statement`` (built-in keyword) AND
    *calls* to a configured set of assertion-method names
    (``assertion_calls``), so unittest / Django ``TestCase`` bodies that
    assert only via ``self.assertEqual(...)`` / ``pytest.raises(...)``
    are recognised rather than read as assertion-less.

    JavaScript: walks for *calls* to a configured set of assertion
    function names. Default set covers Node's ``assert`` module
    (``assert``, ``ok``, ``equal``, ``strictEqual``, ``deepEqual``,
    ``deepStrictEqual``, ``notEqual``, ``notStrictEqual``,
    ``rejects``, ``throws``, ``doesNotThrow``, ``doesNotReject``,
    ``fail``, ``ifError``, ``match``), browser/Node ``console.assert``,
    and the most common test frameworks' entry points (``expect`` for
    Jest / Chai-via-``expect``, ``should`` for Should.js,
    ``vi.expect`` for Vitest - ``vi`` is the receiver, ``expect`` is
    the call name). User can override via ``assertion_calls_javascript``
    in TOML config.
    """

    name = "missing_assertions"
    code = "SAFE601"
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _go.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

    def _resolve_list(self, base_key: str, lang_name: str, default: list[str] | None = None) -> list[str]:
        """Resolve + validate one per-language string-list option.

        Validates as strings so a bare-string typo
        (``assertion_calls_javascript = "assert"``) fails loud instead of
        silently degrading into a set of single characters. TypeScript inherits
        the JavaScript list via the TS→JS fallback in
        :func:`resolve_lang_config_lookup`; Python uses the bare key, every
        other language the ``_<lang>`` suffix. The error is reported against the
        key the value actually came from, not the key for this file's language.

        One owner for the lookup because the rule now reads five such lists
        (``assertion_calls``, ``extend_assertion_calls``,
        ``assertion_receivers``, ``test_registration_calls``,
        ``test_function_prefixes``) and each repetition was a chance for one of
        them to skip the validation.
        """
        raw, error_key = resolve_lang_config_lookup(self.config, base_key, lang_name, default=default if default is not None else [])
        return _validated_string_list(raw, error_key)

    def _resolve_assertions(self, lang_name: str) -> _AssertionSpec:
        """Resolve the per-language assertion vocabulary once (names + receivers).

        Called once per file in :meth:`check_file` (not per function), so the
        config lookups and frozenset construction are not repeated for every
        function node.

        ``extend_assertion_calls`` appends instead of replacing, so a project
        adding one helper does not have to copy the 66-name default list and
        then maintain it against future releases (#220). Same split as
        ``resource_lifecycle``'s ``extend_tracked_functions``, and per language
        through the same key chain, so a TS file picks up
        ``extend_assertion_calls_javascript`` exactly as it inherits the base
        list. Absent from DEFAULTS by design: an extension defaults to empty.

        ``assertion_receivers`` matches a call by its receiver rather than its
        name, which is how Go recognises testify (#221). Empty everywhere else.
        """
        names = self._resolve_list("assertion_calls", lang_name)
        extra = self._resolve_list("extend_assertion_calls", lang_name)
        return _AssertionSpec(frozenset(names + extra), frozenset(self._resolve_list("assertion_receivers", lang_name)))

    @staticmethod
    def _assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], spec: _AssertionSpec, minimum: int, lang_name: str) -> int:
        """Dispatch to the language-appropriate assertion counter (early-exits at *minimum*).

        Python / Java count the built-in ``assert`` keyword AND *calls* in
        *spec*; Rust matches assertion macros; Go adds receiver matching so
        testify is covered without listing its API; PHP and the JS family use
        the generic call-name counter.
        *spec* is pre-resolved by :meth:`_resolve_assertions`.
        """
        if lang_name == "python":
            return _python_assertion_count(func_node, function_types, spec.calls, minimum)
        if lang_name == "java":
            return _java_assertion_count(func_node, function_types, spec.calls, minimum)
        if lang_name == "rust":
            return _rust_assertion_count(func_node, function_types, spec.calls, minimum)
        if lang_name == "go":
            return _go_assertion_count(func_node, function_types, spec, minimum)
        # PHP + JS-family (JS / TS): the generic call-name counter.
        return _javascript_assertion_count(func_node, function_types, spec.calls, minimum)

    def _resolve_min_assertions(self) -> int:
        """Read and validate the ``min_assertions`` config knob.

        Default 1 (any assertion satisfies the rule). Holzmann's rule 5
        asks for a density of two assertions per function; set
        ``min_assertions = 2`` for the paper's threshold. Strict type
        check (``bool`` is an ``int`` subclass, so it is rejected
        explicitly): a TOML typo like ``min_assertions = "2"`` should
        fail loud, not silently compare a string against a count.
        """
        value = self.config.get("min_assertions", 1)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            msg = f"missing_assertions.min_assertions must be an integer >= 1, got {value!r}"
            raise TypeError(msg)
        return value

    @staticmethod
    def _below_minimum_message(label: str, count: int, minimum: int) -> str:
        """Render the violation message for a subject below the assertion threshold.

        *label* is the complete subject, already decided by
        :func:`describe_function` - ``Function "parse"`` for a named function,
        ``Test "rejects a short password"`` for a registered test callback. The
        noun is chosen there rather than here so one owner decides it.
        """
        if count == 0 and minimum == 1:
            return f"{label} has no assertions"
        return f"{label} has {count} assertion(s), minimum is {minimum} (Holzmann rule 5 asks for two per function)"

    def _file_is_test(self, filepath: str, lang_name: str) -> bool:
        """Return True when *filepath* is a file safelint recognises as holding tests."""
        # Validate as a string list so a scalar typo (``test_dirs = "mytests"``)
        # fails loud rather than iterating characters and silently skipping the
        # whole file - matching the fail-loud guard on every other list key.
        # The fallback is the shared default, not a local copy: SAFE601, 701,
        # 702 and every ``skip_test_code`` rule must agree on where tests live.
        test_dirs = _validated_string_list(self.config.get("test_dirs", _DEFAULT_TEST_DIRS), "test_dirs")
        return _is_test_file(filepath, test_dirs, lang_name)

    def _resolve_scope(self, filepath: str) -> _FileScope | None:
        """Resolve everything the per-function check needs, or None to skip the file.

        ``test_functions_only`` is on by default since 2.16.0 (#163): the rule
        fires only on functions it can identify as tests. Setting it to ``false``
        checks *every* function, which is Holzmann rule 5's production-assertion
        intent read verbatim; that was the shipped default until 2.16.0 and it
        made SAFE601 56-92% of all output on four real codebases, because a
        getter, a trait conversion and a migration hook assert nothing by design.

        The whole file is skipped only when nothing in it could be identified as
        a test: the scoping is on, the file is not a test file, and the language
        has no marker route. Rust and Java do have one, and ``#[test]`` /
        ``@Test`` are unambiguous wherever they appear, so their files are
        walked whatever they are called.

        ``min_assertions`` is validated before all of this so a mistyped
        threshold fails loud on every run rather than only on the files the
        scoping happens to keep.
        """
        lang_name = resolve_lang_name(filepath)
        minimum = self._resolve_min_assertions()
        scoped = _validated_bool(self.config.get("test_functions_only", True), "test_functions_only")
        markers = frozenset(self._resolve_list("test_markers", lang_name))
        file_is_test = scoped and self._file_is_test(filepath, lang_name)
        if scoped and not file_is_test and not markers:
            return None
        return _FileScope(
            lang_name=lang_name,
            function_types=_FUNCTION_TYPES_BY_LANG[lang_name],
            scoped=scoped,
            file_is_test=file_is_test,
            # Per language, because the conventions differ in case as well as
            # shape: Python and PHP use ``test_*``, Go requires ``TestXxx``.
            prefixes=tuple(self._resolve_list("test_function_prefixes", lang_name, default=["test"])),
            markers=markers,
            assertions=self._resolve_assertions(lang_name),
            registrations=frozenset(self._resolve_list("test_registration_calls", lang_name)),
            minimum=minimum,
        )

    @staticmethod
    def _is_test_function(node: tree_sitter.Node, func_name: str, subject: TestSubject, scope: _FileScope) -> bool:
        """Return True when *node* is a test, by any of the three identity routes.

        The marker route stands alone; the prefix and registration routes also
        need the function to live in a test file, because a production
        ``test_connection()`` helper is not a test and neither is a
        ``runner.test(...)`` callback in application code.
        """
        if marked_as_test(node, scope.lang_name, scope.markers):
            return True
        if not scope.file_is_test:
            return False
        return subject.is_registered_test or func_name.startswith(scope.prefixes)

    def _check_function(self, filepath: str, node: tree_sitter.Node, scope: _FileScope) -> Violation | None:
        """Return the violation for one function node, or None when it is in the clear."""
        name_node = function_name_node(node, scope.lang_name)
        func_name = node_text(name_node) if name_node else "<anonymous>"
        subject = describe_function(node, scope.lang_name, scope.registrations, func_name)
        if scope.scoped and not self._is_test_function(node, func_name, subject, scope):
            return None
        if registers_tests(node, scope.lang_name, scope.registrations, scope.function_types):
            return None
        count = self._assertion_count(node, scope.function_types, scope.assertions, scope.minimum, scope.lang_name)
        if count >= scope.minimum:
            return None
        return self._make_violation_for_node(filepath, node, self._below_minimum_message(subject.label, count, scope.minimum))

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions with fewer than ``min_assertions`` assertions."""
        scope = self._resolve_scope(filepath)
        if scope is None:
            return []
        violations = []
        for node in walk(tree.root_node):
            if node.type not in scope.function_types:
                continue
            violation = self._check_function(filepath, node, scope)
            if violation is not None:
                violations.append(violation)
        return violations
