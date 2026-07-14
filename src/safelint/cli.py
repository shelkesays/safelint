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
from dataclasses import dataclass
import fnmatch
import functools
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from safelint.core import _diagnostics
from safelint.core._cache import LintCache
from safelint.core.config import MODE_FAIL_ON, SEVERITY_ORDER, load_config
from safelint.core.engine import SafetyEngine
from safelint.core.runner import resolve_cache_dir, run
from safelint.formatters import format_json, format_sarif
from safelint.languages import extra_name_for, supported_extensions, unavailable_extensions


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


# Control characters are visualised before any attacker-controlled string (a
# linted source line, a file path, a rule message carrying source identifiers)
# is echoed to a TTY. A crafted source line containing raw ANSI / OSC escapes
# would otherwise be printed verbatim by the violation gutter, letting a cloned
# repo clear or redraw the terminal, spoof "All checks passed." output, set the
# window title, or drive OSC 52 clipboard writes when its violation is rendered.
# ruff / ripgrep / git (``core.quotePath``) sanitise terminal output the same
# way. Tab (0x09) is preserved so source indentation still renders; everything
# else in C0, DEL, and C1 becomes a visible ``\xNN`` escape.
_CONTROL_ORDS = (*range(0x09), *range(0x0A, 0x20), 0x7F, *range(0x80, 0xA0))
_CONTROL_TRANSLATION = {c: f"\\x{c:02x}" for c in _CONTROL_ORDS}


def _visible(text: str) -> str:
    r"""Replace control characters (except tab) with visible ``\xNN`` escapes."""
    return text.translate(_CONTROL_TRANSLATION)


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
        print(f"{_c(tag, _BOLD, colour)} {_visible(v.message)} [{v.rule}]")
        # Second line: purple arrow + location
        print(f"   {_c('-->', _PURPLE)} {_visible(v.filepath)}:{v.lineno}")
        # Source context: gutter (line number + pipe) in purple, content normal
        lines = _source_lines(v.filepath)
        if lines and 1 <= v.lineno <= len(lines):
            w = len(str(v.lineno))
            sep = _c(" " * w + " |", _PURPLE)
            num = _c(str(v.lineno).rjust(w) + " |", _PURPLE)
            print(f"   {sep}")
            print(f"   {num} {_visible(lines[v.lineno - 1].rstrip())}")
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
    ``sarif`` mode stdout must remain a single, parseable document - so
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
    fix - even if some violations were suppressed. The suppression breakdown
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
    fixes_line = _make_fixes_line(all_violations, suppressed_note)
    return found, fixes_line


def _make_fixes_line(violations: list[Violation], suppressed_note: str) -> str:
    """Build the post-summary 'fixes' notice.

    safelint never auto-applies fixes - that policy is final and
    deliberate (it's a review tool, not a refactoring tool). What
    *can* exist is *suggestions*: per-violation advisory edits that
    editor integrations may surface as Quick Fix code actions, with
    user confirmation always required. The notice text reflects
    whichever situation applies.
    """
    suggestion_count = sum(len(v.suggestions) for v in violations)
    if suggestion_count == 0:
        # No "see --format json" tail when zero suggestions - there's
        # nothing for that flag to surface in this run, and dangling
        # the pointer would falsely imply otherwise.
        return f"No suggestions available (safelint does not auto-fix).{suppressed_note}"
    n = "1 advisory suggestion" if suggestion_count == 1 else f"{suggestion_count} advisory suggestions"
    # Suggestions are emitted in both JSON and SARIF (the SARIF
    # ``fixes[]`` block, advisory by spec) - point at both so users
    # picking a format don't have to discover SARIF support
    # separately.
    return f"{n} available - view via --format json or --format sarif (safelint does not auto-apply fixes).{suppressed_note}"


def _file_summary_line(filepath: str, violations: list[Violation]) -> str:
    """Return a coloured per-file count line: 'path/file.py - 1 error, 3 warnings.'.

    Raises:
        ValueError: If *violations* is empty.

    """
    if not violations:
        msg = "violations must be non-empty"
        raise ValueError(msg)
    return f"{_visible(filepath)} - {', '.join(_severity_parts(violations))}."


def _print_file_summary(filepath: str, violations: list[Violation]) -> None:
    """Print the per-file summary line followed by a blank separator line."""
    print(_file_summary_line(filepath, violations))
    print()


def _stat_row(code: str, rule: str, active: int, supp: int, code_width: int, rule_width: int) -> str:
    """Format one row of the ``--statistics`` table."""
    active_col = _c(str(active).rjust(6), _BOLD, _RED) if active else "     -"
    supp_col = _c(str(supp).rjust(10), _CYAN) if supp else "         -"
    return f"{code.ljust(code_width)}  {rule.ljust(rule_width)}  {active_col}  {supp_col}"


def _print_statistics(violations: list[Violation], suppressed: list[Violation]) -> None:
    """Print a per-rule violation-count table.

    Includes active *and* suppressed counts so users can see what was
    silenced as well as what fired. Sorted by descending total count;
    rules tied on count are sorted alphabetically by code for
    deterministic output across runs. Emits nothing when both lists
    are empty.
    """
    if not violations and not suppressed:
        return
    active_counts = Counter(v.code or v.rule for v in violations)
    suppressed_counts = Counter(v.code or v.rule for v in suppressed)
    all_codes = sorted(set(active_counts) | set(suppressed_counts), key=lambda c: (-(active_counts[c] + suppressed_counts[c]), c))
    rule_for: dict[str, str] = {}
    for v in [*violations, *suppressed]:
        rule_for.setdefault(v.code or v.rule, v.rule)

    code_width = max((len(c) for c in all_codes), default=0)
    rule_width = max((len(rule_for[c]) for c in all_codes), default=0)

    print()
    header = f"{'CODE'.ljust(code_width)}  {'RULE'.ljust(rule_width)}  ACTIVE  SUPPRESSED"
    print(_c(header, _BOLD))
    print(_c("-" * len(header), _PURPLE))
    for code in all_codes:
        print(_stat_row(code, rule_for[code], active_counts[code], suppressed_counts[code], code_width, rule_width))
    print()


@dataclass(frozen=True)
class _PrintOptions:
    """Pretty-mode rendering knobs that don't fit the 'data' arguments.

    Bundled into a dataclass so ``_print_results`` keeps its argument count
    under the ``max_arguments`` rule's threshold while still being explicit
    at call sites: ``options=_PrintOptions(silent_on_clean=True)``.
    """

    silent_on_clean: bool = False
    statistics: bool = False


# Module-level singleton for the default ``_print_results(options=...)`` arg -
# avoids the ``B008`` lint that disallows calling a constructor in a default
# argument expression. Frozen + immutable so accidental mutation is impossible.
_DEFAULT_PRINT_OPTIONS = _PrintOptions()


def _print_results(
    output_format: str,
    violations: list[Violation],
    suppressed: list[Violation],
    *,
    blocking_count: int,
    fail_on: str,
    files_checked: int,
    options: _PrintOptions = _DEFAULT_PRINT_OPTIONS,
) -> None:
    """Emit accumulated lint results in the chosen format.

    For ``pretty`` (default), prints the ruff/ty-style summary block (per-file
    violations were already streamed during the run). For ``json`` / ``sarif``,
    prints a single machine-readable document on stdout. *options* knobs:

    * ``silent_on_clean`` - when True, pretty mode emits nothing on a clean
      run (no violations) - *no summary and no ``--statistics`` table*,
      regardless of suppressions. Hook / stdin mode set this so a clean
      pre-commit run is fully silent (the ruff/ty contract). Rationale:
      pre-commit batches files across hook invocations, so printing the
      ``(N suppressed)`` breakdown or the stats table per batch produces a
      stack of misleading *partial*-count lines (issue #50). The summed
      breakdown stays available via ``safelint check`` (which leaves this
      False) and in every JSON / SARIF document.
    * ``statistics`` - when True, append a per-rule violation-count table
      after the summary. Pretty mode only; gated by the same clean-run
      silence above.

    Stderr diagnostics are unaffected - always written as produced.
    """
    if output_format == "pretty":
        # A clean run under ``silent_on_clean`` emits nothing - summary AND
        # the ``--statistics`` table (the hook parser accepts ``--statistics``,
        # so this gate is what keeps a clean pre-commit batch quiet - issue #50).
        emit = bool(violations) or not options.silent_on_clean
        if emit:
            _print_summary(violations, blocking_count, fail_on, suppressed)
        if options.statistics and emit:
            _print_statistics(violations, suppressed)
        return
    # output_format is "json" or "sarif" here - argparse ``choices`` guarantees
    # it, and "pretty" already returned above. Both formatters share the same
    # signature, so a single dispatch covers both machine-readable documents.
    formatter = format_json if output_format == "json" else format_sarif
    print(
        formatter(
            violations,
            suppressed,
            blocking_count=blocking_count,
            fail_on=fail_on,
            files_checked=files_checked,
        )
    )


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
    # irrelevant here - caching is unconditionally off.
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
        options=_PrintOptions(silent_on_clean=True, statistics=getattr(args, "statistics", False)),
    )
    return 1 if blocking else 0


def _run_hook(args: argparse.Namespace, files: list[str]) -> int:
    """Execute pre-commit hook mode against an explicit list of supported-source files."""
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
        options=_PrintOptions(silent_on_clean=True, statistics=getattr(args, "statistics", False)),
    )
    return 1 if all_blocking else 0


def _is_under_target(abs_path: Path, target_abs: Path) -> bool:
    """Return True when *abs_path* is inside *target_abs* (dir) or equals it (file)."""
    if target_abs.is_dir():
        try:
            abs_path.relative_to(target_abs)
        # ``relative_to`` raising ValueError means "not under" - that's the
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


def _collect_all_supported_files(raw: set[str], git_root: Path) -> list[str]:
    """Return paths for all existing files with a registered language extension (no target filter).

    Paths are relative to cwd when possible, otherwise absolute.
    """
    cwd = Path.cwd()
    exts = tuple(supported_extensions())
    results: list[str] = []
    for rel in raw:
        if not rel.endswith(exts):
            continue
        abs_path = (git_root / rel).resolve()
        if abs_path.exists():
            results.append(_normalize_path(abs_path, cwd))
    return sorted(results)


def _filter_supported_files(raw: set[str], git_root: Path, target_abs: Path) -> list[str]:
    """Filter git-relative paths to existing supported-language files under *target_abs*.

    Returned paths are relative to cwd when possible, which keeps diagnostic
    output (``file:line:``) free of Windows drive-letter colons in the common
    case; absolute paths are used as a fallback for files outside cwd.
    """
    cwd = Path.cwd()
    exts = tuple(supported_extensions())
    results: list[str] = []
    for rel in raw:
        if not rel.endswith(exts):
            continue
        abs_path = (git_root / rel).resolve()
        if abs_path.exists() and _is_under_target(abs_path, target_abs):
            results.append(_normalize_path(abs_path, cwd))
    return sorted(results)


def _filter_modified_under_target(raw: set[str], git_root: Path, target_abs: Path) -> set[str]:
    """Return git-relative paths in *raw* whose resolved location is under *target_abs* AND still exists on disk.

    Matches the target-restriction *and* existence check of
    :func:`_filter_supported_files`, but does *not* filter by supported
    extension - the silent-failure guard needs to see ``.ts`` files
    modified under the requested target even when the TS grammar isn't
    installed (those wouldn't reach ``_filter_supported_files`` because
    its extension filter drops them). The existence check matters
    because ``git diff --name-only HEAD`` reports *deleted* files too;
    without it, a deleted ``.ts`` under target would tip
    ``_handle_no_targets`` into exit 2 ("install the typescript extra")
    even though the user has no remaining ``.ts`` file to lint. Returns
    the git-relative form (same as *raw*) so downstream callers that
    key off ``Path(...).suffix`` work the same as they did against the
    un-filtered set.
    """
    out: set[str] = set()
    for rel in raw:
        abs_path = (git_root / rel).resolve()
        if abs_path.exists() and _is_under_target(abs_path, target_abs):
            out.add(rel)
    return out


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


def _get_git_modified_supported_files(target: Path) -> tuple[list[str], list[str], set[str]] | None:
    """Return changed supported-source-file lists + the considered-modified set, or ``None`` on git failure.

    Filtering is registry-driven via :func:`safelint.languages.supported_extensions`,
    so any language registered in ``safelint.languages`` is included. Includes
    staged, unstaged, and untracked files.

    Returns ``(all_changed, in_target, considered_modified)`` where:

    * *all_changed* - every changed supported-source file across the whole repo.
      Paths are relative to cwd when possible, otherwise absolute.
      Passed to :class:`~safelint.core.engine.SafetyEngine` as ``changed_files``
      so cross-file rules (e.g. ``test_coupling``) see the full diff context.
    * *in_target* - the subset of those files that fall under *target*.
      Same path format as *all_changed*. These are the files actually linted.
    * *considered_modified* - paths git reported as modified under
      *target* (git-relative, **no** supported-extension filter). Lets
      callers detect "user modified files under target but all dropped
      by the supported-extensions filter" - the silent-pass case the
      missing-grammar guard catches when ``in_target`` is empty.
      Restricted to *target*: a ``.ts`` modified elsewhere must NOT
      trip the guard when the user ran ``safelint check src/python/``.

    Returns ``None`` when git is unavailable, the path is outside a git
    repository, or any git command fails - callers should fall back to
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
        return (
            _collect_all_supported_files(raw, git_root),
            _filter_supported_files(raw, git_root, target_abs),
            _filter_modified_under_target(raw, git_root, target_abs),
        )

    # Any git-side failure (no git, not a repo, timeout) means we fall back
    # to scanning all files - that's a documented behaviour, not an error.
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):  # nosafe: SAFE203
        return None


def _config_dir(config_path: Path | None, target: Path) -> Path:
    """Return the directory to use as the config search root."""
    if config_path:
        return config_path if config_path.is_dir() else config_path.parent
    return target if target.is_dir() else target.parent


def _resolve_check_targets(args: argparse.Namespace, target: Path, output_format: str) -> tuple[list[str] | None, list[str] | None, bool, set[str]]:
    """Resolve the (changed_files, files, no_targets, considered_modified) tuple for ``check`` mode.

    Returns a 4-tuple:

    * ``changed_files`` - the full repo-wide diff list passed to the engine
      so cross-file rules see the right context, or None to skip that hint.
    * ``files`` - the explicit list of files to lint (a subset of *target*
      that's been git-modified), or None to fall back to directory discovery.
    * ``no_targets`` - True when git reported no modified files under
      *target* and the caller should short-circuit with an empty result.
    * ``considered_modified`` - the set of paths git reported as modified
      that fall under *target*, with the supported-extension filter NOT
      applied (paths are relative to ``git_root``). Empty when ``--all-files``
      / git unavailable / git reported nothing under target. Callers use
      this to detect the silent-pass case where the user modified files
      under target but every one was dropped by the missing-grammar
      filter - ``no_targets`` would be True in that case, but the
      appropriate exit code is 2 (configuration error), not 0.
      Restricting to *target* matters: a ``.ts`` file modified elsewhere
      in the repo must NOT trip the guard when the user ran
      ``safelint check src/python/``.
    """
    if getattr(args, "all_files", False) or not target.is_dir():
        return None, None, False, set()
    modified = _get_git_modified_supported_files(target)
    if modified is None:
        _print_status(
            "Note: could not determine modified files via git - scanning all files.",
            output_format=output_format,
        )
        return None, None, False, set()
    if not modified[1]:
        _print_status(
            f"No modified supported source files detected under target {target}. "
            "Modified files may be outside the target, or skipped due to missing grammar support; "
            "use --all-files to scan everything or install the needed grammar extra.",
            output_format=output_format,
        )
        return None, None, True, modified[2]
    changed_files, files, considered = modified
    return changed_files, files, False, considered


# Default dir-name exclusions for the missing-grammar walk. Kept narrow -
# this is a fast pre-scan whose purpose is to nudge users, not to mirror
# the engine's full ``exclude_paths`` machinery. The common vendored /
# generated / dependency trees below are virtually always gitignored; if
# a user genuinely wants safelint to see ``.js`` files under
# ``node_modules`` they're far enough off the beaten path to figure out
# the install hint without our nudge.
_GRAMMAR_SCAN_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "target",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".safelint_cache",
    }
)


def _format_install_action(install_hint: str) -> str:
    """Format the user-facing install action for the active execution context.

    *install_hint* is the canonical ``pip install 'safelint[<lang>]'``
    string each language module exports. That command is the right
    answer for direct CLI users - but useless to a pre-commit-only
    user, who can't run pip directly because pre-commit manages the
    hook's isolated environment. Detect via the ``PRE_COMMIT`` env
    var pre-commit sets at hook execution time, and re-route the
    advice to ``additional_dependencies`` (the actual lever a
    pre-commit user has).
    """
    if os.environ.get("PRE_COMMIT") == "1":
        prefix = "pip install "
        spec = install_hint.removeprefix(prefix)
        return f"add {spec} to additional_dependencies in your .pre-commit-config.yaml"
    return f"install with: {install_hint}"


def _matching_suffixes(filenames: list[str], unavailable: dict[str, str]) -> set[str]:
    """Return the subset of *unavailable* extensions present in *filenames*.

    Mirrors ``pathlib.Path.suffix`` semantics:

    * A name with no dot (``"README"``) → no suffix.
    * A leading-dot dotfile (``".ts"``, ``".gitignore"``) → no suffix.
    * A dotfile *inside a directory* (``"src/.ts"``,
      ``"a/b/.gitignore"``) → still no suffix; the basename rule
      applies regardless of where the file sits in the tree.

    Hook-mode callers (``_emit_hook_grammar_warnings``) pass full
    paths like ``src/app.py`` straight from pre-commit's argv. A naive
    ``rfind('.')`` on the full path would treat ``src/.ts`` as having
    suffix ``.ts`` (the rightmost dot is at index > 0 in the full
    string), but the file is actually a dotfile with no suffix. The
    ``Path(name).name`` step strips any directory prefix so the
    ``idx > 0`` guard catches dotfiles in subdirectories too.
    """
    found: set[str] = set()
    for name in filenames:
        base = Path(name).name
        idx = base.rfind(".")
        if idx > 0 and base[idx:] in unavailable:
            found.add(base[idx:])
    return found


def _path_matches_exclude(path: Path, exclude_paths: list[str]) -> bool:
    """Mirror of ``SafetyEngine._is_excluded`` as a free function for the pre-scan."""
    posix = path.as_posix()
    return any(fnmatch.fnmatchcase(posix, pattern) for pattern in exclude_paths)


def _dir_matches_exclude(path: Path, exclude_paths: list[str]) -> bool:
    """Mirror of ``SafetyEngine._is_excluded_dir`` as a free function for the pre-scan.

    Tests both the bare and trailing-slash forms so ``foo/**`` globs prune
    the ``foo`` directory at descent time, the same way the engine's walk
    does.
    """
    bare = path.as_posix().rstrip("/")
    with_slash = bare + "/"
    return any(fnmatch.fnmatchcase(bare, pattern) or fnmatch.fnmatchcase(with_slash, pattern) for pattern in exclude_paths)


def _scan_for_unavailable_extensions(
    target: Path,
    unavailable: dict[str, str],
    exclude_paths: list[str] | None = None,
) -> set[str]:
    """Return the subset of *unavailable* extensions found under *target*.

    Early-exits once every unavailable extension has been seen at least
    once. Walks with the same default dir-name exclusions safelint uses
    for its built-in ``exclude_paths`` so vendored ``node_modules`` /
    ``.venv`` etc. don't trigger the hint spuriously.

    When *exclude_paths* is non-empty (resolved from the user's config
    via ``SafetyEngine._resolve_exclude_paths``), the walk also applies
    the engine's exclusion logic at both file and directory granularity.
    Files in user-excluded subtrees (e.g. ``generated/**``) don't show
    up in the unavailable-extension set, mirroring the engine's
    behaviour: a file safelint won't actually lint shouldn't trigger a
    missing-grammar warning or the silent-failure guard.
    """
    excludes = exclude_paths or []
    if target.is_file():
        if excludes and _path_matches_exclude(target, excludes):
            return set()
        return {target.suffix} if target.suffix in unavailable else set()
    if not target.is_dir():
        return set()
    return _walk_unavailable_extensions(target, unavailable, excludes)


def _walk_unavailable_extensions(
    target: Path,
    unavailable: dict[str, str],
    excludes: list[str],
) -> set[str]:
    """Directory-walk half of :func:`_scan_for_unavailable_extensions`."""
    seen: set[str] = set()
    target_set = set(unavailable)
    # ``os.walk`` (not ``Path.walk``) with ``followlinks=False`` - no symlink
    # descent / no symlink-cycle, same posture as the engine's file discovery.
    # ``Path.walk`` is 3.12+ and ``requires-python`` is ``>=3.11``, so this
    # stays ``os.walk`` until the floor moves; see ``engine._walk_supported_files``.
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        dir_path = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d not in _GRAMMAR_SCAN_EXCLUDED_DIRS and not (excludes and _dir_matches_exclude(dir_path / d, excludes))]
        kept = filenames if not excludes else [f for f in filenames if not _path_matches_exclude(dir_path / f, excludes)]
        seen.update(_matching_suffixes(kept, unavailable))
        if seen == target_set:
            return seen
    return seen


def _emit_missing_grammar_warnings(
    target: Path,
    *,
    silent: bool = False,
    exclude_paths: list[str] | None = None,
) -> set[str]:
    """Walk *target*, return the set of unavailable extensions found; emit warnings unless *silent*.

    The walk and the set-return run unconditionally - that's what the
    silent-failure guard in :func:`_check_exit_code` consumes to fire
    exit code 2 in *every* output mode. The stderr warnings, however,
    are gated on *silent*: pretty mode prints them, JSON / SARIF mode
    suppresses them so the tooling-consumer stderr stays clean for
    parsing pipelines (matching the changelog claim).

    Set ``silent=True`` for machine output modes; leave default for
    interactive runs. Pass *exclude_paths* (the resolved user-config
    list) so files in excluded subtrees neither produce a warning nor
    trip the silent-failure guard - a file safelint won't actually
    lint shouldn't fail the run with "no grammar installed".

    No-op (returns empty set) when every grammar extra is installed
    or when the target tree contains no unavailable-extension files.
    """
    unavailable = unavailable_extensions()
    if not unavailable:
        return set()
    seen_exts = _scan_for_unavailable_extensions(target, unavailable, exclude_paths=exclude_paths)
    if not seen_exts or silent:
        return seen_exts
    grouped: dict[str, list[str]] = {}
    for ext in sorted(seen_exts):
        grouped.setdefault(unavailable[ext], []).append(ext)
    for hint, exts in grouped.items():
        exts_str = ", ".join(exts)
        _diagnostics.print_warning(f"skipping {exts_str} files - {_format_install_action(hint)}")
    return seen_exts


def _emit_hook_grammar_warnings(files: list[str], *, silent: bool = False) -> set[str]:
    """Pre-commit / hook-mode variant of :func:`_emit_missing_grammar_warnings`.

    Pre-commit hands files in directly; no directory walk needed. Group
    the passed files by their unavailable extension, emit one warning
    per missing grammar, and return the set of unavailable extensions
    actually found among *files*. Callers use the return value to fail
    loud when every passed file would be skipped - see ``main()`` for
    the silent-failure guard.

    The set-return runs unconditionally so the silent-failure guard in
    :func:`_guard_hook_silent_failure` can fire exit code 2 in every
    output mode. The stderr warnings, however, are gated on *silent*:
    pretty mode prints one ``safelint: warning: skipping .X files …``
    line per missing grammar, JSON / SARIF mode suppresses them so the
    tooling-consumer stderr stays clean for parsing pipelines -
    symmetric with the directory-walk variant.
    """
    unavailable = unavailable_extensions()
    if not unavailable:
        return set()
    # Reuse ``_matching_suffixes`` so the dotfile-aware suffix logic
    # (``idx > 0`` matching ``Path.suffix`` semantics) lives in one
    # place. Both this helper and the directory walker use the same
    # rule for "what counts as a suffix".
    seen_exts = _matching_suffixes(files, unavailable)
    if not seen_exts or silent:
        return seen_exts
    grouped: dict[str, list[str]] = {}
    for ext in sorted(seen_exts):
        grouped.setdefault(unavailable[ext], []).append(ext)
    for hint, exts in grouped.items():
        exts_str = ", ".join(exts)
        _diagnostics.print_warning(f"skipping {exts_str} files - {_format_install_action(hint)}")
    return seen_exts


def _check_exit_code(
    results: list,  # list[LintResult] - typed loosely to avoid an import cycle in tests
    unavailable_found: set[str],
    all_blocking: list,  # list[Violation]
) -> int:
    """Resolve the exit code for ``_run_check`` after the lint completes.

    Three cases:

    * **Silent-failure** - file discovery saw unavailable-grammar files
      AND no file actually got linted (every entry in *results* either
      doesn't exist or was an empty placeholder for a file whose grammar
      isn't installed). The run is reporting "clean" only because no
      files were processed; surface this as exit 2 (configuration error)
      so pre-commit / CI shows the hook as failed. The "no file got
      linted" check must look past raw list length because ``check_path``
      on a single ``.ts`` target with the TS grammar missing returns
      ``[LintResult(path='foo.ts')]`` - a 1-element list whose lone
      entry was actually skipped at language-lookup time. Treat any
      result whose path's suffix is in *unavailable_found* as skipped.
    * **Blocking violations** - exit 1.
    * **Clean / advisory only** - exit 0.
    """
    if unavailable_found and not _any_result_was_linted(results, unavailable_found):
        action = _install_action_for_extensions(unavailable_found)
        suffix = f" - {action}" if action else ""
        _diagnostics.print_error(f"no files linted - every supported file was skipped because its grammar package isn't installed{suffix}")
        return 2
    return 1 if all_blocking else 0


def _any_result_was_linted(results: list, unavailable_found: set[str]) -> bool:
    """Return True if any ``LintResult`` in *results* corresponds to a file safelint actually linted.

    An entry is considered "actually linted" when its path's suffix is
    NOT in *unavailable_found*. Mirrors :func:`_matching_suffixes`'s
    ``Path.suffix``-style semantics (``rfind(".") > 0`` - leading-dot
    basenames like ``.gitignore`` have no suffix). Short-circuits over
    the list so the typical clean run is O(1).
    """
    for r in results:
        name = Path(r.path).name
        idx = name.rfind(".")
        suffix = name[idx:] if idx > 0 else ""
        if suffix not in unavailable_found:
            return True
    return False


def _guard_hook_silent_failure(passed: list[str], filtered: list[str], unavailable_in_passed: set[str]) -> int:
    """Exit code 2 when every pre-commit-passed file was dropped for missing grammars.

    Pre-commit reports the hook as Passed whenever safelint exits 0,
    even if safelint linted zero files because every passed file's
    grammar wasn't installed. That hidden-green run is the worst
    failure mode - the user thinks safelint is running but nothing is
    actually checked. Fail loud so pre-commit shows the hook as Failed
    and the user is directed to ``additional_dependencies`` (the lever
    they actually have in hook-only setups).

    Returns the exit code the caller should pass to ``sys.exit``: 0
    when everything is fine, 2 when the silent-failure case fires.
    Pure function - caller decides whether to actually exit. Makes
    the helper unit-testable without monkey-patching ``sys.exit``.
    """
    if passed and not filtered and unavailable_in_passed:
        action = _install_action_for_extensions(unavailable_in_passed)
        suffix = f" - {action}" if action else ""
        _diagnostics.print_error(f"no files linted - every file pre-commit passed had a grammar that isn't installed{suffix}")
        return 2
    return 0


def _compose_extras_install_command(extras: set[str]) -> str:
    """Compose a ``pip install 'safelint[a,b,c]'`` line for *extras*.

    Order: alphabetical, so the output is deterministic across runs and
    diffs cleanly in CI logs.
    """
    spec = ",".join(sorted(extras))
    return f"pip install 'safelint[{spec}]'"


def _install_action_for_extensions(exts: set[str]) -> str:
    """Compose the PRE_COMMIT-aware install action for the unavailable *exts*.

    Returns the formatted action string (``install with: pip install
    'safelint[typescript]'`` for direct CLI users, or ``add
    'safelint[typescript]' to additional_dependencies in your
    .pre-commit-config.yaml`` for pre-commit users) so the silent-failure
    errors are self-contained even when stderr warnings were suppressed
    (machine output modes) or never emitted (the no-targets short-circuit
    where the warning walk hasn't run for those paths).

    Empty string when no extension maps to a known extra - defensive
    fallback so the caller's error message degrades gracefully rather
    than dangling with a trailing separator.
    """
    extras = {name for ext in exts if (name := extra_name_for(ext))}
    if not extras:
        return ""
    return _format_install_action(_compose_extras_install_command(extras))


def _emit_skill_install_grammar_hint(target: Path) -> None:
    """After ``safelint skill install``, nudge the user about missing language grammars.

    Symmetric with the existing AI-client auto-detection - ``skill
    install`` finds the AI clients in this project and installs the
    skill files; this helper additionally finds the *languages* in
    this project and tells the user which ``safelint[<lang>]`` extras
    they're missing.

    For multi-language projects (Python + JS, Python + TS, etc.) the
    helper emits a single composed install command
    (``pip install 'safelint[python,typescript]'``) so the user runs
    one ``pip`` command instead of several. The per-language warnings
    from :func:`_emit_missing_grammar_warnings` are intentionally
    *not* emitted here - that helper is the runtime-warning surface
    and the duplicate output would just be noise. The skill-install
    surface emits one compact summary line instead.

    Silent when every needed grammar is already installed - the user
    asked to install skills, not to be lectured about grammars they
    already have.
    """
    unavailable = unavailable_extensions()
    if not unavailable:
        return
    seen_exts = _scan_for_unavailable_extensions(target, unavailable)
    if not seen_exts:
        return
    needed_extras: set[str] = set()
    for ext in seen_exts:
        name = extra_name_for(ext)
        if name is not None:
            needed_extras.add(name)
    if not needed_extras:
        return  # pragma: no cover - defensive; every unavailable ext has an extra
    install = _compose_extras_install_command(needed_extras)
    plural = "" if len(needed_extras) == 1 else "s"
    extras_list = ", ".join(sorted(needed_extras))
    _diagnostics.print_warning(f"Detected source files for {len(needed_extras)} language{plural} ({extras_list}) whose tree-sitter grammar isn't installed. Run: {install}")


def _handle_no_targets(output_format: str, fail_on: str, considered_modified: set[str]) -> int:
    """Resolve the exit code for the ``_resolve_check_targets`` no-targets short-circuit.

    Two distinct cases land here and the exit code differs:

    * **Genuine clean run / nothing under target** - the current
      invocation has no modified files to consider
      (``considered_modified`` is empty - either the user truly hasn't
      modified anything, or the only modified files live outside the
      requested target). Print the empty results document and exit 0.
      Machine output modes still need a parseable empty document on
      stdout so downstream CI uploaders / SARIF consumers don't choke
      on empty input.
    * **Silent-pass** - files under target were modified, but every one
      was dropped by the supported-extensions filter because its grammar
      isn't installed. ``considered_modified`` intersects
      ``unavailable_extensions()``. Print the empty document AND a stderr
      error AND exit 2 so pre-commit / CI shows the run as Failed rather
      than silently Passed.
    """
    unavailable_in_modified = _matching_suffixes(list(considered_modified), unavailable_extensions())
    _print_results(output_format, [], [], blocking_count=0, fail_on=fail_on, files_checked=0, options=_PrintOptions(silent_on_clean=True))
    if unavailable_in_modified:
        action = _install_action_for_extensions(unavailable_in_modified)
        suffix = f" - {action}" if action else ""
        _diagnostics.print_error(f"no files linted - every git-modified source file has a grammar that isn't installed{suffix}")
        return 2
    return 0


def _emit_skill_freshness_warnings() -> None:
    """Emit a stderr warning for each stale AI-client skill install.

    Called from ``_run_check`` only when the user passes
    ``--check-skill-freshness``. The function delegates the
    drift detection to ``_skill_install.stale_install_warnings``
    and routes each result through the diagnostics channel
    (``safelint: warning: …`` on stderr). Doesn't fail the run -
    informational only. Local import avoids paying the
    ``importlib.resources`` cost on the hot path of normal
    ``safelint check`` invocations.
    """
    from safelint import _skill_install  # noqa: PLC0415

    for warning in _skill_install.stale_install_warnings():
        _diagnostics.print_warning(warning)


def _load_config_and_excludes(target: Path, config_path: str | None) -> tuple[dict, list[str]]:
    """Load config from the right directory and resolve its exclude-path list.

    The missing-grammar pre-scan needs the exclude list so an excluded
    ``generated/**`` directory full of ``.ts`` files doesn't trip the
    silent-failure guard or spuriously warn. Calling this *before* the
    pre-scan keeps the guard semantics aligned with what would actually
    be linted.
    """
    config = load_config(_config_dir(Path(config_path) if config_path else None, target))
    return config, SafetyEngine._resolve_exclude_paths(config)


def _run_check(args: argparse.Namespace) -> int:
    """Execute directory/file scan mode."""
    if getattr(args, "check_skill_freshness", False):
        _emit_skill_freshness_warnings()
    config_path = getattr(args, "config", None)
    target = Path(args.target)
    output_format: str = getattr(args, "output_format", "pretty")

    config, exclude_paths = _load_config_and_excludes(target, config_path)

    # Compute the unavailable-extension set in every output mode so the
    # silent-failure guard fires for JSON / SARIF runs too. Stderr
    # warnings are pretty-mode only - JSON / SARIF consumers expect a
    # quiet stderr alongside the parseable stdout document.
    unavailable_found = _emit_missing_grammar_warnings(
        target,
        silent=(output_format != "pretty"),
        exclude_paths=exclude_paths,
    )

    changed_files, files, no_targets, considered_modified = _resolve_check_targets(args, target, output_format)
    fail_on, fail_threshold = _resolve_fail_on(args, config)

    if no_targets:
        return _handle_no_targets(output_format, fail_on, considered_modified)

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

    _print_results(
        output_format,
        all_violations,
        all_suppressed,
        blocking_count=len(all_blocking),
        fail_on=fail_on,
        files_checked=len(results),
        options=_PrintOptions(statistics=getattr(args, "statistics", False)),
    )
    return _check_exit_code(results, unavailable_found, all_blocking)


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
    parser.add_argument(
        "--statistics",
        dest="statistics",
        action="store_true",
        default=False,
        help=(
            "After the run, print a per-rule violation count summary to stdout (pretty mode only). "
            "Useful for 'where do we stand?' snapshots in CI. Counts include both active and "
            "suppressed violations so you can see the full picture."
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
        help="Scan all supported source files under target (default: git-modified files only)",
    )
    parser.add_argument(
        "--check-skill-freshness",
        dest="check_skill_freshness",
        action="store_true",
        default=False,
        help=(
            "Before linting, verify the installed AI-client skill(s) match the bundled version and "
            "emit a stderr warning per stale install. Informational only - doesn't fail the run. "
            "Use ``safelint skill status`` for the dedicated check."
        ),
    )
    _build_common_args(parser)
    return parser


def _build_hook_parser() -> argparse.ArgumentParser:
    """Build the pre-commit hook-mode parser.

    Explicit positional ``files`` (rather than ``parse_known_args``) so an
    unrecognised *flag* fails loudly - silently dropping ``--formta=json``
    would let the user think pretty output was a deliberate choice.
    Pre-commit passes everything (Markdown, Makefiles, source files) as
    positional args, so we filter to entries whose extension is in
    :func:`safelint.languages.supported_extensions` after parsing.
    """
    parser = argparse.ArgumentParser(
        prog="safelint",
        description="AI Safety pre-commit hook (Holzmann rules)",
    )
    _build_common_args(parser)
    parser.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    return parser


def _add_skill_install_arguments(install: argparse.ArgumentParser, install_choices: tuple[str, ...]) -> None:
    """Attach ``--client`` / ``--project`` / ``--symlink`` / ``--force`` to the install subparser."""
    install.add_argument(
        "--client",
        choices=install_choices,
        default="auto",
        help="Target AI client: ``auto`` (default - detect from markers in cwd, then home) or one of: " + ", ".join(c for c in install_choices if c != "auto"),
    )
    install.add_argument(
        "--project",
        action="store_true",
        default=False,
        help="Force project scope (<cwd>/.<client>/...). With ``--client auto``, restricts detection to cwd and refuses to fall back to home",
    )
    install.add_argument(
        "--symlink",
        action="store_true",
        default=False,
        help="Symlink to the bundled files instead of copying. Lets ``pip upgrade safelint`` automatically update the skill / rule, but requires symlink support (POSIX, or Windows developer mode)",
    )
    install.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Replace any existing safelint skill / rule at the target location",
    )


def _build_skill_parser() -> argparse.ArgumentParser:
    """Build the ``skill`` subcommand parser.

    Two actions: ``install`` (materialises the bundled skill / project
    rule into the chosen AI client's directory) and ``path`` (prints
    the bundled-files location for debugging).

    The ``--client`` option on ``install`` defaults to ``auto``, which
    detects which AI client(s) the user is using by scanning for
    marker paths (``CLAUDE.md`` / ``.claude/`` / ``.cursor/`` / etc.)
    in cwd first and home second. Pass an explicit client name to
    skip detection. Choices are derived from the registry in
    :mod:`safelint._skill_install` so adding a new client there
    automatically extends what argparse accepts here.
    """
    # Local import keeps ``importlib.resources`` off the cli import
    # hot path; pulled in only when the user invokes ``skill``.
    from safelint._skill_install import INSTALL_CLIENT_CHOICES, PATH_CLIENT_CHOICES  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="safelint skill",
        description=(
            "Manage the bundled safelint skill / project rule for AI clients (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed, Warp)"
        ),
    )
    sub = parser.add_subparsers(dest="skill_action", required=True, metavar="ACTION")

    install = sub.add_parser(
        "install",
        help="Install the bundled skill / rule into the AI client(s) detected for this project (default: --client auto)",
    )
    _add_skill_install_arguments(install, INSTALL_CLIENT_CHOICES)

    path_parser = sub.add_parser("path", help="Print bundled-skill location: no --client prints the bundle root directory; --client prints that client's artefact file")
    path_parser.add_argument(
        "--client",
        choices=PATH_CLIENT_CHOICES,
        default=None,
        help="Which client's artefact file path to print. Omit to print the bundle ROOT directory instead (parent of every per-client subdir and the shared ``languages/<lang>.md`` addendums).",
    )

    sub.add_parser(
        "status",
        help="Compare every detected installed skill against the bundled version (exit 1 if any differ)",
    )

    update = sub.add_parser(
        "update",
        help="Refresh installed skills whose content has drifted from the bundled wheel (no-op when fresh, --force overrides)",
    )
    _add_skill_update_arguments(update, INSTALL_CLIENT_CHOICES)

    remove = sub.add_parser(
        "remove",
        help="Delete detected installed skills (auto-detects from install paths; --symlink filters to symlink-shape; --path overrides)",
    )
    _add_skill_remove_arguments(remove, INSTALL_CLIENT_CHOICES)

    return parser


def _add_skill_update_arguments(update: argparse.ArgumentParser, install_choices: tuple[str, ...]) -> None:
    """Attach ``--client`` / ``--project`` / ``--symlink`` / ``--force`` to the update subparser.

    Same flags as ``install`` but ``--client auto`` resolves via install
    paths (not marker files). ``--force`` here means "refresh even when
    status says fresh" rather than "replace existing".
    """
    update.add_argument(
        "--client",
        choices=install_choices,
        default="auto",
        help="Target AI client: ``auto`` (default - detect from existing install paths, NOT marker files like ``install``) or one of: " + ", ".join(c for c in install_choices if c != "auto"),
    )
    update.add_argument(
        "--project",
        action="store_true",
        default=False,
        help="Restrict to project-scope installs (<cwd>/.<client>/...)",
    )
    update.add_argument(
        "--symlink",
        action="store_true",
        default=False,
        help="Re-create the install in symlink mode (mirrors install's --symlink)",
    )
    update.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Refresh every matching install regardless of drift status (useful for reverting customisations to bundled)",
    )


def _add_skill_remove_arguments(remove: argparse.ArgumentParser, install_choices: tuple[str, ...]) -> None:
    """Attach ``--client`` / ``--project`` / ``--symlink`` / ``--path`` / ``--dry-run`` to the remove subparser."""
    remove.add_argument(
        "--client",
        choices=install_choices,
        default="auto",
        help="Target AI client: ``auto`` (default - detect from existing install paths) or one of: " + ", ".join(c for c in install_choices if c != "auto"),
    )
    remove.add_argument(
        "--project",
        action="store_true",
        default=False,
        help="Restrict to project-scope installs (<cwd>/.<client>/...)",
    )
    remove.add_argument(
        "--symlink",
        action="store_true",
        default=False,
        help="Filter to symlink-shape installs only - keep copy-mode installs intact (composes with ``--client`` and ``--project``)",
    )
    remove.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Remove one specific install at PATH (overrides every other flag, including auto-detect)",
    )
    remove.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Preview what would be removed without deleting anything",
    )


# Long options that consume the *following* argv token as their value
# (i.e. used in ``--flag VALUE`` form, not ``--flag=VALUE``). Used by the
# routing scanner to skip those values when looking for the first true
# positional argument. Without this, ``safelint --format json check src``
# sees ``json`` as the first positional and falls into hook mode by
# mistake. The ``--flag=VALUE`` form is unaffected because the ``=`` is
# part of the same token. Store-true flags (``--all-files``, ``--no-cache``,
# ``--stdin``) are deliberately omitted - they don't take a separate value.
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


def _known_rule_languages() -> tuple[str, ...]:
    """Return every language name any registered rule lists in ``language``.

    Used as the choice set for ``list-rules --language``. Computed from
    :data:`safelint.rules.ALL_RULES` so the option auto-grows when a new
    language is added; the catalogue stays accurate without an explicit
    table to keep in sync.
    """
    from safelint.rules import ALL_RULES  # noqa: PLC0415

    langs: set[str] = set()
    for cls in ALL_RULES:
        langs.update(cls.language)
    return tuple(sorted(langs))


def _build_list_rules_parser() -> argparse.ArgumentParser:
    """Build the ``list-rules`` subcommand parser.

    Surfaces the rule catalogue for agents, dashboards, and docs
    regeneration. Default output is the text table (grouped by category
    band, one line per rule). ``--format json`` / ``markdown`` / ``sarif``
    switch to the matching structured representation.
    """
    parser = argparse.ArgumentParser(
        prog="safelint list-rules",
        description="Print the catalogue of every shipped rule, optionally filtered by language.",
    )
    parser.add_argument(
        "--language",
        choices=_known_rule_languages(),
        default=None,
        help="Filter to rules that apply to this language (e.g. ``python``, ``rust``). Omit to list every rule.",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "json", "markdown", "sarif"],
        default="text",
        help="Output format. ``text`` (default) prints an aligned table grouped by category band. ``json`` / ``markdown`` / ``sarif`` emit structured representations of the same catalogue.",
    )
    parser.add_argument(
        "--enabled-only",
        dest="enabled_only",
        action="store_true",
        default=False,
        help="Filter to rules enabled by default (drops opt-in rules). Useful for 'what fires out of the box?' views.",
    )
    return parser


def _print_rule_listing(specs: list, fmt: str) -> None:
    """Render *specs* in *fmt* and emit the result to stdout.

    Centralises every ``print`` / stdout write for the rule catalogue so
    :func:`_run_list_rules` stays a pure orchestrator and the SAFE304
    "calls I/O without naming it" heuristic isn't triggered. ``fmt`` is
    one of the choices argparse already validated.
    """
    from safelint._rule_listing import (  # noqa: PLC0415
        format_json_listing,
        format_markdown_listing,
        format_sarif_listing,
        format_text,
    )

    if fmt == "text":
        sys.stdout.write(format_text(specs))
    elif fmt == "markdown":
        sys.stdout.write(format_markdown_listing(specs))
    elif fmt == "json":
        print(format_json_listing(specs))
    else:  # "sarif"
        print(format_sarif_listing(specs))


def _run_list_rules(args: argparse.Namespace) -> int:
    """Execute the ``list-rules`` subcommand.

    Exit code is 0 on success and 2 when the filter combination matches
    zero rules; the second case is treated as a configuration error so a
    typo in a CI script (``--language pythn``) doesn't silently produce
    an empty document.
    """
    from safelint._rule_listing import filter_specs, iter_rule_specs  # noqa: PLC0415

    specs = filter_specs(
        iter_rule_specs(),
        language=args.language,
        enabled_only=args.enabled_only,
    )
    if not specs:
        _diagnostics.print_error("no rules matched the requested filter")
        return 2
    _print_rule_listing(specs, args.output_format)
    return 0


def _run_skill(args: argparse.Namespace) -> int:
    """Dispatch the ``safelint skill <action>`` subcommands."""
    # Local import keeps importlib.resources off the hot path for
    # check/hook/stdin invocations - only paid when the user explicitly
    # asks for skill management.
    from safelint import _skill_install  # noqa: PLC0415

    if args.skill_action == "install":
        rc = _skill_install.run_install(args)
        # After a successful skill install, scan the project for source
        # files whose language grammar isn't installed and nudge the user
        # toward the matching extras. Symmetric with the existing
        # AI-client auto-detection: skill install handles BOTH "which
        # client does this project use" AND "which grammars does this
        # project need". Only fires on success - a failed install
        # already has its own diagnostics, no point piling on.
        if rc == 0:
            _emit_skill_install_grammar_hint(Path.cwd())
        return rc
    if args.skill_action == "path":
        return _skill_install.run_path(args)
    if args.skill_action == "status":
        return _skill_install.run_status(args)
    if args.skill_action == "update":
        return _skill_install.run_update(args)
    if args.skill_action == "remove":
        return _skill_install.run_remove(args)
    return 1  # pragma: no cover - argparse rejects unknown actions before this


# ── help / version (ruff-style top-level CLI surface) ───────────────────────
# safelint mirrors ruff's help layout deliberately so users moving between the
# two tools get a familiar experience: a one-line tagline, ``Usage:`` line,
# ``Commands:``, ``Options:``, and ``Global options:`` sections with bold
# section headers and cyan command/flag names. Activated *only* via
# ``safelint help``, ``safelint -h``, or ``safelint --help``. A bare
# ``safelint`` invocation does NOT show this top-level help - it continues
# through the normal hook-mode routing (silent on success when no
# supported source files are passed) so pre-commit's contract is preserved.


_HELP_COMMANDS: tuple[tuple[str, str], ...] = (
    ("check", "Scan a file or directory for safety violations"),
    ("skill", "Manage the bundled AI-client skill / project rule (Claude, Cursor, Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed, Warp)"),
    ("list-rules", "Print the rule catalogue (filter by --language, render as text / json / markdown / sarif)"),
    ("help", "Print this message or the help of the given subcommand"),
    ("version", "Display SafeLint's version"),
)


# Mirrors the per-subcommand ``help=`` strings on the ``skill`` subparsers
# in ``_build_skill_parser``. Listed at the top level for discoverability -
# ``safelint help`` should make the full lifecycle visible without
# requiring a second ``safelint help skill`` round-trip.
_HELP_SKILL_SUBCOMMANDS: tuple[tuple[str, str], ...] = (
    ("skill install", "Install the bundled skill / rule into the AI client(s) detected for this project"),
    ("skill update", "Refresh installed skills whose content has drifted from the bundled wheel"),
    ("skill remove", "Delete detected installed skills (filterable by client / scope / shape)"),
    ("skill status", "Compare every detected installed skill against the bundled version"),
    ("skill path", "Print the on-disk location of a bundled skill / rule / instructions file (use --client to pick which)"),
)


# Common flags shared across the skill subcommands. Each subcommand has
# its own subset (e.g. ``--dry-run`` is ``remove`` only) - the per-action
# parser is the source of truth. Listed here so users see ``--force``
# and friends without first running ``safelint help skill <action>``.
_HELP_SKILL_FLAGS: tuple[tuple[str, str], ...] = (
    (
        "--client <NAME>",
        "Target AI client: ``auto`` | ``claude`` | ``cursor`` | ``copilot`` | ``gemini`` | ``windsurf`` | ``codex`` | ``continue`` | ``cline`` | ``aider`` | ``trae`` | ``antigravity`` | ``zed`` | ``warp``",  # noqa: E501
    ),
    ("--project", "Restrict to project-scope installs (``<cwd>/.<client>/...``)"),
    ("--symlink", "Use symlink mode instead of copying - ``pip upgrade safelint`` then auto-updates the artefact"),
    ("--force", "``install``: replace existing artefact. ``update``: refresh even when status reports fresh"),
    ("--path <PATH>", "(``remove`` only) Override auto-detect with an explicit install path"),
    ("--dry-run", "(``remove`` only) Preview removals without touching the filesystem"),
)


_HELP_OPTIONS: tuple[tuple[str, str], ...] = (
    ("-h, --help", "Print help (see a summary with -h)"),
    ("-V, --version", "Print version"),
    ("--list-rules", "Alias for the ``list-rules`` subcommand"),
)


_HELP_GLOBAL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("--fail-on <LEVEL>", "Minimum severity that blocks the run: ``error`` | ``warning``"),
    ("--mode <MODE>", "Execution mode: ``local`` (only errors block) | ``ci`` (warnings block too)"),
    ("--ignore <CODE>", "Repeatable; suppress a rule for this run (stacks on top of config ``ignore``)"),
    ("--format <FORMAT>", "Output format: ``pretty`` (default) | ``json`` | ``sarif``"),
    ("--statistics", "Print a per-rule violation count summary at the end of the run"),
    ("--no-cache", "Disable the per-file lint-result cache"),
    ("--stdin", "Read source from stdin (editor mode)"),
    ("--stdin-filename <PATH>", "Pseudo-filename for stdin input; drives language detection by extension"),
)


def _print_main_help() -> None:
    """Print the top-level help in a ruff-inspired format with ANSI colour.

    The layout, typography, and section ordering deliberately mirror
    ``ruff --help`` so users moving between tools get a familiar
    experience. Colour is auto-disabled when stdout is not a TTY (see
    ``_c``), so piping to a file produces clean text.
    """
    tagline = _c("SafeLint", _BOLD, _GREEN) + ": Holzmann-inspired safety lint rules and pre-commit integration for Python, JavaScript, and TypeScript."
    print(tagline)
    print()
    print(f"{_c('Usage:', _BOLD)} {_c('safelint', _CYAN)} [OPTIONS] <COMMAND>")
    print()
    print(_c("Commands:", _BOLD))
    _print_help_table(_HELP_COMMANDS, name_colour=_CYAN)
    print()
    print(_c("Skill subcommands:", _BOLD))
    _print_help_table(_HELP_SKILL_SUBCOMMANDS, name_colour=_CYAN)
    print()
    print(_c("Skill flags:", _BOLD))
    _print_help_table(_HELP_SKILL_FLAGS, name_colour=_CYAN)
    print()
    print(_c("Options:", _BOLD))
    _print_help_table(_HELP_OPTIONS, name_colour=_CYAN)
    print()
    print(_c("Global options:", _BOLD))
    _print_help_table(_HELP_GLOBAL_OPTIONS, name_colour=_CYAN)
    print()
    print(f"For help with a specific command, see: `{_c('safelint help <command>', _CYAN)}`.")


def _print_help_table(rows: tuple[tuple[str, str], ...], *, name_colour: str) -> None:
    """Render a two-column ``name  description`` table aligned to the widest name."""
    width = max(len(name) for name, _ in rows)
    for name, desc in rows:
        padding = " " * (width - len(name) + 2)
        print(f"  {_c(name, name_colour)}{padding}{desc}")


def _print_version() -> None:
    """Print the running safelint version in the conventional ``safelint X.Y.Z`` form."""
    from safelint import __version__  # noqa: PLC0415

    print(f"safelint {__version__}")


def _print_subcommand_help(subcommand: str) -> int:
    """Defer to the relevant argparse parser's --help for subcommand-specific help.

    ``safelint help check`` should produce the same output as
    ``safelint check --help``. Argparse's auto-generated help is good
    enough at the subcommand level; only the top-level (where we have
    multiple parsers) needs the hand-rolled formatter.
    """
    if subcommand == "check":
        _build_check_parser().parse_args(["--help"])
    elif subcommand == "skill":
        _build_skill_parser().parse_args(["--help"])
    elif subcommand == "list-rules":
        _build_list_rules_parser().parse_args(["--help"])
    elif subcommand in ("help", "version"):
        _print_main_help()
    else:
        print(f"safelint: unknown command '{subcommand}'", file=sys.stderr)
        print("Run `safelint help` to see the list of supported commands.", file=sys.stderr)
        return 2
    return 0


def _next_positional(argv: list[str], start: int) -> str | None:
    """Return the first positional token at or after *start*, skipping flags.

    Mirrors :func:`_first_positional_index`'s skip rules: value-taking
    long options consume the following token, store-true flags are
    just skipped. Used by :func:`_is_top_level_help_request` to find
    the optional ``<sub>`` after the ``help`` keyword even when global
    flags are interleaved (``safelint help --format json check`` →
    ``check``).
    """
    skip_next = False
    for arg in argv[start:]:
        if skip_next:
            skip_next = False
            continue
        if arg in _VALUE_TAKING_OPTIONS:
            skip_next = True
            continue
        if not arg.startswith("-"):
            return arg
    return None


def _is_top_level_help_request() -> tuple[bool, str | None]:
    """Detect ``safelint help [<cmd>]`` / ``safelint -h`` / ``safelint --help``.

    Returns ``(matched, sub)`` where *matched* is True when the invocation
    is asking for top-level help, and *sub* is the subcommand to defer to
    (or None for the unfiltered top-level help). The check runs *before*
    argparse so we can intercept ``-h`` / ``--help`` even when no command
    is supplied - argparse would otherwise produce its own less polished
    output.

    The scan walks the full argv with the same value-skipping rules as
    :func:`_first_positional_index`, so global flags placed before the
    help marker (``safelint --format json --help``) don't shadow it.
    The scan stops at the first non-``help`` positional, ceding
    subcommand-specific help (``safelint check --help``) to argparse -
    matching the layout where each subcommand owns its own usage line.
    """
    rest = sys.argv[1:]
    skip_next = False
    for i, arg in enumerate(rest):
        if skip_next:
            skip_next = False
            continue
        if arg in _VALUE_TAKING_OPTIONS:
            skip_next = True
            continue
        if arg in ("-h", "--help"):
            return True, None
        if arg.startswith("-"):
            continue
        if arg == "help":
            return True, _next_positional(rest, i + 1)
        return False, None
    return False, None


def _strip_list_rules_flag(argv: list[str]) -> list[str] | None:
    """Detect ``--list-rules`` anywhere in *argv* and return *argv* without it.

    Returns ``None`` when ``--list-rules`` is absent. The flag is the
    user-facing alias for the ``list-rules`` subcommand; treat any
    invocation containing it as if the user wrote ``safelint list-rules
    <other-flags>``. Removes every occurrence of the literal
    ``--list-rules`` token (the flag is a boolean toggle, so there's
    no ``--list-rules=value`` form to consider); argparse then parses
    the remaining argv with the subcommand's parser so flag-typo
    guarantees stay intact.
    """
    if "--list-rules" not in argv:
        return None
    return [a for a in argv if a != "--list-rules"]


def _is_version_request() -> bool:
    """Detect ``safelint -V`` / ``safelint --version`` / ``safelint version``.

    Mirrors :func:`_is_top_level_help_request`'s position-independent
    scan, so ``safelint --format json --version`` reaches the polished
    version renderer instead of falling through to a parser that would
    reject ``--version`` as an unknown flag.
    """
    rest = sys.argv[1:]
    skip_next = False
    for arg in rest:
        if skip_next:
            skip_next = False
            continue
        if arg in _VALUE_TAKING_OPTIONS:
            skip_next = True
            continue
        if arg in ("-V", "--version"):
            return True
        if arg.startswith("-"):
            continue
        return arg == "version"
    return False


def _dispatch_subcommand(rest: list[str], idx: int) -> int | None:
    """Route the first-positional token at *idx* to its subcommand handler.

    Returns the subcommand's exit code, or ``None`` if the token at
    *idx* isn't a recognised subcommand (caller then falls through to
    hook mode). Each branch drops the token but keeps every surrounding
    flag so ``safelint --format json check src`` parses as
    ``--format json src`` against the subcommand parser.
    """
    subcommand = rest[idx]
    argv_for_sub = rest[:idx] + rest[idx + 1 :]
    if subcommand == "check":
        return _run_check(_build_check_parser().parse_args(argv_for_sub))
    if subcommand == "list-rules":
        return _run_list_rules(_build_list_rules_parser().parse_args(argv_for_sub))
    if subcommand == "skill":
        return _run_skill(_build_skill_parser().parse_args(argv_for_sub))
    return None


def main() -> None:
    """Entry point for direct CLI invocation, pre-commit hook, and stdin mode.

    Routing logic (in order):
    - ``-h`` / ``--help`` / ``help`` (with optional subcommand) → print help.
    - ``-V`` / ``--version`` / ``version`` → print version and exit.
    - ``--list-rules`` anywhere → ``list-rules`` subcommand (flag alias).
    - ``--stdin`` anywhere in argv → read source from stdin (editor mode).
    - First true positional argument is ``check`` / ``list-rules`` /
      ``skill`` → the matching subcommand.
    - Otherwise → pre-commit hook mode (positional arguments whose extension
      is in :func:`safelint.languages.supported_extensions` are files).

    Global flags (``--format``, ``--fail-on``, ``--mode``, ``--ignore``,
    ``--config``, ``--stdin-filename``) may appear before the subcommand;
    the scanner skips their values so ``safelint --format json check src``
    is routed correctly.
    """
    is_help, sub = _is_top_level_help_request()
    if is_help:
        if sub is None:
            _print_main_help()
            sys.exit(0)
        sys.exit(_print_subcommand_help(sub))
    if _is_version_request():
        _print_version()
        sys.exit(0)

    stripped = _strip_list_rules_flag(sys.argv[1:])
    if stripped is not None:
        args = _build_list_rules_parser().parse_args(stripped)
        sys.exit(_run_list_rules(args))

    if "--stdin" in sys.argv[1:]:
        args = _build_stdin_parser().parse_args()
        sys.exit(_run_stdin(args))

    rest = sys.argv[1:]
    idx = _first_positional_index(rest)
    if idx is not None:
        rc = _dispatch_subcommand(rest, idx)
        if rc is not None:
            sys.exit(rc)
    sys.exit(_dispatch_hook_mode())


def _dispatch_hook_mode() -> int:
    """Pre-commit hook entry path used by :func:`main` when no subcommand matched.

    Parses positional file arguments, filters to supported extensions,
    runs the silent-failure guard (exits with code 2 if every file
    would be skipped for a missing grammar), and otherwise hands off
    to :func:`_run_hook`. Extracted from :func:`main` to keep that
    function's cyclomatic complexity below the project's safelint cap.

    **Per-extension warnings are emitted only for *mixed* runs** - runs
    where some files lint successfully and others get skipped. In the
    silent-failure case (every file dropped for a missing grammar), the
    error message from :func:`_guard_hook_silent_failure` already
    carries the install hint, so the per-extension warning would just
    duplicate it. That duplication is especially loud under pre-commit:
    pre-commit batches files across multiple hook invocations to stay
    under OS argv limits, and every batch invocation would otherwise
    emit the same warning + error pair (22 lines for 11 batches). The
    guard error fires once per invocation either way, but skipping the
    warning halves the noise.
    """
    args = _build_hook_parser().parse_args()
    extensions = tuple(supported_extensions())
    files = [f for f in args.files if f.endswith(extensions)]

    # Compute the missing-grammar set without emitting warnings yet so we
    # can decide whether per-extension warnings would add useful context
    # or just duplicate the silent-failure error below.
    unavailable_in_passed = _matching_suffixes(args.files, unavailable_extensions())
    will_silent_fail = bool(args.files and not files and unavailable_in_passed)
    if will_silent_fail:
        return _guard_hook_silent_failure(args.files, files, unavailable_in_passed)

    # Mixed run (or no missing-grammar files at all) - emit per-extension
    # warnings as actionable context for the skipped files, then lint
    # what we have. Machine output modes suppress the warnings to keep
    # stderr parseable; the set-return is not consulted here because
    # we've already decided the guard won't fire.
    output_format: str = getattr(args, "output_format", "pretty")
    _emit_hook_grammar_warnings(args.files, silent=(output_format != "pretty"))
    return _run_hook(args, files)


if __name__ == "__main__":
    main()
