"""Tests for ``missing_assertions`` (SAFE601) on JavaScript files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _enabled_engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with ``missing_assertions`` enabled (it's off by default)."""
    base = {"rules": {"missing_assertions": {"enabled": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config)


def test_js_function_without_assertions_fires_safe601(tmp_path: Path) -> None:
    """A function with no assertion calls fires SAFE601 (when enabled)."""
    sample = tmp_path / "no_assert.js"
    sample.write_text(
        "function add(a, b) { return a + b; }\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    safe601 = [v for v in result.violations if v.code == "SAFE601"]
    assert len(safe601) == 1
    assert "add" in safe601[0].message


def test_js_function_with_node_assert_does_not_fire(tmp_path: Path) -> None:
    """``assert(condition)`` (Node assert module) satisfies the rule."""
    sample = tmp_path / "node_assert.js"
    sample.write_text(
        "function add(a, b) {\n  assert(typeof a === 'number');\n  return a + b;\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert not any(v.code == "SAFE601" for v in result.violations)


def test_js_function_with_assert_equal_does_not_fire(tmp_path: Path) -> None:
    """``assert.equal(a, b)`` — call_name resolves to ``equal`` which is in the default list."""
    sample = tmp_path / "assert_equal.js"
    sample.write_text(
        "function add(a, b) {\n  assert.equal(typeof a, 'number');\n  return a + b;\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert not any(v.code == "SAFE601" for v in result.violations)


def test_js_function_with_console_assert_does_not_fire(tmp_path: Path) -> None:
    """``console.assert(cond, msg)`` satisfies the rule."""
    sample = tmp_path / "console_assert.js"
    sample.write_text(
        "function add(a, b) {\n  console.assert(typeof a === 'number', 'a must be a number');\n  return a + b;\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert not any(v.code == "SAFE601" for v in result.violations)


def test_js_function_with_jest_expect_does_not_fire(tmp_path: Path) -> None:
    """``expect(x).toBe(y)`` (Jest / Chai) — call_name finds ``expect`` in the default list."""
    sample = tmp_path / "jest.js"
    sample.write_text(
        "function testStuff(x) {\n  expect(x).toBe(42);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert not any(v.code == "SAFE601" for v in result.violations)


def test_js_user_can_extend_assertion_calls(tmp_path: Path) -> None:
    """The default list is config-overridable via ``assertion_calls_javascript``."""
    sample = tmp_path / "custom.js"
    sample.write_text(
        "function f() { mustBe(true); return 1; }\n",
        encoding="utf-8",
    )
    # Without override: ``mustBe`` isn't in the default list, so the rule fires.
    result = _enabled_engine().check_file(str(sample))
    assert any(v.code == "SAFE601" for v in result.violations)

    # With override: rule is satisfied.
    result = _enabled_engine(
        {"rules": {"missing_assertions": {"assertion_calls_javascript": ["mustBe"]}}},
    ).check_file(str(sample))
    assert not any(v.code == "SAFE601" for v in result.violations)


def test_js_assertion_in_nested_function_does_not_credit_outer(tmp_path: Path) -> None:
    """An assertion call inside a nested arrow function doesn't credit the outer function."""
    sample = tmp_path / "nested.js"
    sample.write_text(
        "function outer(a, b) {\n"
        "  const helper = () => { assert(a > 0); };\n"
        "  return a + b;\n"  # outer has no own assert
        "}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    safe601 = [v for v in result.violations if v.code == "SAFE601"]
    # ``outer`` should fire (no own assert); ``helper`` (anonymous arrow)
    # would normally also fire but its parameters are not validated and
    # its body has the assert — so helper is fine.
    assert any("outer" in v.message for v in safe601)


def test_js_assertion_calls_javascript_must_be_list_not_string(tmp_path: Path) -> None:
    """A bare-string typo for ``assertion_calls_javascript`` raises TypeError.

    ``assertion_calls_javascript = "assert"`` would otherwise be
    coerced to ``{'a', 's', 'e', 'r', 't'}`` and silently break
    SAFE601 detection — fail loud instead. Same validation shape as
    ``io_functions_javascript`` (SAFE303 / SAFE304) and
    ``global_namespaces_javascript`` (SAFE302).
    """
    sample = tmp_path / "anything.js"
    sample.write_text("function f(a) { return a + 1; }\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True, "assertion_calls_javascript": "assert"}}})
    with pytest.raises(TypeError, match="assertion_calls_javascript"):
        SafetyEngine(cfg).check_file(str(sample))


def test_js_assertion_calls_javascript_rejects_non_string_entries(tmp_path: Path) -> None:
    """Lists with non-string entries also fail clearly."""
    sample = tmp_path / "anything.js"
    sample.write_text("function f(a) { return a + 1; }\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True, "assertion_calls_javascript": ["assert", 42]}}})
    with pytest.raises(TypeError, match="assertion_calls_javascript"):
        SafetyEngine(cfg).check_file(str(sample))
