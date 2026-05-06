"""``safelint skill install`` subcommand — copy/symlink the bundled skill into the user's AI-client directory.

The skill's source files (``SKILL.md`` + ``languages/*.md`` + the
Cursor ``cursor/safelint.mdc`` rule) ship inside the wheel under
``safelint/skill_files/``. This module locates them via
:func:`importlib.resources.files` and materialises them at the target
install location.

Two AI clients ship today (Claude Code and Cursor) but the registry
in ``_CLIENT_SPECS`` is open-ended — adding GitHub Copilot, codex,
windsurf, antigravity, etc. is a matter of appending one
:class:`ClientSpec` entry. No control flow needs to know about the
new client; install / detection / output all read from the spec.

``safelint skill install`` (no ``--client``) auto-detects which AI
client(s) are in use:

* If markers for any client(s) exist in the current working
  directory (e.g. ``CLAUDE.md`` or ``.cursor/``), install each
  detected client's skill **project-scoped**.
* Otherwise, if markers exist in the user's home directory
  (e.g. ``~/.claude/`` or ``~/.cursor/``), install each detected
  client's skill **user-scoped**.
* Otherwise, fail with an error listing the explicit ``--client``
  commands the user can run.

Pass ``--client <name>`` to skip auto-detection and target a single
client, or ``--client auto --project`` to auto-detect but force
project scope (no home fallback).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from importlib import resources
from pathlib import Path
import shutil
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator
    from importlib.abc import Traversable


# ---------------------------------------------------------------------------
# Client registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClientSpec:
    """A single AI client's install profile.

    Adding a new client (Copilot, codex, windsurf, antigravity, …)
    means appending one :class:`ClientSpec` to ``_CLIENT_SPECS`` —
    no control-flow changes elsewhere.
    """

    name: str  # CLI-facing value: ``claude``, ``cursor``
    display_name: str  # User-facing label: ``Claude Code``, ``Cursor``
    artefact_label: str  # Output noun: ``skill`` (directory) / ``rule`` (single file)
    cwd_markers: tuple[str, ...]  # Relative paths under cwd that signal "this client used here"
    home_markers: tuple[str, ...]  # Relative paths under home that signal "this client installed"
    install_relpath: tuple[str, ...]  # Path components, relative to scope root (cwd or home)
    bundled_relpath: tuple[str, ...]  # Path components under skill_files/ (empty = whole tree)
    restart_hint: str
    usage_hint: str
    # Drift-detection inputs. Each tuple is a relpath under
    # ``skill_files/`` whose text must collectively mention every
    # registered rule code / name (``ALL_RULES``) and every supported
    # extension (``supported_extensions()``). Tests parametrised over
    # ``_CLIENT_SPECS`` enforce this — when a contributor adds a new
    # rule or language, the test fails until the bundled docs for
    # *every* registered client are updated.
    documentation_relpaths: tuple[tuple[str, ...], ...]


_CLAUDE_SPEC = ClientSpec(
    name="claude",
    display_name="Claude Code",
    artefact_label="skill",
    # Detection markers, in priority order — the first one that exists
    # is the one we report in the detection notice. ``CLAUDE.md`` and
    # ``.claude/`` are the most common; ``.claude.json`` is the
    # Claude Code settings file (per-user at ``~/.claude.json``,
    # per-project when committed alongside repo config).
    cwd_markers=("CLAUDE.md", ".claude", ".claude.json"),
    home_markers=(".claude", ".claude.json"),
    install_relpath=(".claude", "skills", "safelint"),
    bundled_relpath=(),  # whole skill_files/ tree (minus peer-client dirs)
    restart_hint="Restart Claude Code (or open a new session) to pick up the skill.",
    usage_hint='Then ask Claude Code "run safelint" or "lint with safelint".',
    documentation_relpaths=(("SKILL.md",),),
)


_CURSOR_SPEC = ClientSpec(
    name="cursor",
    display_name="Cursor",
    artefact_label="rule",
    cwd_markers=(".cursor", ".cursorrules"),
    home_markers=(".cursor",),
    install_relpath=(".cursor", "rules", "safelint.mdc"),
    bundled_relpath=("cursor", "safelint.mdc"),
    restart_hint="Restart Cursor (or reload the window) to pick up the new rule.",
    usage_hint='Then ask Cursor "run safelint" or "lint with safelint".',
    documentation_relpaths=(("cursor", "safelint.mdc"),),
)


# Registry — append to extend. Order matters: detection / multi-install
# output follows registry order so users see results in a stable sequence.
_CLIENT_SPECS: tuple[ClientSpec, ...] = (_CLAUDE_SPEC, _CURSOR_SPEC)

_CLIENT_NAMES: tuple[str, ...] = tuple(spec.name for spec in _CLIENT_SPECS)

# CLI ``--client`` choices for the install subcommand: ``auto`` (default)
# plus every registered client by name.
INSTALL_CLIENT_CHOICES: tuple[str, ...] = ("auto", *_CLIENT_NAMES)

# CLI ``--client`` choices for the path subcommand: registered clients
# only. ``auto`` doesn't apply to ``path`` because the cat-friendly
# single-line output convention (e.g. ``cat $(safelint skill path)/SKILL.md``)
# expects exactly one path.
PATH_CLIENT_CHOICES: tuple[str, ...] = _CLIENT_NAMES

# Subdirectories under ``skill_files/`` that hold peer-client bundles.
# Excluded from a Claude install (copy or symlink) so the materialised
# skill folder doesn't carry irrelevant peer artefacts.
_PEER_CLIENT_DIRS: frozenset[str] = frozenset({"cursor"})


# ---------------------------------------------------------------------------
# Bundled-files lookup
# ---------------------------------------------------------------------------


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
    with resources.as_file(root) as path:
        if not path.exists():
            msg = f"bundled skill files not found at {path} — reinstall safelint"
            raise FileNotFoundError(msg)
        return Path(path)


# ---------------------------------------------------------------------------
# Spec resolution
# ---------------------------------------------------------------------------


def _spec_by_name(name: str) -> ClientSpec:
    """Return the registered :class:`ClientSpec` whose name is *name*.

    Raises:
        KeyError: if no client with that name is registered. argparse
            ``choices=`` should have prevented this; the explicit raise
            documents the contract for library callers.

    """
    for spec in _CLIENT_SPECS:
        if spec.name == name:
            return spec
    msg = f"unknown client {name!r}; registered: {', '.join(_CLIENT_NAMES)}"
    raise KeyError(msg)


def _spec_target(spec: ClientSpec, *, project: bool) -> Path:
    """Return the install target path for *spec* under the chosen scope."""
    base = Path.cwd() if project else Path.home()
    return base.joinpath(*spec.install_relpath)


def _spec_bundled_source(spec: ClientSpec) -> Path:
    """Return the bundled source path that gets copied/linked for *spec*.

    For Claude (``bundled_relpath = ()``) this is the whole
    ``skill_files/`` directory; the install primitives prune
    :data:`_PEER_CLIENT_DIRS` from it. For Cursor it's the single
    ``cursor/safelint.mdc`` file.
    """
    return bundled_skill_path().joinpath(*spec.bundled_relpath)


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------


def _first_existing_marker(directory: Path, markers: tuple[str, ...]) -> str | None:
    """Return the first entry in *markers* that exists under *directory*, or None."""
    for m in markers:
        if (directory / m).exists():
            return m
    return None


def _detected_clients(directory: Path, marker_attr: str) -> list[tuple[ClientSpec, str]]:
    """Return [(spec, matched_marker), ...] for each spec with at least one marker under *directory*.

    *marker_attr* is ``"cwd_markers"`` or ``"home_markers"``. The first
    matching marker per spec is the one we report — sufficient for
    user-facing detection notices.
    """
    detected: list[tuple[ClientSpec, str]] = []
    for spec in _CLIENT_SPECS:
        markers: tuple[str, ...] = getattr(spec, marker_attr)
        marker = _first_existing_marker(directory, markers)
        if marker is not None:
            detected.append((spec, marker))
    return detected


def _resolve_install_plan(args: argparse.Namespace) -> tuple[str, list[tuple[ClientSpec, bool]]] | None:
    """Return ``(notice, [(spec, project_scope), ...])`` or None on auto-detect failure.

    *notice* is a one-line string to print before installing (or "" if
    no notice is appropriate, e.g. for explicit ``--client``). On
    auto-detect failure, prints a helpful error to stderr and returns
    None — the caller maps that to exit code 1.
    """
    client = getattr(args, "client", "auto")
    project_flag = bool(getattr(args, "project", False))

    if client != "auto":
        return "", [(_spec_by_name(client), project_flag)]

    cwd_specs = _detected_clients(Path.cwd(), "cwd_markers")
    if cwd_specs:
        return _format_detection_notice(cwd_specs, "current directory"), [(s, True) for s, _ in cwd_specs]

    if project_flag:
        # ``--project`` + auto with empty cwd: don't fall back to home —
        # the user explicitly asked for project scope.
        _print_no_clients_error(scope_description="current directory (--project specified)")
        return None

    home_specs = _detected_clients(Path.home(), "home_markers")
    if home_specs:
        return _format_detection_notice(home_specs, "home directory"), [(s, False) for s, _ in home_specs]

    _print_no_clients_error(scope_description="current directory or home directory")
    return None


def _format_detection_notice(detected: list[tuple[ClientSpec, str]], where: str) -> str:
    """Render the one-line "safelint: detected X (marker) in <where>" notice."""
    parts = [f"{spec.display_name} ({marker})" for spec, marker in detected]
    clients = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
    return f"safelint: detected {clients} in {where}"


# ---------------------------------------------------------------------------
# Print helpers — names start with ``_print_`` so SAFE304 (side_effects)
# auto-exempts them. The actual printing is the whole point of these
# helpers, not an incidental side effect.
# ---------------------------------------------------------------------------


def _print_detection_notice(notice: str) -> None:
    """Print a detection notice to stdout (only when non-empty)."""
    if notice:
        print(notice)


def _print_install_success(spec: ClientSpec, *, target: Path, kind: str, scope: str) -> None:
    """Print the per-install success block: header, restart hint, usage hint."""
    print(f"safelint: {spec.display_name} {spec.artefact_label} {kind} to {target} ({scope} scope)")
    print(f"  → {spec.restart_hint}")
    print(f"  → {spec.usage_hint}")


def _print_target_exists_error(target: Path) -> None:
    """Print the "target already exists" error to stderr."""
    print(f"safelint: error: {target} already exists. Use --force to replace it.", file=sys.stderr)


def _print_no_clients_error(*, scope_description: str) -> None:
    """Print the auto-detect-failure error to stderr with explicit ``--client`` examples."""
    seen_markers = sorted({m for spec in _CLIENT_SPECS for m in (*spec.cwd_markers, *spec.home_markers)})
    print("safelint: error: could not auto-detect an AI client.", file=sys.stderr)
    print(f"  Looked for: {', '.join(seen_markers)} in {scope_description}", file=sys.stderr)
    print("  Specify the client explicitly:", file=sys.stderr)
    for spec in _CLIENT_SPECS:
        user_target = Path.home().joinpath(*spec.install_relpath)
        print(f"    safelint skill install --client {spec.name}            # {spec.display_name} ({user_target})", file=sys.stderr)
        print(f"    safelint skill install --client {spec.name} --project  # Project-scoped {spec.display_name}", file=sys.stderr)
    print("  Run `safelint skill install --help` to see all options.", file=sys.stderr)


def _print_bundled_path(path: Path) -> None:
    """Print the bundled-files path to stdout (used by ``safelint skill path``)."""
    print(path)


# ---------------------------------------------------------------------------
# Install primitives
# ---------------------------------------------------------------------------


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

    Single-file source (e.g. Cursor MDC) → one symlink. Directory source
    (e.g. Claude skill bundle) → per-entry symlinks via
    :func:`_install_symlink_directory_filtered` so peer-client
    subdirectories don't leak into the install.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        target.symlink_to(source, target_is_directory=False)
        return
    _install_symlink_directory_filtered(source, target)


def _install_symlink_directory_filtered(source: Path, target: Path) -> None:
    """Materialise *target* as a directory and symlink each non-peer entry inside.

    Skips entries matching :data:`_PEER_CLIENT_DIRS`. ``pip upgrade
    safelint`` still reflects content changes underneath the linked
    entries; only newly-added top-level entries require re-running
    ``safelint skill install --symlink --force``.
    """
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.name in _PEER_CLIENT_DIRS:
            continue
        link = target / entry.name
        link.symlink_to(entry, target_is_directory=entry.is_dir())


def _install_copy(source: Path, target: Path) -> None:
    """Copy *source* (file or directory tree) to *target*.

    Directory copies exclude :data:`_PEER_CLIENT_DIRS` so a Claude
    install doesn't carry an irrelevant ``cursor/`` sibling.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copyfile(source, target)
        return
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*_PEER_CLIENT_DIRS))


# ---------------------------------------------------------------------------
# Single-install orchestration
# ---------------------------------------------------------------------------


def _install_one(spec: ClientSpec, *, project: bool, args: argparse.Namespace) -> int:
    """Install *spec* at the chosen scope. Returns 0 on success, 1 on a known failure."""
    source = _spec_bundled_source(spec)
    target = _spec_target(spec, project=project)

    if target.exists() or target.is_symlink():
        if not args.force:
            _print_target_exists_error(target)
            return 1
        _remove_existing(target)

    if args.symlink:
        _install_symlink(source, target)
        kind = "symlinked"
    else:
        _install_copy(source, target)
        kind = "copied"

    scope = "project" if project else "user"
    _print_install_success(spec, target=target, kind=kind, scope=scope)
    return 0


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_install(args: argparse.Namespace) -> int:
    """Execute ``safelint skill install`` and return the aggregate exit code.

    Returns 0 on success across all installs, 1 if any install hits a
    known failure (e.g. target already exists without ``--force``) or
    if auto-detection finds no clients. Unexpected errors propagate.
    """
    plan = _resolve_install_plan(args)
    if plan is None:
        return 1
    notice, install_targets = plan
    _print_detection_notice(notice)

    overall_rc = 0
    for spec, project in install_targets:
        rc = _install_one(spec, project=project, args=args)
        if rc != 0:
            overall_rc = rc
    return overall_rc


def run_path(args: argparse.Namespace) -> int:
    """Execute ``safelint skill path`` — print the bundled-files location.

    Default prints the Claude skill bundle root (the cat-friendly
    single-line form). ``--client cursor`` prints the bundled MDC
    file path instead. ``auto`` is intentionally not a choice here —
    a single path is what callers expect from this command.
    """
    client = getattr(args, "client", "claude")
    spec = _spec_by_name(client)
    _print_bundled_path(_spec_bundled_source(spec))
    return 0


# ---------------------------------------------------------------------------
# Freshness / drift detection — compares bundled vs installed
# ---------------------------------------------------------------------------


# Status values returned by :func:`_install_status`.
INSTALL_STATUS_MISSING = "missing"  # target doesn't exist at this scope
INSTALL_STATUS_FRESH = "fresh"  # installed content matches bundle (or is a symlink)
INSTALL_STATUS_DIFFERS = "differs"  # installed content differs from current bundle


def _file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of *path*'s bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(root: Path) -> str:
    """Stable content hash of a directory tree, excluding peer-client subdirs.

    Walks ``root`` recursively in sorted order so the digest is
    deterministic across filesystems. Each contributing file's
    relative path is hashed alongside its content, so renames and
    same-name moves both invalidate. Entries under
    :data:`_PEER_CLIENT_DIRS` (e.g. ``cursor/``) are skipped — they
    don't ship in a Claude install and shouldn't influence its
    freshness verdict.
    """
    digest = hashlib.sha256()
    for entry in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        rel = entry.relative_to(root)
        if rel.parts and rel.parts[0] in _PEER_CLIENT_DIRS:
            continue
        if entry.is_file():
            digest.update(rel.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(entry.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _is_symlink_managed_directory(target: Path) -> bool:
    """Return True if *target* is a Claude-style symlink install.

    Claude ``--symlink`` installs are NOT symlinks at the target path
    itself — :func:`_install_symlink_directory_filtered` materialises
    *target* as a real directory and creates per-entry symlinks inside
    it (one for ``SKILL.md``, one for ``languages/``, etc.). For drift
    detection those installs should behave like a single symlink:
    always fresh, because the symlinks resolve straight back to the
    bundled location that ``pip upgrade safelint`` mutates in place.

    A directory qualifies when (a) it actually exists as a directory
    and (b) every relevant top-level entry (peer-client dirs excluded)
    is a working symlink. A broken inner symlink disqualifies the
    install — same fail-fast posture as the outer broken-symlink check
    in :func:`_install_status`.
    """
    if not target.is_dir():
        return False
    relevant_entries = [entry for entry in target.iterdir() if entry.name not in _PEER_CLIENT_DIRS]
    return bool(relevant_entries) and all(entry.is_symlink() and entry.exists() for entry in relevant_entries)


def _install_status(spec: ClientSpec, *, project: bool) -> str:
    """Return one of :data:`INSTALL_STATUS_MISSING` / ``_FRESH`` / ``_DIFFERS`` for *spec* at *scope*.

    A symlink install is reported as fresh only when its target exists
    — symlinks point at the live bundled location, so ``pip upgrade
    safelint`` reflects immediately. Two shapes of symlink install
    qualify: (a) the target itself is a symlink (Cursor's single-file
    install), or (b) the target is a real directory whose top-level
    entries are all working symlinks (Claude's per-entry install via
    :func:`_install_symlink_directory_filtered`). **Broken** symlinks
    don't qualify — a dangling install is unusable, not "current", and
    is reported as DIFFERS rather than MISSING so the status command
    surfaces it (MISSING is silently skipped). The single-file shape
    short-circuits to that handling explicitly; broken inner symlinks
    in the directory shape fall through to tree-hash comparison and
    naturally diverge from the bundle, also producing DIFFERS.

    For copy installs (the default), the bundled artefact and the
    on-disk install are content-hashed and compared.
    """
    target = _spec_target(spec, project=project)
    if target.is_symlink():
        return INSTALL_STATUS_FRESH if target.exists() else INSTALL_STATUS_DIFFERS
    if _is_symlink_managed_directory(target):
        return INSTALL_STATUS_FRESH
    if not target.exists():
        return INSTALL_STATUS_MISSING
    return _content_status(_spec_bundled_source(spec), target)


def _content_status(source: Path, target: Path) -> str:
    """Compare *source* and *target* by content; return FRESH or DIFFERS.

    Helper for :func:`_install_status`. Single-file sources are SHA-256
    compared; directory sources go through :func:`_tree_hash`. Caller
    has already confirmed *target* exists; this routine just verifies
    the shape matches and the bytes line up.
    """
    if source.is_file():
        if not target.is_file():
            return INSTALL_STATUS_DIFFERS
        return INSTALL_STATUS_FRESH if _file_sha256(source) == _file_sha256(target) else INSTALL_STATUS_DIFFERS
    if not target.is_dir():
        return INSTALL_STATUS_DIFFERS
    return INSTALL_STATUS_FRESH if _tree_hash(source) == _tree_hash(target) else INSTALL_STATUS_DIFFERS


def _refresh_command_for(spec: ClientSpec, *, project: bool) -> str:
    """Return the exact ``safelint skill install`` invocation that refreshes *spec* at *scope*.

    Auto-detect (``safelint skill install --force`` with no ``--client``)
    only refreshes the install corresponding to the cwd's auto-detected
    scope, so suggesting it for a multi-scope or non-detected drift
    leaves other stale installs untouched. The explicit form below
    pins both the client and the scope, regardless of cwd context:

    * project scope → ``safelint skill install --client <name> --force --project``
    * user scope    → ``safelint skill install --client <name> --force``

    Used both in the per-install line printed by ``run_status`` and in
    the per-warning string returned by :func:`stale_install_warnings`,
    so the remediation text is always actionable for the specific
    install that drifted.
    """
    base = f"safelint skill install --client {spec.name} --force"
    return f"{base} --project" if project else base


def _print_status_fresh(spec: ClientSpec, target: Path, scope: str) -> None:
    """Print a single "fresh" line to stdout."""
    print(f"safelint: {spec.display_name} {spec.artefact_label} at {target} ({scope} scope) — fresh")


def _print_status_differs(spec: ClientSpec, target: Path, scope: str, refresh_cmd: str) -> None:
    """Print a single "differs" line plus its scope-specific refresh hint."""
    print(f"safelint: {spec.display_name} {spec.artefact_label} at {target} ({scope} scope) — differs from bundled")
    print(f"  Refresh: {refresh_cmd}")


def _print_status_summary(*, any_drift: bool, any_install: bool) -> None:
    """Print the trailing summary line for ``safelint skill status``."""
    if not any_install:
        print("safelint: no AI-client skill installs detected. Run `safelint skill install` to install.")
        return
    if any_drift:
        print("safelint: one or more installs differ from the bundled version.")
        print("  Run the per-install refresh command above for each affected location.")
        print("  (If you've customised the file deliberately, ignore the diff.)")
        return
    print("safelint: all detected installs match the bundled version.")


def run_status(_args: argparse.Namespace) -> int:
    """Execute ``safelint skill status`` — report drift between bundled and installed skills.

    Iterates every registered :class:`ClientSpec` and both scopes
    (user, project). For each install location that exists, reports
    one of "fresh" or "differs" alongside the path. Returns 0 when
    every detected install is fresh (or no installs exist), 1 when
    any install differs from the bundled artefact. Pipe-friendly:
    use as ``safelint skill status || safelint skill install --force``.
    """
    any_drift = False
    any_install = False
    for spec, project in _iter_install_locations():
        status = _install_status(spec, project=project)
        if status == INSTALL_STATUS_MISSING:
            continue
        any_install = True
        target = _spec_target(spec, project=project)
        scope = "project" if project else "user"
        if status == INSTALL_STATUS_DIFFERS:
            any_drift = True
            _print_status_differs(spec, target, scope, _refresh_command_for(spec, project=project))
        else:
            _print_status_fresh(spec, target, scope)
    _print_status_summary(any_drift=any_drift, any_install=any_install)
    return 1 if any_drift else 0


def _iter_install_locations() -> Iterator[tuple[ClientSpec, bool]]:
    """Yield ``(spec, project)`` for every registered client xboth scopes.

    Centralises the nested loop so freshness / status helpers stay
    flat (one for-loop instead of two). Order: registry order with
    user-scope first, project-scope second.
    """
    for spec in _CLIENT_SPECS:
        for project in (False, True):
            yield spec, project


def stale_install_warnings() -> list[str]:
    """Return a list of human-readable warning strings, one per stale install location.

    Public helper — used by ``safelint check --check-skill-freshness``
    to surface drift via the diagnostics channel without changing the
    lint exit code. An empty list means every detected install is
    fresh (or no installs exist). Symlinks are always fresh by
    construction; missing locations don't produce a warning.
    """
    warnings: list[str] = []
    for spec, project in _iter_install_locations():
        if _install_status(spec, project=project) != INSTALL_STATUS_DIFFERS:
            continue
        target = _spec_target(spec, project=project)
        scope = "project" if project else "user"
        refresh_cmd = _refresh_command_for(spec, project=project)
        warnings.append(f"{spec.display_name} {spec.artefact_label} at {target} ({scope} scope) differs from bundled — run `{refresh_cmd}` to refresh (or ignore if you've customised it)")
    return warnings


# ---------------------------------------------------------------------------
# Update / remove — share install-path-based auto-detection (distinct from
# install's marker-file auto-detection: ``install`` asks "what AI client is
# the user using?", ``update`` / ``remove`` ask "what's actually installed?").
# ---------------------------------------------------------------------------


def _is_symlink_directory_shape(target: Path) -> bool:
    """Return True when *target* has the on-disk shape of a symlink install.

    This is intentionally a shape-only check for cleanup / filtering
    paths such as ``remove --symlink``: top-level entries count as
    symlinks even when their targets are missing. Freshness / validity
    is handled separately by :func:`_is_symlink_managed_directory`,
    which requires the inner symlinks to actually resolve.
    """
    if not target.is_dir():
        return False
    entries = list(target.iterdir())
    if not entries:
        return False
    return all(entry.is_symlink() for entry in entries)


def _install_is_symlink_shape(spec: ClientSpec, *, project: bool) -> bool:
    """Return True when the install at this scope was created in symlink mode.

    Two qualifying shapes: the target itself is a symlink (Cursor's
    single-file install), or the target is a real directory whose
    top-level entries are symlinks (Claude's per-entry install via
    :func:`_install_symlink_directory_filtered`). Broken symlinks still
    qualify here because this predicate is used for cleanup filtering,
    not freshness checks — ``remove --symlink`` must be able to clean
    up a Claude install whose bundled targets have moved or been
    deleted.
    """
    target = _spec_target(spec, project=project)
    if target.is_symlink():
        return True
    return _is_symlink_directory_shape(target)


def _detected_installed_clients(*, only_symlink: bool = False, project_only: bool = False) -> list[tuple[ClientSpec, bool]]:
    """Return [(spec, project)] for every existing install across the registry.

    Used by ``update`` / ``remove`` to answer "what's currently
    installed?" — distinct from :func:`_detected_clients` which scans
    marker files for "what AI client is the user using?". Iterates
    every spec across both scopes, includes locations whose
    ``_install_status`` is anything other than MISSING.

    *only_symlink* (default False): when True, filter to installs whose
    on-disk shape is symlink (used by ``remove --symlink`` to leave
    copy installs untouched).

    *project_only* (default False): when True, restrict to project-scope
    installs and skip user-scope ones. Used by ``update --project`` /
    ``remove --project`` so the ``--project`` flag's scope-restriction
    semantics apply equally to the auto-detect path. Without this,
    ``safelint skill update --project`` would silently process
    user-scope installs too, contradicting the CLI help.
    """
    detected: list[tuple[ClientSpec, bool]] = []
    for spec, project in _iter_install_locations():
        if project_only and not project:
            continue
        if _install_status(spec, project=project) == INSTALL_STATUS_MISSING:
            continue
        if only_symlink and not _install_is_symlink_shape(spec, project=project):
            continue
        detected.append((spec, project))
    return detected


# ---------------------------------------------------------------------------
# update — refresh stale installs (no-op when fresh, --force overrides)
# ---------------------------------------------------------------------------


def _print_update_no_installs() -> None:
    """No detected installs → tell the user how to install."""
    print("safelint: no AI-client skill installs detected. Run `safelint skill install` to install.")


def _print_update_all_fresh() -> None:
    """All detected installs are fresh → silent-friendly summary."""
    print("safelint: all detected installs are already up to date. Nothing to update.")


def _print_update_skipped_fresh(spec: ClientSpec, target: Path, scope: str) -> None:
    """Print the "skipped fresh install" notice emitted by ``update`` without ``--force``."""
    print(f"safelint: {spec.display_name} {spec.artefact_label} at {target} ({scope} scope) — already fresh, skipped")


def _update_one(spec: ClientSpec, *, project: bool, args: argparse.Namespace) -> int:
    """Refresh one install. No-op when fresh unless ``args.force``.

    Reads ``force`` and ``symlink`` via ``getattr`` so library callers
    that construct a partial ``Namespace`` (e.g. tests, programmatic
    invocations) don't trip ``AttributeError`` — matches the defensive
    pattern used by every other arg-reading helper in this module.
    """
    force = bool(getattr(args, "force", False))
    symlink = bool(getattr(args, "symlink", False))
    target = _spec_target(spec, project=project)
    scope = "project" if project else "user"
    status = _install_status(spec, project=project)
    if status == INSTALL_STATUS_FRESH and not force:
        _print_update_skipped_fresh(spec, target, scope)
        return 0
    install_args = argparse.Namespace(
        client=spec.name,
        project=project,
        symlink=symlink,
        force=True,
    )
    return _install_one(spec, project=project, args=install_args)


def _resolve_update_targets(args: argparse.Namespace) -> list[tuple[ClientSpec, bool]]:
    """Resolve which (spec, project) pairs ``run_update`` should refresh.

    Mirrors ``_resolve_remove_candidates``: ``--client auto`` consults
    install paths via ``_detected_installed_clients``; explicit
    ``--client X`` iterates both scopes by default and uses
    ``--project`` as an orthogonal restriction filter.
    """
    explicit_client = getattr(args, "client", "auto")
    project_flag = bool(getattr(args, "project", False))
    if explicit_client == "auto":
        return _detected_installed_clients(project_only=project_flag)
    spec = _spec_by_name(explicit_client)
    scopes = [True] if project_flag else [False, True]
    return [(spec, scope) for scope in scopes if _install_status(spec, project=scope) != INSTALL_STATUS_MISSING]


def run_update(args: argparse.Namespace) -> int:
    """Refresh installs whose content has drifted from the bundled wheel.

    Without ``--force``: idempotent — fresh installs are a silent
    no-op (skipped notice). With ``--force``: re-creates every detected
    install regardless of drift, useful for reverting customised
    installs back to bundled. Inherits ``--client``, ``--project``,
    and ``--symlink`` from install semantics; ``--client auto`` here
    detects via install paths (not marker files like ``install``).
    """
    force = bool(getattr(args, "force", False))
    targets = _resolve_update_targets(args)
    if not targets:
        _print_update_no_installs()
        return 0
    overall_rc = 0
    any_refreshed = False
    for spec, project in targets:
        if _install_status(spec, project=project) != INSTALL_STATUS_FRESH or force:
            any_refreshed = True
        rc = _update_one(spec, project=project, args=args)
        if rc != 0:
            overall_rc = rc
    if not any_refreshed and overall_rc == 0:
        _print_update_all_fresh()
    return overall_rc


# ---------------------------------------------------------------------------
# remove — delete detected installs (filterable by client / scope / shape)
# ---------------------------------------------------------------------------


def _print_remove_no_installs() -> None:
    """No installs match the filter → exit 0 with a helpful note."""
    print("safelint: no installed skill detected. Use `--path PATH` to specify an unusual install location.")


def _print_remove_path_missing(path: Path) -> None:
    """Print the "explicit path doesn't exist" error to stderr."""
    print(f"safelint: error: nothing to remove at {path}.", file=sys.stderr)


def _print_remove_dry_run(spec: ClientSpec | None, target: Path, scope: str | None, *, shape: str) -> None:
    """Print what *would* be removed under ``--dry-run``."""
    if spec is None:
        print(f"safelint: would remove ({shape}) at {target} (--path)")
        return
    print(f"safelint: would remove {spec.display_name} {spec.artefact_label} at {target} ({scope} scope; {shape})")


def _print_remove_success(spec: ClientSpec | None, target: Path, scope: str | None) -> None:
    """Print the "removed X" confirmation."""
    if spec is None:
        print(f"safelint: removed install at {target} (--path)")
        return
    print(f"safelint: {spec.display_name} {spec.artefact_label} removed from {target} ({scope} scope)")


def _shape_label(spec: ClientSpec, *, project: bool) -> str:
    """Return ``symlink`` or ``copy`` describing the install shape at this scope."""
    return "symlink" if _install_is_symlink_shape(spec, project=project) else "copy"


def _remove_one(spec: ClientSpec, *, project: bool, dry_run: bool) -> int:
    """Remove one detected install. Returns 0 on success."""
    target = _spec_target(spec, project=project)
    scope = "project" if project else "user"
    shape = _shape_label(spec, project=project)
    if dry_run:
        _print_remove_dry_run(spec, target, scope, shape=shape)
        return 0
    _remove_existing(target)
    _print_remove_success(spec, target, scope)
    return 0


def _remove_path(path: Path, *, dry_run: bool) -> int:
    """Remove an explicit ``--path`` target. Returns 0 on success, 1 if missing."""
    if not path.exists() and not path.is_symlink():
        _print_remove_path_missing(path)
        return 1
    shape = "symlink" if path.is_symlink() or _is_symlink_managed_directory(path) else "copy"
    if dry_run:
        _print_remove_dry_run(None, path, None, shape=shape)
        return 0
    _remove_existing(path)
    _print_remove_success(None, path, None)
    return 0


def _resolve_remove_candidates(args: argparse.Namespace) -> list[tuple[ClientSpec, bool]]:
    """Resolve which (spec, project) pairs ``run_remove`` should target."""
    explicit_client = getattr(args, "client", "auto")
    project_flag = bool(getattr(args, "project", False))
    only_symlink = bool(getattr(args, "symlink", False))
    if explicit_client == "auto":
        return _detected_installed_clients(only_symlink=only_symlink, project_only=project_flag)
    # Symmetric with auto-detect: ``--client X`` (no ``--project``)
    # considers every scope where X is installed; ``--project`` is
    # the orthogonal scope-restriction filter. The shape-and-existence
    # filter applies per-scope.
    spec = _spec_by_name(explicit_client)
    scopes = [True] if project_flag else [False, True]
    candidates: list[tuple[ClientSpec, bool]] = []
    for scope in scopes:
        if _install_status(spec, project=scope) == INSTALL_STATUS_MISSING:
            continue
        if only_symlink and not _install_is_symlink_shape(spec, project=scope):
            continue
        candidates.append((spec, scope))
    return candidates


def run_remove(args: argparse.Namespace) -> int:
    """Remove detected installs (or one explicit ``--path`` location).

    Auto-detect (``--client auto``, default) scans actual install
    paths — a different question from ``install``'s marker-based
    auto-detect. ``--symlink`` filters to symlink-shape installs only,
    leaving copy installs untouched. ``--path`` overrides every other
    flag and removes one specific location. ``--dry-run`` previews
    without deleting.
    """
    dry_run = bool(getattr(args, "dry_run", False))
    explicit_path = getattr(args, "path", None)
    if explicit_path is not None:
        return _remove_path(Path(explicit_path), dry_run=dry_run)
    candidates = _resolve_remove_candidates(args)
    if not candidates:
        _print_remove_no_installs()
        return 0
    overall_rc = 0
    for spec, project in candidates:
        rc = _remove_one(spec, project=project, dry_run=dry_run)
        if rc != 0:
            overall_rc = rc
    return overall_rc
