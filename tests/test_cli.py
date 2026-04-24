"""Tests for safelint.cli output-formatting helpers."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from safelint.cli import _file_summary_line, _make_summary, _run_hook
from safelint.core.engine import LintResult
from safelint.rules.base import Violation

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip(text: str) -> str:
    """Remove ANSI escape sequences from *text*."""
    return _ANSI_RE.sub("", text)


def _v(severity: str) -> Violation:
    """Return a minimal Violation with the given severity."""
    return Violation(
        rule="test_rule",
        code="SAFE999",
        filepath="path/file.py",
        lineno=1,
        message="test message",
        severity=severity,
    )


# ---------------------------------------------------------------------------
# _file_summary_line
# ---------------------------------------------------------------------------


def test_file_summary_line_error_only() -> None:
    """A single error-severity violation produces '1 error'."""
    line = _strip(_file_summary_line("path/file.py", [_v("error")]))
    assert line == "path/file.py \u2014 1 error."


def test_file_summary_line_errors_plural() -> None:
    """Multiple errors are pluralised correctly."""
    line = _strip(_file_summary_line("path/file.py", [_v("error"), _v("error")]))
    assert line == "path/file.py \u2014 2 errors."


def test_file_summary_line_warning_only() -> None:
    """A single warning-severity violation produces '1 warning'."""
    line = _strip(_file_summary_line("path/file.py", [_v("warning")]))
    assert line == "path/file.py \u2014 1 warning."


def test_file_summary_line_warnings_plural() -> None:
    """Multiple warnings are pluralised correctly."""
    line = _strip(_file_summary_line("path/file.py", [_v("warning"), _v("warning")]))
    assert line == "path/file.py \u2014 2 warnings."


def test_file_summary_line_mixed_violations() -> None:
    """Mixed severities: errors are listed before warnings."""
    line = _strip(_file_summary_line(
        "path/file.py",
        [_v("error"), _v("warning"), _v("warning")],
    ))
    assert line == "path/file.py \u2014 1 error, 2 warnings."


def test_file_summary_line_unknown_severity_counted_as_error() -> None:
    """Unknown severities are treated as errors, consistent with partition_violations."""
    line = _strip(_file_summary_line("path/file.py", [_v("critical")]))
    assert line == "path/file.py \u2014 1 error."


def test_file_summary_line_empty_violations_raises() -> None:
    """Empty violations list raises ValueError."""
    with pytest.raises(ValueError, match="violations must be non-empty"):
        _file_summary_line("path/file.py", [])


# ---------------------------------------------------------------------------
# _make_summary (collective summary)
# ---------------------------------------------------------------------------


def test_make_summary_no_violations() -> None:
    """No violations returns the all-clear message."""
    found, fixes = _make_summary([], n_blocking=0, fail_on="error")
    assert _strip(found) == "All checks passed."
    assert "No fixes available" in _strip(fixes)


def test_make_summary_advisory_only() -> None:
    """When no violations are blocking the run is marked advisory."""
    found, _ = _make_summary([_v("warning")], n_blocking=0, fail_on="error")
    found = _strip(found)
    assert "Advisory only" in found
    assert "[--fail-on=error]" in found


def test_make_summary_blocking() -> None:
    """Blocking violations are not labelled advisory."""
    found, _ = _make_summary([_v("error")], n_blocking=1, fail_on="error")
    found = _strip(found)
    assert "Advisory" not in found
    assert "1 error" in found
    assert "[--fail-on=error]" in found


def test_make_summary_suppressed_note() -> None:
    """Suppressed count appears in both summary lines."""
    found, fixes = _make_summary([], n_blocking=0, fail_on="error", n_suppressed=3)
    assert "3 suppressed" in _strip(found)
    assert "3 suppressed" in _strip(fixes)


def test_make_summary_unknown_severity_counted_as_error() -> None:
    """Unknown severities are treated as errors in the collective summary."""
    found, _ = _make_summary([_v("critical")], n_blocking=1, fail_on="error")
    found = _strip(found)
    assert "1 error" in found
    assert "warning" not in found


# ---------------------------------------------------------------------------
# _run_hook summary gate
# ---------------------------------------------------------------------------


def _make_args(fail_on: str = "error", mode: str = "local") -> argparse.Namespace:
    """Return a minimal argparse.Namespace stand-in."""
    return argparse.Namespace(fail_on=fail_on, mode=mode, ignore=None)


def test_run_hook_no_output_when_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """_run_hook produces no stdout when check_file returns no violations or suppressed counts."""
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")

    mocker.patch(
        "safelint.cli.SafetyEngine.check_file",
        return_value=LintResult(path=str(clean), violations=[], suppressed=0),
    )

    assert _run_hook(_make_args(), [str(clean)]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""


def test_run_hook_prints_summary_when_suppressed(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """_run_hook prints a summary line when there are suppressed violations."""
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")

    fake_result = LintResult(path=str(clean), violations=[], suppressed=1)
    mocker.patch("safelint.cli.SafetyEngine.check_file", return_value=fake_result)

    assert _run_hook(_make_args(), [str(clean)]) == 0

    captured = capsys.readouterr()
    assert "All checks passed." in captured.out
    assert "suppressed" in captured.out
