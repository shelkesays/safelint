"""Tests for ``safelint skill install`` and ``safelint skill path``.

These cover the on-disk install behaviour (copy / symlink / project
scope / force / idempotency / error path) and the routing through
``cli.main``. They use ``tmp_path`` + monkeypatched ``Path.home`` /
``Path.cwd`` so the user's real ``~/.claude/skills/`` is never touched.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest

from safelint import _skill_install, cli


if TYPE_CHECKING:
    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(*, project: bool = False, symlink: bool = False, force: bool = False) -> argparse.Namespace:
    """Return a Namespace shaped like the install argparser produces."""
    return argparse.Namespace(skill_action="install", project=project, symlink=symlink, force=force)


def _redirect_home_and_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """Redirect ``Path.home`` and ``Path.cwd`` so install targets land under tmp_path."""
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: cwd))
    return home, cwd


# ---------------------------------------------------------------------------
# bundled_skill_path: locates SKILL.md inside the package
# ---------------------------------------------------------------------------


def test_bundled_skill_path_returns_existing_directory() -> None:
    """The bundled skill files ship with the wheel and must exist after install."""
    path = _skill_install.bundled_skill_path()
    assert path.is_dir()
    assert (path / "SKILL.md").is_file()
    assert (path / "languages" / "python.md").is_file()


# ---------------------------------------------------------------------------
# run_install: copy mode (default)
# ---------------------------------------------------------------------------


def test_install_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Default install copies SKILL.md + languages/ into ~/.claude/skills/safelint/."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args())
    assert rc == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not target.is_symlink()
    assert (target / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: safelint")
    assert (target / "languages" / "python.md").is_file()
    out = capsys.readouterr().out
    assert "copied" in out
    assert "user scope" in out


def test_install_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--project`` lands under <cwd>/.claude/skills/safelint/ instead of home."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(project=True))
    assert rc == 0
    assert (cwd / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    # User-global location was NOT touched.
    assert not (home / ".claude").exists()


# ---------------------------------------------------------------------------
# run_install: symlink mode
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--symlink`` creates a directory symlink to the bundled location."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(symlink=True))
    assert rc == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_symlink()
    # Resolves to the bundled path.
    assert target.resolve() == _skill_install.bundled_skill_path().resolve()


# ---------------------------------------------------------------------------
# Idempotency / --force / collision
# ---------------------------------------------------------------------------


def test_install_refuses_to_overwrite_existing_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Installing twice without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args()) == 0
    rc = _skill_install.run_install(_make_args())
    assert rc == 1
    captured = capsys.readouterr()
    # Errors go to stderr so wrapper scripts can capture them without
    # polluting stdout (which is reserved for success messages).
    assert "already exists" in captured.err
    assert "--force" in captured.err


def test_install_with_force_replaces_existing_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` deletes the existing install (file/symlink/dir) before re-installing."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".claude" / "skills" / "safelint"
    # Pre-populate with a stale file, then install with --force.
    target.mkdir(parents=True)
    (target / "stale.md").write_text("old", encoding="utf-8")

    assert _skill_install.run_install(_make_args(force=True)) == 0
    assert (target / "SKILL.md").is_file()
    assert not (target / "stale.md").exists()


def test_install_with_force_replaces_existing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` works when the target is a stray file (not a directory)."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".claude" / "skills" / "safelint"
    target.parent.mkdir(parents=True)
    target.write_text("not a directory", encoding="utf-8")

    assert _skill_install.run_install(_make_args(force=True)) == 0
    assert target.is_dir()
    assert (target / "SKILL.md").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlink prerequisites")
def test_install_with_force_replaces_existing_symlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` correctly unlinks a stale symlink before re-installing."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".claude" / "skills" / "safelint"
    target.parent.mkdir(parents=True)
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    target.symlink_to(decoy, target_is_directory=True)

    assert _skill_install.run_install(_make_args(force=True)) == 0
    assert target.is_dir()
    assert not target.is_symlink()


# ---------------------------------------------------------------------------
# run_path
# ---------------------------------------------------------------------------


def test_run_path_prints_bundled_directory(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path`` prints the on-disk location of bundled files."""
    rc = _skill_install.run_path(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out).is_dir()
    assert (Path(out) / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# CLI routing through main()
# ---------------------------------------------------------------------------


def test_cli_routes_skill_install_to_run_install(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install`` routes to _skill_install.run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()
    args = spy.call_args.args[0]
    assert args.project is True
    assert args.symlink is False
    assert args.force is False


def test_cli_routes_skill_path_to_run_path(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill path`` routes to _skill_install.run_path."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "path"])
    spy = mocker.patch.object(_skill_install, "run_path", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()


def test_cli_skill_without_action_errors_out(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Bare ``safelint skill`` with no action exits with argparse usage error."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    # argparse exits 2 on missing required positional.
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "skill" in err.lower()


def test_cli_skill_rejects_unknown_flag_before_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Mistyped flags before ``skill`` must fail loudly, not be silently dropped.

    Regression for argv-routing parity: the ``check`` branch already passes
    pre-subcommand tokens through to its parser so typos like
    ``--formta=json`` get rejected; the ``skill`` branch should do the
    same. Without this, ``safelint --formta=json skill install`` would
    silently install the skill while the user thinks they passed an
    output-format flag (one that doesn't apply to skill anyway).
    """
    monkeypatch.setattr("sys.argv", ["safelint", "--formta=json", "skill", "install"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    # argparse exits 2 on unknown flag.
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "formta" in err or "unrecognized" in err.lower()
