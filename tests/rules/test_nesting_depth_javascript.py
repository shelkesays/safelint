"""Tests for ``nesting_depth`` (SAFE102) on JavaScript files."""

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


def test_js_deeply_nested_if_fires_safe102(tmp_path: Path) -> None:
    """Three nested ``if`` blocks exceed the default max_depth=2."""
    source = (
        "function f(x, y, z) {\n"
        "  if (x) {\n"
        "    if (y) {\n"
        "      if (z) {\n"
        "        return 1;\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "  return 0;\n"
        "}\n"
    )
    sample = tmp_path / "deep.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe102 = [v for v in result.violations if v.code == "SAFE102"]
    assert len(safe102) == 1
    assert "depth is 3" in safe102[0].message


def test_js_deeply_nested_loops_fire_safe102(tmp_path: Path) -> None:
    """``for`` / ``while`` / ``do…while`` all count toward depth."""
    source = (
        "function f() {\n"
        "  for (let i = 0; i < 10; i++) {\n"
        "    while (true) {\n"
        "      do { return; } while (true);\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    sample = tmp_path / "loops.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe102 = [v for v in result.violations if v.code == "SAFE102"]
    assert len(safe102) == 1


def test_js_for_in_and_switch_count(tmp_path: Path) -> None:
    """``for…in`` and ``switch`` both increment depth."""
    source = (
        "function f(items, x) {\n"
        "  for (const k in items) {\n"
        "    switch (x) {\n"
        "      case 1: {\n"
        "        if (true) return;\n"
        "        break;\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    sample = tmp_path / "forswitch.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe102 = [v for v in result.violations if v.code == "SAFE102"]
    assert len(safe102) == 1


def test_js_shallow_function_does_not_fire(tmp_path: Path) -> None:
    """A function with two-level nesting is exactly at the default limit — no fire."""
    source = (
        "function f(x) {\n"
        "  if (x) {\n"
        "    for (let i = 0; i < 10; i++) {\n"
        "      console.log(i);\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    sample = tmp_path / "shallow.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE102" for v in result.violations)


def test_js_nested_function_does_not_inflate_outer(tmp_path: Path) -> None:
    """Nested ``function`` definitions don't count toward the outer's depth."""
    # Outer has just one if; inner has three nested ifs (would fire on its own).
    source = (
        "function outer() {\n"
        "  if (true) {\n"
        "    function inner(a, b, c) {\n"
        "      if (a) { if (b) { if (c) { return 1; } } }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    sample = tmp_path / "nested.js"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"nesting_depth": {"max_depth": 2}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    safe102 = [v for v in result.violations if v.code == "SAFE102"]
    # Inner function fires for depth 3; outer stays at depth 2.
    assert len(safe102) == 1
    assert "inner" in safe102[0].message
