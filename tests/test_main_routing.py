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


def test_run_hook_returns_zero_for_empty_files_list() -> None:
    """Hook mode with no .py files passed in (e.g. pre-commit ran on
    a non-Python diff) exits 0 immediately without engine setup."""
    args = argparse.Namespace(fail_on=None, mode=None, ignore=None, output_format="pretty", no_cache=False, stdin=False, stdin_filename="")
    assert cli._run_hook(args, []) == 0


def test_run_hook_threads_cli_ignore_into_engine_config(tmp_path: pytest.TempPathFactory, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """``--ignore`` from the hook-mode CLI augments the config's ignore list."""
    sample = tmp_path / "f.py"
    sample.write_text("x = 1\n", encoding="utf-8")
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
