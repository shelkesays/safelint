"""SARIF 2.1.0 formatter for safelint output.

SARIF (Static Analysis Results Interchange Format) is the OASIS standard
for static-analysis tool output. GitHub code scanning, Azure DevOps, and
many editor extensions consume it directly.

Reference: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html

This implementation produces a minimally conformant SARIF document with:

* ``runs[].tool.driver`` — name, version, informationUri.
* ``runs[].tool.driver.rules`` — one entry per safelint rule that fired in
  this run, with ``id`` (the SAFE-code) and ``shortDescription``.
* ``runs[].results`` — one entry per active violation, with ``ruleId``,
  ``level`` (error / warning), ``message.text``, and a ``physicalLocation``
  pointing at the file + line.

Suppressed violations are surfaced in ``runs[].results`` with a
``suppressions`` block (kind ``inSource``), matching SARIF's idiomatic
representation of ``# nosafe`` / ``per_file_ignores`` style suppressions.

Severities map: safelint ``error`` → SARIF ``error``;
``warning`` → SARIF ``warning``. SARIF also has ``note`` and ``none`` but
safelint doesn't emit those today.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from safelint import __version__


if TYPE_CHECKING:
    from safelint.rules.base import Violation


_SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json"
_SARIF_VERSION = "2.1.0"
_INFORMATION_URI = "https://github.com/shelkesays/safelint"


def _level(severity: str) -> str:
    """Map safelint severity to SARIF level."""
    if severity == "warning":
        return "warning"
    # "error" + any unknown severity treated as error (matches partition_violations).
    return "error"


def _result_for_violation(v: Violation, *, suppressed: bool) -> dict[str, Any]:
    """Build a SARIF ``results`` entry for one violation."""
    entry: dict[str, Any] = {
        "ruleId": v.code or v.rule,
        "level": _level(v.severity),
        "message": {"text": v.message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": v.filepath},
                    "region": {"startLine": v.lineno},
                }
            }
        ],
    }
    if suppressed:
        # SARIF "inSource" kind covers both inline ``# nosafe`` directives
        # and per-file ignore patterns — the user-controlled mechanism is
        # close enough that one kind is faithful.
        entry["suppressions"] = [{"kind": "inSource"}]
    return entry


def _rules_descriptor_for(violations: list[Violation], suppressed: list[Violation]) -> list[dict[str, Any]]:
    """Build ``tool.driver.rules`` from the unique rules referenced in this run.

    Per SARIF, every ``ruleId`` in ``results`` should map to a descriptor
    in ``tool.driver.rules``. We deduplicate across both active and
    suppressed entries so a suppressed-only rule still gets a descriptor.
    """
    seen: dict[str, dict[str, Any]] = {}
    for v in [*violations, *suppressed]:
        rule_id = v.code or v.rule
        if rule_id in seen:
            continue
        seen[rule_id] = {
            "id": rule_id,
            "name": v.rule,
            "shortDescription": {"text": v.rule.replace("_", " ")},
        }
    # Sort for determinism — easier to diff SARIF output across runs.
    return [seen[k] for k in sorted(seen)]


def format_sarif(
    violations: list[Violation],
    suppressed: list[Violation],
    *,
    blocking_count: int,  # noqa: ARG001 — reserved for future SARIF properties extensions
    fail_on: str,  # noqa: ARG001 — reserved for future SARIF properties extensions
    files_checked: int,  # noqa: ARG001 — reserved for future SARIF properties extensions
    indent: int | None = 2,
) -> str:
    """Return a SARIF 2.1.0 JSON document representing the lint run."""
    rules = _rules_descriptor_for(violations, suppressed)
    results = [
        *(_result_for_violation(v, suppressed=False) for v in violations),
        *(_result_for_violation(v, suppressed=True) for v in suppressed),
    ]
    document = {
        "$schema": _SARIF_SCHEMA,
        "version": _SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "safelint",
                        "version": __version__,
                        "informationUri": _INFORMATION_URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=indent, ensure_ascii=False)
