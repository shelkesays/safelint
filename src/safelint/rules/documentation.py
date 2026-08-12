"""documentation rule - functions should contain at least ``min_assertions`` assertions (heuristic)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages import c as _c
from safelint.languages import cpp as _cpp
from safelint.languages import java as _java
from safelint.languages import javascript as _js
from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages import rust as _rust
from safelint.languages import typescript as _ts
from safelint.languages._node_utils import CALL_TYPES, call_name, function_name_node, node_text, resolve_lang_name, walk
from safelint.rules._test_files import _is_test_file
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF}),
    "javascript": _js.FUNCTION_TYPES,
    "typescript": _js.FUNCTION_TYPES,
    "java": _java.FUNCTION_TYPES,
    "rust": _rust.FUNCTION_TYPES,
    "php": _php.FUNCTION_TYPES,
    "c": _c.FUNCTION_TYPES,
    "cpp": _cpp.FUNCTION_TYPES,
}


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
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

    def _resolve_assertion_calls(self, lang_name: str) -> frozenset[str]:
        """Resolve + validate the per-language ``assertion_calls`` list once (frozenset).

        Called once per file in :meth:`check_file` (not per function), so the
        config lookup and frozenset construction are not repeated for every
        function node. Validates as strings so a bare-string typo
        (``assertion_calls_javascript = "assert"``) fails loud instead of
        silently degrading into a set of single characters. TypeScript inherits
        the JS list via the TS→JS fallback in :func:`resolve_lang_config_lookup`;
        Python uses the bare key, every other language the ``_<lang>`` suffix.
        """
        raw, error_key = resolve_lang_config_lookup(self.config, "assertion_calls", lang_name, default=[])
        return frozenset(_validated_string_list(raw, error_key))

    @staticmethod
    def _assertion_count(func_node: tree_sitter.Node, lang_name: str, function_types: frozenset[str], assertion_calls: frozenset[str], minimum: int) -> int:
        """Dispatch to the language-appropriate assertion counter (early-exits at *minimum*).

        Python / Java count the built-in ``assert`` keyword AND *calls* in
        *assertion_calls*; Rust matches assertion macros; PHP and the JS family
        use the generic call-name counter. *assertion_calls* is pre-resolved by
        :meth:`_resolve_assertion_calls`.
        """
        if lang_name == "python":
            return _python_assertion_count(func_node, function_types, assertion_calls, minimum)
        if lang_name == "java":
            return _java_assertion_count(func_node, function_types, assertion_calls, minimum)
        if lang_name == "rust":
            return _rust_assertion_count(func_node, function_types, assertion_calls, minimum)
        # PHP + JS-family (JS / TS): the generic call-name counter.
        return _javascript_assertion_count(func_node, function_types, assertion_calls, minimum)

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
    def _below_minimum_message(func_name: str, count: int, minimum: int) -> str:
        """Render the violation message for a function below the assertion threshold."""
        if count == 0 and minimum == 1:
            return f'Function "{func_name}" has no assertions'
        return f'Function "{func_name}" has {count} assertion(s), minimum is {minimum} (Holzmann rule 5 asks for two per function)'

    def _test_scope(self, filepath: str, lang_name: str) -> tuple[bool, tuple[str, ...] | None]:
        """Resolve the ``test_functions_only`` scoping for *filepath*.

        By default the rule checks *every* function (Holzmann rule 5's
        production-assertion intent). Projects that instead treat SAFE601 as a
        "tests must assert something" guard - where production code validates by
        raising and fixtures / setup helpers legitimately have no assertions -
        set ``test_functions_only = true`` to restrict firing to functions that
        look like tests: named for a ``test_function_prefixes`` entry (default
        ``["test"]``) **and** living in a file safelint recognises as a test
        file (under ``test_dirs``, or matching the language's test-filename
        convention - the same definition SAFE701/702 use).

        Returns ``(skip_file, prefixes)``:

        * ``(False, None)`` - scoping off; check every function.
        * ``(True, None)`` - scoping on but *filepath* is not a test file; the
          caller skips the whole file.
        * ``(False, prefixes)`` - scoping on and this is a test file; the caller
          checks only functions whose name starts with one of *prefixes*.
        """
        if not self.config.get("test_functions_only", False):
            return False, None
        # Validate as a string list so a scalar typo (``test_dirs = "mytests"``)
        # fails loud rather than iterating characters and silently skipping the
        # whole file - matching the fail-loud guard on every other list key.
        test_dirs = _validated_string_list(self.config.get("test_dirs", ["tests"]), "test_dirs")
        if not _is_test_file(filepath, test_dirs, lang_name):
            return True, None
        prefixes = tuple(_validated_string_list(self.config.get("test_function_prefixes", ["test"]), "test_function_prefixes"))
        return False, prefixes

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions with fewer than ``min_assertions`` assertions."""
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        minimum = self._resolve_min_assertions()
        skip_file, prefixes = self._test_scope(filepath, lang_name)
        if skip_file:
            return []
        assertion_calls = self._resolve_assertion_calls(lang_name)  # resolved once per file, not per function
        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            name_node = function_name_node(node, lang_name)
            func_name = node_text(name_node) if name_node else "<anonymous>"
            if prefixes is not None and not func_name.startswith(prefixes):
                continue
            count = self._assertion_count(node, lang_name, function_types, assertion_calls, minimum)
            if count >= minimum:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    self._below_minimum_message(func_name, count, minimum),
                )
            )
        return violations
