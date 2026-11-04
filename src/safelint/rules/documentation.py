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
from safelint.rules._test_identity import describe_function, is_harness, marked_as_test, registers_tests
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

    *call_prefixes* match a call by how its name STARTS, which is how a
    project's own helper counts without being enumerated (#251): a test whose
    only assertion goes through ``assertIllegalArgumentException(...)`` asserts,
    and exact-name matching read it as assertion-free. It is populated only when
    the function being counted was identified as a test, so a production method
    named ``assertValid()`` is never credited outside one; see
    :meth:`MissingAssertionsRule._check_function`.
    """

    calls: frozenset[str]
    receivers: frozenset[str]
    call_prefixes: tuple[str, ...]


class _FileScope(NamedTuple):
    """Everything resolved once per file, so no per-function work repeats it.

    Carried as one value because the per-function check needs all of it and
    threading the pieces individually would push the helper past the argument
    limit the project holds itself to.

    *scoped* is ``test_functions_only``. *file_is_test* gates the two identity
    routes that need the function to live in a test file (a name prefix, a
    registration callback) and not the marker route, which stands on its own.
    It is resolved whatever *scoped* says, because test identity decides more
    than whether a function is checked: it also decides whether an ``assert*``
    helper counts and whether a callback's assertions do (#251, #252). Reading
    it only under *scoped* left both off for genuine tests under
    ``test_functions_only = false``.
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


def _matches_assertion_name(name: str | None, calls: frozenset[str], call_prefixes: tuple[str, ...]) -> bool:
    """Return True when *name* is an assertion by exact name or by prefix.

    Exact matching is the allowlist the rule has always used. The prefix route
    is what recognises a project's own helper: ``assertEqualCharNodes``,
    ``assertNullPointerException`` and the hundreds of others a large test suite
    grows are all assertions, and enumerating them per project does not scale
    (commons-lang alone needed eight entries to clear half its findings).

    *call_prefixes* is empty unless the enclosing function was identified as a
    test, which is what bounds the obvious risk: inside a test an
    ``assert``-prefixed call is an assertion, and outside one it is not
    credited at all.
    """
    if not name:
        return False
    return name in calls or _matches_prefix(name, call_prefixes)


def _matches_prefix(name: str | None, call_prefixes: tuple[str, ...]) -> bool:
    """Return True when *name* starts with one of *call_prefixes*.

    One owner for the prefix test, because Rust asks it of a plain call while
    every other language folds it into
    :func:`_matches_assertion_name`. An empty *call_prefixes* never matches,
    which is how the whole route switches off outside a test.
    """
    if not name or len(call_prefixes) == 0:
        return False
    return name.startswith(call_prefixes)


def _prefix_tuple(values: list[str]) -> tuple[str, ...]:
    """Return *values* as a prefix tuple, dropping any empty entry.

    ``"name".startswith("")`` is True for every name, so a single empty entry
    would credit every call in every test as an assertion and silently disable
    the rule wherever it is scoped to tests. Nobody means that, and the two
    plausible intentions both land on the right answer once it is dropped:
    ``[""]`` becomes the empty tuple, which is how the route is switched off,
    and ``["assert", ""]`` keeps ``assert``.

    Not a loud failure, because the shape is valid (it is a list of strings,
    which is what :func:`_validated_string_list` polices) and the result is
    what the user asked for either way.
    """
    return tuple(value for value in values if value)


def _python_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], spec: _AssertionSpec, minimum: int) -> int:
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

    Matching is by call NAME only (receiver stripped), the same allowlist
    approach as the other languages' detectors and
    ``tainted_sink.sanitizers`` - and what lets a *bare* project helper
    (``verify_invariant(x)``) count when added to ``assertion_calls``.
    Requiring a specific receiver (``self`` / ``pytest``) to reduce the
    name-collision false-negative (a production call literally named
    ``fail`` / ``raises`` credited as an assertion) would break that
    configurability and newly false-positive on assertions written with
    an unrecognised receiver, so it is intentionally not done;
    ``test_functions_only`` scopes the rule to test functions instead. Inside
    a test an ``assert``-prefixed name also counts, so a project's own helper
    needs no entry (see :func:`_matches_assertion_name`).

    *function_types* is empty when the function being counted is itself a
    test, which is what lets a callback's assertions count (#252); the caller
    decides, so the walk here simply honours what it is given. Counting stops
    as soon as *minimum* is reached - the rule only needs to know whether the
    threshold is met, not the exact total of a heavily-asserted body.
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node:
            continue
        is_call = c.type in CALL_TYPES and _matches_assertion_name(call_name(c), spec.calls, spec.call_prefixes)
        is_assert = c.type == _py.ASSERT_STATEMENT or is_call
        if not is_assert:
            continue
        count += 1
        if count >= minimum:
            return count
    return count


def _java_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], spec: _AssertionSpec, minimum: int) -> int:
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
    * **A project's own ``assert*`` helper**, inside a test, by prefix.
      Java test suites grow these by the hundred
      (``assertIllegalArgumentException``, ``assertEqualCharNodes``), and they
      were the single largest class of SAFE601 finding on commons-lang and
      Guava once the rule was scoped to tests (#251).

    Skips nested function bodies (inner class methods, lambdas) unless the
    method being counted is itself a test, in which case an assertion inside a
    lambda it hands to someone else still counts (#252).
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node:
            continue
        is_call = c.type in CALL_TYPES and _matches_assertion_name(call_name(c), spec.calls, spec.call_prefixes)
        is_assert = c.type == _java.ASSERT_STATEMENT or is_call
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


def _counts_as_rust_assertion(node: tree_sitter.Node, spec: _AssertionSpec) -> bool:
    """Return True when *node* is a Rust assertion, by macro name or helper prefix.

    The standard library's assertions are all macros, which is why
    ``assertion_calls_rust`` is a macro-name list and is matched against nothing
    else: a plain function literally named ``panic`` or ``unreachable`` is not
    an assertion, and the names in that list only mean what they mean with the
    ``!``.

    A project's own helper is the exception, because it is ordinarily a
    function: ``fn assert_roundtrip(a: &Foo)`` called from a test asserts, and
    counting only macros read every such test as assertion-free. Only the
    PREFIX route reaches a call, so this stays off outside a test and no
    configured macro name leaks into call matching (#251).
    """
    if node.type == _rust.MACRO_INVOCATION:
        macro = node.child_by_field_name("macro")
        if macro is None:
            return False
        return _matches_assertion_name(_rust_macro_name(macro), spec.calls, spec.call_prefixes)
    return node.type in CALL_TYPES and _matches_prefix(call_name(node), spec.call_prefixes)


def _rust_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], spec: _AssertionSpec, minimum: int) -> int:
    """Count assertions in the Rust function body, stopping at *minimum*.

    tree-sitter-rust parses an assertion macro as ``macro_invocation`` with a
    ``macro`` field carrying the bareword or qualified name;
    :func:`_counts_as_rust_assertion` decides what qualifies.

    Skips nested function / closure bodies unless the function being counted is
    itself a test, in which case a closure's assertions are the test's own
    (#252).
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node or not _counts_as_rust_assertion(c, spec):
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


def _go_testing_receivers(func_node: tree_sitter.Node) -> frozenset[str]:
    """Return the parameter names *func_node* declares with a ``testing`` type.

    ``func TestX(t *testing.T)`` yields ``{"t"}``, ``func(b *testing.B)``
    ``{"b"}``, and a shared helper taking ``tb testing.TB`` ``{"tb"}``. A
    subtest literal declares its own, so each is resolved against the function
    being counted rather than the outermost test.

    Matched on the type's source text containing ``testing.``, which covers the
    pointer, value and interface forms without enumerating them.
    """
    parameters = func_node.child_by_field_name("parameters")
    if parameters is None:  # pragma: no cover - defensive: every Go function has a parameter list
        return frozenset()
    names = set()
    for declaration in parameters.named_children:
        name = declaration.child_by_field_name("name")
        type_node = declaration.child_by_field_name("type")
        if name is None or type_node is None or "testing." not in node_text(type_node):
            continue
        names.add(node_text(name))
    return frozenset(names)


def _counts_as_go_assertion(call_node: tree_sitter.Node, spec: _AssertionSpec, testing_receivers: frozenset[str]) -> bool:
    """Return True when *call_node* is an assertion, by one of Go's three shapes.

    The receiver decides, because the shipped names are METHODS on
    ``testing.T`` and ``call_name`` strips the receiver before matching:

    * **A bare call** - matched on name alone exactly as every other language
      does, which is what lets a project add its own helper to
      ``assertion_calls_go``. The callee has to be a plain identifier to
      qualify; a receiver safelint cannot read is not the same thing as no
      receiver at all.
    * **A receiver in ``assertion_receivers_go``** - testify's ``assert.`` /
      ``require.``, where the package is the signal and the function name is
      one of dozens.
    * **Any other receiver** - the name must be configured AND the receiver must
      be a ``testing``-typed parameter of this function. Without that condition
      ``fmt.Errorf("...")`` and ``err.Error()`` counted as assertions, which is
      not an edge case in Go: either one inside a test silenced the finding
      completely.

    Anything else does not count. A chained or computed receiver
    (``s.logger.Errorf(...)``, ``newLogger().Fatal(...)``) reaches no shape: it
    is not a bare call, and nothing identifies it as ``testing``-typed or as a
    testify package.

    The prefix route sits ahead of all three, because a helper's receiver is
    not predictable: ``assertEqual(t, a, b)``, ``h.assertEqual(...)`` and
    ``testutil.assertEqual(...)`` are the same helper written three ways, and
    none is a ``testing``-typed receiver or a testify package. It is live only
    inside a test (#251), and the names that forced the receiver condition in
    the first place (``fmt.Errorf``, ``err.Error``) do not start with
    ``assert``, so the tightening it bypasses still holds.
    """
    name = call_name(call_node)
    if _matches_prefix(name, spec.call_prefixes):
        return True
    if _is_bare_go_call(call_node):
        return name in spec.calls
    receiver = _go_receiver_name(call_node)
    if receiver is None:
        return False
    if receiver in spec.receivers:
        return True
    return receiver in testing_receivers and name in spec.calls


def _is_bare_go_call(call_node: tree_sitter.Node) -> bool:
    """Return True when *call_node*'s callee is a plain identifier.

    ``mustEqual(...)`` is bare; ``t.Fatalf(...)``, ``s.logger.Errorf(...)`` and
    ``newLogger().Fatal(...)`` are not. Asking this separately is what keeps
    "safelint found no receiver" apart from "this call has a receiver safelint
    declined to resolve": ``_go_receiver_name`` answers ``None`` to both, and
    reading that as a bare call credited every nested-selector call whose
    trailing name happened to be configured.
    """
    callee = call_node.child_by_field_name("function")
    return callee is not None and callee.type == _go.IDENTIFIER


def _go_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], spec: _AssertionSpec, minimum: int) -> int:
    """Count assertions in the Go function body, stopping at *minimum*.

    Go has no assertion keyword and no production assertion idiom; a test fails
    by calling a failure method on its ``*testing.T`` / ``B`` / ``F``
    (``t.Fatalf("...")``, ``t.Errorf("...")``), so those names make up
    ``assertion_calls_go`` and are counted only on a ``testing``-typed receiver
    (see :func:`_counts_as_go_assertion`).

    Testify is matched by RECEIVER instead. ``assert`` and ``require`` each
    expose dozens of assertion functions (``Equal``, ``NoError``, ``Len``,
    ``ErrorIs``, ...), so a name list would be long, would go stale against the
    library, and would collide with ordinary method names. ``assertion_receivers_go``
    says "any call on this package counts", which is both shorter and more
    accurate.

    Skips nested function / closure bodies when the function being counted is
    not a test, so an ordinary function is not credited for a closure's
    asserts. A table-driven ``TestXxx`` never reaches the counter at all: the
    delegation guard in :func:`registers_tests` returns before it, which is
    what keeps a parent whose assertions all live in ``t.Run`` subtests from
    reporting.
    """
    count = 0
    testing_receivers = _go_testing_receivers(func_node)
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node or c.type not in CALL_TYPES:
            continue
        if not _counts_as_go_assertion(c, spec, testing_receivers):
            continue
        count += 1
        if count >= minimum:
            return count
    return count


def _javascript_assertion_count(func_node: tree_sitter.Node, function_types: frozenset[str], spec: _AssertionSpec, minimum: int) -> int:
    """Count calls to configured assertion functions, stopping at *minimum*.

    Shared by the JS family, PHP, C and C++: none of them has an ``assert``
    keyword the grammar reports as its own statement, so every assertion is a
    call and the name is all there is to go on. Covers Node's ``assert(...)`` /
    ``assert.equal(...)``, test-framework idioms like ``expect(x).toBe(y)``
    (Jest, where ``expect`` is the call name), ``console.assert(...)``, and a
    project's own ``assert*`` helper inside a test.
    """
    count = 0
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node or c.type not in CALL_TYPES:
            continue
        if not _matches_assertion_name(call_name(c), spec.calls, spec.call_prefixes):
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

    Inside a function identified as a test, two further things count in every
    language: a call whose name starts with an ``assertion_call_prefixes``
    entry (``assert`` by default), so a project's own helper needs no entry of
    its own, and an assertion inside a callback the test hands to someone else.
    Neither applies to a function that is not a test, so an ordinary function is
    still answerable for its own body alone.
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

        One owner for the lookup because the rule now reads six such lists
        (``assertion_calls``, ``extend_assertion_calls``,
        ``assertion_receivers``, ``assertion_call_prefixes``,
        ``test_registration_calls``, ``test_function_prefixes``) and each
        repetition was a chance for one of them to skip the validation.
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

        ``assertion_call_prefixes`` matches a call by how its name starts, so a
        project's own helper counts without being enumerated (#251). Resolved
        here for the whole file; which functions it is actually applied to is
        :meth:`_check_function`'s decision, because it is live only inside a
        test.
        """
        names = self._resolve_list("assertion_calls", lang_name)
        extra = self._resolve_list("extend_assertion_calls", lang_name)
        return _AssertionSpec(
            frozenset(names + extra),
            frozenset(self._resolve_list("assertion_receivers", lang_name)),
            _prefix_tuple(self._resolve_list("assertion_call_prefixes", lang_name, default=["assert"])),
        )

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
            return _python_assertion_count(func_node, function_types, spec, minimum)
        if lang_name == "java":
            return _java_assertion_count(func_node, function_types, spec, minimum)
        if lang_name == "rust":
            return _rust_assertion_count(func_node, function_types, spec, minimum)
        if lang_name == "go":
            return _go_assertion_count(func_node, function_types, spec, minimum)
        # PHP, C, C++ and the JS family: the generic call-name counter.
        return _javascript_assertion_count(func_node, function_types, spec, minimum)

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
        file_is_test = self._file_is_test(filepath, lang_name)
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
        ``runner.test(...)`` callback in application code. A name the language's
        own toolchain reserves for a harness (Go's ``TestMain``) is excluded
        from those two routes: it matches the prefix but has nothing to assert.
        """
        if marked_as_test(node, scope.lang_name, scope.markers):
            return True
        if not scope.file_is_test or is_harness(scope.lang_name, func_name):
            return False
        return subject.is_registered_test or func_name.startswith(scope.prefixes)

    def _check_function(self, filepath: str, node: tree_sitter.Node, scope: _FileScope) -> Violation | None:
        """Return the violation for one function node, or None when it is in the clear.

        Test identity decides three things rather than one: whether the function
        is checked at all under ``test_functions_only``, whether an ``assert*``
        helper counts (#251), and whether an assertion inside a callback the
        function hands to someone else counts (#252). Inside a test there is no
        nested function being credited unfairly, because whatever a test's
        callbacks assert the test asserts, so the skip that protects an ordinary
        function from a closure's asserts is dropped for one.
        """
        name_node = function_name_node(node, scope.lang_name)
        func_name = node_text(name_node) if name_node else "<anonymous>"
        subject = describe_function(node, scope.lang_name, scope.registrations, func_name)
        is_test = self._is_test_function(node, func_name, subject, scope)
        if scope.scoped and not is_test:
            return None
        if registers_tests(node, scope.lang_name, scope.registrations, scope.function_types):
            return None
        spec = scope.assertions if is_test else scope.assertions._replace(call_prefixes=())
        counted_types = frozenset() if is_test else scope.function_types
        count = self._assertion_count(node, counted_types, spec, scope.minimum, scope.lang_name)
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
