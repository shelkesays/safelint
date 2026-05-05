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


def _make_args(*, project: bool = False, symlink: bool = False, force: bool = False, client: str = "auto") -> argparse.Namespace:
    """Return a Namespace shaped like the install argparser produces.

    The default ``client="auto"`` matches the CLI default — call
    sites that need a specific client should pass it explicitly so
    intent is obvious and so changes to auto-detection don't
    accidentally hide regressions in single-client tests.
    """
    return argparse.Namespace(skill_action="install", project=project, symlink=symlink, force=force, client=client)


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


def test_bundled_cursor_rule_exists_in_wheel() -> None:
    """The Cursor MDC ships alongside the Claude skill under ``skill_files/cursor/``."""
    path = _skill_install.bundled_skill_path() / "cursor" / "safelint.mdc"
    assert path.is_file()
    # Sanity: MDC frontmatter is YAML-style, opening with ``---`` and
    # carrying ``description:`` so Cursor's rules engine recognises it.
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("---\n")
    assert "description:" in head


# ---------------------------------------------------------------------------
# run_install: copy mode (default)
# ---------------------------------------------------------------------------


def test_install_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Explicit ``--client claude`` install copies SKILL.md + languages/ into ~/.claude/skills/safelint/."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="claude"))
    assert rc == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not target.is_symlink()
    assert (target / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: safelint")
    assert (target / "languages" / "python.md").is_file()
    # Peer-client bundles must NOT leak into the Claude install — the
    # cursor/ subdirectory under skill_files/ is for Cursor users only.
    assert not (target / "cursor").exists()
    out = capsys.readouterr().out
    assert "copied" in out
    assert "user scope" in out


def test_install_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client claude --project`` lands under <cwd>/.claude/skills/safelint/ instead of home."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="claude", project=True))
    assert rc == 0
    assert (cwd / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    # User-global location was NOT touched.
    assert not (home / ".claude").exists()


# ---------------------------------------------------------------------------
# run_install: symlink mode
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--symlink`` materialises a per-entry-symlinked directory at the target.

    For the directory-source case (Claude install), the install
    creates a real target directory and symlinks each allowed
    top-level entry inside it. Symlinking the whole skill_files/
    tree would expose the peer ``cursor/`` subdirectory in the
    Claude install — see :func:`_install_symlink_directory_filtered`.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="claude", symlink=True))
    assert rc == 0
    target = home / ".claude" / "skills" / "safelint"
    # Target itself is a real directory (not a symlink), populated
    # with per-entry symlinks.
    assert target.is_dir()
    assert not target.is_symlink()
    # The expected top-level entries are symlinks pointing into the
    # bundled location, so ``pip upgrade safelint`` still reflects
    # content changes underneath them.
    skill_link = target / "SKILL.md"
    assert skill_link.is_symlink()
    bundled = _skill_install.bundled_skill_path()
    assert skill_link.resolve() == (bundled / "SKILL.md").resolve()
    languages_link = target / "languages"
    assert languages_link.is_symlink()
    assert languages_link.resolve() == (bundled / "languages").resolve()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_symlink_excludes_peer_client_bundles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--symlink`` install must not expose the peer ``cursor/`` bundle inside the Claude install.

    Mirrors the contract enforced by ``test_install_copy_user_scope``
    (``cursor/`` is excluded from the materialised skill folder).
    Symlink mode previously linked the whole skill_files/ directory
    in one call, which transparently included ``cursor/`` — a leak.
    The fixed install symlinks per-entry, skipping peer dirs.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="claude", symlink=True))
    assert rc == 0
    target = home / ".claude" / "skills" / "safelint"
    assert not (target / "cursor").exists()


# ---------------------------------------------------------------------------
# Idempotency / --force / collision
# ---------------------------------------------------------------------------


def test_install_refuses_to_overwrite_existing_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Installing the Claude skill twice without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    rc = _skill_install.run_install(_make_args(client="claude"))
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

    assert _skill_install.run_install(_make_args(client="claude", force=True)) == 0
    assert (target / "SKILL.md").is_file()
    assert not (target / "stale.md").exists()


def test_install_with_force_replaces_existing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` works when the target is a stray file (not a directory)."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".claude" / "skills" / "safelint"
    target.parent.mkdir(parents=True)
    target.write_text("not a directory", encoding="utf-8")

    assert _skill_install.run_install(_make_args(client="claude", force=True)) == 0
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

    assert _skill_install.run_install(_make_args(client="claude", force=True)) == 0
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


# ---------------------------------------------------------------------------
# Cursor client install
# ---------------------------------------------------------------------------


def test_install_cursor_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client cursor`` copies the bundled MDC into ~/.cursor/rules/safelint.mdc."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="cursor"))
    assert rc == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    assert target.is_file()
    assert not target.is_symlink()
    head = target.read_text(encoding="utf-8")[:200]
    assert head.startswith("---\n")
    assert "description:" in head
    out = capsys.readouterr().out
    # Output uses the per-client display_name + artefact_label
    # (``Cursor rule`` for the .mdc, distinct from ``Claude Code skill``).
    assert "Cursor rule" in out
    assert "copied" in out
    assert "user scope" in out
    # Claude skill location must NOT be touched when --client cursor.
    assert not (home / ".claude").exists()


def test_install_cursor_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client cursor --project`` lands at <cwd>/.cursor/rules/safelint.mdc."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="cursor", project=True))
    assert rc == 0
    assert (cwd / ".cursor" / "rules" / "safelint.mdc").is_file()
    # User-global Cursor location was NOT touched.
    assert not (home / ".cursor").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_cursor_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client cursor --symlink`` creates a file symlink to the bundled MDC."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="cursor", symlink=True))
    assert rc == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "cursor" / "safelint.mdc"
    assert target.resolve() == bundled.resolve()


def test_install_cursor_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale Cursor MDC at the target location."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".cursor" / "rules" / "safelint.mdc"
    target.parent.mkdir(parents=True)
    target.write_text("--- stale ---\nold rule\n", encoding="utf-8")

    assert _skill_install.run_install(_make_args(client="cursor", force=True)) == 0
    # Content was replaced, not appended.
    assert "stale" not in target.read_text(encoding="utf-8")


def test_install_cursor_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second cursor install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    rc = _skill_install.run_install(_make_args(client="cursor"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "--force" in captured.err


def test_run_path_with_client_cursor_prints_mdc_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client cursor`` prints the MDC file path (not the directory)."""
    rc = _skill_install.run_path(argparse.Namespace(client="cursor"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "safelint.mdc"


def test_run_path_default_client_prints_claude_directory(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path`` (no client) prints the Claude skill directory."""
    rc = _skill_install.run_path(argparse.Namespace(client="claude"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_dir()
    assert (p / "SKILL.md").is_file()


def test_cli_routes_skill_install_with_cursor_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client cursor`` forwards client=cursor to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "cursor", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "cursor"
    assert args.project is True


def test_cli_routes_skill_install_default_client_is_auto(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install`` (no --client) defaults client to ``auto``.

    The auto default replaced the prior ``claude`` default so a fresh
    ``safelint skill install`` detects whichever AI client(s) the
    current project / user is using and installs each one's skill.
    Explicit ``--client claude`` still works for users who want the
    pre-auto-default behaviour.
    """
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "auto"


def test_cli_skill_install_rejects_unknown_client(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client cline`` (unknown) fails loudly via argparse choice validation."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "cline"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "client" in err
    assert "cline" in err


# ---------------------------------------------------------------------------
# --client auto: detection-driven install
# ---------------------------------------------------------------------------


def test_install_auto_detects_claude_in_cwd_via_claude_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto`` with ``CLAUDE.md`` in cwd installs Claude project-scoped."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "CLAUDE.md").write_text("# project guide", encoding="utf-8")

    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    # Project-scoped install (cwd-detected → cwd-scoped).
    assert (cwd / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    # User-global location was NOT touched.
    assert not (home / ".claude").exists()
    out = capsys.readouterr().out
    assert "detected Claude Code (CLAUDE.md) in current directory" in out
    assert "Claude Code skill copied" in out
    assert "(project scope)" in out


def test_install_auto_detects_claude_in_cwd_via_dot_claude_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client auto`` with ``.claude/`` in cwd also triggers Claude project-scoped install."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".claude").mkdir()  # marker without CLAUDE.md
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    assert not (home / ".claude").exists()


def test_install_auto_detects_claude_in_cwd_via_claude_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto`` with only ``.claude.json`` in cwd also triggers Claude project-scoped install.

    ``.claude.json`` is the Claude Code settings file; some projects
    commit a project-scoped one without an accompanying ``.claude/``
    directory or ``CLAUDE.md``. The detection covers all three forms
    independently — any one is enough.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".claude.json").write_text('{"mcp": {}}', encoding="utf-8")
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    assert not (home / ".claude").exists()
    out = capsys.readouterr().out
    # Detection notice surfaces the actual matched marker.
    assert "Claude Code (.claude.json)" in out


def test_install_auto_falls_back_to_home_via_claude_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Home fallback also covers ``~/.claude.json`` (the user-global Claude Code settings file)."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (home / ".claude.json").write_text('{"mcp": {}}', encoding="utf-8")
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (home / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    assert not (cwd / ".claude").exists()


def test_install_auto_detects_cursor_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto`` with ``.cursor/`` in cwd installs Cursor project-scoped."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".cursor").mkdir()

    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".cursor" / "rules" / "safelint.mdc").is_file()
    assert not (home / ".cursor").exists()
    out = capsys.readouterr().out
    assert "detected Cursor (.cursor) in current directory" in out
    assert "Cursor rule copied" in out


def test_install_auto_detects_both_clients_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto`` with both markers in cwd installs both, in registry order."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "CLAUDE.md").write_text("guide", encoding="utf-8")
    (cwd / ".cursor").mkdir()

    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    # Both installed, both project-scoped.
    assert (cwd / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    assert (cwd / ".cursor" / "rules" / "safelint.mdc").is_file()
    # User-global locations were NOT touched.
    assert not (home / ".claude").exists()
    assert not (home / ".cursor").exists()
    out = capsys.readouterr().out
    # Detection notice mentions both.
    assert "Claude Code (CLAUDE.md) and Cursor (.cursor) in current directory" in out
    # Registry order: claude appears before cursor in the success messages.
    claude_pos = out.index("Claude Code skill copied")
    cursor_pos = out.index("Cursor rule copied")
    assert claude_pos < cursor_pos


def test_install_auto_falls_back_to_home_when_cwd_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto`` with empty cwd but Claude marker in home installs user-scoped."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # cwd has nothing; home has the .claude marker (e.g. user already
    # has Claude Code installed globally).
    (home / ".claude").mkdir()

    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    # User-scoped install (home-detected → home-scoped).
    assert (home / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    # Project location was NOT touched.
    assert not (cwd / ".claude").exists()
    out = capsys.readouterr().out
    assert "in home directory" in out
    assert "(user scope)" in out


def test_install_auto_home_fallback_picks_cursor_when_only_cursor_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Home fallback works for Cursor too — ``~/.cursor/`` triggers a user-scoped Cursor install."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (home / ".cursor").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (home / ".cursor" / "rules" / "safelint.mdc").is_file()
    assert not (cwd / ".cursor").exists()


def test_install_auto_errors_when_no_clients_detected_anywhere(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto`` with empty cwd and empty home prints a helpful error."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 1
    err = capsys.readouterr().err
    # Diagnostic + the exact commands the user can run instead.
    assert "could not auto-detect an AI client" in err
    assert "--client claude" in err
    assert "--client cursor" in err
    assert "current directory or home directory" in err
    # Nothing was installed.
    assert not (cwd / ".claude").exists()
    assert not (home / ".claude").exists()


def test_install_auto_with_project_flag_does_not_fall_back_to_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto --project`` only inspects cwd — refuses the home fallback.

    The ``--project`` flag is the user telling us "I want project
    scope, period". If cwd has no markers, error out rather than
    surprising the user with a user-scope install they didn't ask for.
    """
    home, _cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Home HAS a Claude marker, so without --project this would
    # install at user scope. With --project, we must not fall back.
    (home / ".claude").mkdir()

    rc = _skill_install.run_install(_make_args(client="auto", project=True))
    assert rc == 1
    err = capsys.readouterr().err
    assert "could not auto-detect an AI client" in err
    assert "current directory (--project specified)" in err
    # Crucially: home install was NOT triggered.
    assert not (home / ".claude" / "skills" / "safelint").exists()


def test_install_auto_with_project_flag_installs_when_cwd_has_markers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client auto --project`` happily proceeds when cwd has markers."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".cursor").mkdir()

    rc = _skill_install.run_install(_make_args(client="auto", project=True))
    assert rc == 0
    assert (cwd / ".cursor" / "rules" / "safelint.mdc").is_file()
    assert not (home / ".cursor").exists()


def test_install_auto_explicit_client_skips_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Explicit ``--client claude`` ignores cwd markers (no detection notice)."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".cursor").mkdir()  # Cursor marker present, but user said claude.

    rc = _skill_install.run_install(_make_args(client="claude"))
    assert rc == 0
    # Claude installed at user scope (no --project), not at cwd, even
    # though cwd has a Cursor marker — explicit beats auto.
    assert (home / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    assert not (cwd / ".cursor" / "rules" / "safelint.mdc").exists()
    out = capsys.readouterr().out
    # No "detected ... in current directory" notice — that's
    # auto-mode-only output.
    assert "detected" not in out


def test_install_auto_via_cli_routes_with_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """End-to-end: bare ``safelint skill install`` (no --client) goes through auto detection.

    Uses the real CLI parser (not a mocked Namespace) to verify the
    argparse default of ``auto`` makes it through to ``run_install``.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "CLAUDE.md").write_text("guide", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install"])

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    # Auto detected Claude in cwd → project-scoped install.
    assert (cwd / ".claude" / "skills" / "safelint" / "SKILL.md").is_file()
    assert not (home / ".claude").exists()


def test_install_auto_does_not_emit_detection_notice_for_explicit_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Even when the explicit-client target happens to be installed, no detection notice fires."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="cursor"))
    assert rc == 0
    out = capsys.readouterr().out
    # The detection notice ("safelint: detected ...") is auto-mode only.
    assert "detected" not in out


# ---------------------------------------------------------------------------
# Registry / scalability
# ---------------------------------------------------------------------------


def test_client_registry_choices_derive_from_specs() -> None:
    """``INSTALL_CLIENT_CHOICES`` and ``PATH_CLIENT_CHOICES`` mirror the registry.

    Adding a new ``ClientSpec`` to ``_CLIENT_SPECS`` should automatically
    extend both choice tuples. Locks that contract in so a future
    addition can't accidentally land without surfacing in the CLI.
    """
    spec_names = tuple(spec.name for spec in _skill_install._CLIENT_SPECS)
    # Install accepts ``auto`` plus every registered client.
    assert ("auto", *spec_names) == _skill_install.INSTALL_CLIENT_CHOICES
    # Path accepts every registered client (no auto — single-path
    # convention, see the ``run_path`` docstring).
    assert spec_names == _skill_install.PATH_CLIENT_CHOICES


def test_cli_skill_install_rejects_auto_when_args_lack_default(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown client name still fails loudly under the new auto default."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "windsurf"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    # argparse rejects on choices=.
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "windsurf" in err


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


# ---------------------------------------------------------------------------
# Documentation drift detection — every registered AI client's bundled
# skill must mention every rule and every supported language. Parametrised
# over ``_CLIENT_SPECS`` so adding a new client (Copilot, codex, windsurf,
# antigravity, …) automatically inherits these checks.
#
# The tests scan the union of each spec's ``documentation_relpaths`` files
# for membership tokens. They don't enforce a specific format — only that
# the code / name / extension appears somewhere — so a contributor who
# adds a new rule has flexibility about *where* in the doc to put it,
# without skipping it entirely.
# ---------------------------------------------------------------------------


def _read_skill_docs(spec: _skill_install.ClientSpec) -> str:
    """Concatenate every bundled doc file declared on *spec*.

    Each spec lists the relpaths under ``skill_files/`` whose combined
    text *must* mention every rule and every supported extension —
    that's the drift contract enforced by the tests below.
    """
    root = _skill_install.bundled_skill_path()
    parts = [root.joinpath(*relpath).read_text(encoding="utf-8") for relpath in spec.documentation_relpaths]
    return "\n".join(parts)


@pytest.mark.parametrize("spec", _skill_install._CLIENT_SPECS, ids=lambda s: s.name)
def test_skill_documents_every_active_rule(spec: _skill_install.ClientSpec) -> None:
    """Every code AND name in ``ALL_RULES`` appears in the bundled documentation.

    Drift safety net: when someone adds a new rule, they must update
    each registered AI client's bundled docs. Because the test is
    parametrised over ``_CLIENT_SPECS``, adding a new client to the
    registry automatically inherits this contract — no per-client
    test boilerplate.

    Engine-internal codes (``SAFE000`` parse, ``SAFE004``
    unused_suppression) are deliberately excluded because they live
    outside ``ALL_RULES`` — they're emitted by the engine directly,
    not registered as ``BaseRule`` subclasses.
    """
    from safelint.rules import ALL_RULES  # noqa: PLC0415 — local to keep test imports tight

    text = _read_skill_docs(spec)
    missing_codes = [cls.code for cls in ALL_RULES if cls.code not in text]
    missing_names = [cls.name for cls in ALL_RULES if cls.name not in text]
    assert not missing_codes, f"{spec.name}: rule codes missing from skill docs ({spec.documentation_relpaths}): {missing_codes}"
    assert not missing_names, f"{spec.name}: rule names missing from skill docs ({spec.documentation_relpaths}): {missing_names}"


# ---------------------------------------------------------------------------
# Freshness / drift detection — ``safelint skill status`` and the
# ``safelint check --check-skill-freshness`` opt-in flag both delegate
# to ``_install_status`` / ``stale_install_warnings`` in _skill_install.
# ---------------------------------------------------------------------------


def test_install_status_missing_when_target_does_not_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No install at the scope → MISSING (not "differs", not an error)."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    status = _skill_install._install_status(_skill_install._CLAUDE_SPEC, project=False)
    assert status == _skill_install.INSTALL_STATUS_MISSING


def test_install_status_fresh_immediately_after_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A just-installed copy must report FRESH (content matches the bundle)."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    status = _skill_install._install_status(_skill_install._CLAUDE_SPEC, project=False)
    assert status == _skill_install.INSTALL_STATUS_FRESH


def test_install_status_differs_when_install_is_modified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A locally-modified install reports DIFFERS so the status command can flag it."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    # Customise the installed copy — the docs explicitly invite this.
    skill_md = home / ".claude" / "skills" / "safelint" / "SKILL.md"
    skill_md.write_text("# locally customised\n", encoding="utf-8")
    status = _skill_install._install_status(_skill_install._CLAUDE_SPEC, project=False)
    assert status == _skill_install.INSTALL_STATUS_DIFFERS


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_status_symlink_is_always_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Symlinked installs are live by construction — always reported as FRESH.

    A symlink points at the bundled location, so ``pip upgrade safelint``
    is reflected immediately. The status check shouldn't complain.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor", symlink=True)) == 0
    status = _skill_install._install_status(_skill_install._CURSOR_SPEC, project=False)
    assert status == _skill_install.INSTALL_STATUS_FRESH


def test_run_status_returns_zero_when_no_installs_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Empty home + cwd → status exits 0 with a "no installs detected" notice."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_status(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "no AI-client skill installs detected" in out


def test_run_status_returns_zero_when_install_is_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A just-installed skill yields status 0 + a "fresh" line."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    capsys.readouterr()  # drop install output
    rc = _skill_install.run_status(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "fresh" in out
    assert "all detected installs match" in out


def test_run_status_returns_one_when_install_differs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A locally-modified install yields status 1 + a refresh hint."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    target.write_text("# customised\n", encoding="utf-8")
    capsys.readouterr()  # drop install output
    rc = _skill_install.run_status(argparse.Namespace())
    assert rc == 1
    out = capsys.readouterr().out
    assert "differs from bundled" in out
    assert "safelint skill install --force" in out


def test_cli_routes_skill_status(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill status`` routes to ``_skill_install.run_status``."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "status"])
    spy = mocker.patch.object(_skill_install, "run_status", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()


def test_check_with_skill_freshness_flag_calls_stale_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mocker: MockerFixture) -> None:
    """``safelint check --check-skill-freshness`` consults ``stale_install_warnings``."""
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["safelint", "check", "--check-skill-freshness", "--all-files", str(sample)])
    spy = mocker.patch.object(_skill_install, "stale_install_warnings", return_value=[])
    with pytest.raises(SystemExit):
        cli.main()
    spy.assert_called_once()


def test_check_without_freshness_flag_skips_stale_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mocker: MockerFixture) -> None:
    """Default ``safelint check`` (no flag) does NOT pay the freshness-check cost.

    Locks the contract that the freshness check is opt-in only —
    a regression that made it run by default would slow down every
    ``safelint check`` invocation by an FS scan.
    """
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["safelint", "check", "--all-files", str(sample)])
    spy = mocker.patch.object(_skill_install, "stale_install_warnings", return_value=[])
    with pytest.raises(SystemExit):
        cli.main()
    spy.assert_not_called()


def test_check_with_freshness_flag_emits_stderr_warnings_when_stale(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """End-to-end: stale install + ``--check-skill-freshness`` produces a stderr warning.

    Drives the full ``safelint check`` path through the CLI and
    confirms the diagnostics-channel warning fires. Doesn't assert
    the lint exit code — the freshness check is informational only,
    so a clean lint run still exits 0 even if a stale install is
    detected.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a stale Cursor install.
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    (home / ".cursor" / "rules" / "safelint.mdc").write_text("# customised\n", encoding="utf-8")

    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["safelint", "check", "--check-skill-freshness", "--all-files", str(sample)])
    capsys.readouterr()  # drop install output
    with pytest.raises(SystemExit):
        cli.main()
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "Cursor rule" in err
    assert "differs from bundled" in err


def test_stale_install_warnings_returns_one_per_stale_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The public ``stale_install_warnings`` helper returns one string per stale location.

    This is the primitive consumed by ``safelint check --check-skill-freshness``
    — keeping it exercised in isolation makes the freshness flag's behaviour
    easy to reason about.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Install Cursor user-scoped, then customise it.
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    target.write_text("# customised\n", encoding="utf-8")

    warnings = _skill_install.stale_install_warnings()
    assert len(warnings) == 1
    assert "Cursor rule" in warnings[0]
    assert "differs from bundled" in warnings[0]
    assert "safelint skill install --force" in warnings[0]


def test_stale_install_warnings_empty_when_all_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No installs → empty list (not an error) — matches the ``--check-skill-freshness`` "silent on clean" contract."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.stale_install_warnings() == []


@pytest.mark.parametrize("spec", _skill_install._CLIENT_SPECS, ids=lambda s: s.name)
def test_skill_documents_every_supported_extension(spec: _skill_install.ClientSpec) -> None:
    """Every extension from ``supported_extensions()`` appears in the bundled documentation.

    Adding a new language to ``safelint.languages._REGISTRY`` (e.g.
    TypeScript via ``.ts`` / ``.tsx``) requires updating the language
    registry table inside each registered AI client's skill so the
    agent knows which files safelint can lint. This test fails the
    moment the registry adds an extension that the bundled docs don't
    mention. New clients added to ``_CLIENT_SPECS`` inherit the
    constraint automatically.
    """
    from safelint.languages import supported_extensions  # noqa: PLC0415

    text = _read_skill_docs(spec)
    missing = sorted(ext for ext in supported_extensions() if ext not in text)
    assert not missing, f"{spec.name}: supported extensions missing from skill docs ({spec.documentation_relpaths}): {missing}"
