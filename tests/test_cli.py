"""Tests for safelint.cli output-formatting helpers."""

from __future__ import annotations

import re

from safelint.cli import _file_summary_line, _make_summary
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
