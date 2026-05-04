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


def test_main_routes_to_check_subcommand(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: object) -> None:
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


def test_main_propagates_nonzero_exit_from_runner(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """If the chosen runner returns non-zero, ``main`` exits with that code."""
    monkeypatch.setattr("sys.argv", ["safelint"])
    mocker.patch.object(cli, "_run_hook", return_value=1)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1


def test_main_routes_to_check_when_global_flag_precedes_subcommand(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: object) -> None:
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


def test_main_routes_to_check_with_multiple_value_taking_flags(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: object) -> None:
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


def test_main_routes_to_check_with_equals_form_flag(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: object) -> None:
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


def test_first_positional_index_skips_value_taking_options() -> None:
    """``_first_positional_index`` returns the index of the first true positional."""
    assert cli._first_positional_index(["--format", "json", "check", "src"]) == 2
    assert cli._first_positional_index(["--mode", "ci", "--fail-on", "warning", "x"]) == 4
    # Equals form is one token — no skip.
    assert cli._first_positional_index(["--format=json", "check"]) == 1
    # Store-true flag — no skip.
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


def test_run_hook_threads_cli_ignore_into_engine_config(tmp_path: pytest.TempPathFactory, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """``--ignore`` from the hook-mode CLI augments the config's ignore list.

    Patches the ``SafetyEngine`` constructor used by ``cli._run_hook`` to
    capture the merged config dict, then asserts ``SAFE999`` (passed via
    ``args.ignore``) ended up in ``config["ignore"]``. Without this
    assertion the test only proved ``_run_hook`` returned 0 — it didn't
    actually verify the CLI flag was threaded through.
    """
    sample = tmp_path / "f.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    real_engine_init = cli.SafetyEngine.__init__

    def _capture_init(self: cli.SafetyEngine, config: dict, *args_: object, **kwargs: object) -> None:
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


def test_is_under_target_returns_true_for_file_match(tmp_path: pytest.TempPathFactory) -> None:
    """``_is_under_target`` returns True for an exact file path match."""
    f = tmp_path / "a.py"
    f.write_text("", encoding="utf-8")
    assert cli._is_under_target(f, f) is True


def test_is_under_target_returns_false_for_unrelated_path(tmp_path: pytest.TempPathFactory) -> None:
    """An absolute path outside the target file/dir returns False."""
    a = tmp_path / "a.py"
    b = tmp_path / "elsewhere.py"
    a.write_text("", encoding="utf-8")
    b.write_text("", encoding="utf-8")
    assert cli._is_under_target(a, b) is False


def test_normalize_path_falls_back_to_absolute_for_paths_outside_cwd(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """``_normalize_path`` returns the absolute string when the path is
    outside the cwd (the ``relative_to`` fallback path)."""
    monkeypatch.chdir(tmp_path)
    elsewhere = tmp_path.parent / "elsewhere.py"
    out = cli._normalize_path(elsewhere, tmp_path)
    assert out == str(elsewhere)


def test_config_dir_uses_supplied_directory(tmp_path: pytest.TempPathFactory) -> None:
    """When ``--config`` points at a directory, ``_config_dir`` returns it."""
    out = cli._config_dir(tmp_path, tmp_path / "irrelevant.py")
    assert out == tmp_path


def test_config_dir_uses_parent_when_supplied_path_is_file(tmp_path: pytest.TempPathFactory) -> None:
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
    """Empty input prints nothing — no header, no table, no blank lines."""
    cli._print_statistics([], [])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_run_check_json_emits_empty_doc_when_no_modified_files(
    tmp_path: pytest.TempPathFactory,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` with no git-modified files still emits a parseable
    JSON document on stdout (so CI tools that pipe stdout don't get an
    empty stream)."""
    import json  # noqa: PLC0415

    mocker.patch.object(cli, "_get_git_modified_python_files", return_value=([], []))
    args = argparse.Namespace(
        target=tmp_path,
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
    tmp_path: pytest.TempPathFactory,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``safelint check`` in pretty mode prints ``All checks passed.`` even
    when the run is clean (matching ruff/ty's UX contract; hook mode
    stays silent on success via ``silent_on_clean``)."""
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    # Skip the git-modified-files probe so all_files-style discovery runs.
    mocker.patch.object(cli, "_get_git_modified_python_files", return_value=None)
    args = argparse.Namespace(
        target=sample,
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
    tmp_path: pytest.TempPathFactory,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` skips the per-file pretty stream and emits a single
    JSON doc with the violation list."""
    import json  # noqa: PLC0415

    sample = tmp_path / "long.py"
    sample.write_text("def f():\n" + "    a = 1\n" * 80 + "    return a\n", encoding="utf-8")
    mocker.patch.object(cli, "_get_git_modified_python_files", return_value=None)
    args = argparse.Namespace(
        target=sample,
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
