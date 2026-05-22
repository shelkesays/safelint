"""Tests for ``function_length`` (SAFE101) on Rust files.

Rust-specific cases that exercise the SAFE101 dispatch added for
``next/rust``:

* ``function_item`` is the standard `fn name() { ... }` shape.
* ``closure_expression`` is the closure shape ``|x| body`` /
  ``|x| { body }``.
* Both shapes are in ``_RUST_FUNCTION_TYPES``; SAFE101 counts lines
  (or logical lines) on each.
"""

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


def test_rust_long_function_fires_safe101(tmp_path: Path) -> None:
    """A function over the default 60-line cap fires SAFE101."""
    sample = tmp_path / "long.rs"
    body = "\n".join(f"    let _x{i} = {i};" for i in range(70))
    sample.write_text(f"fn long_fn() {{\n{body}\n}}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    safe101 = [v for v in result.violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "long_fn" in safe101[0].message


def test_rust_short_function_does_not_fire(tmp_path: Path) -> None:
    """A short function is clean."""
    sample = tmp_path / "short.rs"
    sample.write_text(
        "fn small() -> i32 {\n    let x = 1;\n    let y = 2;\n    x + y\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE101" for v in result.violations)


def test_rust_long_closure_fires_safe101(tmp_path: Path) -> None:
    """A closure over the cap fires SAFE101 too (closure_expression is in FUNCTION_TYPES)."""
    sample = tmp_path / "closure.rs"
    body = "\n".join(f"        let _x{i} = {i};" for i in range(70))
    sample.write_text(
        f"fn main() {{\n    let f = |x: i32| {{\n{body}\n        x\n    }};\n}}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe101 = [v for v in result.violations if v.code == "SAFE101"]
    assert any("anonymous" in v.message or "<anonymous>" in v.message for v in safe101), "long closure should fire SAFE101 with the anonymous-name fallback"
