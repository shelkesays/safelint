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

Precedence: --fail-on CLI > fail_on in config (safelint.toml or pyproject.toml) > mode default.
"""

from __future__ import annotations

import argparse
from collections import Counter
import functools
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from safelint.core._cache import LintCache
from safelint.core.config import MODE_FAIL_ON, SEVERITY_ORDER, load_config
from safelint.core.engine import SafetyEngine
from safelint.core.runner import resolve_cache_dir, run
from safelint.formatters import format_json, format_sarif


if TYPE_CHECKING:
    from safelint.rules.base import Violation


# ── ANSI colour helpers ───────────────────────────────────────────────────────
# Colours are suppressed automatically when stdout is not a TTY (e.g. CI logs,
# pipe to file) so downstream tools always receive plain text.

_RED = "\033[31m"  # error codes
_GREEN = "\033[32m"  # all-clear summary
_YELLOW = "\033[33m"  # warning codes
_PURPLE = "\033[35m"  # --> arrow
_CYAN = "\033[36m"  # "help:" / "note:" labels
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _is_error(severity: str) -> bool:
    """Return True when *severity* should be treated as an error.

    Any severity that is not explicitly ``"warning"`` is an error, matching
    the behaviour of :meth:`~safelint.core.engine.SafetyEngine.partition_violations`
    which uses ``SEVERITY_ORDER.get(v.severity, 1)`` (default = error level).
    """
    return severity != "warning"


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
    # Best-effort source context for the violation gutter; an empty tuple
    # makes the renderer omit the source preview, which is acceptable.
    except OSError:  # nosafe: SAFE203
        return ()


def _print_violations(violations: list[Violation]) -> None:
    """Print violations in a ruff/ty-inspired multi-line coloured format."""
    for v in violations:
        tag = v.code or v.rule
        colour = _RED if _is_error(v.severity) else _YELLOW
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
    all_violations: list[Violation],
    n_blocking: int,
    fail_on: str,
    suppressed: list[Violation] | None = None,
) -> None:
    """Print a ruff-style summary block to stdout."""
    found, fixes = _make_summary(all_violations, n_blocking, fail_on, suppressed or [])
    print(found)
    if fixes is not None:
        print(fixes)


def _print_status(message: str, *, output_format: str = "pretty") -> None:
    """Print a status/informational message.

    In ``pretty`` mode the message goes to stdout where the user expects
    it (it's part of the human-readable run summary). In ``json`` /
    ``sarif`` mode stdout must remain a single, parseable document — so
    status text is redirected to stderr where tools that capture only
    stdout won't be tripped up.
    """
    stream = sys.stdout if output_format == "pretty" else sys.stderr
    print(message, file=stream)


def _severity_parts(violations: list[Violation]) -> list[str]:
    """Return coloured 'N error(s)' / 'N warning(s)' parts for *violations*."""
    n_warnings = sum(1 for v in violations if not _is_error(v.severity))
    n_errors = len(violations) - n_warnings
    parts: list[str] = []
    if n_errors:
        parts.append(f"{_c(str(n_errors), _BOLD, _RED)} error{'s' if n_errors != 1 else ''}")
    if n_warnings:
        parts.append(f"{_c(str(n_warnings), _BOLD, _YELLOW)} warning{'s' if n_warnings != 1 else ''}")
    return parts


def _format_suppressed_breakdown(suppressed: list[Violation]) -> str:
    """Return ``"2 SAFE501, 1 SAFE304 suppressed"`` for the given violations.

    Codes are sorted by descending count, ties broken alphabetically so the
    output is deterministic across runs. Returns an empty string when there
    are no suppressions. Falls back to the rule name when ``code`` is empty,
    matching the tag convention in ``_print_violations``.
    """
    if not suppressed:
        return ""
    counts = Counter(v.code or v.rule for v in suppressed)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = [f"{n} {_c(tag, _CYAN)}" for tag, n in ordered]
    return f"{', '.join(parts)} suppressed"


def _make_summary(
    all_violations: list[Violation],
    n_blocking: int,
    fail_on: str,
    suppressed: list[Violation] | None = None,
) -> tuple[str, str | None]:
    """Return a (found_line, fixes_line) pair for *all_violations*.

    ``fixes_line`` is ``None`` on a clean run (no active violations) so the
    caller can skip printing the no-fixes notice when there is nothing to
    fix — even if some violations were suppressed. The suppression breakdown
    is rolled into the all-clear line in that case.
    """
    suppressed = suppressed or []
    breakdown = _format_suppressed_breakdown(suppressed)
    suppressed_note = f" ({breakdown})" if breakdown else ""
    if not all_violations:
        all_clear = _c("All checks passed.", _BOLD, _GREEN)
        return f"{all_clear}{suppressed_note}", None
    parts = _severity_parts(all_violations)
    found = f"Found {', '.join(parts)}."
    fail_note = f" [--fail-on={fail_on}]"
    found = f"{found} Advisory only{fail_note}." if not n_blocking else f"{found}{fail_note}."
    fixes_line = f"No fixes available (safelint does not auto-fix violations).{suppressed_note}"
    return found, fixes_line


def _file_summary_line(filepath: str, violations: list[Violation]) -> str:
    """Return a coloured per-file count line: 'path/file.py — 1 error, 3 warnings.'.

    Raises:
        ValueError: If *violations* is empty.

    """
    if not violations:
        msg = "violations must be non-empty"
        raise ValueError(msg)
    return f"{filepath} \u2014 {', '.join(_severity_parts(violations))}."


def _print_file_summary(filepath: str, violations: list[Violation]) -> None:
    """Print the per-file summary line followed by a blank separator line."""
    print(_file_summary_line(filepath, violations))
    print()


def _print_results(
    output_format: str,
    violations: list[Violation],
    suppressed: list[Violation],
    *,
    blocking_count: int,
    fail_on: str,
    files_checked: int,
    silent_on_clean: bool = False,
) -> None:
    """Emit accumulated lint results in the chosen format.

    For ``pretty`` (default), prints the ruff/ty-style summary block; the
    per-file violations were already streamed during the run. For ``json``
    and ``sarif``, prints a single machine-readable document on stdout
    that contains both the violation list and the summary.

    *silent_on_clean* — when True, pretty mode emits nothing on a clean
    run (no violations and no suppressed entries). Hook mode and stdin
    mode set this so a clean pre-commit run is silent (the long-standing
    ruff/ty contract); ``safelint check`` leaves it False so the user
    gets explicit ``All checks passed.`` confirmation.

    Stderr diagnostics (configuration warnings, oversize-skip messages)
    are unaffected — they are always written as they are produced,
    regardless of format.
    """
    if output_format == "pretty":
        if violations or suppressed or not silent_on_clean:
            _print_summary(violations, blocking_count, fail_on, suppressed)
        return
    if output_format == "json":
        print(
            format_json(
                violations,
                suppressed,
                blocking_count=blocking_count,
                fail_on=fail_on,
                files_checked=files_checked,
            )
        )
        return
    if output_format == "sarif":
        print(
            format_sarif(
                violations,
                suppressed,
                blocking_count=blocking_count,
                fail_on=fail_on,
                files_checked=files_checked,
            )
        )
        return


def _resolve_fail_on(args: argparse.Namespace, config: dict) -> tuple[str, int]:
    """Return (fail_on label, integer threshold) from CLI args and config."""
    mode: str = getattr(args, "mode", None) or config.get("mode", "local")
    mode_default: str = MODE_FAIL_ON.get(mode, "error")
    fail_on: str = getattr(args, "fail_on", None) or config.get("fail_on", mode_default)
    return fail_on, SEVERITY_ORDER.get(fail_on, 1)


def _run_stdin(args: argparse.Namespace) -> int:
    """Read source from stdin and lint it as if it were *--stdin-filename*.

    Engineered for editor integrations: VSCode / Claude Code want to lint
    un-saved buffer contents without round-tripping through a temp file
    (temp files are slow on every keystroke and miss ``# nosafe`` directives
    that aren't yet on disk). The pseudo-filename drives language
    detection (by extension) and shows up as the violation file path.
    """
    config = load_config()
    cli_ignore = args.ignore or []
    if cli_ignore:
        existing = config.get("ignore", [])
        config["ignore"] = list(dict.fromkeys(existing + cli_ignore))
    fail_on, fail_threshold = _resolve_fail_on(args, config)
    # Stdin mode deliberately bypasses the on-disk cache: every keystroke
    # in an editor produces a slightly different buffer (cache miss
    # every time anyway) and writing to ``.safelint_cache/`` per keystroke
    # would just churn the project tree. ``--no-cache`` is therefore
    # irrelevant here — caching is unconditionally off.
    engine = SafetyEngine(config, changed_files=[args.stdin_filename], cache=None)

    source = sys.stdin.read()
    result = engine.check_source(args.stdin_filename, source)

    output_format: str = getattr(args, "output_format", "pretty")
    if output_format == "pretty" and result.violations:
        _print_violations(result.violations)
        _print_file_summary(args.stdin_filename, result.violations)
    blocking, _ = SafetyEngine.partition_violations(result.violations, fail_threshold)
    _print_results(
        output_format,
        result.violations,
        result.suppressed,
        blocking_count=len(blocking),
        fail_on=fail_on,
        files_checked=1,
        silent_on_clean=True,
    )
    return 1 if blocking else 0


def _run_hook(args: argparse.Namespace, files: list[str]) -> int:
    """Execute pre-commit hook mode against an explicit list of .py files."""
    if not files:
        return 0

    config = load_config()
    cli_ignore = args.ignore or []
    if cli_ignore:
        existing = config.get("ignore", [])
        config["ignore"] = list(dict.fromkeys(existing + cli_ignore))
    fail_on, fail_threshold = _resolve_fail_on(args, config)
    no_cache = getattr(args, "no_cache", False)
    # Resolve the cache directory the same way ``check`` mode does: walk
    # up from cwd to the discovered config root so a single project never
    # ends up with multiple ``.safelint_cache/`` directories scattered
    # across subdirectories pre-commit happened to fire from.
    cache_dir = resolve_cache_dir(Path.cwd(), no_cache=no_cache)
    engine = SafetyEngine(config, changed_files=files, cache=LintCache(cache_dir))

    output_format: str = getattr(args, "output_format", "pretty")
    all_blocking: list[Violation] = []
    all_violations: list[Violation] = []
    all_suppressed: list[Violation] = []

    for filepath in files:
        result = engine.check_file(filepath)
        all_suppressed.extend(result.suppressed)
        if not result.violations:
            continue
        # Stream per-file pretty output as we go; non-pretty formats emit
        # one consolidated document at the end (in ``_print_results``).
        if output_format == "pretty":
            _print_violations(result.violations)
            _print_file_summary(filepath, result.violations)
        blocking, _ = engine.partition_violations(result.violations, fail_threshold)
        all_blocking.extend(blocking)
        all_violations.extend(result.violations)

    _print_results(
        output_format,
        all_violations,
        all_suppressed,
        blocking_count=len(all_blocking),
        fail_on=fail_on,
        files_checked=len(files),
        silent_on_clean=True,
    )
    return 1 if all_blocking else 0


def _is_under_target(abs_path: Path, target_abs: Path) -> bool:
    """Return True when *abs_path* is inside *target_abs* (dir) or equals it (file)."""
    if target_abs.is_dir():
        try:
            abs_path.relative_to(target_abs)
        # ``relative_to`` raising ValueError means "not under" — that's the
        # answer this predicate exists to compute, not an error to log.
        except ValueError:  # nosafe: SAFE203
            return False
        else:
            return True
    return abs_path == target_abs


def _normalize_path(abs_path: Path, cwd: Path) -> str:
    """Return *abs_path* relative to *cwd*, or as an absolute string if outside *cwd*."""
    try:
        return str(abs_path.relative_to(cwd))
    # ValueError means the path is outside cwd; falling back to the absolute
    # form is the documented behaviour, not an error.
    except ValueError:  # nosafe: SAFE203
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
    diff_proc = subprocess.run(  # noqa: S603
        [git_bin, "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=10,
        check=False,
    )
    cached_proc = subprocess.run(  # noqa: S603
        [git_bin, "diff", "--name-only", "--cached"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=10,
        check=False,
    )
    untracked_proc = subprocess.run(  # noqa: S603
        [git_bin, "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=git_root,
        timeout=10,
        check=False,
    )
    if diff_proc.returncode != 0 or cached_proc.returncode != 0 or untracked_proc.returncode != 0:
        return None
    return set(diff_proc.stdout.splitlines()) | set(cached_proc.stdout.splitlines()) | set(untracked_proc.stdout.splitlines())


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
            return None

        target_abs = target.resolve()
        work_dir = target_abs if target_abs.is_dir() else target_abs.parent

        root_proc = subprocess.run(  # noqa: S603
            [git_bin, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=10,
            check=False,
        )
        if root_proc.returncode != 0:
            return None
        git_root = Path(root_proc.stdout.strip())

        raw = _get_raw_changed_files(git_bin, git_root)
        if raw is None:
            return None
        return _collect_all_py_files(raw, git_root), _filter_py_files(raw, git_root, target_abs)

    # Any git-side failure (no git, not a repo, timeout) means we fall back
    # to scanning all files — that's a documented behaviour, not an error.
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):  # nosafe: SAFE203
        return None


def _config_dir(config_path: Path | None, target: Path) -> Path:
    """Return the directory to use as the config search root."""
    if config_path:
        return config_path if config_path.is_dir() else config_path.parent
    return target if target.is_dir() else target.parent


def _resolve_check_targets(args: argparse.Namespace, target: Path, output_format: str) -> tuple[list[str] | None, list[str] | None, bool]:
    """Resolve the (changed_files, files, no_targets) tuple for ``check`` mode.

    Returns a 3-tuple:

    * ``changed_files`` — the full repo-wide diff list passed to the engine
      so cross-file rules see the right context, or None to skip that hint.
    * ``files`` — the explicit list of files to lint (a subset of *target*
      that's been git-modified), or None to fall back to directory discovery.
    * ``no_targets`` — True when git reported no modified files under
      *target* and the caller should short-circuit with an empty result.
    """
    if getattr(args, "all_files", False) or not target.is_dir():
        return None, None, False
    modified = _get_git_modified_python_files(target)
    if modified is None:
        _print_status(
            "Note: could not determine modified files via git — scanning all files.",
            output_format=output_format,
        )
        return None, None, False
    if not modified[1]:
        _print_status(
            "No modified Python files detected. Use --all-files to scan everything.",
            output_format=output_format,
        )
        return None, None, True
    changed_files, files = modified
    return changed_files, files, False


def _run_check(args: argparse.Namespace) -> int:
    """Execute directory/file scan mode."""
    config_path = getattr(args, "config", None)
    target = Path(args.target)
    output_format: str = getattr(args, "output_format", "pretty")

    changed_files, files, no_targets = _resolve_check_targets(args, target, output_format)
    config = load_config(_config_dir(Path(config_path) if config_path else None, target))
    fail_on, fail_threshold = _resolve_fail_on(args, config)

    if no_targets:
        # Machine modes still need a parseable empty document on stdout
        # so downstream tools (CI uploaders, SARIF consumers) don't choke
        # on empty input. Pretty mode already emitted the human-readable
        # status above and exits 0 silently.
        _print_results(output_format, [], [], blocking_count=0, fail_on=fail_on, files_checked=0, silent_on_clean=True)
        return 0

    results = run(
        target,
        config_path=config_path,
        files=files,
        changed_files=changed_files,
        ignore=args.ignore,
        no_cache=getattr(args, "no_cache", False),
    )

    all_blocking: list[Violation] = []
    all_violations: list[Violation] = []
    all_suppressed: list[Violation] = []

    for result in results:
        all_suppressed.extend(result.suppressed)
        if not result.violations:
            continue
        if output_format == "pretty":
            _print_violations(result.violations)
            _print_file_summary(result.path, result.violations)
        blocking, _ = SafetyEngine.partition_violations(result.violations, fail_threshold)
        all_blocking.extend(blocking)
        all_violations.extend(result.violations)

    _print_results(output_format, all_violations, all_suppressed, blocking_count=len(all_blocking), fail_on=fail_on, files_checked=len(results))
    return 1 if all_blocking else 0


def _add_severity_args(parser: argparse.ArgumentParser) -> None:
    """Add --fail-on, --mode, --ignore: control which violations block."""
    parser.add_argument("--fail-on", dest="fail_on", choices=["error", "warning"], default=None, help="Minimum severity that blocks the run (overrides configured fail_on)")
    parser.add_argument("--mode", choices=["local", "ci"], default=None, help="Execution mode: local (fail_on=error) | ci (fail_on=warning)")
    parser.add_argument("--ignore", action="append", default=None, metavar="CODE", help="Repeatable flag to ignore a rule code or name, e.g. --ignore SAFE101 --ignore function_length")


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    """Add --format and --no-cache: how output is emitted and cached."""
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["pretty", "json", "sarif"],
        default="pretty",
        help=(
            "Output format. 'pretty' (default) writes the ruff/ty-style "
            "multi-line coloured violations + summary to stdout. 'json' "
            "and 'sarif' emit machine-readable documents for tooling "
            "consumers (editor plugins, CI scanners, the Claude Code "
            "skill / VSCode plugin). Stderr diagnostics are unaffected."
        ),
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        default=False,
        help=(
            "Disable the per-file lint-result cache. By default safelint "
            "memoises rule output keyed on sha256(source + engine config + filepath) "
            "in a ``.safelint_cache/`` directory next to the config file, "
            "so re-runs on unchanged files are essentially instant."
        ),
    )


def _add_stdin_args(parser: argparse.ArgumentParser) -> None:
    """Add --stdin and --stdin-filename: read source from stdin (editor mode)."""
    parser.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help=(
            "Read source from stdin instead of from disk. Use with "
            "--stdin-filename to give the buffer a path for diagnostics, "
            "language detection, and exclude_paths matching. Designed for "
            "editor integrations linting un-saved buffers."
        ),
    )
    parser.add_argument(
        "--stdin-filename",
        dest="stdin_filename",
        default="<stdin>.py",
        metavar="PATH",
        help=("Pseudo-filename for the source read from stdin (default '<stdin>.py'). Determines language by extension and is shown as the violation file path. Only meaningful with --stdin."),
    )


def _build_common_args(parser: argparse.ArgumentParser) -> None:
    """Add the full set of CLI flags shared by check / hook / stdin modes."""
    _add_severity_args(parser)
    _add_output_args(parser)
    _add_stdin_args(parser)


def _build_stdin_parser() -> argparse.ArgumentParser:
    """Build the stdin-mode parser (editor / Claude Code skill).

    Pre-commit hooks sometimes still pass file paths positionally even
    with ``--stdin``; accept them with ``nargs='*'`` so they don't
    trigger an "unknown argument" error, while still using ``parse_args``
    so genuine flag typos like ``--formta=json`` fail loudly instead of
    silently falling back to defaults.
    """
    parser = argparse.ArgumentParser(
        prog="safelint --stdin",
        description="Lint source read from stdin as if from --stdin-filename",
    )
    _build_common_args(parser)
    parser.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    return parser


def _build_check_parser() -> argparse.ArgumentParser:
    """Build the ``check`` subcommand parser (direct / CI scan mode)."""
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
            "Directory to use as the config discovery root, or a file whose parent directory is used as the root (safelint.toml takes precedence over pyproject.toml [tool.safelint] when both exist)"
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
    return parser


def _build_hook_parser() -> argparse.ArgumentParser:
    """Build the pre-commit hook-mode parser.

    Explicit positional ``files`` (rather than ``parse_known_args``) so an
    unrecognised *flag* fails loudly — silently dropping ``--formta=json``
    would let the user think pretty output was a deliberate choice.
    Pre-commit passes everything (Markdown, Makefiles, ``.py``) as
    positional args, so we filter to ``.py`` after parsing.
    """
    parser = argparse.ArgumentParser(
        prog="safelint",
        description="AI Safety pre-commit hook (Holzmann rules)",
    )
    _build_common_args(parser)
    parser.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    return parser


def _build_skill_parser() -> argparse.ArgumentParser:
    """Build the ``skill`` subcommand parser.

    Two actions today: ``install`` (materialises the bundled skill into
    ``~/.claude/skills/safelint/`` or a project-local equivalent) and
    ``path`` (prints the bundled-files location for debugging).
    """
    parser = argparse.ArgumentParser(
        prog="safelint skill",
        description="Manage the bundled Claude Code skill for safelint",
    )
    sub = parser.add_subparsers(dest="skill_action", required=True, metavar="ACTION")

    install = sub.add_parser(
        "install",
        help="Install the bundled skill into Claude Code (default: ~/.claude/skills/safelint)",
    )
    install.add_argument(
        "--project",
        action="store_true",
        default=False,
        help="Install into <cwd>/.claude/skills/safelint instead of the user-global location",
    )
    install.add_argument(
        "--symlink",
        action="store_true",
        default=False,
        help="Symlink to the bundled files instead of copying. Lets ``pip upgrade safelint`` automatically update the skill, but requires symlink support (POSIX, or Windows developer mode)",
    )
    install.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Replace any existing safelint skill at the target location",
    )

    sub.add_parser("path", help="Print the on-disk location of the bundled skill files")

    return parser


# Long options that consume the *following* argv token as their value
# (i.e. used in ``--flag VALUE`` form, not ``--flag=VALUE``). Used by the
# routing scanner to skip those values when looking for the first true
# positional argument. Without this, ``safelint --format json check src``
# sees ``json`` as the first positional and falls into hook mode by
# mistake. The ``--flag=VALUE`` form is unaffected because the ``=`` is
# part of the same token. Store-true flags (``--all-files``, ``--no-cache``,
# ``--stdin``) are deliberately omitted — they don't take a separate value.
_VALUE_TAKING_OPTIONS: frozenset[str] = frozenset(
    {
        "--fail-on",
        "--mode",
        "--ignore",
        "--format",
        "--stdin-filename",
        "--config",
    }
)


def _first_positional_index(argv: list[str]) -> int | None:
    """Return the index of the first true positional in *argv*, or None.

    Skips both options (anything starting with ``-``) and the *values*
    that follow value-taking long options. Recognises the ``=``-form
    (``--format=json``) as self-contained, so only the space-separated
    form (``--format json``) triggers the look-ahead.
    """
    skip_next = False
    for i, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg in _VALUE_TAKING_OPTIONS:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        return i
    return None


def _run_skill(args: argparse.Namespace) -> int:
    """Dispatch the ``safelint skill <action>`` subcommands."""
    # Local import keeps importlib.resources off the hot path for
    # check/hook/stdin invocations — only paid when the user explicitly
    # asks for skill management.
    from safelint import _skill_install  # noqa: PLC0415

    if args.skill_action == "install":
        return _skill_install.run_install(args)
    if args.skill_action == "path":
        return _skill_install.run_path(args)
    return 1  # pragma: no cover — argparse rejects unknown actions before this


def main() -> None:
    """Entry point for direct CLI invocation, pre-commit hook, and stdin mode.

    Routing logic (in order):
    - ``--stdin`` anywhere in argv → read source from stdin (editor mode).
    - First true positional argument is ``check`` → ``check`` subcommand.
    - First true positional argument is ``skill`` → ``skill`` subcommand
      (install / path).
    - Otherwise → pre-commit hook mode (``.py`` positional arguments are files).

    Global flags (``--format``, ``--fail-on``, ``--mode``, ``--ignore``,
    ``--config``, ``--stdin-filename``) may appear before the subcommand;
    the scanner skips their values so ``safelint --format json check src``
    is routed correctly.
    """
    if "--stdin" in sys.argv[1:]:
        args = _build_stdin_parser().parse_args()
        sys.exit(_run_stdin(args))

    rest = sys.argv[1:]
    idx = _first_positional_index(rest)
    if idx is not None and rest[idx] == "check":
        # Drop the ``check`` token but keep every flag (and its value)
        # before and after it so e.g. ``safelint --format json check src``
        # parses cleanly as ``--format json src``.
        argv_for_check = rest[:idx] + rest[idx + 1 :]
        args = _build_check_parser().parse_args(argv_for_check)
        sys.exit(_run_check(args))
    if idx is not None and rest[idx] == "skill":
        # Drop the ``skill`` token but keep every flag (and its value)
        # before and after it. Pre-skill tokens then fall to the skill
        # parser, which rejects unknowns — matching the "fail loudly on
        # unknown flags" posture of every other branch. Without this,
        # ``safelint --formta=json skill install`` would silently swallow
        # the typo. The skill parser doesn't accept the global formatter
        # flags by design (there's no JSON output for ``skill install``);
        # passing one in front of ``skill`` is therefore an error, not a
        # global override.
        argv_for_skill = rest[:idx] + rest[idx + 1 :]
        args = _build_skill_parser().parse_args(argv_for_skill)
        sys.exit(_run_skill(args))

    args = _build_hook_parser().parse_args()
    files = [f for f in args.files if f.endswith(".py")]
    sys.exit(_run_hook(args, files))


if __name__ == "__main__":
    main()
