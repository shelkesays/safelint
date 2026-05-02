"""``safelint skill install`` subcommand — copy/symlink the bundled skill into the user's Claude Code skills directory.

The skill's source files (``SKILL.md`` + ``languages/*.md``) ship inside
the wheel under ``safelint/skill_files/``. This module locates them
via :func:`importlib.resources.files` and materialises them at the
target install location.

Two flavours of install:

* **Copy** (default) — snapshot the bundled files. Stable across
  ``pip upgrade safelint`` runs; the user re-runs ``skill install``
  to pick up newer skill content. Works on every platform, including
  Windows where symlink creation needs developer-mode or admin.
* **Symlink** (``--symlink``) — link to the live bundled location.
  ``pip upgrade safelint`` immediately changes what Claude Code sees.
  Useful for skill development; relies on POSIX-style symlinks.

Two install scopes:

* **User** (default) — ``~/.claude/skills/safelint/``. Active for every
  Claude Code session.
* **Project** (``--project``) — ``<cwd>/.claude/skills/safelint/``.
  Active only inside the current project. Useful when you want
  team-shared skill overrides without affecting personal sessions.
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


def _resolve_target(*, project: bool) -> Path:
    """Return the install target directory based on scope."""
    if project:
        return Path.cwd() / ".claude" / "skills" / _SKILL_DIR_NAME
    return Path.home() / ".claude" / "skills" / _SKILL_DIR_NAME


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
    """Create *target* as a symlink to *source*."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source, target_is_directory=True)


def _install_copy(source: Path, target: Path) -> None:
    """Copy *source* tree to *target*."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)


def run_install(args: argparse.Namespace) -> int:
    """Execute ``safelint skill install`` and return the exit code.

    Returns 0 on success, 1 on a known failure (e.g. target already
    exists without ``--force``). Unexpected errors (filesystem fault,
    bundled files missing) propagate.
    """
    source = bundled_skill_path()
    target = _resolve_target(project=args.project)

    if target.exists() or target.is_symlink():
        if not args.force:
            # Errors go to stderr so a wrapper script's `safelint skill install
            # || handle-error` flow can capture stderr without polluting stdout.
            # nosafe: SAFE304 — explicit user-facing diagnostic by design.
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
    # want to log "what got installed where". nosafe: SAFE304 — these are
    # the subcommand's whole purpose; printing IS their job.
    print(f"safelint: skill {kind} to {target} ({scope} scope)")  # nosafe: SAFE304
    print("Restart Claude Code (or open a new session) to pick up the skill.")  # nosafe: SAFE304
    return 0


def run_path(_args: argparse.Namespace) -> int:
    """Execute ``safelint skill path`` — print the bundled-files location.

    Useful for debugging install issues or for users who want to
    inspect the bundled SKILL.md without installing.
    """
    # The whole point of this subcommand is to print the path to stdout
    # so it's pipeable (e.g. ``cat $(safelint skill path)/SKILL.md``).
    # nosafe: SAFE304 — printing IS the subcommand's purpose.
    print(bundled_skill_path())  # nosafe: SAFE304
    return 0
