"""Command-line interface for safelint.

Two usage modes
---------------
Pre-commit hook (files passed by pre-commit as positional arguments)::

    safelint [--fail-on=error|warning] [--mode=local|ci] file1.py file2.py …

Direct invocation (default: git-modified files only when target is a directory)::

    safelint check <path> [--all-files] [--config <cfg>] [--fail-on=error|warning] [--mode=local|ci]

Severity model
--------------
Each rule carries per-rule severity (error | warning). The --fail-on threshold
controls which severity level blocks the run:

  --fail-on=error    → only error-severity violations block  (lenient - onboarding)
  --fail-on=warning  → error + warning violations block      (strict  - production)

Precedence: --fail-on CLI > fail_on in config (pyproject.toml or .safelint.yaml) > mode default.
"""

from __future__ import annotations

import argparse
import functools
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from safelint.core.config import MODE_FAIL_ON, SEVERITY_ORDER, load_config
from safelint.core.engine import SafetyEngine
from safelint.core.runner import run
from safelint.rules.base import Violation

_log = logging.getLogger(__name__)

# ── ANSI colour helpers ───────────────────────────────────────────────────────
# Colours are suppressed automatically when stdout is not a TTY (e.g. CI logs,
# pipe to file) so downstream tools always receive plain text.

_RED = "\033[31m"  # error codes
_YELLOW = "\033[33m"  # warning codes
_PURPLE = "\033[35m"  # --> arrow
_CYAN = "\033[36m"  # "help:" / "note:" labels
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _c(text: str, *codes: str) -> str:
    """Wrap *text* in ANSI *codes* when colour is enabled."""
    stream = getattr(sys, "stdout", None)
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty) or not isatty():
        return text
    return "".join(codes) + text + _RESET


@functools.lru_cache(maxsize=256)
def _source_lines(filepath: str) -> tuple[str, ...]:
    """Return the lines of *filepath* as a cached tuple (empty on read error)."""
    try:
        return tuple(Path(filepath).read_text(encoding="utf-8").splitlines())
    except OSError as exc:
        _log.debug("Could not read source lines for %s: %s", filepath, exc)
        return ()


def _print_violations(violations: list[Violation]) -> None:
    """Print violations in a ruff/ty-inspired multi-line coloured format."""
    for v in violations:
        tag = v.code if v.code else v.rule
        colour = _RED if v.severity == "error" else _YELLOW
        # First line: coloured CODE  message [rule]
        print(f"{_c(tag, _BOLD, colour)} {v.message} [{v.rule}]")
        # Second line: purple arrow + location
        print(f"   {_c('-->', _PURPLE)} {v.filepath}:{v.lineno}")
        # Source context: gutter (line number + pipe) in purple, content normal
        lines = _source_lines(v.filepath)
        if lines and 1 <= v.lineno <= len(lines):
            w = len(str(v.lineno))
            sep = _c(" " * w + " |", _PURPLE)
            num = _c(str(v.lineno).rjust(w) + " |", _PURPLE)
            print(f"   {sep}")
            print(f"   {num} {lines[v.lineno - 1].rstrip()}")
            print(f"   {sep}")
        print()  # blank line between violations for readability


def _print_summary(
    all_violations: list[Violation], n_blocking: int, fail_on: str, n_suppressed: int = 0
) -> None:
    """Print a ruff-style summary block to stdout."""
    found, fixes = _make_summary(all_violations, n_blocking, fail_on, n_suppressed)
    print(found)
    print(fixes)


def _print_status(message: str) -> None:
    """Print a status/informational message to stdout."""
    print(message)


def _severity_parts(violations: list[Violation]) -> list[str]:
    """Return coloured 'N error(s)' / 'N warning(s)' parts for *violations*.

    Any severity that is not explicitly ``"warning"`` is counted as an error,
    consistent with :meth:`~safelint.core.engine.SafetyEngine.partition_violations`
    which uses ``SEVERITY_ORDER.get(v.severity, 1)`` (default = error level).
    """
    n_warnings = sum(1 for v in violations if v.severity == "warning")
    n_errors = len(violations) - n_warnings
    parts: list[str] = []
    if n_errors:
        parts.append(f"{_c(str(n_errors), _BOLD, _RED)} error{'s' if n_errors != 1 else ''}")
    if n_warnings:
        parts.append(
            f"{_c(str(n_warnings), _BOLD, _YELLOW)} warning{'s' if n_warnings != 1 else ''}"
        )
    return parts


def _make_summary(
    all_violations: list[Violation], n_blocking: int, fail_on: str, n_suppressed: int = 0
) -> tuple[str, str]:
    """Return a (found_line, fixes_line) pair for *all_violations*."""
    suppressed_note = (
        f" ({_c(str(n_suppressed), _CYAN)} suppressed via # nosafe)" if n_suppressed else ""
    )
    fixes_line = f"No fixes available (safelint does not auto-fix violations).{suppressed_note}"
    if not all_violations:
        if n_suppressed:
            return f"All checks passed.{suppressed_note}", fixes_line
        return "All checks passed.", fixes_line
    parts = _severity_parts(all_violations)
    found = f"Found {', '.join(parts)}."
    fail_note = f" [--fail-on={fail_on}]"
    if not n_blocking:
        found = f"{found} Advisory only{fail_note}."
    else:
        found = f"{found}{fail_note}."
    return found, fixes_line


def _file_summary_line(filepath: str, violations: list[Violation]) -> str:
    """Return a coloured per-file count line: 'path/file.py — 1 error, 3 warnings.'

    Raises:
        ValueError: If *violations* is empty.
    """
    if not violations:
        raise ValueError("violations must be non-empty")
    return f"{filepath} \u2014 {', '.join(_severity_parts(violations))}."


def _resolve_fail_on(args: argparse.Namespace, config: dict) -> tuple[str, int]:
    """Return (fail_on label, integer threshold) from CLI args and config."""
    mode: str = getattr(args, "mode", None) or config.get("mode", "local")
    mode_default: str = MODE_FAIL_ON.get(mode, "error")
    fail_on: str = getattr(args, "fail_on", None) or config.get("fail_on", mode_default)
    return fail_on, SEVERITY_ORDER.get(fail_on, 1)


def _run_hook(args: argparse.Namespace, files: list[str]) -> int:
    """Execute pre-commit hook mode against an explicit list of .py files."""
    if not files:
        return 0

    config = load_config()
    fail_on, fail_threshold = _resolve_fail_on(args, config)
    engine = SafetyEngine(config, changed_files=files)

    all_blocking: list[Violation] = []
    all_violations: list[Violation] = []
    n_suppressed = 0

    for filepath in files:
        result = engine.check_file(filepath)
        n_suppressed += result.suppressed
        if not result.violations:
            continue
        _print_violations(result.violations)
        blocking, _ = engine.partition_violations(result.violations, fail_threshold)
        print(_file_summary_line(filepath, result.violations))
        print()
        all_blocking.extend(blocking)
        all_violations.extend(result.violations)

    _print_summary(all_violations, len(all_blocking), fail_on, n_suppressed)
    return 1 if all_blocking else 0


def _is_under_target(abs_path: Path, target_abs: Path) -> bool:
    """Return True when *abs_path* is inside *target_abs* (dir) or equals it (file)."""
    if target_abs.is_dir():
        try:
            abs_path.relative_to(target_abs)
            return True
        except ValueError:
            _log.debug("Path %s is not relative to %s", abs_path, target_abs)
            return False
    return abs_path == target_abs


def _normalize_path(abs_path: Path, cwd: Path) -> str:
    """Return *abs_path* relative to *cwd*, or as an absolute string if outside *cwd*."""
    try:
        return str(abs_path.relative_to(cwd))
    except ValueError:
        _log.debug("Path %s is not relative to cwd %s; using absolute path", abs_path, cwd)
        return str(abs_path)


def _collect_all_py_files(raw: set[str], git_root: Path) -> list[str]:
    """Return paths for all existing .py files in *raw* (no target filter).

    Paths are relative to cwd when possible, otherwise absolute.
    """
    cwd = Path.cwd()
    results: list[str] = []
    for rel in raw:
        if not rel.endswith(".py"):
            continue
        abs_path = (git_root / rel).resolve()
        if abs_path.exists():
            results.append(_normalize_path(abs_path, cwd))
    return sorted(results)


def _filter_py_files(raw: set[str], git_root: Path, target_abs: Path) -> list[str]:
    """Filter git-relative paths to existing .py files under *target_abs*.

    Returned paths are relative to cwd when possible, which keeps diagnostic
    output (``file:line:``) free of Windows drive-letter colons in the common
    case; absolute paths are used as a fallback for files outside cwd.
    """
    cwd = Path.cwd()
    results: list[str] = []
    for rel in raw:
        if not rel.endswith(".py"):
            continue
        abs_path = (git_root / rel).resolve()
        if abs_path.exists() and _is_under_target(abs_path, target_abs):
            results.append(_normalize_path(abs_path, cwd))
    return sorted(results)


def _get_raw_changed_files(git_bin: str, git_root: Path) -> set[str] | None:
    """Run git diff + ls-files and return the union of all changed paths, or None on error."""
    diff_proc = subprocess.run(
        [git_bin, "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=10,
    )
    cached_proc = subprocess.run(
        [git_bin, "diff", "--name-only", "--cached"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=10,
    )
    untracked_proc = subprocess.run(
        [git_bin, "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=10,
    )
    if diff_proc.returncode != 0 or cached_proc.returncode != 0 or untracked_proc.returncode != 0:
        _log.debug(
            "git command failed (diff rc=%s, cached rc=%s, untracked rc=%s); "
            "treating as git unavailable",
            diff_proc.returncode,
            cached_proc.returncode,
            untracked_proc.returncode,
        )
        return None
    return (
        set(diff_proc.stdout.splitlines())
        | set(cached_proc.stdout.splitlines())
        | set(untracked_proc.stdout.splitlines())
    )


def _get_git_modified_python_files(target: Path) -> tuple[list[str], list[str]] | None:
    """Return a 2-tuple of changed .py file lists, or ``None`` on git failure.

    Includes staged, unstaged, and untracked files.

    Returns ``(all_changed_py, in_target_py)`` where:

    * *all_changed_py* — every changed .py file across the whole repo.
      Paths are relative to cwd when possible, otherwise absolute.
      Passed to :class:`~safelint.core.engine.SafetyEngine` as ``changed_files``
      so cross-file rules (e.g. ``test_coupling``) see the full diff context.
    * *in_target_py* — the subset of those files that fall under *target*.
      Same path format as *all_changed_py*. These are the files actually linted.

    Returns ``None`` when git is unavailable, the path is outside a git
    repository, or any git command fails — callers should fall back to
    scanning all files.
    """
    try:
        git_bin = shutil.which("git")
        if not git_bin:
            _log.debug("git executable not found on PATH")
            return None

        target_abs = target.resolve()
        work_dir = target_abs if target_abs.is_dir() else target_abs.parent

        root_proc = subprocess.run(
            [git_bin, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=10,
        )
        if root_proc.returncode != 0:
            return None
        git_root = Path(root_proc.stdout.strip())

        raw = _get_raw_changed_files(git_bin, git_root)
        if raw is None:
            return None
        return _collect_all_py_files(raw, git_root), _filter_py_files(raw, git_root, target_abs)

    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        _log.debug("git unavailable or not a repo: %s", exc)
        return None


def _config_dir(config_path: Path | None, target: Path) -> Path:
    """Return the directory to use as the config search root."""
    if config_path:
        return config_path if config_path.is_dir() else config_path.parent
    return target if target.is_dir() else target.parent


def _run_check(args: argparse.Namespace) -> int:
    """Execute directory/file scan mode."""
    config_path = getattr(args, "config", None)
    all_files: bool = getattr(args, "all_files", False)
    target = Path(args.target)

    files: list[str] | None = None
    changed_files: list[str] | None = None
    if not all_files and target.is_dir():
        modified = _get_git_modified_python_files(target)
        if modified is None:
            _print_status("Note: could not determine modified files via git — scanning all files.")
        elif not modified[1]:
            _print_status("No modified Python files detected. Use --all-files to scan everything.")
            return 0
        else:
            changed_files, files = modified

    results = run(target, config_path=config_path, files=files, changed_files=changed_files)

    config = load_config(_config_dir(Path(config_path) if config_path else None, target))
    fail_on, fail_threshold = _resolve_fail_on(args, config)

    all_blocking: list[Violation] = []
    all_violations: list[Violation] = []
    n_suppressed = 0

    for result in results:
        n_suppressed += result.suppressed
        if not result.violations:
            continue
        _print_violations(result.violations)
        blocking, _ = SafetyEngine.partition_violations(result.violations, fail_threshold)
        print(_file_summary_line(result.path, result.violations))
        print()
        all_blocking.extend(blocking)
        all_violations.extend(result.violations)

    _print_summary(all_violations, len(all_blocking), fail_on, n_suppressed)
    return 1 if all_blocking else 0


def _build_common_args(parser: argparse.ArgumentParser) -> None:
    """Add --fail-on and --mode to *parser*."""
    parser.add_argument(
        "--fail-on",
        dest="fail_on",
        choices=["error", "warning"],
        default=None,
        help="Minimum severity that blocks the run (overrides configured fail_on)",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "ci"],
        default=None,
        help="Execution mode: local (fail_on=error) | ci (fail_on=warning)",
    )


def main() -> None:
    """Entry point for both pre-commit hook and direct CLI invocation.

    Routing logic:
    - If the first non-flag argument is ``check``, use the ``check`` subcommand.
    - Otherwise, treat all ``.py`` positional arguments as files (pre-commit mode).
    """
    non_flag = [a for a in sys.argv[1:] if not a.startswith("-")]

    if non_flag and non_flag[0] == "check":
        # ── Direct / CI scan mode ─────────────────────────────────────────
        parser = argparse.ArgumentParser(
            prog="safelint check",
            description="Scan a file or directory for safety violations",
        )
        parser.add_argument("target", type=Path, help="File or directory to scan")
        parser.add_argument(
            "--config",
            type=Path,
            default=None,
            help=(
                "Directory to use as the config discovery root, or a file whose parent"
                " directory is used as the root (pyproject.toml takes precedence over"
                " .safelint.yaml when both exist)"
            ),
        )
        parser.add_argument(
            "--all-files",
            dest="all_files",
            action="store_true",
            default=False,
            help="Scan all Python files under target (default: git-modified files only)",
        )
        _build_common_args(parser)
        args = parser.parse_args(sys.argv[2:])  # skip 'check'
        sys.exit(_run_check(args))

    else:
        # ── Pre-commit hook mode ──────────────────────────────────────────
        parser = argparse.ArgumentParser(
            prog="safelint",
            description="AI Safety pre-commit hook (Holzmann rules)",
        )
        _build_common_args(parser)
        args, remaining = parser.parse_known_args()
        files = [f for f in remaining if f.endswith(".py")]
        sys.exit(_run_hook(args, files))


if __name__ == "__main__":
    main()
