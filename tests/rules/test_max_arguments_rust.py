"""Tests for ``max_arguments`` (SAFE103) on Rust files.

Rust parameter shapes covered:

* ``function_item.parameters`` -> ``parameter`` children (typed
  ``name: Type``); ``self_parameter`` excluded.
* ``closure_expression.parameters`` -> ``closure_parameters`` -> bare
  ``identifier`` (untyped, ``|x, y|``) or ``parameter`` (typed).
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


def test_rust_too_many_typed_params_fires_safe103(tmp_path: Path) -> None:
    """A function with 8 typed parameters (over default 7) fires SAFE103."""
    sample = tmp_path / "many.rs"
    sample.write_text(
        "fn many(a: i32, b: i32, c: i32, d: i32, e: i32, f: i32, g: i32, h: i32) {}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message


def test_rust_self_parameter_does_not_count(tmp_path: Path) -> None:
    """``&self`` / ``self`` / ``&mut self`` is excluded (analogous to Python's ``self``)."""
    sample = tmp_path / "self_method.rs"
    sample.write_text(
        "struct S; impl S { fn m(&self, a: i32, b: i32, c: i32, d: i32, e: i32, f: i32, g: i32) {} }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    # 1 self + 7 typed args = effective 7 (under cap of 7); clean.
    assert not any(v.code == "SAFE103" for v in result.violations)


def test_rust_self_parameter_excluded_but_method_still_fires_with_too_many(tmp_path: Path) -> None:
    """Self exclusion doesn't help when the rest still exceed."""
    sample = tmp_path / "many_method.rs"
    sample.write_text(
        "struct S; impl S { fn m(&self, a: i32, b: i32, c: i32, d: i32, e: i32, f: i32, g: i32, h: i32) {} }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message


def test_rust_untyped_closure_args_counted(tmp_path: Path) -> None:
    """``|a, b, c, d, e, f, g, h| ...`` counts as 8 args."""
    sample = tmp_path / "closure.rs"
    sample.write_text(
        "fn main() { let f = |a, b, c, d, e, f, g, h| (a, b, c, d, e, f, g, h); }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert any("8 arguments" in v.message for v in safe103), "untyped closure with 8 params should fire SAFE103"


def test_rust_few_params_clean(tmp_path: Path) -> None:
    """3 args is well under the default 7 cap."""
    sample = tmp_path / "few.rs"
    sample.write_text("fn three(a: i32, b: i32, c: i32) -> i32 { a + b + c }\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE103" for v in result.violations)
