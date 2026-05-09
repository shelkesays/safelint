"""Tests for ``unbounded_loops`` (SAFE501) on JavaScript files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def test_js_while_true_no_break_fires_safe501(tmp_path: Path) -> None:
    """``while (true) { ... }`` with no break inside fires SAFE501."""
    sample = tmp_path / "infinite.js"
    sample.write_text(
        "function f() {\n  while (true) {\n    work();\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE501" for v in result.violations)


def test_js_while_true_with_break_does_not_fire(tmp_path: Path) -> None:
    """``while (true) { ... break; ... }`` is bounded and clean."""
    sample = tmp_path / "bounded.js"
    sample.write_text(
        "function f(queue) {\n  while (true) {\n    const item = queue.shift();\n    if (item === undefined) break;\n    work(item);\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE501" for v in result.violations)


def test_js_while_with_property_access_does_not_fire(tmp_path: Path) -> None:
    """Idiomatic JS like ``while (queue.length)`` does NOT fire (different from Python).

    The Python rule fires on non-comparison conditions because ``while x:``
    is unusual style; in JS, ``while (queue.length)``, ``while (token)``,
    ``while (cursor.next())`` are all idiomatic and bounded.
    """
    sample = tmp_path / "idiomatic.js"
    sample.write_text(
        "function f(queue) {\n  while (queue.length) {\n    work(queue.shift());\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE501" for v in result.violations)


def test_js_while_with_function_call_does_not_fire(tmp_path: Path) -> None:
    """``while (token = next())`` (JS-style cursor pattern) does NOT fire."""
    sample = tmp_path / "cursor.js"
    sample.write_text(
        "function f(stream) {\n  let token;\n  while ((token = stream.next())) {\n    process(token);\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE501" for v in result.violations)


def test_js_break_in_nested_loop_does_not_save_outer(tmp_path: Path) -> None:
    """A ``break`` inside a nested loop / function exits *that* construct, not the outer ``while (true)``.

    The break-scope-boundaries set must include ``for_statement`` and
    nested function types so the walk doesn't accidentally see the
    inner break and credit the outer ``while (true)`` with it.
    """
    sample = tmp_path / "nested.js"
    sample.write_text(
        "function f() {\n"
        "  while (true) {\n"
        "    for (let i = 0; i < 10; i++) {\n"
        "      if (i === 5) break;\n"  # this break exits the for loop, not the while
        "    }\n"
        "    work();\n"  # the outer while keeps spinning forever
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE501" for v in result.violations)


def test_js_break_in_inner_function_does_not_save_outer(tmp_path: Path) -> None:
    """A ``break`` inside a nested function definition is a syntax error in JS — but a return-from-inner-arrow shouldn't either."""
    # Realistic scenario: outer ``while (true)`` with a nested arrow function
    # that early-returns. The outer while still has no break.
    sample = tmp_path / "innerfn.js"
    sample.write_text(
        "function f() {\n  while (true) {\n    const helper = () => { return; };\n    helper();\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE501" for v in result.violations)
