"""Tests for the ``--stdin`` mode used by editor integrations."""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import TYPE_CHECKING

from safelint.cli import _run_stdin
from safelint.core.config import DEFAULTS
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    import pytest

    from safelint.core.engine import LintResult


def _args(
    output_format: str = "pretty",
    stdin_filename: str = "<stdin>.py",
    fail_on: str | None = None,
    mode: str | None = None,
    ignore: list[str] | None = None,
) -> argparse.Namespace:
    """Build a minimal argparse Namespace shaped like ``_build_common_args`` produces."""
    return argparse.Namespace(
        output_format=output_format,
        stdin=True,
        stdin_filename=stdin_filename,
        fail_on=fail_on,
        mode=mode,
        ignore=ignore,
    )


# ---------------------------------------------------------------------------
# SafetyEngine.check_source — pure unit
# ---------------------------------------------------------------------------


def test_engine_check_source_lints_in_memory_buffer() -> None:
    """``check_source`` runs the same rule pipeline as ``check_file`` but on
    a caller-provided string instead of reading from disk."""
    source = "def f():\n    if True:\n        if True:\n            if True:\n                pass\n"
    result = SafetyEngine(DEFAULTS).check_source("<buffer>.py", source)
    # Three nested ifs — nesting_depth fires.
    assert any(v.rule == "nesting_depth" for v in result.violations)
    # And the violation's filepath is the caller-supplied pseudo-name.
    assert all(v.filepath == "<buffer>.py" for v in result.violations)


def test_engine_check_source_empty_for_unsupported_extension() -> None:
    """Filename extensions that aren't registered (e.g. .rs) skip cleanly."""
    result = SafetyEngine(DEFAULTS).check_source("buffer.rs", "fn main() {}")
    assert result.violations == []
    assert result.suppressed == []


def test_engine_check_source_respects_exclude_paths() -> None:
    """Exclude patterns still apply to in-memory sources — important for
    editor integrations that lint files in excluded dirs.

    Uses ``extend_exclude_paths`` (the documented recommended form,
    additive on top of the vendor-dir defaults) rather than
    ``exclude_paths`` (which would replace those defaults). The
    in-memory-source check goes through the same matcher either way,
    so this exercises the path that real users hit.
    """
    cfg = {**DEFAULTS, "extend_exclude_paths": ["build/**"]}
    result = SafetyEngine(cfg).check_source("build/generated.py", "x = 1\n")
    assert result.violations == []


def test_engine_check_source_reports_parse_errors() -> None:
    """Malformed Python in the buffer produces a SAFE000 violation, not a crash."""
    bad = "def foo(\n    pass\n"  # missing closing paren / colon
    result = SafetyEngine(DEFAULTS).check_source("bad.py", bad)
    parse_errs = [v for v in result.violations if v.code == "SAFE000"]
    assert parse_errs, "malformed source must produce a SAFE000 violation"


# ---------------------------------------------------------------------------
# CLI _run_stdin — integration through the CLI helper
# ---------------------------------------------------------------------------


def test_run_stdin_pretty_output_for_clean_buffer(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A clean buffer exits 0 with no stdout — matches the hook-mode contract
    (silent on success). Editors can rely on exit code for the success signal."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("x = 1\n"))
    rc = _run_stdin(_args())
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_run_stdin_pretty_output_for_buffer_with_violations(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A buffer with violations exits 1 and prints them with the right pseudo-filename."""
    source = "def f():\n    if True:\n        if True:\n            if True:\n                pass\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(source))
    rc = _run_stdin(_args(stdin_filename="my_buffer.py"))
    assert rc == 1
    out = capsys.readouterr().out
    assert "my_buffer.py" in out
    assert "SAFE102" in out


def test_run_stdin_json_output_shape(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--stdin --format=json`` emits a parseable JSON document."""
    source = "def f():\n    if True:\n        if True:\n            if True:\n                pass\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(source))
    rc = _run_stdin(_args(output_format="json", stdin_filename="buf.py"))
    assert rc == 1
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["summary"]["files_checked"] == 1
    assert doc["summary"]["violations"] >= 1
    assert any(v["filepath"] == "buf.py" for v in doc["violations"])


def test_run_stdin_sarif_output_shape(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--stdin --format=sarif`` emits a parseable SARIF 2.1.0 document."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("x = 1\n"))
    rc = _run_stdin(_args(output_format="sarif", stdin_filename="clean.py"))
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "safelint"


def test_run_stdin_unsupported_extension_returns_zero_with_empty_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stdin with a non-Python pseudo-filename (e.g. ``.rs``) skips silently."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("fn main() {}"))
    rc = _run_stdin(_args(stdin_filename="<stdin>.rs"))
    assert rc == 0
    # Pretty mode with no violations and no suppressed: no all-clear is
    # produced (matching how the file path behaves for unsupported types).
    captured = capsys.readouterr()
    assert "SAFE" not in captured.out
    assert "Found" not in captured.out


def test_run_stdin_threads_cli_ignore_into_engine(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--ignore`` from the CLI must apply in stdin mode too — same as file mode."""
    source = "def f():\n    if True:\n        if True:\n            if True:\n                pass\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(source))
    rc = _run_stdin(_args(ignore=["SAFE102"], stdin_filename="buf.py"))
    # SAFE102 was the only violation that would fire; ignoring it leaves a
    # clean run — exit 0 with no violations on stdout.
    assert rc == 0
    out = capsys.readouterr().out
    assert "SAFE102" not in out


def test_run_stdin_returns_lintresult_with_correct_path() -> None:
    """Sanity check on the underlying engine API: the LintResult carries the
    pseudo-filename so violation rendering can show it correctly."""
    result: LintResult = SafetyEngine(DEFAULTS).check_source("editor_buffer.py", "x = 1\n")
    assert result.path == "editor_buffer.py"
