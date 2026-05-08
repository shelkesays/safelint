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


# ---------------------------------------------------------------------------
# GitHub Copilot client install
# ---------------------------------------------------------------------------


def test_bundled_copilot_instructions_exist_in_wheel() -> None:
    """The Copilot instructions ship under ``skill_files/copilot/``."""
    path = _skill_install.bundled_skill_path() / "copilot" / "copilot-instructions.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    # Plain Markdown — no MDC frontmatter (Copilot reads ``.github/
    # copilot-instructions.md`` as raw Markdown).
    assert head.startswith("# safelint")


def test_install_copilot_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client copilot`` copies the bundled instructions into ~/.github/copilot-instructions.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="copilot"))
    assert rc == 0
    target = home / ".github" / "copilot-instructions.md"
    assert target.is_file()
    assert not target.is_symlink()
    out = capsys.readouterr().out
    assert "GitHub Copilot instructions" in out
    assert "user scope" in out
    # Sibling clients must NOT be touched.
    assert not (home / ".claude").exists()
    assert not (home / ".cursor").exists()


def test_install_copilot_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client copilot --project`` lands at <cwd>/.github/copilot-instructions.md (the canonical Copilot location)."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="copilot", project=True))
    assert rc == 0
    assert (cwd / ".github" / "copilot-instructions.md").is_file()
    # User-global location was NOT touched.
    assert not (home / ".github").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_copilot_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client copilot --symlink`` creates a file symlink to the bundled instructions."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="copilot", symlink=True))
    assert rc == 0
    target = home / ".github" / "copilot-instructions.md"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "copilot" / "copilot-instructions.md"
    assert target.resolve() == bundled.resolve()


def test_install_copilot_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale Copilot instructions file at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".github" / "copilot-instructions.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale instructions\n", encoding="utf-8")

    assert _skill_install.run_install(_make_args(client="copilot", force=True)) == 0
    assert "stale instructions" not in target.read_text(encoding="utf-8")


def test_install_copilot_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second copilot install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="copilot")) == 0
    rc = _skill_install.run_install(_make_args(client="copilot"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "--force" in captured.err


def test_install_auto_detects_copilot_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An existing ``.github/copilot/`` directory triggers project-scope Copilot install on auto-detect.

    We plant the ``.github/copilot/`` custom-prompts directory rather
    than the install destination ``.github/copilot-instructions.md``
    itself, so auto-detect still fires (``.github/copilot`` is one of
    the registered cwd markers) but the install can write the
    instructions file fresh without colliding with an existing one.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a Copilot marker at cwd. Use ``.github/copilot/`` (a custom
    # prompts directory) rather than the install destination itself, so
    # the auto-detect picks it up but the install can still write the
    # instructions file fresh.
    (cwd / ".github" / "copilot").mkdir(parents=True)
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".github" / "copilot-instructions.md").is_file()
    out = capsys.readouterr().out
    assert "GitHub Copilot" in out
    # Sibling clients aren't installed unless their markers also exist.
    assert not (home / ".claude").exists()
    assert not (home / ".cursor").exists()


def test_run_path_with_client_copilot_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client copilot`` prints the bundled instructions file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="copilot"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "copilot-instructions.md"


def test_cli_routes_skill_install_with_copilot_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client copilot --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "copilot", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "copilot"
    assert args.project is True


def test_install_copy_excludes_peer_copilot_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``copilot/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "copilot").exists(), "peer copilot/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# Gemini client install
# ---------------------------------------------------------------------------


def test_bundled_gemini_instructions_exist_in_wheel() -> None:
    """The Gemini instructions ship under ``skill_files/gemini/`` as ``GEMINI.md``."""
    path = _skill_install.bundled_skill_path() / "gemini" / "GEMINI.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    # Plain Markdown — Gemini CLI reads ``GEMINI.md`` as raw Markdown.
    assert head.startswith("# safelint")


def test_install_gemini_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client gemini`` copies the bundled instructions into ~/GEMINI.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="gemini"))
    assert rc == 0
    target = home / "GEMINI.md"
    assert target.is_file()
    assert not target.is_symlink()
    out = capsys.readouterr().out
    assert "Gemini instructions" in out
    assert "user scope" in out
    # Sibling clients must NOT be touched.
    assert not (home / ".claude").exists()
    assert not (home / ".cursor").exists()


def test_install_gemini_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client gemini --project`` lands at <cwd>/GEMINI.md (the canonical Gemini CLI location)."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="gemini", project=True))
    assert rc == 0
    assert (cwd / "GEMINI.md").is_file()
    # User-global location was NOT touched.
    assert not (home / "GEMINI.md").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_gemini_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client gemini --symlink`` creates a file symlink to the bundled GEMINI.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="gemini", symlink=True))
    assert rc == 0
    target = home / "GEMINI.md"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "gemini" / "GEMINI.md"
    assert target.resolve() == bundled.resolve()


def test_install_gemini_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale GEMINI.md at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / "GEMINI.md"
    target.write_text("stale gemini instructions\n", encoding="utf-8")

    assert _skill_install.run_install(_make_args(client="gemini", force=True)) == 0
    assert "stale gemini instructions" not in target.read_text(encoding="utf-8")


def test_install_gemini_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second gemini install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="gemini")) == 0
    rc = _skill_install.run_install(_make_args(client="gemini"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "--force" in captured.err


def test_install_auto_detects_gemini_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A ``.gemini/`` directory in cwd triggers project-scope Gemini install on auto-detect."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a Gemini config dir as the marker (avoids clashing with
    # the install destination ``GEMINI.md`` so the install can proceed
    # to write a fresh file).
    (cwd / ".gemini").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / "GEMINI.md").is_file()
    out = capsys.readouterr().out
    assert "Gemini" in out
    # Sibling clients aren't installed unless their markers also exist.
    assert not (home / ".claude").exists()
    assert not (home / ".cursor").exists()


def test_run_path_with_client_gemini_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client gemini`` prints the bundled GEMINI.md path."""
    rc = _skill_install.run_path(argparse.Namespace(client="gemini"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "GEMINI.md"


def test_cli_routes_skill_install_with_gemini_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client gemini --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "gemini", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "gemini"
    assert args.project is True


def test_install_copy_excludes_peer_gemini_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``gemini/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "gemini").exists(), "peer gemini/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# Windsurf client install
# ---------------------------------------------------------------------------


def test_bundled_windsurf_rules_exist_in_wheel() -> None:
    """The Windsurf rules ship under ``skill_files/windsurf/safelint-rules.md``."""
    path = _skill_install.bundled_skill_path() / "windsurf" / "safelint-rules.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_windsurf_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client windsurf`` copies the bundled rules into ~/.windsurfrules (renames during copy)."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="windsurf"))
    assert rc == 0
    target = home / ".windsurfrules"
    assert target.is_file()
    assert not target.is_symlink()
    # Content matches the bundled file (basename differs but contents
    # are byte-equal — copy operation is content-preserving).
    bundled = _skill_install.bundled_skill_path() / "windsurf" / "safelint-rules.md"
    assert target.read_text(encoding="utf-8") == bundled.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "Windsurf rules" in out
    assert "user scope" in out
    # Sibling clients must NOT be touched.
    assert not (home / ".claude").exists()
    assert not (home / ".cursor").exists()


def test_install_windsurf_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client windsurf --project`` lands at <cwd>/.windsurfrules (the canonical Windsurf location)."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="windsurf", project=True))
    assert rc == 0
    assert (cwd / ".windsurfrules").is_file()
    # User-global location was NOT touched.
    assert not (home / ".windsurfrules").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_windsurf_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client windsurf --symlink`` creates a file symlink to the bundled rules."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="windsurf", symlink=True))
    assert rc == 0
    target = home / ".windsurfrules"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "windsurf" / "safelint-rules.md"
    assert target.resolve() == bundled.resolve()


def test_install_windsurf_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale .windsurfrules at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".windsurfrules"
    target.write_text("stale windsurf rules\n", encoding="utf-8")

    assert _skill_install.run_install(_make_args(client="windsurf", force=True)) == 0
    assert "stale windsurf rules" not in target.read_text(encoding="utf-8")


def test_install_windsurf_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second windsurf install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="windsurf")) == 0
    rc = _skill_install.run_install(_make_args(client="windsurf"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "--force" in captured.err


def test_install_auto_detects_windsurf_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A ``.codeium/`` directory in cwd triggers project-scope Windsurf install on auto-detect."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".codeium").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".windsurfrules").is_file()
    out = capsys.readouterr().out
    assert "Windsurf" in out
    # Sibling clients aren't installed unless their markers also exist.
    assert not (home / ".claude").exists()
    assert not (home / ".cursor").exists()


def test_run_path_with_client_windsurf_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client windsurf`` prints the bundled rules file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="windsurf"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "safelint-rules.md"


def test_cli_routes_skill_install_with_windsurf_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client windsurf --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "windsurf", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "windsurf"
    assert args.project is True


def test_install_copy_excludes_peer_windsurf_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``windsurf/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "windsurf").exists(), "peer windsurf/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# codex client install — primary at .codex/instructions.md, secondary
# section in AGENTS.md when present
# ---------------------------------------------------------------------------


def test_bundled_codex_instructions_exist_in_wheel() -> None:
    """The codex instructions ship under ``skill_files/codex/instructions.md``."""
    path = _skill_install.bundled_skill_path() / "codex" / "instructions.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_codex_copy_user_scope_no_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client codex`` installs the primary instructions; without AGENTS.md the secondary is a no-op."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="codex"))
    assert rc == 0
    assert (home / ".codex" / "instructions.md").is_file()
    # No AGENTS.md — secondary did not fire.
    assert not (home / "AGENTS.md").exists()
    out = capsys.readouterr().out
    assert "codex instructions" in out
    assert "user scope" in out


def test_install_codex_writes_section_when_agents_md_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """When AGENTS.md already exists, codex install also writes a delimited section into it.

    User content in the file is preserved — only bytes between the
    safelint markers change.
    """
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    user_content = "# Project AGENTS\n\nMy own instructions for other agents.\n"
    (cwd / "AGENTS.md").write_text(user_content, encoding="utf-8")

    rc = _skill_install.run_install(_make_args(client="codex", project=True))
    assert rc == 0
    primary = cwd / ".codex" / "instructions.md"
    assert primary.is_file()

    agents_text = (cwd / "AGENTS.md").read_text(encoding="utf-8")
    # User content preserved.
    assert "My own instructions for other agents." in agents_text
    # Section markers present.
    assert "<!-- safelint:begin -->" in agents_text
    assert "<!-- safelint:end -->" in agents_text
    # Section body matches bundled (whitespace-stripped equality).
    bundled = (_skill_install.bundled_skill_path() / "codex" / "instructions.md").read_text(encoding="utf-8")
    body = _skill_install._extract_section_body(agents_text, ("<!-- safelint:begin -->", "<!-- safelint:end -->"))
    assert body is not None
    assert body.strip() == bundled.strip()

    out = capsys.readouterr().out
    assert "also wrote section into" in out
    assert "AGENTS.md" in out


def test_install_codex_does_not_create_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """codex must NOT auto-create AGENTS.md — secondary only fires when the file exists."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="codex", project=True))
    assert rc == 0
    assert not (cwd / "AGENTS.md").exists(), "codex must not auto-create AGENTS.md"


def test_install_codex_replaces_stale_section_in_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Re-installing codex with --force refreshes a stale safelint section in AGENTS.md."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    agents_path = cwd / "AGENTS.md"
    stale = "# AGENTS\n\n<!-- safelint:begin -->\nOLD STALE SAFELINT INSTRUCTIONS\n<!-- safelint:end -->\n\nOther agent notes follow.\n"
    agents_path.write_text(stale, encoding="utf-8")

    assert _skill_install.run_install(_make_args(client="codex", project=True, force=True)) == 0
    agents_text = agents_path.read_text(encoding="utf-8")
    assert "OLD STALE SAFELINT INSTRUCTIONS" not in agents_text
    assert "# AGENTS" in agents_text  # user header preserved
    assert "Other agent notes follow." in agents_text


def test_install_codex_status_reports_secondary_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_install_status`` returns DIFFERS when the AGENTS.md section drifts even though the primary is FRESH."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "AGENTS.md").write_text("# AGENTS\n\nuser content\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="codex", project=True)) == 0
    # Tamper with the AGENTS.md section.
    agents_path = cwd / "AGENTS.md"
    agents_path.write_text(
        agents_path.read_text(encoding="utf-8").replace("# safelint", "# tampered safelint"),
        encoding="utf-8",
    )
    status = _skill_install._install_status(_skill_install._CODEX_SPEC, project=True)
    assert status == _skill_install.INSTALL_STATUS_DIFFERS


def test_remove_codex_strips_section_preserves_other_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``skill remove --client codex`` deletes the primary AND strips the AGENTS.md section, preserving user content."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    user_content = "# AGENTS\n\nMy own notes for other agents.\n"
    (cwd / "AGENTS.md").write_text(user_content, encoding="utf-8")

    assert _skill_install.run_install(_make_args(client="codex", project=True)) == 0
    primary = cwd / ".codex" / "instructions.md"
    agents_path = cwd / "AGENTS.md"
    assert primary.is_file()
    assert "<!-- safelint:begin -->" in agents_path.read_text(encoding="utf-8")

    rc = _skill_install.run_remove(_make_remove_args(client="codex", project=True))
    assert rc == 0
    assert not primary.exists(), "primary instructions should be removed"
    # AGENTS.md still exists; user content preserved; section stripped.
    assert agents_path.is_file()
    agents_text = agents_path.read_text(encoding="utf-8")
    assert "<!-- safelint:begin -->" not in agents_text
    assert "<!-- safelint:end -->" not in agents_text
    assert "My own notes for other agents." in agents_text


def test_remove_codex_deletes_agents_md_when_only_safelint_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When AGENTS.md contains *only* the safelint section, remove deletes the file rather than leaving it empty."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Create a minimal AGENTS.md so the secondary install fires.
    (cwd / "AGENTS.md").write_text("", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="codex", project=True)) == 0
    agents_path = cwd / "AGENTS.md"
    assert agents_path.is_file()

    rc = _skill_install.run_remove(_make_remove_args(client="codex", project=True))
    assert rc == 0
    # File removed because nothing user-authored remained.
    assert not agents_path.exists()


def test_install_auto_detects_codex_via_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An existing AGENTS.md in cwd triggers project-scope codex install on auto-detect."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "AGENTS.md").write_text("user agent notes\n", encoding="utf-8")
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".codex" / "instructions.md").is_file()
    out = capsys.readouterr().out
    assert "codex" in out


def test_run_path_with_client_codex_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client codex`` prints the bundled instructions file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="codex"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "instructions.md"


def test_cli_routes_skill_install_with_codex_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client codex --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "codex", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "codex"
    assert args.project is True


def test_install_copy_excludes_peer_codex_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``codex/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "codex").exists(), "peer codex/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# Continue.dev client install
# ---------------------------------------------------------------------------


def test_bundled_continue_rule_exists_in_wheel() -> None:
    """The Continue.dev rule ships under ``skill_files/continue/safelint.md``."""
    path = _skill_install.bundled_skill_path() / "continue" / "safelint.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_continue_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client continue`` copies the bundled rule to ~/.continue/rules/safelint.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="continue"))
    assert rc == 0
    target = home / ".continue" / "rules" / "safelint.md"
    assert target.is_file()
    assert not target.is_symlink()
    out = capsys.readouterr().out
    assert "Continue.dev rule" in out
    assert "user scope" in out


def test_install_continue_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client continue --project`` lands at <cwd>/.continue/rules/safelint.md."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="continue", project=True))
    assert rc == 0
    assert (cwd / ".continue" / "rules" / "safelint.md").is_file()
    assert not (home / ".continue").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_continue_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client continue --symlink`` creates a file symlink to the bundled rule."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="continue", symlink=True))
    assert rc == 0
    target = home / ".continue" / "rules" / "safelint.md"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "continue" / "safelint.md"
    assert target.resolve() == bundled.resolve()


def test_install_continue_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale Continue.dev rule at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".continue" / "rules" / "safelint.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale rule\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="continue", force=True)) == 0
    assert "stale rule" not in target.read_text(encoding="utf-8")


def test_install_continue_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second continue install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="continue")) == 0
    rc = _skill_install.run_install(_make_args(client="continue"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err


def test_install_auto_detects_continue_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A ``.continue/`` directory in cwd triggers project-scope Continue.dev install on auto-detect."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".continue").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".continue" / "rules" / "safelint.md").is_file()
    out = capsys.readouterr().out
    assert "Continue.dev" in out


def test_run_path_with_client_continue_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client continue`` prints the bundled rule file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="continue"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "safelint.md"


def test_cli_routes_skill_install_with_continue_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client continue --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "continue", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "continue"
    assert args.project is True


def test_install_copy_excludes_peer_continue_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``continue/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "continue").exists(), "peer continue/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# Cline client install
# ---------------------------------------------------------------------------


def test_bundled_cline_rule_exists_in_wheel() -> None:
    """The Cline rule ships under ``skill_files/cline/safelint.md``."""
    path = _skill_install.bundled_skill_path() / "cline" / "safelint.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_cline_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client cline`` copies the bundled rule to ~/.clinerules/safelint.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="cline"))
    assert rc == 0
    target = home / ".clinerules" / "safelint.md"
    assert target.is_file()
    assert not target.is_symlink()
    out = capsys.readouterr().out
    assert "Cline rule" in out
    assert "user scope" in out


def test_install_cline_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client cline --project`` lands at <cwd>/.clinerules/safelint.md."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="cline", project=True))
    assert rc == 0
    assert (cwd / ".clinerules" / "safelint.md").is_file()
    assert not (home / ".clinerules").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_cline_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client cline --symlink`` creates a file symlink to the bundled rule."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="cline", symlink=True))
    assert rc == 0
    target = home / ".clinerules" / "safelint.md"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "cline" / "safelint.md"
    assert target.resolve() == bundled.resolve()


def test_install_cline_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale Cline rule at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".clinerules" / "safelint.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale rule\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="cline", force=True)) == 0
    assert "stale rule" not in target.read_text(encoding="utf-8")


def test_install_cline_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second cline install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cline")) == 0
    rc = _skill_install.run_install(_make_args(client="cline"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err


def test_install_auto_detects_cline_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A ``.clinerules/`` directory in cwd triggers project-scope Cline install on auto-detect."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".clinerules").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".clinerules" / "safelint.md").is_file()
    out = capsys.readouterr().out
    assert "Cline" in out


def test_run_path_with_client_cline_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client cline`` prints the bundled rule file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="cline"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "safelint.md"


def test_cli_routes_skill_install_with_cline_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client cline --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "cline", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "cline"
    assert args.project is True


def test_install_copy_excludes_peer_cline_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``cline/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "cline").exists(), "peer cline/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# aider client install
# ---------------------------------------------------------------------------


def test_bundled_aider_conventions_exist_in_wheel() -> None:
    """The aider conventions ship under ``skill_files/aider/CONVENTIONS.md``."""
    path = _skill_install.bundled_skill_path() / "aider" / "CONVENTIONS.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_aider_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client aider`` copies the bundled conventions to ~/CONVENTIONS.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="aider"))
    assert rc == 0
    target = home / "CONVENTIONS.md"
    assert target.is_file()
    out = capsys.readouterr().out
    assert "aider conventions" in out
    assert "user scope" in out
    # Restart hint reminds user to wire it into aider.conf.yml.
    assert "read:" in out or "aider.conf" in out


def test_install_aider_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client aider --project`` lands at <cwd>/CONVENTIONS.md."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="aider", project=True))
    assert rc == 0
    assert (cwd / "CONVENTIONS.md").is_file()
    assert not (home / "CONVENTIONS.md").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_aider_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client aider --symlink`` creates a file symlink to the bundled conventions."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="aider", symlink=True))
    assert rc == 0
    target = home / "CONVENTIONS.md"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "aider" / "CONVENTIONS.md"
    assert target.resolve() == bundled.resolve()


def test_install_aider_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale CONVENTIONS.md at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / "CONVENTIONS.md"
    target.write_text("stale conventions\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="aider", force=True)) == 0
    assert "stale conventions" not in target.read_text(encoding="utf-8")


def test_install_aider_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second aider install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="aider")) == 0
    rc = _skill_install.run_install(_make_args(client="aider"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err


def test_install_auto_detects_aider_via_conf_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An existing ``.aider.conf.yml`` in cwd triggers project-scope aider install on auto-detect."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".aider.conf.yml").write_text("# aider config\n", encoding="utf-8")
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / "CONVENTIONS.md").is_file()
    out = capsys.readouterr().out
    assert "aider" in out


def test_run_path_with_client_aider_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client aider`` prints the bundled conventions file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="aider"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "CONVENTIONS.md"


def test_cli_routes_skill_install_with_aider_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client aider --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "aider", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "aider"
    assert args.project is True


def test_install_copy_excludes_peer_aider_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``aider/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "aider").exists(), "peer aider/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# Trae client install
# ---------------------------------------------------------------------------


def test_bundled_trae_rule_exists_in_wheel() -> None:
    """The Trae rule ships under ``skill_files/trae/safelint.md``."""
    path = _skill_install.bundled_skill_path() / "trae" / "safelint.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_trae_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client trae`` copies the bundled rule to ~/.trae/rules/safelint.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="trae"))
    assert rc == 0
    target = home / ".trae" / "rules" / "safelint.md"
    assert target.is_file()
    out = capsys.readouterr().out
    assert "Trae rule" in out
    assert "user scope" in out


def test_install_trae_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client trae --project`` lands at <cwd>/.trae/rules/safelint.md."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="trae", project=True))
    assert rc == 0
    assert (cwd / ".trae" / "rules" / "safelint.md").is_file()
    assert not (home / ".trae").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_trae_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client trae --symlink`` creates a file symlink to the bundled rule."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="trae", symlink=True))
    assert rc == 0
    target = home / ".trae" / "rules" / "safelint.md"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "trae" / "safelint.md"
    assert target.resolve() == bundled.resolve()


def test_install_trae_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale Trae rule at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".trae" / "rules" / "safelint.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale rule\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="trae", force=True)) == 0
    assert "stale rule" not in target.read_text(encoding="utf-8")


def test_install_trae_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second trae install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="trae")) == 0
    rc = _skill_install.run_install(_make_args(client="trae"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err


def test_install_auto_detects_trae_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A ``.trae/`` directory in cwd triggers project-scope Trae install on auto-detect."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".trae").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".trae" / "rules" / "safelint.md").is_file()
    out = capsys.readouterr().out
    assert "Trae" in out


def test_run_path_with_client_trae_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client trae`` prints the bundled rule file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="trae"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "safelint.md"


def test_cli_routes_skill_install_with_trae_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client trae --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "trae", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "trae"
    assert args.project is True


def test_install_copy_excludes_peer_trae_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``trae/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "trae").exists(), "peer trae/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# Antigravity client install
# ---------------------------------------------------------------------------


def test_bundled_antigravity_rule_exists_in_wheel() -> None:
    """The Antigravity rule ships under ``skill_files/antigravity/safelint.md``."""
    path = _skill_install.bundled_skill_path() / "antigravity" / "safelint.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_antigravity_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client antigravity`` copies the bundled rule to ~/.antigravity/rules/safelint.md."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="antigravity"))
    assert rc == 0
    target = home / ".antigravity" / "rules" / "safelint.md"
    assert target.is_file()
    out = capsys.readouterr().out
    assert "Antigravity rule" in out
    assert "user scope" in out


def test_install_antigravity_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client antigravity --project`` lands at <cwd>/.antigravity/rules/safelint.md."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="antigravity", project=True))
    assert rc == 0
    assert (cwd / ".antigravity" / "rules" / "safelint.md").is_file()
    assert not (home / ".antigravity").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_antigravity_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client antigravity --symlink`` creates a file symlink to the bundled rule."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="antigravity", symlink=True))
    assert rc == 0
    target = home / ".antigravity" / "rules" / "safelint.md"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "antigravity" / "safelint.md"
    assert target.resolve() == bundled.resolve()


def test_install_antigravity_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale Antigravity rule at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".antigravity" / "rules" / "safelint.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale rule\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="antigravity", force=True)) == 0
    assert "stale rule" not in target.read_text(encoding="utf-8")


def test_install_antigravity_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second antigravity install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="antigravity")) == 0
    rc = _skill_install.run_install(_make_args(client="antigravity"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err


def test_install_auto_detects_antigravity_in_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A ``.antigravity/`` directory in cwd triggers project-scope Antigravity install on auto-detect."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".antigravity").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".antigravity" / "rules" / "safelint.md").is_file()
    out = capsys.readouterr().out
    assert "Antigravity" in out


def test_run_path_with_client_antigravity_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client antigravity`` prints the bundled rule file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="antigravity"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "safelint.md"


def test_cli_routes_skill_install_with_antigravity_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client antigravity --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "antigravity", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "antigravity"
    assert args.project is True


def test_install_copy_excludes_peer_antigravity_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``antigravity/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "antigravity").exists(), "peer antigravity/ leaked into Claude skill"


# ---------------------------------------------------------------------------
# Zed editor client install
# ---------------------------------------------------------------------------


def test_bundled_zed_rules_exist_in_wheel() -> None:
    """The Zed rules ship under ``skill_files/zed/safelint.md``."""
    path = _skill_install.bundled_skill_path() / "zed" / "safelint.md"
    assert path.is_file()
    head = path.read_text(encoding="utf-8")[:200]
    assert head.startswith("# safelint")


def test_install_zed_copy_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client zed`` copies the bundled rules to ~/.rules."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="zed"))
    assert rc == 0
    target = home / ".rules"
    assert target.is_file()
    out = capsys.readouterr().out
    assert "Zed rules" in out
    assert "user scope" in out


def test_install_zed_copy_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client zed --project`` lands at <cwd>/.rules."""
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="zed", project=True))
    assert rc == 0
    assert (cwd / ".rules").is_file()
    assert not (home / ".rules").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_zed_symlink_user_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client zed --symlink`` creates a file symlink to the bundled rules."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_install(_make_args(client="zed", symlink=True))
    assert rc == 0
    target = home / ".rules"
    assert target.is_symlink()
    bundled = _skill_install.bundled_skill_path() / "zed" / "safelint.md"
    assert target.resolve() == bundled.resolve()


def test_install_zed_with_force_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--force`` replaces a stale .rules file at the target."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".rules"
    target.write_text("stale rules\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="zed", force=True)) == 0
    assert "stale rules" not in target.read_text(encoding="utf-8")


def test_install_zed_refuses_overwrite_without_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second zed install without ``--force`` exits 1 with the error on stderr."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="zed")) == 0
    rc = _skill_install.run_install(_make_args(client="zed"))
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err


def test_install_auto_detects_zed_via_zed_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A ``.zed/`` directory in cwd triggers project-scope Zed install on auto-detect."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / ".zed").mkdir()
    rc = _skill_install.run_install(_make_args(client="auto"))
    assert rc == 0
    assert (cwd / ".rules").is_file()
    out = capsys.readouterr().out
    assert "Zed" in out


def test_run_path_with_client_zed_prints_md_file(capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill path --client zed`` prints the bundled rules file path."""
    rc = _skill_install.run_path(argparse.Namespace(client="zed"))
    assert rc == 0
    out = capsys.readouterr().out.strip()
    p = Path(out)
    assert p.is_file()
    assert p.name == "safelint.md"


def test_cli_routes_skill_install_with_zed_client(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill install --client zed --project`` forwards both flags to run_install."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "zed", "--project"])
    spy = mocker.patch.object(_skill_install, "run_install", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    args = spy.call_args.args[0]
    assert args.client == "zed"
    assert args.project is True


def test_install_copy_excludes_peer_zed_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The materialised Claude skill folder must NOT contain the peer ``zed/`` subdirectory."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    target = home / ".claude" / "skills" / "safelint"
    assert target.is_dir()
    assert not (target / "zed").exists(), "peer zed/ leaked into Claude skill"


def test_section_body_extraction_round_trips() -> None:
    """``_render_section_body`` and ``_extract_section_body`` round-trip identically (no content mutation)."""
    spec = _skill_install._CODEX_SPEC
    bundled = "line one\nline two with `code`\n"
    rendered = _skill_install._render_section_body(spec, bundled)
    body = _skill_install._extract_section_body(rendered, spec.secondary_install_section_markers)
    assert body is not None
    assert body.strip() == bundled.strip()


def test_append_section_handles_empty_file() -> None:
    """Appending into an empty file produces just the section (no leading separator)."""
    out = _skill_install._append_section("", "<!-- s:b -->\nbody\n<!-- s:e -->\n")
    assert out == "<!-- s:b -->\nbody\n<!-- s:e -->\n"


def test_append_section_handles_file_without_trailing_newline() -> None:
    """Appending after a non-newline-terminated file inserts a blank-line gap."""
    out = _skill_install._append_section("body without newline", "[SECTION]")
    assert out == "body without newline\n\n[SECTION]"


def test_append_section_handles_file_with_double_trailing_newline() -> None:
    """Appending after a file that already ends with a blank line uses no extra separator."""
    out = _skill_install._append_section("body\n\n", "[SECTION]")
    assert out == "body\n\n[SECTION]"


def test_replace_or_append_handles_malformed_section_with_only_begin_marker() -> None:
    """A file with only the begin marker (no end) is treated as malformed — section appended instead of repaired."""
    spec = _skill_install._CODEX_SPEC
    existing = "user content\n<!-- safelint:begin -->\noops, no end marker\n"
    out = _skill_install._replace_or_append_section(existing, spec, "fresh body")
    # Original (malformed) text preserved verbatim, with a well-formed
    # fresh section appended after.
    assert out.startswith(existing)
    assert "<!-- safelint:end -->" in out


def test_strip_section_no_op_when_section_absent() -> None:
    """``_strip_section`` returns input unchanged when no safelint markers are present."""
    spec = _skill_install._CODEX_SPEC
    text = "# AGENTS\n\nuser content only\n"
    assert _skill_install._strip_section(text, spec) == text


def test_strip_section_no_op_on_malformed_only_begin_marker() -> None:
    """A malformed file (begin without end) is left alone — never damaged."""
    spec = _skill_install._CODEX_SPEC
    text = "<!-- safelint:begin -->\nbody but no end\n"
    assert _skill_install._strip_section(text, spec) == text


def test_install_secondary_no_op_when_target_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_install_secondary`` returns False when AGENTS.md doesn't exist (it doesn't auto-create)."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install._install_secondary(_skill_install._CODEX_SPEC, project=True) is False


def test_install_secondary_no_op_when_section_already_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_install_secondary`` returns False on the second call — section already matches bundle."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "AGENTS.md").write_text("user content\n", encoding="utf-8")
    # First install writes the section.
    assert _skill_install._install_secondary(_skill_install._CODEX_SPEC, project=True) is True
    # Second call is a no-op.
    assert _skill_install._install_secondary(_skill_install._CODEX_SPEC, project=True) is False


def test_remove_secondary_no_op_when_target_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_remove_secondary`` returns False when AGENTS.md doesn't exist."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install._remove_secondary(_skill_install._CODEX_SPEC, project=True) is False


def test_remove_secondary_no_op_when_no_section_to_strip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_remove_secondary`` returns False when AGENTS.md exists but has no safelint section."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "AGENTS.md").write_text("just user content\n", encoding="utf-8")
    assert _skill_install._remove_secondary(_skill_install._CODEX_SPEC, project=True) is False


def test_secondary_status_missing_when_agents_md_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_secondary_status`` reports MISSING when AGENTS.md doesn't exist."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    status = _skill_install._secondary_status(_skill_install._CODEX_SPEC, project=True)
    assert status == _skill_install.INSTALL_STATUS_MISSING


def test_secondary_status_missing_when_no_section_in_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_secondary_status`` reports MISSING when AGENTS.md has no safelint section."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "AGENTS.md").write_text("just user content\n", encoding="utf-8")
    status = _skill_install._secondary_status(_skill_install._CODEX_SPEC, project=True)
    assert status == _skill_install.INSTALL_STATUS_MISSING


def test_install_codex_refuses_directory_at_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``_install_secondary`` MUST NOT crash when ``AGENTS.md`` exists as a directory.

    Without the guard, ``read_text``/``write_text`` would raise
    ``IsADirectoryError`` and abort the whole ``skill install`` flow.
    With the guard, the install completes the primary copy, prints a
    stderr warning about the directory, and leaves the directory
    untouched.
    """
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Create AGENTS.md as a directory containing a file the install
    # must NOT touch.
    agents_dir = cwd / "AGENTS.md"
    agents_dir.mkdir()
    (agents_dir / "untouched.txt").write_text("DO NOT MODIFY\n", encoding="utf-8")

    rc = _skill_install.run_install(_make_args(client="codex", project=True))
    # Primary install still succeeds.
    assert rc == 0
    assert (cwd / ".codex" / "instructions.md").is_file()
    # Directory and its contents UNCHANGED — refused.
    assert agents_dir.is_dir()
    assert (agents_dir / "untouched.txt").read_text(encoding="utf-8") == "DO NOT MODIFY\n"
    err = capsys.readouterr().err
    assert "refusing" in err.lower()
    assert "not a regular file" in err.lower()


def test_remove_codex_refuses_directory_at_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``_remove_secondary`` MUST NOT crash when ``AGENTS.md`` exists as a directory."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a real AGENTS.md, install codex normally so primary exists.
    (cwd / "AGENTS.md").write_text("user content\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="codex", project=True)) == 0
    capsys.readouterr()
    # Now replace AGENTS.md with a directory.
    (cwd / "AGENTS.md").unlink()
    agents_dir = cwd / "AGENTS.md"
    agents_dir.mkdir()
    (agents_dir / "untouched.txt").write_text("DO NOT MODIFY\n", encoding="utf-8")

    rc = _skill_install.run_remove(_make_remove_args(client="codex", project=True))
    assert rc == 0
    # Primary removed; directory and its contents untouched; warning surfaced.
    assert not (cwd / ".codex" / "instructions.md").exists()
    assert agents_dir.is_dir()
    assert (agents_dir / "untouched.txt").read_text(encoding="utf-8") == "DO NOT MODIFY\n"
    err = capsys.readouterr().err
    assert "refusing" in err.lower()
    assert "not a regular file" in err.lower()


def test_secondary_status_treats_directory_as_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_secondary_status`` reports MISSING when ``AGENTS.md`` is a directory (not a regular file)."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "AGENTS.md").mkdir()
    status = _skill_install._secondary_status(_skill_install._CODEX_SPEC, project=True)
    assert status == _skill_install.INSTALL_STATUS_MISSING


def test_remove_codex_dry_run_mentions_secondary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``skill remove --client codex --dry-run`` mentions the AGENTS.md section will also be stripped."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    (cwd / "AGENTS.md").write_text("user notes\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="codex", project=True)) == 0
    capsys.readouterr()  # discard install output

    rc = _skill_install.run_remove(_make_remove_args(client="codex", project=True, dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "would also strip safelint section" in out
    # Files NOT actually changed.
    assert (cwd / ".codex" / "instructions.md").is_file()
    assert "<!-- safelint:begin -->" in (cwd / "AGENTS.md").read_text(encoding="utf-8")


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
    """``--client <unknown>`` fails loudly via argparse choice validation."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "definitely-not-a-real-client"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "client" in err
    assert "definitely-not-a-real-client" in err


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
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "install", "--client", "totally-not-a-client"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    # argparse rejects on choices=.
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "totally-not-a-client" in err


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


def _appears_as_token(text: str, token: str) -> bool:
    """Return True if *token* appears in *text* as a standalone token.

    Plain ``token in text`` would falsely match ``side_effects`` inside
    ``side_effects_hidden`` and ``.py`` inside ``.pyw`` — so a doc with
    only the longer name / extension would silently pass the drift test
    that's meant to catch the missing shorter one. The boundary check
    rejects matches whose neighbours are identifier characters
    (alphanumeric or underscore).
    """
    import re  # noqa: PLC0415 — keep the import local to the helper

    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text) is not None


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
    missing_codes = [cls.code for cls in ALL_RULES if not _appears_as_token(text, cls.code)]
    missing_names = [cls.name for cls in ALL_RULES if not _appears_as_token(text, cls.name)]
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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_status_claude_symlink_directory_is_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A Claude ``--symlink`` install is reported FRESH despite being a real directory.

    Claude symlink installs aren't symlinks at the target path — they're
    real directories whose top-level entries are symlinks back to
    bundled. ``target.is_symlink()`` returns False. Without explicit
    handling, the code falls through to tree-hashing and reports DIFFERS
    if the bundle adds a new top-level file (the install dir doesn't
    yet have a symlink for it). That's both noisy in the common case
    and contradicts the documented "symlink installs are live"
    contract. ``_is_symlink_managed_directory`` catches this shape.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude", symlink=True)) == 0
    target = home / ".claude" / "skills" / "safelint"
    # Sanity: target itself is a directory, but its entries are symlinks.
    assert target.is_dir()
    assert not target.is_symlink()
    assert (target / "SKILL.md").is_symlink()
    # The drift check must still report fresh.
    status = _skill_install._install_status(_skill_install._CLAUDE_SPEC, project=False)
    assert status == _skill_install.INSTALL_STATUS_FRESH


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_status_broken_symlink_is_not_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A broken symlink (target removed) must NOT be reported FRESH.

    ``Path.is_symlink()`` returns True even for dangling symlinks.
    Without an additional ``exists()`` check, ``safelint skill status``
    would incorrectly say the install is current even though following
    the link fails. Test plants a Cursor symlink install, removes the
    bundled target out from under it, and asserts the status check
    catches the broken-link condition instead of returning FRESH.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".cursor" / "rules" / "safelint.mdc"
    target.parent.mkdir(parents=True)
    # Plant a symlink whose target doesn't exist (broken from creation).
    target.symlink_to(tmp_path / "nonexistent.mdc")
    assert target.is_symlink()
    assert not target.exists()  # broken symlink

    status = _skill_install._install_status(_skill_install._CURSOR_SPEC, project=False)
    # A dangling install is neither installed nor current — it must be
    # surfaced as DIFFERS, not silently classified as MISSING (which
    # ``run_status`` and ``stale_install_warnings`` would skip).
    assert status == _skill_install.INSTALL_STATUS_DIFFERS


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_status_claude_symlink_with_broken_inner_link_is_not_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A Claude symlink install with one broken inner symlink must NOT be reported FRESH.

    Same fail-fast posture as the outer broken-symlink check: a
    dangling install is not "current". Builds a Claude symlink install,
    breaks one of the per-entry links by re-pointing it at a removed
    path, and asserts the status check rejects the install.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude", symlink=True)) == 0
    target_dir = home / ".claude" / "skills" / "safelint"
    skill_md_link = target_dir / "SKILL.md"
    # Repoint the SKILL.md symlink at a removed path → broken link.
    skill_md_link.unlink()
    skill_md_link.symlink_to(tmp_path / "vanished.md")
    assert skill_md_link.is_symlink()
    assert not skill_md_link.exists()  # broken

    status = _skill_install._install_status(_skill_install._CLAUDE_SPEC, project=False)
    # ``_is_symlink_managed_directory`` rejects the install (broken
    # inner symlink fails the working-symlink check), so we fall
    # through to tree-hash. The broken symlink doesn't contribute to
    # the install hash, so it diverges from the bundle → DIFFERS.
    assert status == _skill_install.INSTALL_STATUS_DIFFERS


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_run_status_surfaces_broken_symlink_install_with_exit_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill status`` must surface (not silently skip) a broken symlink install.

    A dangling symlink would previously classify as MISSING — and
    ``run_status`` skips MISSING locations — leaving a broken install
    unreported and exit 0. Locks the contract that broken symlinks
    propagate as DIFFERS through to the user-facing exit code and
    output.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    target = home / ".cursor" / "rules" / "safelint.mdc"
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "vanished.mdc")
    assert target.is_symlink()
    assert not target.exists()

    rc = _skill_install.run_status(argparse.Namespace())
    assert rc == 1
    out = capsys.readouterr().out
    assert "differs from bundled" in out
    # Path appears in the output so the user can fix it.
    assert str(target) in out


def test_run_status_emits_scope_aware_refresh_hint_per_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Per-install lines carry the precise ``--client X --force [--project]`` command for that scope.

    The previous blanket ``Run safelint skill install --force`` hint
    was wrong for multi-scope drift: bare ``--force`` only refreshes
    the auto-detected scope, so a stale user-scope install would keep
    failing after the user runs the suggested command on the
    project-scope install. Each detected drift now gets its own
    explicit ``skill update`` command (the canonical shape-preserving
    refresh path).
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a stale Cursor user-scoped install.
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    (home / ".cursor" / "rules" / "safelint.mdc").write_text("# customised\n", encoding="utf-8")
    capsys.readouterr()

    rc = _skill_install.run_status(argparse.Namespace())
    assert rc == 1
    out = capsys.readouterr().out
    # The exact refresh command — ``skill update``, explicit client,
    # explicit scope (no --project for user).
    assert "Refresh: safelint skill update --client cursor" in out


def test_stale_install_warnings_carry_scope_aware_refresh_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``stale_install_warnings`` returns the per-scope refresh command, not the bare ``--force``.

    Same correctness concern as ``run_status``: the warning text is
    consumed verbatim by ``--check-skill-freshness``; if it suggested
    bare ``--force``, the user would mis-refresh their other scope.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant TWO stale installs, one user-scoped and one project-scoped.
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    assert _skill_install.run_install(_make_args(client="cursor", project=True)) == 0
    (home / ".cursor" / "rules" / "safelint.mdc").write_text("# user customised\n", encoding="utf-8")
    (cwd / ".cursor" / "rules" / "safelint.mdc").write_text("# project customised\n", encoding="utf-8")

    warnings = _skill_install.stale_install_warnings()
    assert len(warnings) == 2
    # Each warning lists its own scope-specific refresh command.
    user_warning = next(w for w in warnings if "user scope" in w)
    project_warning = next(w for w in warnings if "project scope" in w)
    assert "safelint skill update --client cursor`" in user_warning  # no --project
    assert "safelint skill update --client cursor --project`" in project_warning


def test_drift_token_match_rejects_substring_false_positives() -> None:
    """The drift-test helper distinguishes ``side_effects`` from ``side_effects_hidden``.

    Direct ``in`` membership would falsely accept SAFE304's name as
    "documented" merely because SAFE303's longer name appears.
    ``_appears_as_token`` uses identifier-character lookbehind /
    lookahead so the shorter name needs to appear standalone.
    """
    text_with_only_long = "| SAFE303 | side_effects_hidden | … |"
    text_with_short = "| SAFE304 | side_effects | … |"
    text_with_both = "| SAFE303 | side_effects_hidden | … |\n| SAFE304 | side_effects | … |"
    assert not _appears_as_token(text_with_only_long, "side_effects")
    assert _appears_as_token(text_with_short, "side_effects")
    assert _appears_as_token(text_with_both, "side_effects")
    # And the longer name still matches when present.
    assert _appears_as_token(text_with_only_long, "side_effects_hidden")
    assert _appears_as_token(text_with_both, "side_effects_hidden")


def test_drift_token_match_rejects_extension_substring_false_positives() -> None:
    """``.py`` is not falsely matched inside ``.pyw``.

    Same identifier-boundary semantics work for dotted extensions:
    ``.py`` inside ``.pyw`` has a word char (``w``) immediately after,
    so the negative lookahead fails.
    """
    assert not _appears_as_token("supports .pyw extension", ".py")
    assert _appears_as_token("supports .py and .pyw", ".py")
    assert _appears_as_token("supports .pyw extension", ".pyw")


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
    # Scope-aware refresh command — uses ``skill update`` (the canonical
    # shape-preserving refresh) with ``--client cursor`` so the user
    # refreshes the right scope.
    assert "safelint skill update --client cursor" in out


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
    # Scope-aware refresh command — see the dedicated regression
    # ``test_stale_install_warnings_carry_scope_aware_refresh_command``
    # for the user-vs-project differentiation.
    assert "safelint skill update --client cursor" in warnings[0]


def test_stale_install_warnings_empty_when_all_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No installs → empty list (not an error) — matches the ``--check-skill-freshness`` "silent on clean" contract."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.stale_install_warnings() == []


def test_run_status_skips_oserror_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``run_status`` treats an OSError-raising install location as missing rather than crashing.

    Plant a Cursor install, patch ``_install_status`` to raise OSError
    so the status walk would otherwise propagate, and confirm
    ``run_status`` completes (matching the auto-discovery
    OSError-tolerance pattern enforced by ``_detected_installed_clients``).
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    # Should NOT raise — the OSError install is treated as missing.
    rc = _skill_install.run_status(argparse.Namespace())
    captured = capsys.readouterr()
    assert rc == 0
    assert "no AI-client skill installs detected" in captured.out


def test_update_one_skips_oserror_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_update_one`` returns rc=0 silently when ``_install_status`` raises OSError.

    Mirrors the OSError-tolerance pattern in ``run_status`` and
    ``_detected_installed_clients``: an unreadable install location
    (permission denied, transient I/O) is skipped rather than
    crashing the whole update walk.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    rc = _skill_install._update_one(
        _skill_install._CURSOR_SPEC,
        project=False,
        args=argparse.Namespace(force=False, symlink=False),
    )
    assert rc == 0


def test_update_one_uses_precomputed_status_skipping_compute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When *status* is provided, ``_update_one`` does not invoke ``_install_status_or_none``.

    Regression test for the optimisation that lets ``run_update``
    compute status once per target and pass it through, so the hash/walk
    runs at most once per install per run.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    call_count = {"n": 0}

    def _counted(spec: _skill_install.ClientSpec, *, project: bool) -> str | None:
        call_count["n"] += 1
        return _skill_install.INSTALL_STATUS_FRESH

    monkeypatch.setattr(_skill_install, "_install_status_or_none", _counted)
    rc = _skill_install._update_one(
        _skill_install._CURSOR_SPEC,
        project=False,
        args=argparse.Namespace(force=False, symlink=False),
        status=_skill_install.INSTALL_STATUS_FRESH,
    )
    assert rc == 0
    assert call_count["n"] == 0, "precomputed status should bypass internal compute"


def test_run_update_silent_when_all_targets_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``run_update`` does not print the all-fresh summary when every target OSError'd.

    Without the ``any_processed`` gate, a run where every target was
    silently skipped due to permission errors would falsely report
    "all detected installs are already up to date" — masking a real
    I/O failure as a clean run.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    rc = _skill_install.run_update(_make_update_args())
    out = capsys.readouterr().out
    assert rc == 0
    assert "already up to date" not in out, "must not claim freshness when targets were skipped"


def test_resolve_update_targets_skips_oserror_explicit_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit-client update filtering treats OSError installs as MISSING (skipped).

    Without OSError-tolerance, ``safelint skill update --client X``
    would crash if any candidate scope was unreadable.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    targets = _skill_install._resolve_update_targets(argparse.Namespace(client="cursor", project=False))
    assert targets == []


def test_resolve_remove_candidates_skips_oserror_explicit_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_resolve_remove_candidates`` skips OSError installs for explicit-client remove.

    Same OSError-tolerance contract as the update path — a transient
    I/O error in one scope shouldn't crash ``safelint skill remove
    --client X``.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    candidates = _skill_install._resolve_remove_candidates(
        argparse.Namespace(client="cursor", project=False, symlink=False),
    )
    assert candidates == []


def test_stale_install_warnings_skips_oserror_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``stale_install_warnings`` swallows per-install OSErrors instead of aborting the walk.

    The freshness diagnostic feeds ``--check-skill-freshness``; a
    single unreadable install location must not crash an unrelated
    lint run.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    # Should NOT raise — returns an empty list because the OSError
    # install is treated as not-DIFFERS.
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
    missing = sorted(ext for ext in supported_extensions() if not _appears_as_token(text, ext))
    assert not missing, f"{spec.name}: supported extensions missing from skill docs ({spec.documentation_relpaths}): {missing}"


# ---------------------------------------------------------------------------
# safelint skill update — refresh stale installs (no-op when fresh)
# ---------------------------------------------------------------------------


def _make_update_args(*, project: bool = False, symlink: bool = False, force: bool = False, client: str = "auto") -> argparse.Namespace:
    """Namespace shaped like the update argparser produces."""
    return argparse.Namespace(skill_action="update", project=project, symlink=symlink, force=force, client=client)


def test_update_is_noop_when_install_is_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill update`` on a fresh install exits 0 and reports skipped."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    capsys.readouterr()  # drop install output

    rc = _skill_install.run_update(_make_update_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "already fresh, skipped" in out


def test_update_refreshes_drifted_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint skill update`` re-installs when the on-disk content has drifted."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    target.write_text("# customised — diverges from bundled\n", encoding="utf-8")
    capsys.readouterr()

    rc = _skill_install.run_update(_make_update_args())
    assert rc == 0
    # Content was restored from bundled.
    assert "customised" not in target.read_text(encoding="utf-8")
    # Status now fresh.
    assert _skill_install._install_status(_skill_install._CURSOR_SPEC, project=False) == _skill_install.INSTALL_STATUS_FRESH


def test_update_force_refreshes_even_fresh_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--force`` re-installs even when the install is already fresh.

    Useful for reverting a customised install — the customisation
    would normally pass status as drift, but ``--force`` also covers
    the case where the user wants to reset a fresh install (e.g.
    after manually editing then deciding to revert).
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    capsys.readouterr()

    rc = _skill_install.run_update(_make_update_args(force=True))
    assert rc == 0
    out = capsys.readouterr().out
    # Force path goes through install_one's success print.
    assert "copied" in out
    # And NOT the skipped notice.
    assert "already fresh, skipped" not in out


def test_update_returns_zero_when_no_installs_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``update`` with no detected installs is informational, not an error."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_update(_make_update_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "no AI-client skill installs detected" in out


def test_update_auto_uses_install_paths_not_marker_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client auto`` for update scans installed paths, NOT marker files.

    A user can have ``.cursor/`` markers in cwd without a Cursor
    install (just installed Cursor today, hasn't run safelint skill
    install yet) — update auto must report nothing to do, not silently
    re-trigger an install.
    """
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant cwd Cursor markers but no actual install.
    (cwd / ".cursor").mkdir()
    capsys.readouterr()

    rc = _skill_install.run_update(_make_update_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "no AI-client skill installs detected" in out


def test_update_explicit_client_without_project_targets_both_scopes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``update --client cursor`` (no ``--project``) refreshes BOTH user and project installs.

    Symmetric with ``--client auto``: the ``--project`` flag is the
    orthogonal scope-restriction filter. Without this, the explicit-
    client path silently skipped project-scope installs, contradicting
    the auto-detect path's behaviour.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    assert _skill_install.run_install(_make_args(client="cursor", project=True)) == 0
    user_target = home / ".cursor" / "rules" / "safelint.mdc"
    project_target = cwd / ".cursor" / "rules" / "safelint.mdc"
    user_target.write_text("# user customised\n", encoding="utf-8")
    project_target.write_text("# project customised\n", encoding="utf-8")
    capsys.readouterr()

    rc = _skill_install.run_update(_make_update_args(client="cursor"))
    assert rc == 0
    # BOTH installs were refreshed, not just user.
    assert "user customised" not in user_target.read_text(encoding="utf-8")
    assert "project customised" not in project_target.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_update_force_preserves_symlink_install_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``update --force`` on a symlink install keeps it as a symlink (doesn't convert to copy).

    Without explicit ``--symlink``, the user hasn't asked to change
    the install mode — only to refresh content. Silently flipping a
    symlink install to copy on every force-refresh would strip the
    user's deliberate live-link guarantee. The fix derives the mode
    from the existing install's shape when ``--symlink`` isn't
    explicit. Passing ``--symlink`` still wins, so users can switch
    a copy install to symlink mode mid-flight.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a Cursor symlink install.
    assert _skill_install.run_install(_make_args(client="cursor", symlink=True)) == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    assert target.is_symlink()  # baseline

    # Force-refresh without --symlink. Old behaviour: would replace with
    # a copy. Fixed behaviour: preserves the symlink shape.
    rc = _skill_install.run_update(_make_update_args(force=True))
    assert rc == 0
    assert target.is_symlink(), "force-refresh must preserve symlink shape"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_update_force_with_explicit_symlink_switches_copy_to_symlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``update --force --symlink`` on a copy install converts it to symlink.

    Explicit ``--symlink`` is the user's opt-in to switch modes —
    must override the shape-preservation default. Symmetric to
    ``install --symlink --force``.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    assert target.is_file()
    assert not target.is_symlink()  # copy-mode baseline

    rc = _skill_install.run_update(_make_update_args(force=True, symlink=True))
    assert rc == 0
    assert target.is_symlink(), "explicit --symlink must convert copy → symlink"


def test_install_status_or_none_returns_none_on_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_install_status_or_none`` returns None instead of crashing on transient I/O errors.

    Used by ``_detected_installed_clients`` so auto-discovery doesn't
    abort the whole walk if one install location is unreadable.
    Callers treat None the same as MISSING (skip). The user can still
    target the install via ``--client X`` + ``--project`` or
    ``--path PATH`` if they need to act on it.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a Cursor install so the location exists.
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    # Patch _install_status to raise OSError as if the FS reported a
    # permission denied / transient IO error during status detection.
    real_install_status = _skill_install._install_status

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    result = _skill_install._install_status_or_none(_skill_install._CURSOR_SPEC, project=False)
    assert result is None

    # Restore so other tests aren't affected (monkeypatch handles
    # this on teardown but the assertion below sanity-checks it).
    monkeypatch.setattr(_skill_install, "_install_status", real_install_status)


def test_detected_installed_clients_skips_oserror_locations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Auto-discovery skips installs whose ``_install_status`` raises, doesn't propagate.

    End-to-end test for the OSError-skip path: plant a Cursor install,
    patch ``_install_status`` to raise OSError, run
    ``_detected_installed_clients`` and confirm the iteration
    completes (returns an empty list rather than raising).
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    def _raise_oserror(spec: _skill_install.ClientSpec, *, project: bool) -> str:
        msg = "permission denied (simulated)"
        raise OSError(msg)

    monkeypatch.setattr(_skill_install, "_install_status", _raise_oserror)
    # Should NOT raise.
    detected = _skill_install._detected_installed_clients()
    assert detected == []


def test_is_symlink_directory_shape_returns_false_on_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_is_symlink_directory_shape`` fails closed when iterdir raises OSError.

    An unreadable install directory (permission denied, transient
    I/O) shouldn't crash ``update`` / ``remove --symlink``. Without
    the OSError catch, the cleanup paths would propagate the
    exception up to the user. Patches ``iterdir`` on a real
    directory to raise OSError and asserts the predicate returns
    False (treating "can't tell" as "not symlink-shape").
    """
    real_dir = tmp_path / "claude_install"
    real_dir.mkdir()
    # Use monkeypatch on the Path class so the iterdir call inside
    # the helper hits our patched method.
    original_iterdir = Path.iterdir

    def _raise_oserror(self: Path) -> object:
        if self == real_dir:
            msg = "permission denied (simulated)"
            raise OSError(msg)
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _raise_oserror)
    assert _skill_install._is_symlink_directory_shape(real_dir) is False


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_is_symlink_directory_shape_true_for_mixed_install(tmp_path: Path) -> None:
    """An install with at least one symlink entry counts as symlink-shape.

    Originally implemented with ``all(...)``, which meant a single
    user-added real file (e.g. a notes file dropped alongside the
    bundled symlinks) silently demoted the install to "not symlink"
    and made ``remove --symlink`` skip it. The intent is shape-only:
    *any* symlink at the top level qualifies, so cleanup can still
    reach a customised install.
    """
    install_dir = tmp_path / "claude_skills_safelint"
    install_dir.mkdir()
    bundled = _skill_install.bundled_skill_path()
    (install_dir / "languages").symlink_to(bundled / "languages", target_is_directory=True)
    # User-added real file alongside the bundled symlink.
    (install_dir / "NOTES.md").write_text("personal customisation\n", encoding="utf-8")

    assert _skill_install._is_symlink_directory_shape(install_dir) is True


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_remove_path_dry_run_labels_broken_symlink_directory_as_symlink(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``remove --path`` shape label uses shape-only predicate, not freshness.

    A Claude-style symlink directory with a broken inner symlink is
    still symlink-shape; its ``--dry-run`` output should say
    "symlink", not "copy". The previous implementation used
    ``_is_symlink_managed_directory`` (working-symlinks-required)
    for the shape label, mislabelling broken installs as copy.

    Path is built under a Claude-shaped tail
    (``.claude/skills/safelint``) so the security guard introduced in
    the v1.11.0 hardening accepts it.
    """
    odd_dir = tmp_path / ".claude" / "skills" / "safelint"
    odd_dir.mkdir(parents=True)
    # Build a Claude-style symlink directory with a broken inner symlink.
    bundled = _skill_install.bundled_skill_path()
    (odd_dir / "languages").symlink_to(bundled / "languages", target_is_directory=True)
    # Plus a broken inner symlink to trigger the freshness predicate's
    # working-symlink rejection.
    (odd_dir / "SKILL.md").symlink_to(tmp_path / "vanished.md")

    rc = _skill_install.run_remove(_make_remove_args(path=odd_dir, dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "(symlink)" in out, "broken Claude-style directory should label as symlink"


# ---------------------------------------------------------------------------
# Security hardening (v1.11.0): symlink refusal at the secondary install
# destination, and install-shape validation on `skill remove --path PATH`.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_codex_refuses_symlinked_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``_install_secondary`` MUST NOT follow a symlink at AGENTS.md (would clobber the target file).

    Threat model: an attacker with cwd write access (e.g. shared CI
    workspace) plants ``AGENTS.md`` as a symlink to a sensitive file
    (``/etc/passwd``, ``~/.ssh/authorized_keys``, etc.). When the
    victim runs ``safelint skill install``, codex auto-detects (via
    ``.codex/`` or ``AGENTS.md`` markers) and the secondary install
    would normally read+rewrite the file *through* the symlink,
    corrupting whatever it points at. Hardening: refuse to follow,
    print a warning, leave the symlink target untouched.
    """
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a sensitive-looking file outside the install scope.
    sensitive = tmp_path / "sensitive.txt"
    sensitive.write_text("DO NOT MODIFY\n", encoding="utf-8")
    # Make AGENTS.md a symlink to it.
    (cwd / "AGENTS.md").symlink_to(sensitive)

    rc = _skill_install.run_install(_make_args(client="codex", project=True))
    # Primary install still succeeds.
    assert rc == 0
    assert (cwd / ".codex" / "instructions.md").is_file()
    # Sensitive file UNCHANGED — symlink was refused.
    assert sensitive.read_text(encoding="utf-8") == "DO NOT MODIFY\n"
    # Warning surfaced to stderr.
    err = capsys.readouterr().err
    err_lower = err.lower()
    assert "refusing" in err_lower
    assert "symlink" in err_lower


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_remove_codex_refuses_symlinked_agents_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``_remove_secondary`` MUST NOT follow a symlink at AGENTS.md when stripping the section."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Plant a real AGENTS.md, install codex normally.
    (cwd / "AGENTS.md").write_text("user content\n", encoding="utf-8")
    assert _skill_install.run_install(_make_args(client="codex", project=True)) == 0
    capsys.readouterr()
    # Now replace AGENTS.md with a symlink to a sensitive file.
    sensitive = tmp_path / "sensitive.txt"
    sensitive.write_text("DO NOT MODIFY\n", encoding="utf-8")
    (cwd / "AGENTS.md").unlink()
    (cwd / "AGENTS.md").symlink_to(sensitive)

    rc = _skill_install.run_remove(_make_remove_args(client="codex", project=True))
    assert rc == 0
    # Primary removed, sensitive target untouched, warning surfaced.
    assert not (cwd / ".codex" / "instructions.md").exists()
    assert sensitive.read_text(encoding="utf-8") == "DO NOT MODIFY\n"
    err = capsys.readouterr().err
    err_lower = err.lower()
    assert "refusing" in err_lower
    assert "symlink" in err_lower


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_secondary_status_treats_symlink_as_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_secondary_status`` must treat a symlinked AGENTS.md as MISSING (refuse to read through)."""
    _, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    sensitive = tmp_path / "sensitive.txt"
    sensitive.write_text("DO NOT READ\n", encoding="utf-8")
    (cwd / "AGENTS.md").symlink_to(sensitive)

    status = _skill_install._secondary_status(_skill_install._CODEX_SPEC, project=True)
    assert status == _skill_install.INSTALL_STATUS_MISSING


def test_remove_path_refuses_unrecognised_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``skill remove --path PATH`` must refuse paths that don't match any registered install shape.

    Catches typos / shell-expansion accidents (e.g. ``--path ~/.config``
    instead of ``--path ~/.cursor/...``) before they trigger
    ``shutil.rmtree`` on the wrong directory.
    """
    bogus = tmp_path / "definitely-not-a-safelint-install"
    bogus.mkdir()
    (bogus / "important_file.txt").write_text("DO NOT DELETE\n", encoding="utf-8")

    rc = _skill_install.run_remove(_make_remove_args(path=bogus))
    assert rc == 1
    # Path NOT deleted.
    assert bogus.is_dir()
    assert (bogus / "important_file.txt").read_text(encoding="utf-8") == "DO NOT DELETE\n"
    err = capsys.readouterr().err
    assert "refusing to remove" in err
    assert "registered safelint install shape" in err


def test_remove_path_accepts_unusual_parent_with_known_install_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--path`` allows non-standard parent dirs as long as the tail matches a registered install shape.

    Use case: user has a Cursor install at ``~/projects/foo/.cursor/rules/safelint.mdc``
    that auto-detect missed. The tail matches Cursor's ``install_relpath``
    so the security guard accepts it.
    """
    odd_install = tmp_path / "unusual" / "place" / ".cursor" / "rules" / "safelint.mdc"
    odd_install.parent.mkdir(parents=True)
    odd_install.write_text("safelint cursor rule\n", encoding="utf-8")

    rc = _skill_install.run_remove(_make_remove_args(path=odd_install))
    assert rc == 0
    assert not odd_install.exists()


def test_path_looks_like_safelint_install_recognises_every_registered_client() -> None:
    """The shape-check helper must recognise every registered client's canonical install path.

    Regression test: when a new client is added to ``_CLIENT_SPECS``,
    its ``install_relpath`` should be automatically allowed by the
    ``--path`` security guard (the helper iterates over the registry).
    """
    for spec in _skill_install._CLIENT_SPECS:
        canonical = Path("/some/parent").joinpath(*spec.install_relpath)
        assert _skill_install._path_looks_like_safelint_install(canonical), f"{spec.name}'s canonical install path {canonical} should be recognised"


def test_update_one_handles_namespace_without_force_attribute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_update_one`` reads ``force`` defensively via ``getattr``.

    Library callers / tests that construct a partial Namespace
    shouldn't trip ``AttributeError``. Matches the defensive pattern
    used elsewhere in the module.

    Redirects home/cwd via ``_redirect_home_and_cwd`` so the
    downstream ``_install_one`` (reached because no install exists
    yet → MISSING → re-install) writes into ``tmp_path``, not the
    developer's real ``~/.cursor/...``.
    """
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Argparse-Namespace-like object with NO ``force`` attribute.
    args = argparse.Namespace()  # empty
    # Use a mocker-free, in-process path: just verify the helper
    # doesn't raise. It might fail on later steps (no install exists)
    # but it must not raise AttributeError on the ``force`` lookup.
    spec = _skill_install._CURSOR_SPEC
    try:
        _skill_install._update_one(spec, project=False, args=args)
    except AttributeError as e:
        pytest.fail(f"_update_one raised AttributeError on partial Namespace: {e}")
    # No assertion on rc — partial Namespace may legitimately fail
    # downstream (e.g. when reading ``symlink``); the contract is
    # simply that the missing-attribute case doesn't blow up at
    # the ``force`` read.


def test_update_project_flag_filters_auto_detect_to_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``update --project`` (with auto-detect) skips user-scope installs.

    Plant both a user-scope and a project-scope install for the
    same client, drift both, and run ``update --project``. Only the
    project-scope install should be refreshed; the user-scope drift
    must remain visible (status would still report it as differs).
    Regression for ``--project`` being silently dropped on the
    ``--client auto`` path.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    assert _skill_install.run_install(_make_args(client="cursor", project=True)) == 0
    user_target = home / ".cursor" / "rules" / "safelint.mdc"
    project_target = cwd / ".cursor" / "rules" / "safelint.mdc"
    user_target.write_text("# user customised\n", encoding="utf-8")
    project_target.write_text("# project customised\n", encoding="utf-8")
    capsys.readouterr()

    rc = _skill_install.run_update(_make_update_args(project=True))
    assert rc == 0
    # Project-scope install was refreshed (customisation gone).
    assert "project customised" not in project_target.read_text(encoding="utf-8")
    # User-scope install was NOT touched — customisation survives.
    assert "user customised" in user_target.read_text(encoding="utf-8")


def test_update_explicit_client_at_missing_scope_is_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``update --client claude`` when no Claude install exists is a clean no-op."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_update(_make_update_args(client="claude"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "no AI-client skill installs detected" in out


def test_cli_routes_skill_update(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill update`` routes to ``_skill_install.run_update``."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "update"])
    spy = mocker.patch.object(_skill_install, "run_update", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()


# ---------------------------------------------------------------------------
# safelint skill remove — delete detected installs
# ---------------------------------------------------------------------------


def _make_remove_args(*, project: bool = False, symlink: bool = False, dry_run: bool = False, client: str = "auto", path: Path | None = None) -> argparse.Namespace:
    """Namespace shaped like the remove argparser produces."""
    return argparse.Namespace(skill_action="remove", project=project, symlink=symlink, dry_run=dry_run, client=client, path=path)


def test_remove_deletes_detected_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Bare ``safelint skill remove`` deletes the auto-detected install."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    assert target.exists()
    capsys.readouterr()

    rc = _skill_install.run_remove(_make_remove_args())
    assert rc == 0
    assert not target.exists()
    out = capsys.readouterr().out
    assert "Cursor rule removed from" in out


def test_remove_returns_zero_with_helpful_note_when_nothing_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``remove`` with nothing installed exits 0 with a hint about ``--path``."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_remove(_make_remove_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "no installed skill detected" in out
    assert "--path PATH" in out


def test_remove_dry_run_does_not_delete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--dry-run`` previews without deleting anything."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    target = home / ".cursor" / "rules" / "safelint.mdc"
    capsys.readouterr()

    rc = _skill_install.run_remove(_make_remove_args(dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "would remove" in out
    # Crucially: target is untouched.
    assert target.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_remove_symlink_filter_skips_copy_installs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--symlink`` removes only symlink-shape installs; copy installs survive.

    The user's specific use case: "delete only the symlinks, keep my
    copies". Plant a copy-mode Cursor install user-scoped and a
    symlink-mode Claude install user-scoped; assert remove --symlink
    deletes only Claude.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    # Cursor in copy mode (default).
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    cursor_target = home / ".cursor" / "rules" / "safelint.mdc"
    assert cursor_target.exists()
    assert not cursor_target.is_symlink()
    # Claude in symlink mode.
    assert _skill_install.run_install(_make_args(client="claude", symlink=True)) == 0
    claude_target = home / ".claude" / "skills" / "safelint"
    assert (claude_target / "SKILL.md").is_symlink()
    capsys.readouterr()

    rc = _skill_install.run_remove(_make_remove_args(symlink=True))
    assert rc == 0
    # Claude (symlink) is gone.
    assert not claude_target.exists()
    # Cursor (copy) is intact.
    assert cursor_target.exists()


def test_remove_path_deletes_explicit_location(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--path PATH`` removes one specific location, bypassing detection.

    Path is built under a Cursor-shaped tail
    (``.cursor/rules/safelint.mdc``) so the security guard introduced
    in the v1.11.0 hardening accepts it.
    """
    odd_location = tmp_path / "weird" / "place" / ".cursor" / "rules" / "safelint.mdc"
    odd_location.parent.mkdir(parents=True)
    odd_location.write_text("# stray install\n", encoding="utf-8")

    rc = _skill_install.run_remove(_make_remove_args(path=odd_location))
    assert rc == 0
    assert not odd_location.exists()
    out = capsys.readouterr().out
    assert "removed install at" in out
    assert "(--path)" in out


def test_remove_path_missing_returns_one_with_stderr_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--path PATH`` to a non-existent location is an error, not a silent no-op."""
    nonexistent = tmp_path / "not" / "here.mdc"
    rc = _skill_install.run_remove(_make_remove_args(path=nonexistent))
    assert rc == 1
    err = capsys.readouterr().err
    assert "nothing to remove at" in err
    assert str(nonexistent) in err


def test_remove_path_dry_run_previews_without_deleting(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--path PATH --dry-run`` previews; the file must remain on disk.

    Same Cursor-shaped tail as the deletion test so the install-shape
    security guard accepts the path.
    """
    odd_location = tmp_path / "weird" / "place" / ".cursor" / "rules" / "safelint.mdc"
    odd_location.parent.mkdir(parents=True)
    odd_location.write_text("# stray\n", encoding="utf-8")

    rc = _skill_install.run_remove(_make_remove_args(path=odd_location, dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "would remove" in out
    assert "(--path)" in out
    # File still exists.
    assert odd_location.exists()


def test_remove_explicit_client_at_missing_scope_is_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``remove --client claude`` with no Claude install reports nothing-installed cleanly."""
    _redirect_home_and_cwd(monkeypatch, tmp_path)
    rc = _skill_install.run_remove(_make_remove_args(client="claude"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "no installed skill detected" in out


def test_remove_explicit_client_without_project_targets_both_scopes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``remove --client cursor`` (no ``--project``) deletes BOTH user and project installs.

    Symmetric with ``--client auto``: ``--project`` is the orthogonal
    scope-restriction filter. The destructive nature of remove makes
    the asymmetric behaviour particularly footgun-y — silently
    leaving a project-scope install alive after the user thought
    they'd cleaned up the client.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    assert _skill_install.run_install(_make_args(client="cursor", project=True)) == 0
    user_target = home / ".cursor" / "rules" / "safelint.mdc"
    project_target = cwd / ".cursor" / "rules" / "safelint.mdc"

    rc = _skill_install.run_remove(_make_remove_args(client="cursor"))
    assert rc == 0
    # BOTH installs gone.
    assert not user_target.exists()
    assert not project_target.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_install_is_symlink_shape_returns_true_for_broken_inner_symlinks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``_install_is_symlink_shape`` recognises a Claude install whose inner symlinks broke.

    Shape detection (used by ``remove --symlink`` filter) is distinct
    from freshness detection: a Claude install with dangling inner
    symlinks is still symlink-shape (``--symlink`` cleanup must reach
    it), even though it's not "fresh" any more (the bundled targets
    moved). Without this, ``remove --symlink`` would skip a broken
    symlink install and leave it on disk forever.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude", symlink=True)) == 0
    target_dir = home / ".claude" / "skills" / "safelint"
    # Break one inner symlink by repointing it at a removed path.
    skill_md_link = target_dir / "SKILL.md"
    skill_md_link.unlink()
    skill_md_link.symlink_to(tmp_path / "vanished.md")
    assert skill_md_link.is_symlink()
    assert not skill_md_link.exists()  # broken

    # Shape predicate still recognises this as symlink-shape.
    assert _skill_install._install_is_symlink_shape(_skill_install._CLAUDE_SPEC, project=False) is True


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_remove_symlink_filter_cleans_up_broken_claude_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``remove --symlink`` removes a Claude install with broken inner symlinks.

    The user-facing scenario for the shape-vs-freshness split: the
    bundled source moved (e.g. virtualenv rebuilt, wheel cache cleared),
    leaving the Claude symlink install dangling. ``remove --symlink``
    must still reach and clean it up — anything else strands the user
    with an unusable install they can't easily wipe.
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude", symlink=True)) == 0
    target_dir = home / ".claude" / "skills" / "safelint"
    # Break one inner symlink to simulate the moved-bundle case.
    skill_md_link = target_dir / "SKILL.md"
    skill_md_link.unlink()
    skill_md_link.symlink_to(tmp_path / "moved.md")
    capsys.readouterr()

    rc = _skill_install.run_remove(_make_remove_args(symlink=True))
    assert rc == 0
    # Install directory is gone — user can run ``install`` from a
    # clean state without manually rm'ing the dangling layout.
    assert not target_dir.exists()


def test_remove_project_flag_filters_auto_detect_to_project_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``remove --project`` (with auto-detect) skips user-scope installs.

    Mirror of the update regression: plant both scopes, run
    ``remove --project``, assert only the project-scope install is
    deleted. Without the scope filter, the user-scope install would
    be silently nuked too — that's a real footgun on ``remove``
    because it's destructive.
    """
    home, cwd = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0
    assert _skill_install.run_install(_make_args(client="cursor", project=True)) == 0
    user_target = home / ".cursor" / "rules" / "safelint.mdc"
    project_target = cwd / ".cursor" / "rules" / "safelint.mdc"
    capsys.readouterr()

    rc = _skill_install.run_remove(_make_remove_args(project=True))
    assert rc == 0
    # Project-scope install removed.
    assert not project_target.exists()
    # User-scope install untouched.
    assert user_target.exists()


def test_remove_explicit_client_with_symlink_filter_skips_copy_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--client cursor --symlink`` skips a Cursor install that's in copy mode.

    Composes the explicit-client path with the symlink filter — the
    install exists, but its shape doesn't match the filter, so
    ``remove`` reports nothing-installed (and leaves the install
    untouched).
    """
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="cursor")) == 0  # copy mode
    target = home / ".cursor" / "rules" / "safelint.mdc"
    capsys.readouterr()

    rc = _skill_install.run_remove(_make_remove_args(client="cursor", symlink=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "no installed skill detected" in out
    # Copy install untouched.
    assert target.exists()


def test_remove_explicit_client_filters_to_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--client claude`` removes only the Claude install, leaves Cursor alone."""
    home, _ = _redirect_home_and_cwd(monkeypatch, tmp_path)
    assert _skill_install.run_install(_make_args(client="claude")) == 0
    assert _skill_install.run_install(_make_args(client="cursor")) == 0

    rc = _skill_install.run_remove(_make_remove_args(client="claude"))
    assert rc == 0
    # Claude gone, Cursor intact.
    assert not (home / ".claude" / "skills" / "safelint").exists()
    assert (home / ".cursor" / "rules" / "safelint.mdc").exists()


def test_cli_routes_skill_remove(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``safelint skill remove`` routes to ``_skill_install.run_remove``."""
    monkeypatch.setattr("sys.argv", ["safelint", "skill", "remove"])
    spy = mocker.patch.object(_skill_install, "run_remove", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()
