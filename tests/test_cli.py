"""Tests for safelint.cli output-formatting helpers."""

from __future__ import annotations

import argparse
import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

import pytest

from safelint.cli import (
    _check_exit_code,
    _compose_extras_install_command,
    _emit_hook_grammar_warnings,
    _emit_missing_grammar_warnings,
    _emit_skill_install_grammar_hint,
    _file_summary_line,
    _format_install_action,
    _guard_hook_silent_failure,
    _make_summary,
    _matching_suffixes,
    _run_hook,
    _scan_for_unavailable_extensions,
)
from safelint.core.engine import LintResult
from safelint.languages import extra_name_for
from safelint.rules.base import Violation


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip(text: str) -> str:
    """Remove ANSI escape sequences from *text*."""
    return _ANSI_RE.sub("", text)


def _v(severity: str, code: str = "SAFE999", rule: str = "test_rule") -> Violation:
    """Return a minimal Violation with the given severity (and optional code/rule)."""
    return Violation(
        rule=rule,
        code=code,
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
    line = _strip(
        _file_summary_line(
            "path/file.py",
            [_v("error"), _v("warning"), _v("warning")],
        )
    )
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
    """No violations returns the all-clear message and no fixes line."""
    found, fixes = _make_summary([], n_blocking=0, fail_on="error")
    assert _strip(found) == "All checks passed."
    assert fixes is None


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


def test_make_summary_suppressed_clean_run_breaks_down_by_code() -> None:
    """Clean run with suppressions surfaces a per-code breakdown and no fixes line."""
    suppressed = [
        _v("warning", code="SAFE501"),
        _v("warning", code="SAFE501"),
        _v("warning", code="SAFE304"),
    ]
    found, fixes = _make_summary([], n_blocking=0, fail_on="error", suppressed=suppressed)
    found_text = _strip(found)
    assert "All checks passed." in found_text
    assert "2 SAFE501" in found_text
    assert "1 SAFE304" in found_text
    assert "suppressed" in found_text
    assert fixes is None


def test_make_summary_suppressed_with_violations_surfaces_breakdown_in_fixes_line() -> None:
    """When violations exist, the suppression breakdown rides on the fixes line.

    Updated in 1.8.0 — the line now reads "No suggestions available (safelint
    does not auto-fix; …)" since "fixes" was renamed to "suggestions" to
    reflect the never-auto-apply policy. The suppression breakdown still
    rides at the end in the canonical "(… suppressed)" form.
    """
    suppressed = [_v("warning", code="SAFE501"), _v("warning", code="SAFE304")]
    _, fixes = _make_summary([_v("error")], n_blocking=1, fail_on="error", suppressed=suppressed)
    assert fixes is not None
    fixes_text = _strip(fixes)
    assert fixes_text.startswith("No suggestions available")
    assert "does not auto-fix" in fixes_text
    assert "1 SAFE304" in fixes_text
    assert "1 SAFE501" in fixes_text
    assert "suppressed)" in fixes_text


def test_make_summary_suppressed_breakdown_sorted_by_count_desc_then_code() -> None:
    """Codes with the same count appear alphabetically; higher counts come first."""
    suppressed = [
        _v("warning", code="SAFE304"),
        _v("warning", code="SAFE501"),
        _v("warning", code="SAFE501"),
        _v("warning", code="SAFE201"),
    ]
    found, _ = _make_summary([], n_blocking=0, fail_on="error", suppressed=suppressed)
    found_text = _strip(found)
    # SAFE501 (count 2) first, then SAFE201 and SAFE304 (count 1) alphabetically.
    pos_501 = found_text.find("2 SAFE501")
    pos_201 = found_text.find("1 SAFE201")
    pos_304 = found_text.find("1 SAFE304")
    assert 0 <= pos_501 < pos_201 < pos_304


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
        return_value=LintResult(path=str(clean), violations=[], suppressed=[]),
    )

    assert _run_hook(_make_args(), [str(clean)]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    # A clean hook run shouldn't surface ANY output — including stray
    # diagnostics on stderr. Pre-commit's contract is silence-on-success.
    assert captured.err == ""


def test_run_hook_prints_summary_when_suppressed(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """_run_hook prints a summary line when there are suppressed violations."""
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")

    fake_result = LintResult(path=str(clean), violations=[], suppressed=[_v("warning", code="SAFE501")])
    mocker.patch("safelint.cli.SafetyEngine.check_file", return_value=fake_result)

    assert _run_hook(_make_args(), [str(clean)]) == 0

    captured = capsys.readouterr()
    out = _strip(captured.out)
    assert "All checks passed." in out
    assert "1 SAFE501" in out
    assert "suppressed" in out
    # Clean run should NOT print the no-suggestions / no-fixes line.
    assert "No suggestions available" not in out
    assert "No fixes available" not in out


# ---------------------------------------------------------------------------
# v2.0.0 — missing-grammar hint
# ---------------------------------------------------------------------------


def test_scan_for_unavailable_extensions_finds_matching_files(tmp_path: Path) -> None:
    """Walker reports the set of unavailable extensions actually present under *target*."""
    (tmp_path / "app.ts").write_text("x = 1;\n", encoding="utf-8")
    (tmp_path / "module.js").write_text("x = 1;\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    found = _scan_for_unavailable_extensions(tmp_path, {".ts": "hint-ts", ".js": "hint-js"})
    assert found == {".ts", ".js"}


def test_scan_for_unavailable_extensions_returns_empty_when_no_matches(tmp_path: Path) -> None:
    """No unavailable-extension files → empty set, regardless of how many supported files exist."""
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    assert _scan_for_unavailable_extensions(tmp_path, {".ts": "hint"}) == set()


def test_scan_for_unavailable_extensions_skips_excluded_dirs(tmp_path: Path) -> None:
    """The walk skips vendored / generated dirs so node_modules / .venv don't trigger spurious hints."""
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "lib.js").write_text("x = 1;\n", encoding="utf-8")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "dep.ts").write_text("x = 1;\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    # Walker should report nothing — vendored dirs are filtered.
    assert _scan_for_unavailable_extensions(tmp_path, {".ts": "hint-ts", ".js": "hint-js"}) == set()


def test_scan_for_unavailable_extensions_handles_single_file_target(tmp_path: Path) -> None:
    """Target may be a file (not just a directory) — single-file path is exercised."""
    single = tmp_path / "lone.ts"
    single.write_text("x = 1;\n", encoding="utf-8")
    assert _scan_for_unavailable_extensions(single, {".ts": "hint"}) == {".ts"}


def test_scan_for_unavailable_extensions_handles_nonexistent_target(tmp_path: Path) -> None:
    """Target that doesn't exist (and isn't a file or dir) returns empty — no crash."""
    missing = tmp_path / "does-not-exist"
    assert _scan_for_unavailable_extensions(missing, {".ts": "hint"}) == set()


def test_emit_missing_grammar_warnings_silent_when_no_unavailable_extensions(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """When every grammar is installed, the helper is a no-op (no stderr noise)."""
    mocker.patch("safelint.cli.unavailable_extensions", return_value={})
    _emit_missing_grammar_warnings(tmp_path)
    assert capsys.readouterr().err == ""


def test_emit_missing_grammar_warnings_emits_per_hint(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """One stderr line per unique install hint, listing the extensions covered."""
    (tmp_path / "a.ts").write_text("x = 1;\n", encoding="utf-8")
    (tmp_path / "b.tsx").write_text("x = 1;\n", encoding="utf-8")
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={
            ".ts": "pip install 'safelint[typescript]'",
            ".tsx": "pip install 'safelint[typescript]'",
            ".as": "pip install 'safelint[typescript]'",
        },
    )
    _emit_missing_grammar_warnings(tmp_path)
    err = capsys.readouterr().err
    # One line, listing both extensions present, with the single shared hint.
    assert err.count("safelint: warning:") == 1
    assert ".ts" in err
    assert ".tsx" in err
    assert "pip install 'safelint[typescript]'" in err


def test_emit_hook_grammar_warnings_emits_only_for_passed_files(capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """Hook-mode helper takes the explicit file list — no directory walk."""
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'"},
    )
    _emit_hook_grammar_warnings(["app.py", "module.ts", "other.py"])
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert ".ts" in err
    assert "pip install 'safelint[typescript]'" in err


def test_emit_hook_grammar_warnings_silent_when_no_unavailable_files_passed(capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """Pure-Python file list with unavailable TS grammar still produces no warning (no TS files were passed)."""
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'"},
    )
    assert _emit_hook_grammar_warnings(["app.py", "module.py"]) == set()
    assert capsys.readouterr().err == ""


def test_emit_hook_grammar_warnings_returns_seen_unavailable_extensions(mocker: MockerFixture) -> None:
    """Return value lets ``main()`` detect the total-skip silent-failure case."""
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'", ".js": "pip install 'safelint[javascript]'"},
    )
    assert _emit_hook_grammar_warnings(["app.ts", "lib.js", "other.py"]) == {".ts", ".js"}


def test_emit_missing_grammar_warnings_returns_seen_extensions(tmp_path: Path, mocker: MockerFixture) -> None:
    """Directory-walk variant also returns the set of unavailable extensions found."""
    (tmp_path / "main.ts").write_text("x = 1;\n", encoding="utf-8")
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'"},
    )
    assert _emit_missing_grammar_warnings(tmp_path) == {".ts"}


# ---------------------------------------------------------------------------
# Pre-commit context detection
# ---------------------------------------------------------------------------


def test_format_install_action_outside_precommit_uses_pip_install_phrasing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``PRE_COMMIT`` env var, the hint nudges the user toward ``pip install``."""
    monkeypatch.delenv("PRE_COMMIT", raising=False)
    msg = _format_install_action("pip install 'safelint[python]'")
    assert msg == "install with: pip install 'safelint[python]'"


def test_format_install_action_under_precommit_uses_additional_dependencies_phrasing(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``PRE_COMMIT=1``, the hint switches to the additional_dependencies form.

    Pre-commit users can't run ``pip install`` directly — the hook env
    is isolated. ``additional_dependencies`` in ``.pre-commit-config.yaml``
    is the actual lever they have.
    """
    monkeypatch.setenv("PRE_COMMIT", "1")
    msg = _format_install_action("pip install 'safelint[python]'")
    assert "additional_dependencies" in msg
    assert ".pre-commit-config.yaml" in msg
    assert "'safelint[python]'" in msg
    assert "pip install" not in msg


def test_format_install_action_typescript_extra_under_precommit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-commit hint preserves whichever extra spec the language module exports."""
    monkeypatch.setenv("PRE_COMMIT", "1")
    msg = _format_install_action("pip install 'safelint[typescript]'")
    assert "'safelint[typescript]'" in msg
    assert "additional_dependencies" in msg


def test_emit_warnings_use_precommit_hint_when_running_under_precommit(capsys: pytest.CaptureFixture[str], mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: warning emitted in pre-commit context names additional_dependencies, not pip install."""
    monkeypatch.setenv("PRE_COMMIT", "1")
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".py": "pip install 'safelint[python]'"},
    )
    _emit_hook_grammar_warnings(["app.py"])
    err = capsys.readouterr().err
    assert "additional_dependencies" in err
    assert ".pre-commit-config.yaml" in err
    assert "pip install" not in err


# ---------------------------------------------------------------------------
# Silent-failure guard exit codes
# ---------------------------------------------------------------------------


def test_check_exit_code_returns_2_when_all_files_skipped_for_missing_grammar() -> None:
    """``_check_exit_code`` returns 2 when discovery found unavailable files AND zero files got linted.

    Regression guard: the silent-failure guard must fire in *every*
    output mode (pretty / json / sarif), since CI pipelines often run
    ``--format sarif`` and a hidden-green run there is the worst case
    — a code-quality dashboard would show "no issues" when actually no
    linting happened.
    """
    assert _check_exit_code(results=[], unavailable_found={".py"}, all_blocking=[]) == 2


def test_check_exit_code_returns_1_when_blocking_violations_present() -> None:
    """Normal failure: at least one blocking violation → exit 1."""
    fake_violation = object()  # type doesn't matter for the boolean test
    assert _check_exit_code(results=[object()], unavailable_found=set(), all_blocking=[fake_violation]) == 1


def test_check_exit_code_returns_0_on_clean_run() -> None:
    """No violations, nothing skipped → exit 0."""
    assert _check_exit_code(results=[object()], unavailable_found=set(), all_blocking=[]) == 0


def test_check_exit_code_returns_0_when_no_files_and_no_unavailable() -> None:
    """Zero files discovered but no unavailable extensions either — likely an empty dir, not a misconfig. Exit 0."""
    assert _check_exit_code(results=[], unavailable_found=set(), all_blocking=[]) == 0


def test_guard_hook_silent_failure_returns_2_when_every_passed_file_unavailable() -> None:
    """Hook-mode guard returns 2 (exit-code suggestion) when pre-commit passed files but none could be linted."""
    rc = _guard_hook_silent_failure(passed=["app.py", "lib.py"], filtered=[], unavailable_in_passed={".py"})
    assert rc == 2


def test_guard_hook_silent_failure_returns_0_when_some_files_linted() -> None:
    """Mixed run with some lintable files — guard doesn't trigger, returns 0."""
    rc = _guard_hook_silent_failure(passed=["app.py", "lib.ts"], filtered=["app.py"], unavailable_in_passed={".ts"})
    assert rc == 0


def test_guard_hook_silent_failure_returns_0_when_no_files_passed() -> None:
    """Pre-commit invokes the hook with no files — not a misconfig, returns 0."""
    rc = _guard_hook_silent_failure(passed=[], filtered=[], unavailable_in_passed=set())
    assert rc == 0


def test_emit_missing_grammar_warnings_silent_mode_suppresses_stderr_keeps_return_set(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """``silent=True`` suppresses stderr warnings but still returns the seen-extension set.

    The silent-failure guard depends on the return value to fire exit
    code 2 in JSON / SARIF mode; the stderr warnings would noise up
    tooling consumers' parse pipelines. Both must be independently
    controllable.
    """
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".py": "pip install 'safelint[python]'"},
    )
    seen = _emit_missing_grammar_warnings(tmp_path, silent=True)
    assert seen == {".py"}  # return value preserved for the silent-failure guard
    assert capsys.readouterr().err == ""  # but no stderr noise for JSON / SARIF consumers


def test_matching_suffixes_ignores_leading_dot_dotfiles() -> None:
    """Regression: a literal file named ``.ts`` shouldn't trigger the missing-TS-grammar hint.

    Mirrors ``pathlib.Path.suffix`` semantics — dotfiles have no
    suffix, so the walker must ignore them. Without the ``idx > 0``
    guard (vs ``idx != -1``), ``.ts`` / ``.py`` / ``.gitignore``
    would be misclassified.
    """
    found = _matching_suffixes([".ts", ".py", ".gitignore", "real.ts"], {".ts": "hint", ".py": "hint"})
    assert found == {".ts"}, f"expected only real.ts to match; got {found}"


# ---------------------------------------------------------------------------
# safelint skill install — language-grammar nudge
# ---------------------------------------------------------------------------


def test_compose_extras_install_command_alphabetical(mocker: MockerFixture) -> None:
    """Composed install command lists extras alphabetically (deterministic for diffs)."""
    assert _compose_extras_install_command({"typescript", "python"}) == "pip install 'safelint[python,typescript]'"
    assert _compose_extras_install_command({"python"}) == "pip install 'safelint[python]'"
    assert _compose_extras_install_command({"javascript", "python", "typescript"}) == "pip install 'safelint[javascript,python,typescript]'"


def test_emit_skill_install_grammar_hint_silent_when_every_grammar_installed(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """Dev install (every grammar present) → helper is a no-op, no stderr noise."""
    mocker.patch("safelint.cli.unavailable_extensions", return_value={})
    _emit_skill_install_grammar_hint(tmp_path)
    assert capsys.readouterr().err == ""


def test_emit_skill_install_grammar_hint_silent_when_no_source_files_present(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """Empty target tree → no nudge, even when extras are uninstalled (nothing to nudge about)."""
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".py": "pip install 'safelint[python]'"},
    )
    _emit_skill_install_grammar_hint(tmp_path)
    assert capsys.readouterr().err == ""


def test_emit_skill_install_grammar_hint_emits_composed_command_for_multi_language(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """Python + TypeScript project with neither grammar installed → ONE composed command, not two."""
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app.ts").write_text("const x = 1;\n", encoding="utf-8")
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={
            ".py": "pip install 'safelint[python]'",
            ".ts": "pip install 'safelint[typescript]'",
            ".tsx": "pip install 'safelint[typescript]'",
            ".as": "pip install 'safelint[typescript]'",
        },
    )
    mocker.patch("safelint.cli.extra_name_for", new={".py": "python", ".ts": "typescript", ".tsx": "typescript", ".as": "typescript"}.get)
    _emit_skill_install_grammar_hint(tmp_path)
    err = capsys.readouterr().err
    # Single warning line, with the composed two-extra command.
    assert err.count("safelint: warning:") == 1
    assert "safelint[python,typescript]" in err
    assert "2 language" in err  # plural "languages" or count "2 language(s)"


def test_emit_skill_install_grammar_hint_emits_single_extra_for_single_language(tmp_path: Path, capsys: pytest.CaptureFixture[str], mocker: MockerFixture) -> None:
    """Single-language project missing one grammar → single-extra install command."""
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    mocker.patch(
        "safelint.cli.unavailable_extensions",
        return_value={".py": "pip install 'safelint[python]'"},
    )
    mocker.patch("safelint.cli.extra_name_for", new={".py": "python"}.get)
    _emit_skill_install_grammar_hint(tmp_path)
    err = capsys.readouterr().err
    assert "safelint[python]" in err
    assert "," not in err.split("safelint[")[-1].split("]")[0]  # no comma inside the bracket → not composed
    assert "1 language" in err


def test_extra_name_for_returns_none_when_extension_supported() -> None:
    """``extra_name_for(".py")`` is None when the Python grammar is installed (dev env)."""
    assert extra_name_for(".py") is None  # dev env has all grammars
    assert extra_name_for(".unknown") is None  # never-registered extension
