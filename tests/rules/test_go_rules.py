"""Tests for the Go-only rules: empty_error_check (SAFE209) and panic_calls_outside_tests (SAFE211)."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


_SAFE209 = {"rules": {"empty_error_check": {"enabled": True}}}
_SAFE211 = {"rules": {"panic_calls_outside_tests": {"enabled": True}}}


def test_go_empty_error_body_fires_safe209(tmp_path: Path) -> None:
    """``if err != nil {}`` with an empty body fires SAFE209."""
    sample = tmp_path / "swallow.go"
    sample.write_text("package main\nfunc f() {\n\tif err != nil {}\n}\n", encoding="utf-8")
    safe209 = [v for v in _engine(_SAFE209).check_file(str(sample)).violations if v.code == "SAFE209"]
    assert len(safe209) == 1


def test_go_comment_only_error_body_fires_safe209(tmp_path: Path) -> None:
    """A comment-only ``if err != nil`` body still counts as swallowed."""
    sample = tmp_path / "comment.go"
    sample.write_text("package main\nfunc f() {\n\tif err != nil {\n\t\t// ignore\n\t}\n}\n", encoding="utf-8")
    assert any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_handled_error_is_clean(tmp_path: Path) -> None:
    """An ``if err != nil`` with a real body is clean."""
    sample = tmp_path / "handled.go"
    sample.write_text("package main\nfunc f() {\n\tif err != nil {\n\t\thandle(err)\n\t}\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_custom_error_name_via_config(tmp_path: Path) -> None:
    """A non-default error name is honoured via ``error_names_go``."""
    sample = tmp_path / "custom.go"
    sample.write_text("package main\nfunc f() {\n\tif e != nil {}\n}\n", encoding="utf-8")
    # Default ``["err"]`` should not fire on ``e``.
    assert not any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)
    cfg = {"rules": {"empty_error_check": {"enabled": True, "error_names_go": ["e"]}}}
    assert any(v.code == "SAFE209" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_non_binary_if_condition_is_clean(tmp_path: Path) -> None:
    """An ``if ok {}`` (non-comparison condition) with an empty body does not fire SAFE209."""
    sample = tmp_path / "nonbin.go"
    sample.write_text("package main\nfunc f() {\n\tif ok {}\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_non_nil_comparison_is_clean(tmp_path: Path) -> None:
    """An ``if a < b {}`` empty body is not an error check and does not fire SAFE209."""
    sample = tmp_path / "lt.go"
    sample.write_text("package main\nfunc f() {\n\tif a < b {}\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_nil_on_left_side_still_fires(tmp_path: Path) -> None:
    """``if nil != err {}`` (operands reversed) still fires SAFE209."""
    sample = tmp_path / "rev.go"
    sample.write_text("package main\nfunc f() {\n\tif nil != err {}\n}\n", encoding="utf-8")
    assert any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_err_eq_nil_empty_success_branch_is_clean(tmp_path: Path) -> None:
    """``if err == nil {}`` (no else) is an empty success path, not a swallowed error."""
    sample = tmp_path / "eqnil.go"
    sample.write_text("package main\nfunc f() {\n\tif err == nil {}\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_err_eq_nil_handled_in_else_is_clean(tmp_path: Path) -> None:
    """``if err == nil { ok() } else { handle() }`` handles the error in the else - clean."""
    sample = tmp_path / "eqnilhandled.go"
    sample.write_text("package main\nfunc f() {\n\tif err == nil {\n\t\tok()\n\t} else {\n\t\thandle(err)\n\t}\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_err_eq_nil_empty_else_fires(tmp_path: Path) -> None:
    """``if err == nil { ok() } else {}`` swallows the error in the empty else branch."""
    sample = tmp_path / "eqnilempty.go"
    sample.write_text("package main\nfunc f() {\n\tif err == nil {\n\t\tok()\n\t} else {}\n}\n", encoding="utf-8")
    assert any(v.code == "SAFE209" for v in _engine(_SAFE209).check_file(str(sample)).violations)


def test_go_panic_in_production_fires_safe211(tmp_path: Path) -> None:
    """A ``panic(...)`` in a non-test file fires SAFE211."""
    sample = tmp_path / "prod.go"
    sample.write_text('package main\nfunc f() {\n\tpanic("boom")\n}\n', encoding="utf-8")
    safe211 = [v for v in _engine(_SAFE211).check_file(str(sample)).violations if v.code == "SAFE211"]
    assert len(safe211) == 1
    assert "panic" in safe211[0].message


def test_go_panic_in_test_file_is_exempt(tmp_path: Path) -> None:
    """A ``panic(...)`` inside a ``_test.go`` file is exempt from SAFE211."""
    sample = tmp_path / "prod_test.go"
    sample.write_text('package main\nfunc TestF(t *T) {\n\tpanic("boom")\n}\n', encoding="utf-8")
    assert not any(v.code == "SAFE211" for v in _engine(_SAFE211).check_file(str(sample)).violations)


def test_go_custom_panic_call_via_config(tmp_path: Path) -> None:
    """``panic_calls_go`` can extend the flagged set (e.g. a wrapper ``fatal``)."""
    sample = tmp_path / "fatal.go"
    sample.write_text('package main\nfunc f() {\n\tfatal("x")\n}\n', encoding="utf-8")
    assert not any(v.code == "SAFE211" for v in _engine(_SAFE211).check_file(str(sample)).violations)
    cfg = {"rules": {"panic_calls_outside_tests": {"enabled": True, "panic_calls_go": ["fatal"]}}}
    assert any(v.code == "SAFE211" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_selector_panic_calls_match_via_config(tmp_path: Path) -> None:
    """Selector calls like ``log.Fatal`` / ``os.Exit`` match by resolved bareword (`Fatal` / `Exit`)."""
    sample = tmp_path / "fatalexit.go"
    sample.write_text('package main\nfunc f() {\n\tlog.Fatal("boom")\n\tos.Exit(1)\n}\n', encoding="utf-8")
    # Default config (`["panic"]`) does not flag these.
    assert not any(v.code == "SAFE211" for v in _engine(_SAFE211).check_file(str(sample)).violations)
    cfg = {"rules": {"panic_calls_outside_tests": {"enabled": True, "panic_calls_go": ["Fatal", "Exit"]}}}
    fired = [v for v in _engine(cfg).check_file(str(sample)).violations if v.code == "SAFE211"]
    assert len(fired) == 2
