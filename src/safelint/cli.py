"""Command-line interface for safelint.

Two usage modes
---------------
Pre-commit hook (files passed by pre-commit as positional arguments)::

    safelint [--fail-on=error|warning] [--mode=local|ci] file1.py file2.py …

Direct invocation / CI scan (directory or single file)::

    safelint check <path> [--config <cfg>] [--fail-on=error|warning] [--mode=local|ci]

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
import sys
from pathlib import Path

from safelint.core.config import MODE_FAIL_ON, SEVERITY_ORDER, load_config
from safelint.core.engine import SafetyEngine
from safelint.core.runner import run
from safelint.rules.base import Violation


def _print_file_violations(filepath: str, violations: list[Violation]) -> None:
    """Print violations for a single file in human-readable format."""
    print(f"\n{'─' * 64}")
    print(f"  {filepath}")
    print(f"{'─' * 64}")
    for v in violations:
        icon = "❌" if v.severity == "error" else "⚠️ "
        tag = f"{v.code}" if v.code else v.rule
        print(f"  {icon}  {tag} [{v.rule}] line {v.lineno}: {v.message}")


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

    for filepath in files:
        violations = engine.check_file(filepath)
        if not violations:
            continue
        _print_file_violations(filepath, violations)
        blocking, advisory = engine.partition_violations(violations, fail_threshold)
        all_blocking.extend(blocking)
        all_advisory.extend(advisory)

    print()
    if all_advisory:
        print(
            f"⚠️  {len(all_advisory)} advisory violation(s) - below --fail-on={fail_on} threshold."
        )
    if all_blocking:
        count = len(all_blocking)
        print(f"🚫 {count} violation(s) at or above --fail-on={fail_on} - commit rejected.")
        return 1

    print("✅ All safety checks passed.")
    return 0


def _run_check(args: argparse.Namespace) -> int:
    """Execute directory/file scan mode."""
    config_path = getattr(args, "config", None)
    results = run(args.target, config_path=config_path)

    config = load_config(Path(config_path).parent if config_path else Path(args.target))
    fail_on, fail_threshold = _resolve_fail_on(args, config)

    # Reuse engine's partition helper
    dummy_engine = SafetyEngine.__new__(SafetyEngine)
    dummy_engine.exclude_paths = []

    all_blocking: list[Violation] = []
    all_advisory: list[Violation] = []

    for result in results:
        if not result.violations:
            continue
        _print_file_violations(result.path, result.violations)
        blocking, advisory = dummy_engine.partition_violations(result.violations, fail_threshold)
        all_blocking.extend(blocking)
        all_advisory.extend(advisory)

    print()
    if all_advisory:
        print(
            f"⚠️  {len(all_advisory)} advisory violation(s) - below --fail-on={fail_on} threshold."
        )
    if all_blocking:
        print(f"🚫 {len(all_blocking)} violation(s) at or above --fail-on={fail_on} - not clean.")
        return 1

    if not any(r.violations for r in results):
        print("✅ All safety checks passed.")
    return 0


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
            help="Directory or path used as the search root for .safelint.yaml",
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
