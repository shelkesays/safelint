"""``safelint skill install`` subcommand — copy/symlink the bundled skill into the user's AI-client directory.

The skill's source files (``SKILL.md`` + ``languages/*.md`` + the
Cursor ``cursor/safelint.mdc`` rule) ship inside the wheel under
``safelint/skill_files/``. This module locates them via
:func:`importlib.resources.files` and materialises them at the target
install location.

Two AI clients are supported:

* **Claude Code** (default, ``--client claude``) — installs the
  full skill bundle (``SKILL.md`` + ``languages/*.md`` + ``README.md``)
  as a directory at ``~/.claude/skills/safelint/`` (user) or
  ``<cwd>/.claude/skills/safelint/`` (project, with ``--project``).
* **Cursor** (``--client cursor``) — installs the single MDC project
  rule at ``~/.cursor/rules/safelint.mdc`` (user) or
  ``<cwd>/.cursor/rules/safelint.mdc`` (project). The bundled
  language addendums stay accessible via ``safelint skill path``;
  the MDC tells the agent how to find them when needed.

Two install flavours apply to both clients:

* **Copy** (default) — snapshot the bundled file(s). Stable across
  ``pip upgrade safelint`` runs; the user re-runs ``skill install``
  to pick up newer content. Works on every platform, including
  Windows where symlink creation needs developer-mode or admin.
* **Symlink** (``--symlink``) — link to the live bundled location.
  ``pip upgrade safelint`` immediately changes what the agent sees.
  Useful for skill development; relies on POSIX-style symlinks.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
import shutil
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import argparse
    from importlib.abc import Traversable


_SKILL_DIR_NAME = "safelint"
_CURSOR_RULE_FILENAME = "safelint.mdc"

# Subdirectory under ``skill_files/`` that holds peer-client bundles.
# Excluded from the Claude install so the copy at ``~/.claude/skills/
# safelint/`` doesn't carry an irrelevant ``cursor/`` sibling that
# Claude Code would never read.
_PEER_CLIENT_DIRS: frozenset[str] = frozenset({"cursor"})


def _bundled_skill_root() -> Traversable:
    """Return the bundled skill_files root as an importlib Traversable."""
    return resources.files("safelint") / "skill_files"


def bundled_skill_path() -> Path:
    """Return the on-disk path to the bundled skill files.

    Works for both wheel installs (where the files live under
    ``site-packages/safelint/skill_files/``) and editable installs
    (where they live under ``src/safelint/skill_files/`` in the source
    tree). ``importlib.resources`` abstracts both cases.

    Raises:
        FileNotFoundError: if the bundle is missing — meaning safelint
            was installed without its skill files (very old build, or
            the user removed them by hand).

    """
    root = _bundled_skill_root()
    # ``files()`` returns a Traversable; for filesystem-backed installs
    # we can resolve to a concrete Path. PEP 706 / 711 wheel installs
    # are filesystem-backed, so this works for ``pip install`` and ``uv``.
    with resources.as_file(root) as path:
        if not path.exists():
            msg = f"bundled skill files not found at {path} — reinstall safelint"
            raise FileNotFoundError(msg)
        return Path(path)


def _bundled_source(client: str) -> Path:
    """Return the bundled source path for *client*.

    Claude install copies the whole ``skill_files/`` tree (minus the
    cursor/ subdirectory). Cursor install copies just the single
    ``cursor/safelint.mdc`` file.
    """
    root = bundled_skill_path()
    if client == "cursor":
        return root / "cursor" / _CURSOR_RULE_FILENAME
    return root


def _resolve_target(*, client: str, project: bool) -> Path:
    """Return the install target path based on *client* and scope."""
    if client == "cursor":
        base = Path.cwd() if project else Path.home()
        return base / ".cursor" / "rules" / _CURSOR_RULE_FILENAME
    base = Path.cwd() if project else Path.home()
    return base / ".claude" / "skills" / _SKILL_DIR_NAME


def _remove_existing(target: Path) -> None:
    """Remove a pre-existing skill install (file, symlink, or directory)."""
    # ``is_symlink`` first because symlinks-to-directories report True for
    # ``is_dir`` too, and we want to delete the link, not its target.
    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    if target.is_dir():
        shutil.rmtree(target)


def _install_symlink(source: Path, target: Path) -> None:
    """Create *target* as a symlink to *source*.

    Works for both file (Cursor MDC) and directory (Claude skill)
    sources — :meth:`Path.symlink_to` infers the target type from the
    source unless we pass ``target_is_directory`` explicitly.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source, target_is_directory=source.is_dir())


def _install_copy(source: Path, target: Path) -> None:
    """Copy *source* (file or directory tree) to *target*.

    For the Claude directory install, peer-client bundles (the
    ``cursor/`` subdirectory) are excluded so users don't see an
    irrelevant ``cursor/`` sibling inside their Claude skill folder.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copyfile(source, target)
        return
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*_PEER_CLIENT_DIRS))


def _restart_hint(client: str) -> str:
    """Return the per-client restart instruction printed after a successful install."""
    if client == "cursor":
        return "Restart Cursor (or reload the window) to pick up the new project rule."
    return "Restart Claude Code (or open a new session) to pick up the skill."


def run_install(args: argparse.Namespace) -> int:
    """Execute ``safelint skill install`` and return the exit code.

    Returns 0 on success, 1 on a known failure (e.g. target already
    exists without ``--force``). Unexpected errors (filesystem fault,
    bundled files missing) propagate.
    """
    client = getattr(args, "client", "claude")
    source = _bundled_source(client)
    target = _resolve_target(client=client, project=args.project)

    if target.exists() or target.is_symlink():
        if not args.force:
            # Errors go to stderr so a wrapper script's `safelint skill install
            # || handle-error` flow can capture stderr without polluting stdout.
            # The inline suppression on the print line below is the explicit
            # user-facing-diagnostic exemption from SAFE304.
            print(f"safelint: error: {target} already exists. Use --force to replace it.", file=sys.stderr)  # nosafe: SAFE304
            return 1
        _remove_existing(target)

    if args.symlink:
        _install_symlink(source, target)
        kind = "symlinked"
    else:
        _install_copy(source, target)
        kind = "copied"

    scope = "project" if args.project else "user"
    # Success notices on stdout — pipe-friendly for scripted installs that
    # want to log "what got installed where". SAFE304 already fires once
    # per function on the first I/O call (the stderr print above), so
    # these stdout prints don't need further suppressions.
    print(f"safelint: {client} skill {kind} to {target} ({scope} scope)")
    print(_restart_hint(client))
    return 0


def run_path(args: argparse.Namespace) -> int:
    """Execute ``safelint skill path`` — print the bundled-files location.

    Default prints the skill_files/ root (the Claude bundle); with
    ``--client cursor`` prints the path to the bundled
    ``cursor/safelint.mdc``. Useful for debugging install issues or
    for users who want to inspect bundled content without installing.
    """
    client = getattr(args, "client", "claude")
    # The whole point of this subcommand is to print the path to stdout
    # so it's pipeable (e.g. ``cat $(safelint skill path)/SKILL.md``).
    # The inline SAFE304 suppression on the print line is the side-effects
    # exemption — this is the subcommand's purpose.
    print(_bundled_source(client))  # nosafe: SAFE304
    return 0
