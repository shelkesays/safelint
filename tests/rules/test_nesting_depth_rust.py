"""Tests for ``nesting_depth`` (SAFE102) on Rust files.

Rust-specific depth nodes the rule counts: ``if_expression`` /
``if_let_expression`` / ``for_expression`` / ``while_expression`` /
``while_let_expression`` / ``loop_expression`` / ``match_expression``.
``unsafe_block`` is deliberately NOT a nesting step.
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


def test_rust_deep_nesting_fires_safe102(tmp_path: Path) -> None:
    """3-deep nesting (default max=2) fires SAFE102."""
    sample = tmp_path / "deep.rs"
    sample.write_text(
        'fn deep(xs: Vec<i32>) {\n    for x in xs {\n        if x > 0 {\n            while x > 0 {\n                println!("{}", x);\n            }\n        }\n    }\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe102 = [v for v in result.violations if v.code == "SAFE102"]
    assert len(safe102) == 1
    assert "deep" in safe102[0].message


def test_rust_match_counts_as_nesting(tmp_path: Path) -> None:
    """``match`` is a nesting step, same as the other branches."""
    sample = tmp_path / "match_nest.rs"
    sample.write_text(
        "fn m(x: Option<i32>) {\n"
        "    if x.is_some() {\n"
        "        match x {\n"
        "            Some(v) => {\n"
        "                if v > 0 {\n"
        '                    println!("positive");\n'
        "                }\n"
        "            }\n"
        "            None => {}\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE102" for v in result.violations)


def test_rust_unsafe_block_does_not_count(tmp_path: Path) -> None:
    """``unsafe { ... }`` is visual indentation but not a nesting step."""
    sample = tmp_path / "unsafe.rs"
    sample.write_text(
        'fn raw_ptr(p: *const i32) {\n    if !p.is_null() {\n        unsafe {\n            println!("{}", *p);\n        }\n    }\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    # if + unsafe-block (not counted) = effective depth 1, under cap.
    assert not any(v.code == "SAFE102" for v in result.violations)
