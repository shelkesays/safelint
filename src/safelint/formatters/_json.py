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

    from safelint.rules.base import Suggestion, TextEdit, Violation


def _violation_to_dict(v: Violation) -> dict[str, Any]:
    """Render a Violation as a JSON-friendly dict.

    Position fields (``end_lineno``, ``column_start``, ``column_end``)
    were added in safelint 1.7.0. They may be ``null`` for synthetic
    violations without a Tree-sitter node (e.g. ``test_existence``
    reports against a missing file with no source span). Editor
    consumers should treat ``column_start == null`` as "underline the
    whole line".

    For multi-line constructs (``end_lineno > lineno``), ``column_end``
    is the column on ``end_lineno``, not on ``lineno`` — the four
    fields together specify a half-open ``[start, end)`` range that
    maps cleanly to LSP / VSCode ``Range`` semantics.

    *Added in 1.10.0:* the ``suggestions`` array carries advisory
    fixes the rule offers. **Editors and CI tools must never apply
    these automatically** — every edit goes through user
    confirmation. Each suggestion has a one-line ``description`` and
    zero or more ``edits`` (range + replacement text). Empty array
    when the rule has no fix to offer.
    """
    return {
        "code": v.code,
        "rule": v.rule,
        "severity": v.severity,
        "filepath": v.filepath,
        "lineno": v.lineno,
        "end_lineno": v.end_lineno,
        "column_start": v.column_start,
        "column_end": v.column_end,
        "message": v.message,
        "suggestions": [_suggestion_to_dict(s) for s in v.suggestions],
    }


def _suggestion_to_dict(s: Suggestion) -> dict[str, Any]:
    """Render a :class:`Suggestion` as a JSON-friendly dict.

    Strict attribute access. ``Violation.suggestions`` is always a
    ``tuple[Suggestion, ...]`` at runtime — the cache pipeline
    reconstructs dataclasses on read (see ``core/_cache.py:
    _dict_to_violation``), so by the time a violation reaches the
    formatter, its suggestions are dataclass instances. A non-Suggestion
    value here is a programming error worth surfacing as
    :class:`AttributeError` rather than silently producing a partial
    document.
    """
    return {
        "description": s.description,
        "edits": [_edit_to_dict(e) for e in s.edits],
    }


def _edit_to_dict(e: TextEdit) -> dict[str, Any]:
    """Render a :class:`TextEdit` as a JSON-friendly dict.

    Strict attribute access — see :func:`_suggestion_to_dict` for the
    rationale.
    """
    return {
        "start_line": e.start_line,
        "start_column": e.start_column,
        "end_line": e.end_line,
        "end_column": e.end_column,
        "replacement": e.replacement,
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
