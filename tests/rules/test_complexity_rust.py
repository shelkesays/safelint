"""Tests for ``complexity`` (SAFE104) on Rust files.

Rust-specific branching nodes the rule counts:

* ``if_expression`` / ``for_expression`` / ``while_expression`` /
  ``loop_expression`` (and ``if let`` / ``while let`` which parse as
  the standard ``if_expression`` / ``while_expression``).
* ``match_arm`` - one branch per arm (analogous to Java's
  switch_block_statement_group / switch_rule).
* ``try_expression`` - the ``?`` operator is a conditional
  early-return; counted as one branch.
* ``binary_expression`` filtered to ``&&`` / ``||``; Rust has no
  ``??``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def test_rust_high_complexity_fires_safe104(tmp_path: Path) -> None:
    """A function with many if-branches fires SAFE104 (default max=10)."""
    sample = tmp_path / "complex.rs"
    branches = "\n".join(f"    if x == {i} {{ return {i}; }}" for i in range(12))
    sample.write_text(f"fn complex(x: i32) -> i32 {{\n{branches}\n    0\n}}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    safe104 = [v for v in result.violations if v.code == "SAFE104"]
    assert len(safe104) == 1
    assert "complex" in safe104[0].message


def test_rust_match_arms_count_as_branches(tmp_path: Path) -> None:
    """Each ``match_arm`` adds one to cyclomatic complexity."""
    sample = tmp_path / "match_cc.rs"
    arms = "\n".join(f"        {i} => {i}," for i in range(12))
    sample.write_text(
        f"fn m(x: i32) -> i32 {{\n    match x {{\n{arms}\n        _ => 0,\n    }}\n}}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE104" for v in result.violations)


def test_rust_try_operator_counts_as_branch(tmp_path: Path) -> None:
    """``foo()?`` is a ``try_expression`` and counts as one branch."""
    sample = tmp_path / "try_cc.rs"
    # 1 base + 9 ifs (=10) + 1 try = 11, over default max=10.
    ifs = "\n".join(f"    if x == {i} {{ return Ok({i}); }}" for i in range(9))
    sample.write_text(
        f"fn chain(x: i32) -> Result<i32, ()> {{\n{ifs}\n    let _v: i32 = Ok::<i32, ()>(0)?;\n    Ok(0)\n}}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe104 = [v for v in result.violations if v.code == "SAFE104"]
    assert len(safe104) == 1
    assert "11" in safe104[0].message


def test_rust_short_circuit_operators_count(tmp_path: Path) -> None:
    """``&&`` and ``||`` add one each; ``+`` does NOT."""
    sample = tmp_path / "bool_cc.rs"
    # 1 base + 1 if + 9 && = 11; over max=10.
    ands = " && ".join(f"x > {i}" for i in range(10))
    sample.write_text(
        f"fn bools(x: i32) -> bool {{\n    if {ands} {{ return true; }}\n    false\n}}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE104" for v in result.violations)


def test_rust_plus_operator_does_not_count(tmp_path: Path) -> None:
    """Non-short-circuiting binary operators are NOT branches."""
    sample = tmp_path / "arith.rs"
    sample.write_text(
        "fn arith(a: i32, b: i32, c: i32) -> i32 {\n    a + b + c + a + b + c + a + b + c + a + b + c\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE104" for v in result.violations)


def test_rust_simple_function_clean(tmp_path: Path) -> None:
    """A small function with one if is clean."""
    sample = tmp_path / "simple.rs"
    sample.write_text(
        "fn abs(x: i32) -> i32 {\n    if x < 0 { -x } else { x }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE104" for v in result.violations)
