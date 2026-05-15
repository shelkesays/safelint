"""documentation rule - functions should contain at least one assert (heuristic)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import ASSERT_STATEMENT, ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
}


def _python_has_assertion(func_node: tree_sitter.Node, function_types: frozenset[str]) -> bool:
    """Return True when the function body contains at least one ``assert`` statement.

    Skips nested function bodies so the outer function isn't credited
    for asserts that live inside an inner ``def``.
    """
    return any(c.type == ASSERT_STATEMENT for c in walk(func_node, skip_types=tuple(function_types)) if c is not func_node)


def _java_has_assertion(func_node: tree_sitter.Node, function_types: frozenset[str], assertion_calls: frozenset[str]) -> bool:
    """Return True when the Java method body contains an assert.

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
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node:
            continue
        if c.type == "assert_statement":
            return True
        if c.type in CALL_TYPES and call_name(c) in assertion_calls:
            return True
    return False


def _javascript_has_assertion(func_node: tree_sitter.Node, function_types: frozenset[str], assertion_calls: frozenset[str]) -> bool:
    """Return True when the function body contains a call to a configured assertion function.

    JS doesn't have a built-in ``assert`` keyword (``assert`` is just a
    function from the ``assert`` module). The rule looks for *calls* to
    any name in *assertion_calls* - covering Node's ``assert(...)`` /
    ``assert.equal(...)`` and test-framework idioms like
    ``expect(x).toBe(y)`` (Jest, where ``expect`` is the call name) and
    ``console.assert(...)``.
    """
    for c in walk(func_node, skip_types=tuple(function_types)):
        if c is func_node:
            continue
        if c.type not in CALL_TYPES:
            continue
        name = call_name(c)
        if name and name in assertion_calls:
            return True
    return False


class MissingAssertionsRule(BaseRule):
    """Warn when a function contains no assert statements (disabled by default).

    Python: walks for the AST ``assert_statement`` (built-in keyword).

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
    language = ("python", "javascript", "typescript", "java")

    def _has_assertion(self, func_node: tree_sitter.Node, lang_name: str, function_types: frozenset[str]) -> bool:
        """Dispatch to the language-appropriate assertion-presence check.

        Validates the per-language ``assertion_calls`` list as strings
        before building the frozenset. A bare-string typo
        (``assertion_calls_javascript = "assert"``) would otherwise be
        coerced into ``{'a', 's', 'e', 'r', 't'}`` and silently break
        detection - fail loud instead. Same shape as the validation
        on ``io_functions_javascript`` and ``global_namespaces_javascript``.
        """
        if lang_name == "python":
            return _python_has_assertion(func_node, function_types)
        if lang_name == "java":
            # Java accepts BOTH the built-in ``assert`` keyword (handled
            # inside ``_java_has_assertion``) AND configured JUnit / AssertJ
            # method-call names. TypeScript inherits the JS list by default
            # via the TS→JS fallback; Java has its own dedicated set.
            raw, error_key = resolve_lang_config_lookup(self.config, "assertion_calls", "java", default=[])
            assertion_calls = frozenset(_validated_string_list(raw, error_key))
            return _java_has_assertion(func_node, function_types, assertion_calls)
        # JS-family (JS / TS): TypeScript inherits the JS list by default
        # via the TS→JS fallback in ``get_per_language_config``.
        raw, error_key = resolve_lang_config_lookup(self.config, "assertion_calls", lang_name, default=[])
        assertion_calls = frozenset(_validated_string_list(raw, error_key))
        return _javascript_has_assertion(func_node, function_types, assertion_calls)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions that lack any assert statement."""
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            if self._has_assertion(node, lang_name, function_types):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else "<anonymous>"
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'Function "{func_name}" has no assert statements',
                )
            )
        return violations
