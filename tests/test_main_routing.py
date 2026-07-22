"""Integration tests for ``safelint.cli.main`` argv-routing.

The ``main`` function decides between three runners (stdin / check / hook)
based on the shape of ``sys.argv``. These tests drive each branch end-to-end
through ``main()`` and assert the right runner was invoked with the right
exit code, covering the routing logic that smaller unit tests skip.
"""

from __future__ import annotations

import argparse
import io
from typing import TYPE_CHECKING

import pytest

from safelint import cli


if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from pytest_mock import MockerFixture


def test_main_routes_to_stdin_when_flag_present(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--stdin`` anywhere in argv invokes ``_run_stdin`` and exits with its code."""
    monkeypatch.setattr("sys.argv", ["safelint", "--stdin", "--stdin-filename", "buf.py"])
    monkeypatch.setattr("sys.stdin", io.StringIO("x = 1\n"))
    spy = mocker.patch.object(cli, "_run_stdin", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()


def test_main_routes_to_check_subcommand(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: Path) -> None:
    """First non-flag arg ``check`` selects the directory-scan runner."""
    monkeypatch.setattr("sys.argv", ["safelint", "check", str(tmp_path)])
    spy = mocker.patch.object(cli, "_run_check", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()


def test_main_routes_to_hook_mode_with_files(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """No ``--stdin`` and first non-flag arg isn't ``check`` → hook mode with .py args as files."""
    monkeypatch.setattr("sys.argv", ["safelint", "a.py", "b.py", "--fail-on=error"])
    spy = mocker.patch.object(cli, "_run_hook", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    _args, files = spy.call_args.args
    assert sorted(files) == ["a.py", "b.py"]


def test_main_hook_mode_filters_non_py_args(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """In hook mode, only ``.py`` positional args become files; others are ignored."""
    monkeypatch.setattr("sys.argv", ["safelint", "README.md", "src/foo.py", "Makefile"])
    spy = mocker.patch.object(cli, "_run_hook", return_value=0)
    with pytest.raises(SystemExit):
        cli.main()
    _args, files = spy.call_args.args
    assert files == ["src/foo.py"]


def test_dispatch_hook_silent_failure_emits_only_error_no_redundant_warning(
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Silent-failure case (every file dropped for missing grammar) emits ONE message, not two.

    Regression for the UX bug where pre-commit batched files across N
    invocations and each invocation emitted both a per-extension
    warning AND the silent-failure error containing the same install
    hint - N batches * 2 lines = noisy duplication. The fix detects
    the silent-failure case *before* emitting per-extension warnings
    and skips the warning since the error already carries the
    actionable install hint.
    """
    # TS grammar unavailable, all passed files are .ts → silent-failure case.
    mocker.patch.object(
        cli,
        "unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'"},
    )
    mocker.patch.object(cli, "supported_extensions", return_value=frozenset({".py"}))
    monkeypatch.setattr("sys.argv", ["safelint", "app.ts", "lib.ts"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2

    err = capsys.readouterr().err
    # Error: present, single line about the missing grammar.
    assert err.count("safelint: error: no files linted") == 1
    # Warning: must NOT be present in silent-failure case (the error covers it).
    assert "safelint: warning: skipping" not in err, f"per-extension warning should be suppressed in silent-failure case; got stderr: {err!r}"


def test_dispatch_hook_mixed_run_still_emits_per_extension_warning(
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mixed run (some files lintable, others skipped) still emits the per-extension warning as context.

    The warning is actionable in mixed runs: it tells the user which
    additional extra would let safelint also lint the skipped files.
    Only the silent-failure case suppresses it.
    """
    mocker.patch.object(
        cli,
        "unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'"},
    )
    mocker.patch.object(cli, "supported_extensions", return_value=frozenset({".py"}))
    mocker.patch.object(cli, "_run_hook", return_value=0)
    # One .py (will lint), one .ts (will be skipped) - mixed case.
    monkeypatch.setattr("sys.argv", ["safelint", "app.py", "lib.ts"])

    with pytest.raises(SystemExit):
        cli.main()

    err = capsys.readouterr().err
    assert "safelint: warning: skipping .ts files" in err, f"per-extension warning expected in mixed run; got stderr: {err!r}"
    # No silent-failure error in a mixed run.
    assert "no files linted" not in err


def test_main_propagates_nonzero_exit_from_runner(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """If the chosen runner returns non-zero, ``main`` exits with that code."""
    monkeypatch.setattr("sys.argv", ["safelint"])
    mocker.patch.object(cli, "_run_hook", return_value=1)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1


def test_main_routes_to_check_when_global_flag_precedes_subcommand(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: Path) -> None:
    """``safelint --format json check src`` routes to check, not hook.

    Regression for an argv-routing bug: the scanner used to take the first
    non-``-`` token as the subcommand, but ``--format json`` puts ``json``
    in that position because the value of a value-taking option doesn't
    start with a dash.
    """
    monkeypatch.setattr("sys.argv", ["safelint", "--format", "json", "check", str(tmp_path)])
    spy = mocker.patch.object(cli, "_run_check", return_value=0)
    hook_spy = mocker.patch.object(cli, "_run_hook", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()
    hook_spy.assert_not_called()
    # The check parser still sees --format json after the routing strip.
    args = spy.call_args.args[0]
    assert args.output_format == "json"


def test_main_routes_to_check_with_multiple_value_taking_flags(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: Path) -> None:
    """Several global flags before ``check`` all have their values skipped."""
    monkeypatch.setattr(
        "sys.argv",
        ["safelint", "--mode", "ci", "--fail-on", "warning", "--ignore", "SAFE101", "check", str(tmp_path)],
    )
    spy = mocker.patch.object(cli, "_run_check", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.mode == "ci"
    assert args.fail_on == "warning"
    assert args.ignore == ["SAFE101"]


def test_main_routes_to_check_with_equals_form_flag(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: Path) -> None:
    """``--format=json`` (equals form) is one token, so routing still works."""
    monkeypatch.setattr("sys.argv", ["safelint", "--format=json", "check", str(tmp_path)])
    spy = mocker.patch.object(cli, "_run_check", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()


def test_main_routes_to_hook_when_first_positional_is_a_file(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """A leading global flag with a value still routes to hook when no ``check``."""
    monkeypatch.setattr("sys.argv", ["safelint", "--fail-on", "warning", "a.py"])
    spy = mocker.patch.object(cli, "_run_hook", return_value=0)
    check_spy = mocker.patch.object(cli, "_run_check", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()
    check_spy.assert_not_called()


def test_main_does_not_print_help_when_no_args(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Bare ``safelint`` (no args) routes to hook mode and stays silent - it does NOT print help.

    This documents the actual behaviour and locks it in: top-level
    help is reached only via ``safelint help`` / ``safelint -h`` /
    ``safelint --help``. A bare invocation is reserved for pre-commit
    hook mode (which is silent on success when no ``.py`` files are
    passed in).
    """
    monkeypatch.setattr("sys.argv", ["safelint"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    # Hook mode with empty file list returns 0.
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Should NOT show the help banner.
    assert "Usage: safelint" not in out


def test_main_prints_help_for_explicit_help_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint --help`` prints the ruff-style top-level help and exits 0."""
    monkeypatch.setattr("sys.argv", ["safelint", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Usage: safelint [OPTIONS] <COMMAND>" in out
    assert "Commands:" in out
    assert "Global options:" in out


def test_main_prints_help_for_short_h_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint -h`` matches ``--help`` (also printed via the same path)."""
    monkeypatch.setattr("sys.argv", ["safelint", "-h"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "Usage: safelint" in capsys.readouterr().out


def test_main_prints_help_for_help_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint help`` (no subcommand) matches ``--help``."""
    monkeypatch.setattr("sys.argv", ["safelint", "help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "Usage: safelint" in capsys.readouterr().out


def test_main_prints_version_for_short_v_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint -V`` prints the version on stdout and exits 0."""
    monkeypatch.setattr("sys.argv", ["safelint", "-V"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("safelint ")


def test_main_prints_version_for_long_version_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint --version`` matches ``-V``."""
    monkeypatch.setattr("sys.argv", ["safelint", "--version"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().startswith("safelint ")


def test_main_prints_version_for_version_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint version`` matches ``-V``."""
    monkeypatch.setattr("sys.argv", ["safelint", "version"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().startswith("safelint ")


# ---------------------------------------------------------------------------
# Help / version scanning is position-independent - global flags placed
# *before* the help / version marker (``safelint --format json --version``)
# must still reach the polished top-level renderer rather than falling
# through to argparse. Locks the contract in so a future early-router
# refactor can't silently regress to ``argv[1]``-only inspection.
# ---------------------------------------------------------------------------


def test_main_prints_version_after_value_taking_global_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint --format json --version`` reaches the polished version renderer."""
    monkeypatch.setattr("sys.argv", ["safelint", "--format", "json", "--version"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().startswith("safelint ")


def test_main_prints_help_after_value_taking_global_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint --mode ci --help`` reaches the polished ruff-style top-level help."""
    monkeypatch.setattr("sys.argv", ["safelint", "--mode", "ci", "--help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Polished renderer emits ``Usage: safelint [OPTIONS] <COMMAND>`` and the
    # ``Commands:`` / ``Global options:`` section headers - argparse's
    # auto-generated help has neither.
    assert "Usage: safelint [OPTIONS] <COMMAND>" in out
    assert "Commands:" in out
    assert "Global options:" in out


def test_main_prints_help_with_short_v_after_global_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint --format pretty -V`` short form still reaches version renderer."""
    monkeypatch.setattr("sys.argv", ["safelint", "--format", "pretty", "-V"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().startswith("safelint ")


def _assert_check_subcommand_help(out: str) -> None:
    """Assert *out* is the ``check`` subcommand's argparse usage banner.

    Tighter than ``"check" in out`` (which the top-level help - which
    *lists* ``check`` as a command - would also satisfy). The check
    parser's auto-generated help starts with ``usage: safelint
    check`` on its first non-empty line, which the top-level
    polished help (``Usage: safelint [OPTIONS] <COMMAND>``) does not.
    """
    first_line = next((line for line in out.splitlines() if line.strip()), "")
    lowered = first_line.lower().lstrip()
    assert lowered.startswith("usage:"), f"expected a usage banner, got: {first_line!r}"
    assert "safelint check" in lowered, f"expected the ``check`` subcommand banner, got: {first_line!r}"


def test_main_routes_help_keyword_after_global_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint --format json help check`` finds ``help`` and forwards ``check`` as the sub.

    The ``help`` keyword form supports per-subcommand help; the scan must
    locate ``help`` past the value-taking flag and then locate the next
    positional (``check``) past any further flags.
    """
    monkeypatch.setattr("sys.argv", ["safelint", "--format", "json", "help", "check"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    _assert_check_subcommand_help(capsys.readouterr().out)


def test_main_routes_help_keyword_with_flags_interleaved(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint help --format json check`` skips the value-taking flag and finds ``check``.

    Exercises ``_next_positional``'s value-skipping when the user
    interleaves a global flag *between* the ``help`` keyword and the
    subcommand it's asking about.
    """
    monkeypatch.setattr("sys.argv", ["safelint", "help", "--format", "json", "check"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    _assert_check_subcommand_help(capsys.readouterr().out)


def test_main_routes_to_normal_parser_when_subcommand_precedes_help(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint check --help`` does NOT match the early router - argparse owns subcommand help.

    The early scan stops at the first non-``help`` positional (``check``
    here), so ``--help`` after that point goes to argparse - matching
    the design where each subcommand owns its own usage line.
    """
    monkeypatch.setattr("sys.argv", ["safelint", "check", "--help"])
    # _print_main_help is the polished top-level renderer; it must NOT fire.
    main_help_spy = mocker.patch.object(cli, "_print_main_help")
    with pytest.raises(SystemExit):
        cli.main()
    main_help_spy.assert_not_called()


def test_help_for_unknown_subcommand_returns_nonzero(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint help bogus`` reports the unknown command on stderr and exits non-zero."""
    monkeypatch.setattr("sys.argv", ["safelint", "help", "bogus"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "unknown command" in err
    assert "bogus" in err


def test_first_positional_index_skips_value_taking_options() -> None:
    """``_first_positional_index`` returns the index of the first true positional."""
    assert cli._first_positional_index(["--format", "json", "check", "src"]) == 2
    assert cli._first_positional_index(["--mode", "ci", "--fail-on", "warning", "x"]) == 4
    # Equals form is one token - no skip.
    assert cli._first_positional_index(["--format=json", "check"]) == 1
    # Store-true flag - no skip.
    assert cli._first_positional_index(["--all-files", "src"]) == 1
    # Nothing positional.
    assert cli._first_positional_index(["--format", "json"]) is None
    # Empty.
    assert cli._first_positional_index([]) is None


def test_run_hook_returns_zero_for_empty_files_list() -> None:
    """Hook mode with no .py files passed in (e.g. pre-commit ran on
    a non-Python diff) exits 0 immediately without engine setup."""
    args = argparse.Namespace(fail_on=None, mode=None, ignore=None, output_format="pretty", no_cache=False, stdin=False, stdin_filename="")
    assert cli._run_hook(args, []) == 0


def test_run_hook_threads_cli_ignore_into_engine_config(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """``--ignore`` from the hook-mode CLI augments the config's ignore list.

    Patches the ``SafetyEngine`` constructor used by ``cli._run_hook`` to
    capture the merged config dict, then asserts ``SAFE999`` (passed via
    ``args.ignore``) ended up in ``config["ignore"]``. Without this
    assertion the test only proved ``_run_hook`` returned 0 - it didn't
    actually verify the CLI flag was threaded through.
    """
    sample = tmp_path / "f.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    real_engine_init = cli.SafetyEngine.__init__

    def _capture_init(self: cli.SafetyEngine, config: dict[str, Any], *args_: Any, **kwargs: Any) -> None:
        captured["config"] = config
        real_engine_init(self, config, *args_, **kwargs)

    mocker.patch.object(cli.SafetyEngine, "__init__", _capture_init)

    args = argparse.Namespace(
        fail_on=None,
        mode=None,
        ignore=["SAFE999"],
        output_format="pretty",
        no_cache=True,
        stdin=False,
        stdin_filename="",
    )
    rc = cli._run_hook(args, [str(sample)])
    assert rc == 0
    config = captured["config"]
    assert isinstance(config, dict)
    assert "SAFE999" in config["ignore"]


def test_c_returns_ansi_when_stdout_is_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_c`` wraps text in ANSI codes when stdout reports as a TTY."""

    class _FakeTty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdout", _FakeTty())
    out = cli._c("hello", cli._RED)
    assert out.startswith(cli._RED)
    assert out.endswith(cli._RESET)
    assert "hello" in out


def test_is_under_target_returns_true_for_file_match(tmp_path: Path) -> None:
    """``_is_under_target`` returns True for an exact file path match."""
    f = tmp_path / "a.py"
    f.write_text("", encoding="utf-8")
    assert cli._is_under_target(f, f) is True


def test_is_under_target_returns_false_for_unrelated_path(tmp_path: Path) -> None:
    """An absolute path outside the target file/dir returns False."""
    a = tmp_path / "a.py"
    b = tmp_path / "elsewhere.py"
    a.write_text("", encoding="utf-8")
    b.write_text("", encoding="utf-8")
    assert cli._is_under_target(a, b) is False


def test_filter_modified_under_target_excludes_paths_outside_target(tmp_path: Path) -> None:
    """``_filter_modified_under_target`` restricts the raw set to paths under *target*.

    Regression for the bug where ``_handle_no_targets`` received the
    *repo-wide* raw set: a ``.ts`` file modified outside the requested
    target (e.g. ``safelint check src/python/`` while the only
    modification was to ``ui/widget.ts``) would trip the silent-failure
    guard even though nothing under the requested target was actually
    skipped. The new helper filters the git output to *target* before
    the guard consults it, so the guard fires only for files the
    invocation would have considered.
    """
    (tmp_path / "src" / "python").mkdir(parents=True)
    (tmp_path / "ui").mkdir()
    in_target = tmp_path / "src" / "python" / "app.py"
    off_target = tmp_path / "ui" / "widget.ts"
    in_target.write_text("", encoding="utf-8")
    off_target.write_text("", encoding="utf-8")

    raw = {"src/python/app.py", "ui/widget.ts"}
    target_abs = (tmp_path / "src" / "python").resolve()
    result = cli._filter_modified_under_target(raw, tmp_path, target_abs)

    assert result == {"src/python/app.py"}, f"Expected only files under target; got {result}"


def test_filter_modified_under_target_keeps_only_extension_in_target_when_off_target_is_unavailable(tmp_path: Path) -> None:
    """An off-target ``.ts`` (with TS grammar missing) must NOT appear in the considered set when running against a Python-only subdir."""
    (tmp_path / "src" / "python").mkdir(parents=True)
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "widget.ts").write_text("", encoding="utf-8")

    raw = {"ui/widget.ts"}
    target_abs = (tmp_path / "src" / "python").resolve()
    result = cli._filter_modified_under_target(raw, tmp_path, target_abs)

    assert result == set(), "off-target .ts must not leak into the considered-modified set"


def test_filter_modified_under_target_drops_deleted_paths(tmp_path: Path) -> None:
    """A path git reports as modified but that no longer exists on disk (e.g. a staged delete) must NOT trip the silent-failure guard.

    Regression for the bug where ``git diff --name-only HEAD`` reports
    deleted files, ``_filter_modified_under_target`` kept them in
    ``considered_modified``, and ``_handle_no_targets`` then exited 2
    telling the user to install the grammar for a file they had just
    deleted. The fix mirrors ``_filter_supported_files``'s existence
    check.
    """
    (tmp_path / "src" / "python").mkdir(parents=True)
    # Do NOT create src/python/old_module.ts - simulates a deletion that's
    # still in git's diff output.
    raw = {"src/python/old_module.ts"}
    target_abs = (tmp_path / "src" / "python").resolve()
    result = cli._filter_modified_under_target(raw, tmp_path, target_abs)

    assert result == set(), "deleted (no-longer-on-disk) paths must not appear in the considered-modified set"


def test_normalize_path_falls_back_to_absolute_for_paths_outside_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``_normalize_path`` returns the absolute string when the path is
    outside the cwd (the ``relative_to`` fallback path)."""
    monkeypatch.chdir(tmp_path)
    elsewhere = tmp_path.parent / "elsewhere.py"
    out = cli._normalize_path(elsewhere, tmp_path)
    assert out == str(elsewhere)


def test_config_dir_uses_supplied_directory(tmp_path: Path) -> None:
    """When ``--config`` points at a directory, ``_config_dir`` returns it."""
    out = cli._config_dir(tmp_path, tmp_path / "irrelevant.py")
    assert out == tmp_path


def test_config_dir_uses_parent_when_supplied_path_is_file(tmp_path: Path) -> None:
    """When ``--config`` points at a file, the parent is the search root."""
    cfg_file = tmp_path / "pyproject.toml"
    cfg_file.write_text("", encoding="utf-8")
    out = cli._config_dir(cfg_file, tmp_path / "irrelevant.py")
    assert out == tmp_path


def test_print_status_writes_to_stderr_in_machine_modes(capsys: pytest.CaptureFixture[str]) -> None:
    """In ``json``/``sarif`` modes, status messages go to stderr so stdout
    stays a single parseable document."""
    cli._print_status("info", output_format="json")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "info" in captured.err


def test_print_status_writes_to_stdout_in_pretty_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Pretty mode keeps the existing behaviour: status text on stdout."""
    cli._print_status("info", output_format="pretty")
    captured = capsys.readouterr()
    assert "info" in captured.out
    assert captured.err == ""


def test_print_statistics_emits_per_rule_table(capsys: pytest.CaptureFixture[str]) -> None:
    """``--statistics`` prints a CODE / RULE / ACTIVE / SUPPRESSED breakdown."""
    from safelint.rules.base import Violation  # noqa: PLC0415

    active = [
        Violation(rule="function_length", code="SAFE101", filepath="a.py", lineno=1, message="m", severity="error"),
        Violation(rule="function_length", code="SAFE101", filepath="b.py", lineno=1, message="m", severity="error"),
        Violation(rule="bare_except", code="SAFE201", filepath="c.py", lineno=1, message="m", severity="error"),
    ]
    suppressed = [Violation(rule="side_effects", code="SAFE304", filepath="d.py", lineno=1, message="m", severity="warning")]
    cli._print_statistics(active, suppressed)
    out = capsys.readouterr().out
    assert "SAFE101" in out
    assert "SAFE201" in out
    assert "SAFE304" in out
    assert "ACTIVE" in out
    assert "SUPPRESSED" in out


def test_print_statistics_silent_when_no_violations(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty input prints nothing - no header, no table, no blank lines."""
    cli._print_statistics([], [])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_run_check_json_emits_empty_doc_when_no_modified_files(
    tmp_path: Path,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` with no git-modified files still emits a parseable
    JSON document on stdout (so CI tools that pipe stdout don't get an
    empty stream)."""
    import json  # noqa: PLC0415

    # 3-tuple per v2.0.0+ signature: (all_changed, in_target, considered_modified).
    # ``considered_modified`` is the set of git-modified paths under target
    # (no supported-extension filter applied); empty means "user genuinely
    # modified nothing under target" - distinct from "modified but all
    # filtered out by missing-grammar extensions" which is the silent-pass case.
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=([], [], set()))
    args = argparse.Namespace(
        targets=[tmp_path],
        config=None,
        all_files=False,
        fail_on=None,
        mode=None,
        ignore=None,
        output_format="json",
        no_cache=True,
        stdin=False,
        stdin_filename="",
    )
    rc = cli._run_check(args)
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["summary"]["files_checked"] == 0
    assert doc["violations"] == []


def test_run_check_pretty_prints_all_clear_on_clean_run(
    tmp_path: Path,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``safelint check`` in pretty mode prints ``All checks passed.`` even
    when the run is clean (matching ruff/ty's UX contract; hook mode
    stays silent on success via ``silent_on_clean``)."""
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    # Skip the git-modified-files probe so all_files-style discovery runs.
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=None)
    args = argparse.Namespace(
        targets=[sample],
        config=None,
        all_files=True,
        fail_on=None,
        mode=None,
        ignore=None,
        output_format="pretty",
        no_cache=True,
        stdin=False,
        stdin_filename="",
    )
    rc = cli._run_check(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "All checks passed." in out


def test_run_check_json_emits_doc_with_violations(
    tmp_path: Path,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` skips the per-file pretty stream and emits a single
    JSON doc with the violation list."""
    import json  # noqa: PLC0415

    sample = tmp_path / "long.py"
    sample.write_text("def f():\n" + "    a = 1\n" * 80 + "    return a\n", encoding="utf-8")
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=None)
    args = argparse.Namespace(
        targets=[sample],
        config=None,
        all_files=True,
        fail_on=None,
        mode=None,
        ignore=None,
        output_format="json",
        no_cache=True,
        stdin=False,
        stdin_filename="",
    )
    rc = cli._run_check(args)
    assert rc == 1  # function_length is error-severity
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert any(v["code"] == "SAFE101" for v in doc["violations"])


def test_run_check_returns_2_when_only_modified_files_have_unavailable_grammar(tmp_path: Path, mocker: MockerFixture) -> None:
    """Silent-pass guard: git-modified files all dropped for missing grammars → exit 2.

    Regression for the bug where ``_resolve_check_targets`` returned
    ``no_targets=True`` whenever the post-filter file list was empty,
    masking the case where the user DID modify files but every one
    was filtered out because its grammar isn't installed.
    ``no_targets=True`` would then exit 0 (silent pass) without ever
    consulting the unavailable-extension state - exactly the worst-
    case CI scenario.

    Fix plumbs the ``considered_modified`` set (git-modified paths under
    target, **no** supported-extension filter applied) through, so the
    no-targets path can distinguish "user modified nothing under target"
    from "user modified .ts files under target but TS grammar isn't installed".
    """
    # Simulate: user modified app.ts under target. TS grammar not installed.
    # ``considered_modified`` carries the .ts entry (extension filter is NOT
    # applied to this set); ``in_target`` (the supported-only list) is empty
    # because .ts isn't in supported_extensions() without the [typescript] extra.
    mocker.patch.object(
        cli,
        "_get_git_modified_supported_files",
        return_value=([], [], {"app.ts"}),
    )
    mocker.patch.object(
        cli,
        "unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'"},
    )
    args = argparse.Namespace(
        targets=[tmp_path],
        config=None,
        all_files=False,
        ignore=None,
        no_cache=True,
        statistics=False,
        fail_on=None,
        mode=None,
        output_format="pretty",
    )
    rc = cli._run_check(args)
    assert rc == 2, f"Expected exit 2 (silent-pass guard) when considered_modified has unavailable-grammar files but the supported-extension list is empty; got {rc}"


def test_run_check_returns_0_when_genuinely_no_modifications(tmp_path: Path, mocker: MockerFixture) -> None:
    """Negative control: empty ``considered_modified`` (user truly modified nothing under target) → exit 0, no false silent-pass alarm."""
    mocker.patch.object(
        cli,
        "_get_git_modified_supported_files",
        return_value=([], [], set()),  # empty considered set - genuine clean
    )
    mocker.patch.object(
        cli,
        "unavailable_extensions",
        return_value={".ts": "pip install 'safelint[typescript]'"},
    )
    args = argparse.Namespace(
        targets=[tmp_path],
        config=None,
        all_files=False,
        ignore=None,
        no_cache=True,
        statistics=False,
        fail_on=None,
        mode=None,
        output_format="pretty",
    )
    rc = cli._run_check(args)
    assert rc == 0, f"Expected exit 0 (genuine clean run) when considered_modified is empty; got {rc}"


def _multipath_args(targets: list[Path], **overrides: object) -> argparse.Namespace:
    """Build a ``check``-mode Namespace for the multi-path tests."""
    base = {
        "targets": targets,
        "config": None,
        "all_files": True,
        "fail_on": "warning",
        "mode": None,
        "ignore": None,
        "output_format": "json",
        "no_cache": True,
        "stdin": False,
        "stdin_filename": "",
        "statistics": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_run_check_multiple_paths_aggregate_violations(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint check <a> <b>`` lints both paths and aggregates into one JSON doc + one exit code."""
    import json  # noqa: PLC0415

    a = tmp_path / "a" / "long.py"
    a.parent.mkdir()
    a.write_text("def f():\n" + "    x = 1\n" * 80 + "    return x\n", encoding="utf-8")  # SAFE101 (error)
    b = tmp_path / "b" / "ok.py"
    b.parent.mkdir()
    b.write_text("y = 1\n", encoding="utf-8")  # clean
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=None)

    rc = cli._run_check(_multipath_args([a.parent, b.parent]))
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1  # SAFE101 from path a blocks
    assert any(v["code"] == "SAFE101" for v in doc["violations"])
    assert doc["summary"]["files_checked"] == 2


def test_run_check_overlapping_paths_dedupe_file(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """A file reached via both a directory and its explicit path is linted/reported once."""
    import json  # noqa: PLC0415

    bad = tmp_path / "bad.py"
    bad.write_text("def r(n):\n    return r(n - 1)\n", encoding="utf-8")  # SAFE105 (warning)
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=None)

    rc = cli._run_check(_multipath_args([tmp_path, bad]))
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1  # fail_on=warning -> SAFE105 blocks
    assert doc["summary"]["files_checked"] == 1, "overlapping targets must dedupe to one file"
    assert sum(1 for v in doc["violations"] if v["code"] == "SAFE105") == 1


def test_run_check_all_paths_clean_returns_zero(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """Two clean paths aggregate to a clean run (exit 0)."""
    import json  # noqa: PLC0415

    for name in ("one.py", "two.py"):
        (tmp_path / name).write_text("z = 1\n", encoding="utf-8")
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=None)

    rc = cli._run_check(_multipath_args([tmp_path / "one.py", tmp_path / "two.py"]))
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert doc["violations"] == []


def test_run_check_empty_targets_returns_zero(tmp_path: Path) -> None:
    """A direct caller passing an empty targets list is handled cleanly (no IndexError)."""
    rc = cli._run_check(_multipath_args([], output_format="json"))
    assert rc == 0  # nothing to lint, nothing considered modified


def test_run_check_silent_pass_not_masked_by_a_sibling_target(tmp_path: Path, mocker: MockerFixture) -> None:
    """One target whose only git-modified file has a missing grammar still forces exit 2, even when a sibling target lints clean files.

    Regression for the multi-target masking bug: the exit-2 silent-pass guard
    used to fire only when EVERY target had no files, so a clean sibling made
    the un-linted, grammar-missing target read green.
    """
    strict = tmp_path / "frontend"
    strict.mkdir()
    clean = tmp_path / "backend"
    clean.mkdir()
    (clean / "api.py").write_text("x = 1\n", encoding="utf-8")

    # frontend: a modified app.ts with no TS grammar (silent-pass); backend: a clean modified .py.
    def _modified(target: Path) -> tuple | None:
        if target == strict:
            return ([], [], {"app.ts"})  # no supported files, considered has .ts
        return ([str(clean / "api.py")], [str(clean / "api.py")], {str(clean / "api.py")})

    mocker.patch.object(cli, "_get_git_modified_supported_files", side_effect=_modified)
    mocker.patch.object(cli, "unavailable_extensions", return_value={".ts": "pip install 'safelint[typescript]'"})

    rc = cli._run_check(_multipath_args([strict, clean], all_files=False, output_format="pretty"))
    assert rc == 2, f"a grammar-missing target must not be masked green by a clean sibling; got {rc}"


def test_run_check_all_files_silent_pass_not_masked_by_sibling(tmp_path: Path, mocker: MockerFixture) -> None:
    """--all-files discovery: a target whose only file is grammar-missing forces exit 2, even beside a clean sibling.

    The all-files analogue of the git-modified masking regression: discovery
    returns a skipped placeholder for the grammar-missing file, which must
    still trip the exit-2 guard rather than reading green off the sibling.
    """
    from safelint.core.engine import LintResult  # noqa: PLC0415

    strict = tmp_path / "frontend"
    strict.mkdir()
    (strict / "app.ts").write_text("const x = 1;\n", encoding="utf-8")
    clean = tmp_path / "backend"
    clean.mkdir()
    (clean / "api.py").write_text("x = 1\n", encoding="utf-8")

    mocker.patch.object(cli, "unavailable_extensions", return_value={".ts": "pip install 'safelint[typescript]'"})
    # Discovery on the frontend target returns only a skipped .ts placeholder.
    real_run = cli.run

    def _run(target: Path, **kwargs: object) -> list:
        if target == strict:
            return [LintResult(path=str(strict / "app.ts"))]
        return real_run(target, **kwargs)

    mocker.patch.object(cli, "run", side_effect=_run)

    rc = cli._run_check(_multipath_args([strict, clean], all_files=True, output_format="pretty"))
    assert rc == 2, f"a grammar-missing --all-files target must not be masked green by a clean sibling; got {rc}"


def test_run_check_all_files_zero_files_still_prints_all_clear(tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """An ``--all-files`` run that discovers ZERO lintable files (all excluded / empty tree) still prints ``All checks passed.``.

    Regression: the multi-path refactor routed every "nothing linted" case
    through the silent (pre-commit-friendly) no-targets path, so
    ``safelint check <excluded-or-empty> --all-files`` printed nothing at all
    instead of the interactive clean-run message it printed before 2.10.
    Only the git-modified *no-targets* short-circuit should stay silent.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=None)

    rc = cli._run_check(_multipath_args([empty], all_files=True, output_format="pretty"))
    assert rc == 0
    assert "All checks passed." in capsys.readouterr().out


def test_run_check_empty_sibling_does_not_inherit_missing_grammar(tmp_path: Path, mocker: MockerFixture) -> None:
    """An empty (or no-op) target must not inherit an earlier target's missing-grammar extension.

    Regression: silent-pass was keyed off the cross-target ``out.unavailable``
    union, so ``check src/ empty/`` where src/ has both app.ts (grammar missing)
    and a clean app.py would wrongly exit 2 - even though app.py linted fine and
    empty/ simply has nothing. Silent-pass must key off each target's OWN
    missing-grammar set.
    """
    from safelint.core.engine import LintResult  # noqa: PLC0415

    src = tmp_path / "src"
    src.mkdir()
    (src / "app.ts").write_text("const x = 1;\n", encoding="utf-8")
    (src / "app.py").write_text("x = 1\n", encoding="utf-8")  # clean, real
    empty = tmp_path / "empty"
    empty.mkdir()

    mocker.patch.object(cli, "unavailable_extensions", return_value={".ts": "pip install 'safelint[typescript]'"})
    real_run = cli.run

    def _run(target: Path, **kwargs: object) -> list:
        if target == src:
            # src lints app.py for real, app.ts is a skipped placeholder.
            return [LintResult(path=str(src / "app.ts")), *real_run(src, **kwargs)]
        return real_run(target, **kwargs)

    mocker.patch.object(cli, "run", side_effect=_run)

    rc = cli._run_check(_multipath_args([src, empty], all_files=True, output_format="pretty"))
    assert rc == 0, f"empty sibling must not inherit src/'s missing .ts grammar; app.py linted clean, so exit 0. got {rc}"


def test_run_check_per_target_fail_on_keeps_stricter_subtree_gate(tmp_path: Path, mocker: MockerFixture) -> None:
    """A stricter subtree's fail_on is honoured even when bundled with a laxer first target.

    Regression: fail_on used to be resolved once from the first target and
    applied to all, so a warning in a fail_on=warning subtree bundled after a
    default (fail_on=error) target was downgraded to advisory and exited 0.
    """
    lax = tmp_path / "root"
    lax.mkdir()
    (lax / "ok.py").write_text("k = 1\n", encoding="utf-8")  # clean
    strict = tmp_path / "strict"
    strict.mkdir()
    (strict / "safelint.toml").write_text("fail_on = 'warning'\n", encoding="utf-8")
    (strict / "warn.py").write_text("def r(n):\n    return r(n - 1)\n", encoding="utf-8")  # SAFE105 (warning)
    mocker.patch.object(cli, "_get_git_modified_supported_files", return_value=None)

    # No CLI --fail-on/--mode, so each target's own config governs its threshold.
    rc = cli._run_check(_multipath_args([lax, strict], all_files=True, fail_on=None, mode=None, output_format="pretty"))
    assert rc == 1, f"the strict subtree's fail_on=warning must still block; got {rc}"
