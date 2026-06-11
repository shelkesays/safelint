"""Tests for ``blanket_suppression`` (SAFE603), disabled by default.

Flags un-scoped suppressions of OTHER analysers across all five languages,
while leaving scoped suppressions and safelint's own ``# nosafe`` alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine() -> SafetyEngine:
    overrides = {"rules": {"blanket_suppression": {"enabled": True}}}
    return SafetyEngine(deep_merge(DEFAULTS, overrides))


def _safe603(result) -> list:
    return [v for v in result.violations if v.code == "SAFE603"]


# ---- Python ----


def test_python_bare_noqa_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.py"
    sample.write_text("x = bad_call()  # noqa\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_python_scoped_noqa_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "a.py"
    sample.write_text("x = bad_call()  # noqa: E501\n", encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


def test_python_bare_type_ignore_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.py"
    sample.write_text("x = y  # type: ignore\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_python_scoped_type_ignore_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "a.py"
    sample.write_text("x = y  # type: ignore[assignment]\n", encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


def test_python_pylint_disable_all_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.py"
    sample.write_text("x = 1  # pylint: disable=all\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_python_nosafe_never_flagged(tmp_path: Path) -> None:
    """safelint's own directive must never be flagged by SAFE603."""
    sample = tmp_path / "a.py"
    sample.write_text("while True:  # nosafe: SAFE501\n    pass\n", encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


def test_directive_in_string_literal_not_flagged(tmp_path: Path) -> None:
    """A directive-looking token inside a string is not a comment node."""
    sample = tmp_path / "a.py"
    sample.write_text('msg = "# noqa"\n', encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


# ---- JavaScript / TypeScript ----


def test_js_bare_eslint_disable_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.js"
    sample.write_text("/* eslint-disable */\nconst x = 1;\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_js_scoped_eslint_disable_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "a.js"
    sample.write_text("/* eslint-disable no-console */\nconst x = 1;\n", encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


def test_js_eslint_disable_next_line_bare_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.js"
    sample.write_text("// eslint-disable-next-line\nconst x = 1;\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_ts_nocheck_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.ts"
    sample.write_text("// @ts-nocheck\nconst x: number = 1;\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_ts_ignore_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.ts"
    sample.write_text("// @ts-ignore\nconst x: number = y;\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_ts_expect_error_is_clean(tmp_path: Path) -> None:
    """``@ts-expect-error`` self-polices, so it is not flagged."""
    sample = tmp_path / "a.ts"
    sample.write_text("// @ts-expect-error\nconst x: number = y;\n", encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


# ---- Java ----


def test_java_suppress_warnings_all_fires(tmp_path: Path) -> None:
    sample = tmp_path / "A.java"
    sample.write_text('class A {\n  @SuppressWarnings("all") void f() {}\n}\n', encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_java_suppress_warnings_all_in_array_fires(tmp_path: Path) -> None:
    sample = tmp_path / "A.java"
    sample.write_text('class A {\n  @SuppressWarnings({"unchecked", "all"}) void f() {}\n}\n', encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_java_scoped_suppress_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "A.java"
    sample.write_text('class A {\n  @SuppressWarnings("unchecked") void f() {}\n}\n', encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


# ---- Rust ----


def test_rust_allow_clippy_all_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.rs"
    sample.write_text("#[allow(clippy::all)]\nfn a() {}\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_rust_inner_allow_warnings_fires(tmp_path: Path) -> None:
    sample = tmp_path / "a.rs"
    sample.write_text("#![allow(warnings)]\nfn a() {}\n", encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1


def test_rust_scoped_allow_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "a.rs"
    sample.write_text("#[allow(dead_code)]\nfn a() {}\n#[allow(clippy::too_many_arguments)]\nfn b() {}\n", encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


# ---- default ----


def test_disabled_by_default(tmp_path: Path) -> None:
    sample = tmp_path / "a.py"
    sample.write_text("x = 1  # noqa\n", encoding="utf-8")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert [v for v in result.violations if v.code == "SAFE603"] == []


def test_ts_nocheck_lookalike_is_clean(tmp_path: Path) -> None:
    """``@ts-nocheckthis`` is not the ``@ts-nocheck`` directive (token boundary)."""
    sample = tmp_path / "a.ts"
    sample.write_text("// @ts-nocheckthis is just a note\nconst x: number = 1;\n", encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


def test_rust_allow_with_reason_mentioning_warnings_is_clean(tmp_path: Path) -> None:
    """A scoped allow whose ``reason`` string mentions ``warnings`` must not fire."""
    sample = tmp_path / "a.rs"
    sample.write_text('#[allow(dead_code, reason = "silences spurious warnings")]\nfn a() {}\n', encoding="utf-8")
    assert _safe603(_engine().check_file(str(sample))) == []


def test_rust_allow_warnings_with_reason_still_fires(tmp_path: Path) -> None:
    """A genuine ``allow(warnings)`` still fires even with a reason note."""
    sample = tmp_path / "a.rs"
    sample.write_text('#[allow(warnings, reason = "third-party macro")]\nfn a() {}\n', encoding="utf-8")
    assert len(_safe603(_engine().check_file(str(sample)))) == 1
