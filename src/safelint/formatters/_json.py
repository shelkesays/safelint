r"""Compact JSON formatter for safelint output.

Designed for tooling consumers (editor plugins, CI scripts, the upcoming
Claude Code skill) that need a stable, machine-readable shape rather than
parsing the human-friendly ruff/ty-style text.

Top-level shape::

    {
      "version": "1.5.0",
      "summary": {
        "files_checked": 12,
        "violations": 5,
        "errors": 2,
        "warnings": 3,
        "blocking": 2,
        "fail_on": "warning",
        "suppressed": {
          "total": 4,
          "by_code": {"SAFE501": 3, "SAFE304": 1}
        }
      },
      "violations": [
        {
          "code": "SAFE101",
          "rule": "function_length",
          "severity": "error",
          "filepath": "src/foo.py",
          "lineno": 42,
          "message": "Function \"bar\" is 80 lines (max 60)"
        }
      ],
      "suppressed": [...]
    }

Design notes:
* No ANSI escapes anywhere — output is safe to pipe / cat / parse.
* Top-level ``version`` is the safelint version producing the document.
* Counts in ``summary`` mirror what the pretty formatter would have shown.
* ``violations`` and ``suppressed`` are flat lists ordered as encountered.
* The schema is intentionally narrow (no per-rule URLs, no fix data)
  so the contract is small and easy to extend later.
"""

from __future__ import annotations

from collections import Counter
import json
from typing import TYPE_CHECKING, Any

from safelint import __version__


if TYPE_CHECKING:
    from collections.abc import Iterable

    from safelint.rules.base import Violation


def _violation_to_dict(v: Violation) -> dict[str, Any]:
    """Render a Violation as a JSON-friendly dict.

    ``column_start`` and ``column_end`` are present in the output (added
    in safelint 1.7.0) and may be ``null`` for synthetic violations
    that don't have a Tree-sitter node to position against (e.g.
    ``test_existence`` reports against a missing file with no source
    span). Editor consumers should treat ``null`` as "underline the
    whole line".
    """
    return {
        "code": v.code,
        "rule": v.rule,
        "severity": v.severity,
        "filepath": v.filepath,
        "lineno": v.lineno,
        "column_start": v.column_start,
        "column_end": v.column_end,
        "message": v.message,
    }


def _build_summary(
    violations: Iterable[Violation],
    suppressed: Iterable[Violation],
    *,
    blocking_count: int,
    fail_on: str,
    files_checked: int,
) -> dict[str, Any]:
    """Build the top-level ``summary`` block."""
    violations_list = list(violations)
    n_errors = sum(1 for v in violations_list if v.severity == "error")
    n_warnings = sum(1 for v in violations_list if v.severity == "warning")
    suppressed_list = list(suppressed)
    suppressed_counts = Counter(v.code or v.rule for v in suppressed_list)
    return {
        "files_checked": files_checked,
        "violations": len(violations_list),
        "errors": n_errors,
        "warnings": n_warnings,
        "blocking": blocking_count,
        "fail_on": fail_on,
        "suppressed": {
            "total": len(suppressed_list),
            "by_code": dict(sorted(suppressed_counts.items())),
        },
    }


def format_json(
    violations: list[Violation],
    suppressed: list[Violation],
    *,
    blocking_count: int,
    fail_on: str,
    files_checked: int,
    indent: int | None = 2,
) -> str:
    """Return a JSON document representing *violations* + *suppressed*.

    ``indent=2`` (default) makes the output human-skimmable; pass
    ``indent=None`` for a single-line compact form when piping through
    another tool that re-formats.
    """
    document = {
        "version": __version__,
        "summary": _build_summary(
            violations,
            suppressed,
            blocking_count=blocking_count,
            fail_on=fail_on,
            files_checked=files_checked,
        ),
        "violations": [_violation_to_dict(v) for v in violations],
        "suppressed": [_violation_to_dict(v) for v in suppressed],
    }
    return json.dumps(document, indent=indent, ensure_ascii=False)
