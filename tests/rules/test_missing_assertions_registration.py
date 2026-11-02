"""Tests for SAFE601 recognising tests registered through a callback (#222).

JavaScript and TypeScript tests are written as callbacks handed to ``it`` /
``test``, so they are anonymous: before this, ``test_functions_only = true``
skipped every one of them and the option turned the rule off for the JS family
instead of scoping it to tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with ``missing_assertions`` enabled and scoped to tests."""
    base = {"rules": {"missing_assertions": {"enabled": True, "test_functions_only": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    return SafetyEngine(deep_merge(DEFAULTS, base))


def _safe601(engine: SafetyEngine, sample: Path) -> list[str]:
    """Return the SAFE601 messages for *sample*."""
    result = engine.check_file(str(sample))
    return [v.message for v in result.violations if v.code == "SAFE601"]


@pytest.mark.parametrize(
    "registration",
    (
        'it("a title", () => { const x = 1; })',
        'test("a title", function () { const x = 1; })',
        'it.only("a title", () => { const x = 1; })',
        'test.skip("a title", () => { const x = 1; })',
        'it.concurrent("a title", async () => { const x = 1; })',
        'it.failing("a title", () => { const x = 1; })',
        't.test("a title", (t) => { const x = 1; })',
        'it.each([[1], [2]])("a title", (n) => { const x = n; })',
        'it.each`a`("a title", () => { const x = 1; })',
    ),
)
def test_registered_test_without_assertions_fires_with_its_title(tmp_path: Path, registration: str) -> None:
    """Every registration shape is recognised, and the finding carries the title.

    The bare form, the four modifier forms, node:test's receiver form and both
    parametrised forms. ``call_name`` cannot distinguish these - it resolves
    ``it.only(...)`` to ``"only"`` - which is why the callee chain is matched.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text(f"{registration};\n", encoding="utf-8")
    assert _safe601(_engine(), sample) == ['Test "a title" has no assertions']


def test_registered_test_with_an_assertion_is_clean(tmp_path: Path) -> None:
    """An ``it`` callback that asserts does not fire."""
    sample = tmp_path / "a.test.js"
    sample.write_text('it("asserts", () => { expect(1).toBe(1); });\n', encoding="utf-8")
    assert _safe601(_engine(), sample) == []


def test_typescript_inherits_the_javascript_registration_names(tmp_path: Path) -> None:
    """A ``.test.ts`` file resolves ``test_registration_calls_javascript`` via the TS→JS chain."""
    sample = tmp_path / "a.test.ts"
    sample.write_text('it("ts title", (): void => { const x: number = 1; });\n', encoding="utf-8")
    assert _safe601(_engine(), sample) == ['Test "ts title" has no assertions']


def test_named_function_in_a_test_file_still_fires_by_prefix(tmp_path: Path) -> None:
    """The prefix route is untouched: a named ``test*`` function is still checked."""
    sample = tmp_path / "a.test.js"
    sample.write_text("function testNamedNoAssert() { const z = 3; }\n", encoding="utf-8")
    assert _safe601(_engine(), sample) == ['Function "testNamedNoAssert" has no assertions']


def test_hooks_and_plain_helpers_are_not_treated_as_tests(tmp_path: Path) -> None:
    """``beforeEach`` is not a registration call, and an unprefixed helper is out of scope.

    Both are the reason ``test_functions_only`` exists: setup code and helpers
    legitimately assert nothing.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text(
        "beforeEach(() => { const setup = 1; });\nfunction buildFixture() { return 1; }\n",
        encoding="utf-8",
    )
    assert _safe601(_engine(), sample) == []


def test_a_describe_block_is_not_reported_for_its_children_assertions(tmp_path: Path) -> None:
    """A grouping block delegates to the tests inside it, so it is not itself a finding.

    Checked with the scoping OFF, where every function is in scope, because that
    is the configuration in which a ``describe`` callback was reported as
    ``Function "<anonymous>" has no assertions``.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text(
        'describe("a group", () => {\n  it("inner", () => { expect(1).toBe(1); });\n});\n',
        encoding="utf-8",
    )
    engine = _engine({"rules": {"missing_assertions": {"test_functions_only": False}}})
    assert _safe601(engine, sample) == []


def test_a_registering_function_in_scope_is_skipped_not_reported(tmp_path: Path) -> None:
    """A prefixed function whose body only registers tests is not a finding.

    ``testSuite`` matches ``test_function_prefixes``, so it IS in scope; the
    assertion counters stop at nested functions by design, so without the
    delegation guard it would report although every test it registers asserts.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text(
        'function testSuite() {\n  it("inner", () => { expect(1).toBe(1); });\n}\n',
        encoding="utf-8",
    )
    assert _safe601(_engine(), sample) == []


def test_a_registration_call_with_no_callback_does_not_excuse_the_parent(tmp_path: Path) -> None:
    """The guard needs an actual callback argument, not just a matching name.

    ``test(value)`` inside a test function registers nothing, so the function
    has genuinely asserted nothing and must still be reported.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text("function testThing() {\n  test(42);\n}\n", encoding="utf-8")
    assert _safe601(_engine(), sample) == ['Function "testThing" has no assertions']


def test_a_computed_title_keeps_the_anonymous_function_label(tmp_path: Path) -> None:
    """A non-literal title is not rendered as a quoted name.

    The callback is still recognised as a test (it fires under
    ``test_functions_only``), but the label falls back rather than printing an
    expression where a title belongs.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text("it(caseName, () => { const x = 1; });\n", encoding="utf-8")
    assert _safe601(_engine(), sample) == ['Function "<anonymous>" has no assertions']


def test_a_table_identifier_named_test_does_not_register_a_test(tmp_path: Path) -> None:
    """The callee chain stops at the argument list, so a table value cannot match.

    ``other.each(test)("x", fn)`` has an identifier called ``test`` inside the
    callee. Collecting the whole callee subtree would read that as the
    registration name and check an arbitrary callback as a test.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text('other.each(test)("x", () => { const x = 1; });\n', encoding="utf-8")
    assert _safe601(_engine(), sample) == []


def test_registration_names_are_configurable_and_replace_the_default(tmp_path: Path) -> None:
    """``test_registration_calls_javascript`` replaces the shipped list, like the other keys."""
    sample = tmp_path / "a.test.js"
    sample.write_text(
        'scenario("custom", () => { const x = 1; });\nit("builtin", () => { const y = 2; });\n',
        encoding="utf-8",
    )
    engine = _engine({"rules": {"missing_assertions": {"test_registration_calls_javascript": ["scenario"]}}})
    assert _safe601(engine, sample) == ['Test "custom" has no assertions']


def test_a_mistyped_registration_list_fails_loud(tmp_path: Path) -> None:
    """A scalar instead of a list raises rather than iterating characters."""
    sample = tmp_path / "a.test.js"
    sample.write_text('it("a", () => { const x = 1; });\n', encoding="utf-8")
    engine = _engine({"rules": {"missing_assertions": {"test_registration_calls_javascript": "it"}}})
    with pytest.raises(TypeError, match="test_registration_calls_javascript"):
        engine.check_file(str(sample))


def test_the_title_is_used_even_when_scoping_is_off(tmp_path: Path) -> None:
    """The label does not depend on ``test_functions_only``.

    With the scoping off every function is checked, and a reader of that output
    needs the title just as much.
    """
    sample = tmp_path / "a.test.js"
    sample.write_text('it("titled", () => { const x = 1; });\n', encoding="utf-8")
    engine = _engine({"rules": {"missing_assertions": {"test_functions_only": False}}})
    assert _safe601(engine, sample) == ['Test "titled" has no assertions']


def test_python_scoping_is_unchanged(tmp_path: Path) -> None:
    """Control: Python has no registration callbacks, so the prefix route is all there is."""
    sample = tmp_path / "test_thing.py"
    sample.write_text(
        "def test_nothing():\n    x = 1\n\n\ndef helper():\n    y = 2\n",
        encoding="utf-8",
    )
    assert _safe601(_engine(), sample) == ['Function "test_nothing" has no assertions']
