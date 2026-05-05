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

import contextlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from safelint import __version__


if TYPE_CHECKING:
    from safelint.rules.base import TextEdit, Violation


_SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json"
_SARIF_VERSION = "2.1.0"
_INFORMATION_URI = "https://github.com/shelkesays/safelint"


def _level(severity: str) -> str:
    """Map safelint severity to SARIF level."""
    if severity == "warning":
        return "warning"
    # "error" + any unknown severity treated as error (matches partition_violations).
    return "error"


def _artifact_uri(filepath: str) -> str:
    r"""Return a SARIF-conformant URI for *filepath*.

    SARIF ``artifactLocation.uri`` must be a valid URI reference (RFC 3986).
    Raw filepaths can fail that contract on Windows (backslash separators
    aren't legal URI characters) and for absolute paths that begin with a
    drive letter or root slash.

    Behaviour:

    * Backslash separators are normalised to forward slashes *before*
      constructing the ``Path``. ``pathlib.PosixPath`` would otherwise
      treat ``\\`` as part of the filename on a POSIX runner, so a SARIF
      file produced on Linux that's about to be uploaded to GitHub code
      scanning would still leak Windows-style backslashes through.
    * Absolute paths are converted to a path *relative to cwd* when
      possible — keeps the SARIF artefact list short and consumable
      (GitHub code scanning treats ``uri`` as repo-relative). Falls back
      to the absolute POSIX form for paths outside cwd.
    * Special characters (spaces, ``#``, ``?``) are percent-encoded;
      the path separator ``/`` is preserved.
    """
    p = Path(filepath.replace("\\", "/"))
    if p.is_absolute():
        with contextlib.suppress(ValueError):
            # Outside cwd — fall back to the absolute form.
            p = p.relative_to(Path.cwd())
    return quote(p.as_posix(), safe="/")


def _build_region(v: Violation) -> dict[str, Any]:
    """Build the SARIF ``region`` block for *v*.

    Always includes ``startLine``. The optional ``endLine`` /
    ``startColumn`` / ``endColumn`` fields are added only when the
    violation carries the corresponding data (rules with a Tree-sitter
    node attach all of them; synthetic file-level violations like
    ``test_existence`` don't). All values are 1-based, matching
    safelint's convention and SARIF 2.1.0's contract.

    ``endLine`` is omitted when it equals ``startLine`` — per SARIF
    spec, an absent ``endLine`` defaults to ``startLine``, so emitting
    a redundant value just bloats the output. When emitted, it
    correctly anchors ``endColumn`` to the end-line of multi-line
    constructs (function definitions, except clauses, while loops),
    instead of letting consumers mistakenly assume ``endColumn``
    applied to ``startLine``.
    """
    region: dict[str, Any] = {"startLine": v.lineno}
    if v.column_start is not None:
        region["startColumn"] = v.column_start
    if v.end_lineno is not None and v.end_lineno != v.lineno:
        region["endLine"] = v.end_lineno
    if v.column_end is not None:
        region["endColumn"] = v.column_end
    return region


def _build_fixes(v: Violation) -> list[dict[str, Any]]:
    """Build SARIF ``fixes[]`` entries from the violation's suggestions.

    Each returned item is a SARIF fix object containing both a
    ``description`` and an ``artifactChanges`` array — the function's
    output goes straight into a ``result.fixes`` array, one fix per
    *actionable* :class:`Suggestion` on the violation.

    Description-only suggestions (those with ``edits == ()``) are
    skipped: SARIF 2.1.0 spec says ``fix.artifactChanges[].replacements``
    *SHALL* contain at least one element, so emitting a fix with no
    replacements would produce a non-conformant document. The
    description-only form is still a valid :class:`Suggestion` — a
    hint without a mechanical recipe — and remains in the JSON
    output (see :mod:`safelint.formatters._json`); it just doesn't
    translate cleanly to SARIF's "apply this to fix it" model. If
    every suggestion on a violation is description-only, this
    function returns ``[]`` and the caller omits the ``fixes`` key
    entirely (avoiding an empty ``fixes: []`` array on the result).

    SARIF 2.1.0's ``fixes`` block is *advisory by spec* — the consumer
    decides whether to apply replacements. That matches safelint's
    review-only posture: editor integrations may render these as
    "Quick Fix" code actions, but every edit goes through user
    confirmation.

    Each actionable suggestion becomes one ``fixes[]`` entry with:

    * ``description.text`` — the suggestion's human-readable summary.
    * ``artifactChanges[]`` — a single artifact-change entry targeting
      the violation's filepath.
    * ``artifactChanges[].artifactLocation.uri`` — the violation's
      filepath (URI-normalised via :func:`_artifact_uri`).
    * ``artifactChanges[].replacements[]`` — one per ``TextEdit``, with
      a ``deletedRegion`` describing the range to replace and an
      ``insertedContent.text`` with the replacement string.

    Direct attribute access (no ``getattr`` defaults) is intentional:
    SARIF output must accurately reflect the structured violation, and
    a missing field on a ``Suggestion`` / ``TextEdit`` is a programming
    error worth surfacing as an :class:`AttributeError` rather than
    silently producing a malformed-but-valid SARIF document.
    """
    artifact = {"uri": _artifact_uri(v.filepath)}
    return [
        {
            "description": {"text": suggestion.description},
            "artifactChanges": [
                {
                    "artifactLocation": artifact,
                    "replacements": [_text_edit_to_replacement(e) for e in suggestion.edits],
                }
            ],
        }
        for suggestion in v.suggestions
        if suggestion.edits  # skip description-only suggestions (SARIF requires ≥1 replacement)
    ]


def _text_edit_to_replacement(edit: TextEdit) -> dict[str, Any]:
    """Render a :class:`TextEdit` as a SARIF ``replacements`` entry.

    Strict attribute access — see :func:`_build_fixes` for
    the rationale. A malformed input fails fast.
    """
    return {
        "deletedRegion": {
            "startLine": edit.start_line,
            "startColumn": edit.start_column,
            "endLine": edit.end_line,
            "endColumn": edit.end_column,
        },
        "insertedContent": {"text": edit.replacement},
    }


def _result_for_violation(v: Violation, *, suppressed: bool) -> dict[str, Any]:
    """Build a SARIF ``results`` entry for one violation."""
    entry: dict[str, Any] = {
        "ruleId": v.code or v.rule,
        "level": _level(v.severity),
        "message": {"text": v.message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": _artifact_uri(v.filepath)},
                    "region": _build_region(v),
                }
            }
        ],
    }
    if suppressed:
        # SARIF "inSource" kind covers both inline ``# nosafe`` directives
        # and per-file ignore patterns — the user-controlled mechanism is
        # close enough that one kind is faithful.
        entry["suppressions"] = [{"kind": "inSource"}]
    if v.suggestions:
        # SARIF ``fixes[]`` is advisory by spec — exactly matches
        # safelint's "review-only, never auto-apply" contract.
        # ``_build_fixes`` skips description-only suggestions (those
        # with empty ``edits``) because SARIF requires ≥1 replacement
        # per fix; the result may therefore be empty even when
        # ``v.suggestions`` is not. Omit the key entirely in that
        # case rather than emitting a ``fixes: []`` array.
        fixes = _build_fixes(v)
        if fixes:
            entry["fixes"] = fixes
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
