"""Tests for ``complexity`` (SAFE104) on JavaScript files."""

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


def test_js_high_complexity_function_fires_safe104(tmp_path: Path) -> None:
    """A function with many control-flow branches exceeds the default cap (10)."""
    # 11 branches: if + 9 else-if + ternary  = 1 base + 11 = 12 > 10
    source = (
        "function f(x) {\n"
        "  if (x === 1) return 1;\n"
        "  else if (x === 2) return 2;\n"
        "  else if (x === 3) return 3;\n"
        "  else if (x === 4) return 4;\n"
        "  else if (x === 5) return 5;\n"
        "  else if (x === 6) return 6;\n"
        "  else if (x === 7) return 7;\n"
        "  else if (x === 8) return 8;\n"
        "  else if (x === 9) return 9;\n"
        "  else if (x === 10) return 10;\n"
        "  return x > 0 ? 99 : -1;\n"
        "}\n"
    )
    sample = tmp_path / "branchy.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe104 = [v for v in result.violations if v.code == "SAFE104"]
    assert len(safe104) == 1


def test_js_short_circuit_operators_count(tmp_path: Path) -> None:
    """``&&`` / ``||`` / ``??`` each add 1 to complexity."""
    # Short-circuit ops in a return expression — each counts 1.
    # Complexity = 1 (base) + 11 short-circuits = 12 > 10
    source = "function f(a, b, c, d, e) {\n  return a && b && c && d && e || a || b || c || d || e ?? a;\n}\n"
    sample = tmp_path / "shortcircuit.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe104 = [v for v in result.violations if v.code == "SAFE104"]
    assert len(safe104) == 1


def test_js_arithmetic_binary_expr_does_not_count(tmp_path: Path) -> None:
    """``binary_expression`` with non-short-circuit operators (``+``, ``>``, ``<``, etc.) does not add complexity.

    Without the operator-string filter, a function full of arithmetic
    would get a wildly inflated complexity score. Confirms the filter
    is in place.
    """
    # 100 ``+`` operators, no branches — should be complexity 1, way under cap.
    arithmetic = " + ".join(["a"] * 100)
    source = f"function add(a, b) {{ return {arithmetic}; }}\n"
    sample = tmp_path / "arith.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE104" for v in result.violations)


def test_js_switch_cases_count(tmp_path: Path) -> None:
    """Each ``case`` arm in a ``switch`` adds 1 to complexity."""
    # 12 case arms = base 1 + 12 = 13 > 10
    cases = "\n".join(f"    case {i}: return {i};" for i in range(12))
    source = f"function f(x) {{\n  switch (x) {{\n{cases}\n  }}\n}}\n"
    sample = tmp_path / "switch.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe104 = [v for v in result.violations if v.code == "SAFE104"]
    assert len(safe104) == 1


def test_js_simple_function_does_not_fire(tmp_path: Path) -> None:
    """A function with no branches has complexity 1 — well under the cap."""
    sample = tmp_path / "simple.js"
    sample.write_text("function add(a, b) { return a + b; }\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE104" for v in result.violations)


def test_js_loops_and_catch_count(tmp_path: Path) -> None:
    """``for`` / ``for…in`` / ``while`` / ``do`` / ``catch`` each add 1."""
    # 1 (base) + for + for_in + while + do + catch = 6
    source = "function f(items, x) {\n  for (let i = 0; i < 10; i++) {}\n  for (const k in items) {}\n  while (x) {}\n  do {} while (x);\n  try {} catch (e) {}\n}\n"
    sample = tmp_path / "loops.js"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"complexity": {"max_complexity": 5}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    safe104 = [v for v in result.violations if v.code == "SAFE104"]
    assert len(safe104) == 1
    # Verify the count surfaces in the message.
    assert "complexity 6" in safe104[0].message
