"""Command-line interface for safelint.

Two usage modes
---------------
Pre-commit hook (files passed by pre-commit as positional arguments)::

    safelint [--fail-on=error|warning] [--mode=local|ci] file1.py file2.py …

Direct invocation (default: git-modified files only)::

    safelint check <path> [--all-files] [--config <cfg>] [--fail-on=error|warning] [--mode=local|ci]

Severity model
--------------
Each rule carries per-rule severity (error | warning). The --fail-on threshold
controls which severity level blocks the run:

  --fail-on=error    → only error-severity violations block  (lenient - onboarding)
  --fail-on=warning  → error + warning violations block      (strict  - production)

Precedence: --fail-on CLI > fail_on in .safelint.yaml > mode default.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from safelint.core.config import MODE_FAIL_ON, SEVERITY_ORDER, load_config
from safelint.core.engine import SafetyEngine
from safelint.core.runner import run
from safelint.rules.base import Violation

logger = logging.getLogger(__name__)


def _print_violations(violations: list[Violation]) -> None:
    """Print violations one per line in ruff-style format: file:line: CODE message  [rule]"""
    for v in violations:
        tag = v.code if v.code else v.rule
        print(f"{v.filepath}:{v.lineno}: {tag} {v.message}  [{v.rule}]")


def _print_summary(all_violations: list[Violation], n_blocking: int, fail_on: str) -> None:
    """Print a ruff-style summary line to stdout."""
    print(_make_summary(all_violations, n_blocking, fail_on))


def _print_status(message: str) -> None:
    """Print a status/informational message to stdout."""
    print(message)


def _make_summary(all_violations: list[Violation], n_blocking: int, fail_on: str) -> str:
    """Return a ruff-style summary line for *all_violations*."""
    if not all_violations:
        return "All checks passed."
    n_errors = sum(1 for v in all_violations if v.severity == "error")
    n_warnings = sum(1 for v in all_violations if v.severity == "warning")
    parts = []
    if n_errors:
        parts.append(f"{n_errors} error{'s' if n_errors != 1 else ''}")
    if n_warnings:
        parts.append(f"{n_warnings} warning{'s' if n_warnings != 1 else ''}")
    found = f"Found {', '.join(parts)}."
    if n_blocking:
        return f"{found} [--fail-on={fail_on}]"
    return f"{found} Advisory only [--fail-on={fail_on}]."


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
    all_advisory: list[Violation] = []

    all_violations: list[Violation] = []
    for filepath in files:
        violations = engine.check_file(filepath)
        if not violations:
            continue
        _print_violations(violations)
        blocking, advisory = engine.partition_violations(violations, fail_threshold)
        all_blocking.extend(blocking)
        all_advisory.extend(advisory)
        all_violations.extend(violations)

    _print_summary(all_violations, len(all_blocking), fail_on)
    return 1 if all_blocking else 0


def _is_under_target(abs_path: Path, target_abs: Path) -> bool:
    """Return True when *abs_path* is inside *target_abs* (dir) or equals it (file)."""
    if target_abs.is_dir():
        try:
            abs_path.relative_to(target_abs)
            return True
        except ValueError:
            logger.debug("Path %s is not relative to %s", abs_path, target_abs)
            return False
    return abs_path == target_abs


def _filter_py_files(raw: set[str], git_root: Path, target_abs: Path) -> list[str]:
    """Filter git-relative paths to existing .py files under *target_abs*."""
    results: list[str] = []
    for rel in raw:
        if not rel.endswith(".py"):
            continue
        abs_path = (git_root / rel).resolve()
        if abs_path.exists() and _is_under_target(abs_path, target_abs):
            results.append(str(abs_path))
    return sorted(results)


def _get_git_modified_python_files(target: Path) -> list[str] | None:
    """Return modified/added .py paths under *target* according to git.

    Combines staged and unstaged changes vs HEAD.  Returns ``None`` when git
    is unavailable or the path is not inside a git repository — callers should
    fall back to scanning all files.
    """
    try:
        target_abs = target.resolve()
        work_dir = target_abs if target_abs.is_dir() else target_abs.parent

        root_proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=work_dir,
        )
        if root_proc.returncode != 0:
            return None
        git_root = Path(root_proc.stdout.strip())

        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            cwd=git_root,
        )
        cached_proc = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True,
            text=True,
            cwd=git_root,
        )
        if diff_proc.returncode != 0 or cached_proc.returncode != 0:
            logger.debug(
                "git diff command failed (diff rc=%s, cached rc=%s); treating as git unavailable",
                diff_proc.returncode,
                cached_proc.returncode,
            )
            return None

        raw = set(diff_proc.stdout.splitlines()) | set(cached_proc.stdout.splitlines())
        return _filter_py_files(raw, git_root, target_abs)

    except (FileNotFoundError, OSError) as exc:
        logger.debug("git unavailable or not a repo: %s", exc)
        return None


def _run_check(args: argparse.Namespace) -> int:
    """Execute directory/file scan mode."""
    config_path = getattr(args, "config", None)
    all_files: bool = getattr(args, "all_files", False)
    target = Path(args.target)

    files: list[str] | None = None
    if not all_files:
        modified = _get_git_modified_python_files(target)
        if modified is None:
            _print_status("Note: git unavailable — scanning all files.")
        elif not modified:
            _print_status("No modified Python files detected. Use --all-files to scan everything.")
            return 0
        else:
            files = modified

    results = run(target, config_path=config_path, files=files)

    config = load_config(Path(config_path).parent if config_path else Path(args.target))
    fail_on, fail_threshold = _resolve_fail_on(args, config)

    # Reuse engine's partition helper
    dummy_engine = SafetyEngine.__new__(SafetyEngine)
    dummy_engine.exclude_paths = []

    all_blocking: list[Violation] = []
    all_advisory: list[Violation] = []

    all_violations: list[Violation] = []
    for result in results:
        if not result.violations:
            continue
        _print_violations(result.violations)
        blocking, advisory = dummy_engine.partition_violations(result.violations, fail_threshold)
        all_blocking.extend(blocking)
        all_advisory.extend(advisory)
        all_violations.extend(result.violations)

    _print_summary(all_violations, len(all_blocking), fail_on)
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
            help="Path to a .safelint.yaml config file (overrides automatic discovery)",
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
