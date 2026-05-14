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
    """A ``break`` inside a nested function definition is a syntax error in JS - but a return-from-inner-arrow shouldn't either."""
    # Realistic scenario: outer ``while (true)`` with a nested arrow function
    # that early-returns. The outer while still has no break.
    sample = tmp_path / "innerfn.js"
    sample.write_text(
        "function f() {\n  while (true) {\n    const helper = () => { return; };\n    helper();\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE501" for v in result.violations)


def test_js_while_double_parens_true_no_break_fires_safe501(tmp_path: Path) -> None:
    """``while ((true)) { ... }`` - extra formatting parens still detected.

    The mandatory ``while (...)`` outer paren wraps the condition in a
    ``parenthesized_expression``; extra formatting parens nest another
    layer. Single-layer unwrap left ``is_literal_true`` False on the
    outer wrapper and silently skipped the no-break check - a real
    false-negative that automated reformatters can introduce.
    """
    sample = tmp_path / "double_paren.js"
    sample.write_text(
        "function f() { while ((true)) { work(); } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe501 = [v for v in result.violations if v.code == "SAFE501"]
    assert len(safe501) == 1


def test_js_while_double_parens_true_with_break_does_not_fire(tmp_path: Path) -> None:
    """``while ((true))`` with a break is still recognised as bounded - positive control."""
    sample = tmp_path / "double_paren_break.js"
    sample.write_text(
        "function f() { while ((true)) { if (cond) break; work(); } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE501" for v in result.violations)


def test_js_while_true_no_break_message_uses_js_syntax(tmp_path: Path) -> None:
    """SAFE501 message on a JS file says ``while (true)``, not ``while True``.

    The hazard is the same in both languages but the surface syntax
    differs - a Python-flavored ``while True`` message in a JS
    violation block would be visually jarring and look like a bug.
    """
    sample = tmp_path / "msg.js"
    sample.write_text(
        "function f() { while (true) { work(); } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe501 = [v for v in result.violations if v.code == "SAFE501"]
    assert len(safe501) == 1
    assert "while (true)" in safe501[0].message
    assert "while True" not in safe501[0].message


def test_js_labeled_break_from_nested_for_exits_outer_while(tmp_path: Path) -> None:
    """``outer: while (true) { for (...) { break outer; } }`` - labelled break exits the while.

    Regression guard: the pruned walk prunes nested loops wholesale,
    so a labelled break inside a nested ``for`` would otherwise be
    invisible to the rule and the outer ``while (true)`` would be
    flagged as having no exit. This is a real false-positive that
    automated reformatters / refactors can introduce (extracting a
    loop into a nested loop with a labelled break is a common
    pattern in algorithm code).
    """
    sample = tmp_path / "labeled.js"
    sample.write_text(
        "function f(items, target) {\n  outer: while (true) {\n    for (const item of items) {\n      if (item === target) { break outer; }\n      process(item);\n    }\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE501" for v in result.violations)


def test_js_labeled_break_from_nested_switch_exits_outer_while(tmp_path: Path) -> None:
    """Same fix applies to labelled breaks from inside a ``switch`` - also a pruned construct."""
    sample = tmp_path / "labeled_switch.js"
    sample.write_text(
        "function f(token) {\n  outer: while (true) {\n    switch (token.type) {\n      case 'END': break outer;\n      default: token = next(token);\n    }\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE501" for v in result.violations)


def test_js_labeled_break_to_different_label_still_fires(tmp_path: Path) -> None:
    """A labelled break targeting a *different* label doesn't satisfy our while.

    ``outer: while (true) { inner: for (...) { break inner; } }`` -
    ``break inner`` exits the for, not the while. The outer
    ``while (true)`` has no exit and should still fire SAFE501.
    """
    sample = tmp_path / "labeled_other.js"
    sample.write_text(
        "function f(items) {\n  outer: while (true) {\n    inner: for (const item of items) {\n      if (item.done) { break inner; }\n      process(item);\n    }\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE501" for v in result.violations)


def test_js_unlabeled_while_unaffected(tmp_path: Path) -> None:
    """A ``while (true)`` with no label and no break still fires - the new code path doesn't regress the existing case."""
    sample = tmp_path / "unlabeled.js"
    sample.write_text(
        "function f() { while (true) { work(); } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE501" for v in result.violations)
