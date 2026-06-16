"""Tests for blanket_suppression (SAFE603) and test-coverage rules (SAFE701/702) on Go files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_go_bare_nolint_fires_safe603(tmp_path: Path) -> None:
    """A bare ``//nolint`` (all golangci linters) fires SAFE603 when enabled."""
    sample = tmp_path / "nolint.go"
    sample.write_text("package main\n//nolint\nfunc f() {}\n", encoding="utf-8")
    cfg = {"rules": {"blanket_suppression": {"enabled": True}}}
    safe603 = [v for v in _engine(cfg).check_file(str(sample)).violations if v.code == "SAFE603"]
    assert len(safe603) == 1
    assert "//nolint" in safe603[0].message


def test_go_scoped_nolint_is_clean(tmp_path: Path) -> None:
    """A scoped ``//nolint:errcheck`` targets a named linter and is clean."""
    sample = tmp_path / "scoped.go"
    sample.write_text("package main\n//nolint:errcheck\nfunc f() {}\n", encoding="utf-8")
    cfg = {"rules": {"blanket_suppression": {"enabled": True}}}
    assert not any(v.code == "SAFE603" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_bare_lint_ignore_fires_safe603(tmp_path: Path) -> None:
    """A bare ``//lint:ignore`` (staticcheck, no checks) fires SAFE603."""
    sample = tmp_path / "lintignore.go"
    sample.write_text("package main\n//lint:ignore\nfunc f() {}\n", encoding="utf-8")
    cfg = {"rules": {"blanket_suppression": {"enabled": True}}}
    assert any(v.code == "SAFE603" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_spaced_nolint_is_not_a_directive(tmp_path: Path) -> None:
    """``// nolint`` (space after //) is prose, not a golangci directive - not flagged."""
    sample = tmp_path / "prose.go"
    sample.write_text("package main\n// nolint here is just a word\nfunc f() {}\n", encoding="utf-8")
    cfg = {"rules": {"blanket_suppression": {"enabled": True}}}
    assert not any(v.code == "SAFE603" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_missing_sibling_test_fires_safe701(tmp_path: Path) -> None:
    """A ``foo.go`` with no sibling ``foo_test.go`` fires SAFE701 when enabled."""
    sample = tmp_path / "widget.go"
    sample.write_text("package main\nfunc Widget() {}\n", encoding="utf-8")
    cfg = {"rules": {"test_existence": {"enabled": True}}}
    safe701 = [v for v in _engine(cfg).check_file(str(sample)).violations if v.code == "SAFE701"]
    assert len(safe701) == 1
    assert "widget_test.go" in safe701[0].message


def test_go_sibling_test_file_clears_safe701(tmp_path: Path) -> None:
    """A sibling ``foo_test.go`` in the same directory clears SAFE701."""
    (tmp_path / "widget.go").write_text("package main\nfunc Widget() {}\n", encoding="utf-8")
    (tmp_path / "widget_test.go").write_text("package main\nfunc TestWidget(t *T) {}\n", encoding="utf-8")
    cfg = {"rules": {"test_existence": {"enabled": True}}}
    out = _engine(cfg).check_file(str(tmp_path / "widget.go")).violations
    assert not any(v.code == "SAFE701" for v in out)


def test_go_test_file_itself_is_skipped(tmp_path: Path) -> None:
    """A ``_test.go`` file is itself a test and never fires SAFE701."""
    sample = tmp_path / "widget_test.go"
    sample.write_text("package main\nfunc TestWidget(t *T) {}\n", encoding="utf-8")
    cfg = {"rules": {"test_existence": {"enabled": True}}}
    assert not any(v.code == "SAFE701" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_changed_source_without_test_fires_safe702(tmp_path: Path) -> None:
    """Changing ``foo.go`` without its sibling ``foo_test.go`` fires SAFE702."""
    (tmp_path / "widget.go").write_text("package main\nfunc Widget() {}\n", encoding="utf-8")
    (tmp_path / "widget_test.go").write_text("package main\nfunc TestWidget(t *T) {}\n", encoding="utf-8")
    cfg = {"rules": {"test_coupling": {"enabled": True}}}
    src = str(tmp_path / "widget.go")
    engine = SafetyEngine(deep_merge(DEFAULTS, cfg), changed_files=[src])
    assert any(v.code == "SAFE702" for v in engine.check_file(src).violations)


def test_go_changed_source_with_test_is_clean(tmp_path: Path) -> None:
    """Changing both ``foo.go`` and its sibling ``foo_test.go`` clears SAFE702."""
    (tmp_path / "widget.go").write_text("package main\nfunc Widget() {}\n", encoding="utf-8")
    (tmp_path / "widget_test.go").write_text("package main\nfunc TestWidget(t *T) {}\n", encoding="utf-8")
    cfg = {"rules": {"test_coupling": {"enabled": True}}}
    src = str(tmp_path / "widget.go")
    test = str(tmp_path / "widget_test.go")
    engine = SafetyEngine(deep_merge(DEFAULTS, cfg), changed_files=[src, test])
    assert not any(v.code == "SAFE702" for v in engine.check_file(src).violations)
