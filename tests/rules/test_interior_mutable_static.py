"""Tests for ``interior_mutable_static`` (SAFE307), Rust-only, disabled by default."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path

    from safelint.core.engine import LintResult
    from safelint.rules.base import Violation

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(extra: dict | None = None) -> SafetyEngine:
    overrides = {"rules": {"interior_mutable_static": {"enabled": True}}}
    if extra:
        overrides["rules"]["interior_mutable_static"].update(extra)
    return SafetyEngine(deep_merge(DEFAULTS, overrides))


def _safe307(result: LintResult) -> list[Violation]:
    return [v for v in result.violations if v.code == "SAFE307"]


def test_mutex_static_fires(tmp_path: Path) -> None:
    sample = tmp_path / "m.rs"
    sample.write_text("static CACHE: Mutex<Vec<u8>> = Mutex::new(Vec::new());\n", encoding="utf-8")
    hits = _safe307(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert "CACHE" in hits[0].message


def test_atomic_static_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.rs"
    sample.write_text("static COUNT: AtomicUsize = AtomicUsize::new(0);\n", encoding="utf-8")
    assert len(_safe307(_engine().check_file(str(sample)))) == 1


def test_qualified_path_fires(tmp_path: Path) -> None:
    sample = tmp_path / "q.rs"
    sample.write_text("static L: std::sync::RwLock<i32> = std::sync::RwLock::new(0);\n", encoding="utf-8")
    assert len(_safe307(_engine().check_file(str(sample)))) == 1


def test_lazy_static_macro_fires(tmp_path: Path) -> None:
    sample = tmp_path / "lz.rs"
    sample.write_text('lazy_static! {\n    static ref CFG: String = String::from("x");\n}\n', encoding="utf-8")
    assert len(_safe307(_engine().check_file(str(sample)))) == 1


def test_plain_static_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "plain.rs"
    sample.write_text("static MAX: i32 = 10;\n", encoding="utf-8")
    assert _safe307(_engine().check_file(str(sample))) == []


def test_const_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "c.rs"
    sample.write_text("const MAX: i32 = 10;\n", encoding="utf-8")
    assert _safe307(_engine().check_file(str(sample))) == []


def test_static_mut_is_clean_safe602_territory(tmp_path: Path) -> None:
    """``static mut`` is SAFE602's unsafe-gated territory; SAFE307 must not double-report."""
    sample = tmp_path / "raw.rs"
    sample.write_text("static mut RAW: i32 = 0;\n", encoding="utf-8")
    assert _safe307(_engine().check_file(str(sample))) == []


def test_lazy_does_not_substring_match_user_type(tmp_path: Path) -> None:
    """Word-boundary matching: a user type containing a wrapper name as a substring is clean."""
    sample = tmp_path / "u.rs"
    sample.write_text("static G: MutexGuardWrapper = MutexGuardWrapper::new();\n", encoding="utf-8")
    assert _safe307(_engine().check_file(str(sample))) == []


def test_disabled_by_default(tmp_path: Path) -> None:
    """With no opt-in, SAFE307 does not run."""
    sample = tmp_path / "m.rs"
    sample.write_text("static CACHE: Mutex<Vec<u8>> = Mutex::new(Vec::new());\n", encoding="utf-8")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert [v for v in result.violations if v.code == "SAFE307"] == []


def test_custom_type_list_narrows(tmp_path: Path) -> None:
    """A narrowed ``interior_mutable_types_rust`` drops the default Mutex match."""
    sample = tmp_path / "m.rs"
    sample.write_text("static CACHE: Mutex<i32> = Mutex::new(0);\n", encoding="utf-8")
    eng = _engine({"interior_mutable_types_rust": ["AtomicUsize"]})
    assert _safe307(eng.check_file(str(sample))) == []


def test_interior_mutable_types_rust_bare_string_raises(tmp_path: Path) -> None:
    """A bare-string config typo fails loud instead of silently matching characters."""
    sample = tmp_path / "m.rs"
    sample.write_text("static CACHE: Mutex<i32> = Mutex::new(0);\n", encoding="utf-8")
    eng = _engine({"interior_mutable_types_rust": "Mutex"})  # should be a list
    with pytest.raises(TypeError):
        eng.check_file(str(sample))
