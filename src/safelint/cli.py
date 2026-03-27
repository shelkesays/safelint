"""Command-line interface for safelint."""

from __future__ import annotations

import argparse
from pathlib import Path

from safelint.core.runner import run


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the safelint CLI."""
    parser = argparse.ArgumentParser(
        prog="safelint", description="Safety-oriented lint checks for Python code"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check", help="Run lint checks against a file or directory"
    )
    check_parser.add_argument("target", type=Path, help="File or directory to scan")
    check_parser.add_argument("--config", type=Path, help="Path to YAML or JSON config file")
    return parser


def main() -> int:
    """Entry point: parse arguments, run checks, and print violations."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command != "check":
        parser.error(f"Unsupported command: {args.command}")

    results = run(args.target, args.config)
    violation_count = 0
    for result in results:
        for violation in result.violations:
            violation_count += 1
            print(
                f"{result.path}:{violation.line}:{violation.column}: "
                f"{violation.code} {violation.message}"
            )

    if violation_count == 0:
        print("No violations found.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
