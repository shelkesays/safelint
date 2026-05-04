"""Tests for the JSON and SARIF output formatters."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from safelint import __version__
from safelint.formatters import format_json, format_sarif
from safelint.rules.base import Violation


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _v(severity: str = "error", code: str = "SAFE101", rule: str = "function_length", lineno: int = 10) -> Violation:
    """Helper to build a minimal Violation for tests."""
    return Violation(
        rule=rule,
        code=code,
        filepath="src/foo.py",
        lineno=lineno,
        message=f"sample {rule} message",
        severity=severity,
    )


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------


def test_json_empty_run_has_well_formed_summary() -> None:
    """A clean run still produces a parseable JSON document with zero counts."""
    out = format_json([], [], blocking_count=0, fail_on="error", files_checked=0)
    doc = json.loads(out)
    assert "version" in doc
    assert doc["summary"]["files_checked"] == 0
    assert doc["summary"]["violations"] == 0
    assert doc["summary"]["blocking"] == 0
    assert doc["summary"]["suppressed"]["total"] == 0
    assert doc["violations"] == []
    assert doc["suppressed"] == []


def test_json_violation_structure() -> None:
    """Each violation dict carries the documented fields."""
    out = format_json(
        [_v(severity="error", code="SAFE101", rule="function_length", lineno=42)],
        [],
        blocking_count=1,
        fail_on="error",
        files_checked=1,
    )
    doc = json.loads(out)
    assert doc["summary"]["violations"] == 1
    assert doc["summary"]["errors"] == 1
    assert doc["summary"]["warnings"] == 0
    v = doc["violations"][0]
    # Position fields (end_lineno, column_start, column_end) default to None
    # for synthetic test Violations (added in 1.7.0). suggestions defaults to
    # an empty list (added in 1.10.0). Real rules attach Tree-sitter positions
    # and may attach suggestions.
    assert v == {
        "code": "SAFE101",
        "rule": "function_length",
        "severity": "error",
        "filepath": "src/foo.py",
        "lineno": 42,
        "message": "sample function_length message",
        "end_lineno": None,
        "column_start": None,
        "column_end": None,
        "suggestions": [],
    }


def test_json_violation_includes_full_range_when_present() -> None:
    """Multi-line violations carry start/end lines + columns through JSON."""
    out = format_json(
        [Violation(rule="function_length", code="SAFE101", filepath="src/foo.py", lineno=42, message="m", severity="error", column_start=1, column_end=9, end_lineno=68)],
        [],
        blocking_count=1,
        fail_on="error",
        files_checked=1,
    )
    doc = json.loads(out)
    v = doc["violations"][0]
    assert v["lineno"] == 42
    assert v["end_lineno"] == 68
    assert v["column_start"] == 1
    assert v["column_end"] == 9


def test_json_violation_includes_suggestions_when_present() -> None:
    """Suggestions on a Violation round-trip through the JSON formatter (1.10.0)."""
    from safelint.rules.base import Suggestion, TextEdit  # noqa: PLC0415

    edit = TextEdit(start_line=4, start_column=5, end_line=4, end_column=12, replacement="except Exception:")
    sug = Suggestion(description="Catch Exception", edits=(edit,))
    v = Violation(
        rule="bare_except",
        code="SAFE201",
        filepath="src/foo.py",
        lineno=4,
        message="m",
        severity="error",
        suggestions=(sug,),
    )
    doc = json.loads(format_json([v], [], blocking_count=1, fail_on="error", files_checked=1))
    suggestions = doc["violations"][0]["suggestions"]
    assert suggestions == [
        {
            "description": "Catch Exception",
            "edits": [{"start_line": 4, "start_column": 5, "end_line": 4, "end_column": 12, "replacement": "except Exception:"}],
        }
    ]


def test_sarif_violation_with_suggestions_emits_fixes_block() -> None:
    """SARIF ``fixes[]`` is populated from suggestions; native advisory by spec (1.10.0)."""
    from safelint.rules.base import Suggestion, TextEdit  # noqa: PLC0415

    edit = TextEdit(start_line=4, start_column=5, end_line=4, end_column=12, replacement="except Exception:")
    sug = Suggestion(description="Catch Exception", edits=(edit,))
    v = Violation(
        rule="bare_except",
        code="SAFE201",
        filepath="src/foo.py",
        lineno=4,
        message="m",
        severity="error",
        suggestions=(sug,),
    )
    doc = json.loads(format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1))
    fixes = doc["runs"][0]["results"][0]["fixes"]
    assert len(fixes) == 1
    fix = fixes[0]
    assert fix["description"]["text"] == "Catch Exception"
    rep = fix["artifactChanges"][0]["replacements"][0]
    assert rep["deletedRegion"] == {"startLine": 4, "startColumn": 5, "endLine": 4, "endColumn": 12}
    assert rep["insertedContent"]["text"] == "except Exception:"


def test_sarif_violation_without_suggestions_omits_fixes_block() -> None:
    """No suggestions → no ``fixes`` key on the result (matches SARIF optional-field convention)."""
    v = Violation(rule="r", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error")
    doc = json.loads(format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1))
    assert "fixes" not in doc["runs"][0]["results"][0]


def test_json_summary_counts_errors_and_warnings_separately() -> None:
    """Mixed-severity input produces separate error / warning counts."""
    violations = [
        _v(severity="error", code="SAFE101"),
        _v(severity="error", code="SAFE102"),
        _v(severity="warning", code="SAFE304"),
    ]
    out = format_json(violations, [], blocking_count=2, fail_on="warning", files_checked=3)
    doc = json.loads(out)
    assert doc["summary"]["errors"] == 2
    assert doc["summary"]["warnings"] == 1
    assert doc["summary"]["fail_on"] == "warning"


def test_json_suppressed_breakdown_groups_by_code() -> None:
    """``suppressed.by_code`` reports counts per rule code."""
    suppressed = [_v(code="SAFE501"), _v(code="SAFE501"), _v(code="SAFE304")]
    out = format_json([], suppressed, blocking_count=0, fail_on="error", files_checked=2)
    doc = json.loads(out)
    assert doc["summary"]["suppressed"]["total"] == 3
    assert doc["summary"]["suppressed"]["by_code"] == {"SAFE304": 1, "SAFE501": 2}
    assert len(doc["suppressed"]) == 3


def test_json_includes_safelint_version() -> None:
    """Top-level ``version`` matches the package metadata."""
    out = format_json([], [], blocking_count=0, fail_on="error", files_checked=0)
    doc = json.loads(out)
    assert doc["version"] == __version__


def test_json_compact_form_when_indent_none() -> None:
    """``indent=None`` produces a single-line JSON string for piping."""
    out = format_json([], [], blocking_count=0, fail_on="error", files_checked=0, indent=None)
    assert "\n" not in out


# ---------------------------------------------------------------------------
# SARIF formatter
# ---------------------------------------------------------------------------


def test_sarif_minimal_document_is_valid() -> None:
    """An empty run produces a SARIF 2.1.0 document with the required keys."""
    out = format_sarif([], [], blocking_count=0, fail_on="error", files_checked=0)
    doc = json.loads(out)
    assert doc["version"] == "2.1.0"
    assert doc["$schema"].endswith("sarif-schema-2.1.0.json")
    assert len(doc["runs"]) == 1
    driver = doc["runs"][0]["tool"]["driver"]
    assert driver["name"] == "safelint"
    assert driver["informationUri"].startswith("https://")
    assert "version" in driver
    assert driver["rules"] == []
    assert doc["runs"][0]["results"] == []


def test_sarif_violation_becomes_result_with_location() -> None:
    """A violation maps to a result with ruleId, level, message, and physicalLocation."""
    out = format_sarif(
        [_v(severity="error", code="SAFE101", rule="function_length", lineno=42)],
        [],
        blocking_count=1,
        fail_on="error",
        files_checked=1,
    )
    doc = json.loads(out)
    results = doc["runs"][0]["results"]
    assert len(results) == 1
    r = results[0]
    assert r["ruleId"] == "SAFE101"
    assert r["level"] == "error"
    assert r["message"]["text"] == "sample function_length message"
    loc = r["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "src/foo.py"
    assert loc["region"]["startLine"] == 42


def test_sarif_warning_severity_maps_to_warning_level() -> None:
    """``severity == "warning"`` maps to SARIF ``"warning"``; everything else → ``"error"``."""
    out = format_sarif(
        [_v(severity="warning", code="SAFE304"), _v(severity="error", code="SAFE101"), _v(severity="critical", code="SAFE000")],
        [],
        blocking_count=2,
        fail_on="warning",
        files_checked=1,
    )
    doc = json.loads(out)
    levels = [r["level"] for r in doc["runs"][0]["results"]]
    assert levels == ["warning", "error", "error"]


def test_sarif_suppressed_violations_carry_in_source_marker() -> None:
    """Suppressed entries appear in results with a ``suppressions`` block."""
    out = format_sarif(
        [],
        [_v(code="SAFE501")],
        blocking_count=0,
        fail_on="error",
        files_checked=1,
    )
    doc = json.loads(out)
    results = doc["runs"][0]["results"]
    assert len(results) == 1
    assert results[0].get("suppressions") == [{"kind": "inSource"}]


def test_sarif_region_includes_columns_when_present() -> None:
    """Single-line violations with column data emit startLine + columns; endLine is omitted (defaults to startLine per SARIF spec)."""
    v = Violation(rule="function_length", code="SAFE101", filepath="src/foo.py", lineno=42, message="m", severity="error", column_start=5, column_end=18, end_lineno=42)
    out = format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1)
    doc = json.loads(out)
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region == {"startLine": 42, "startColumn": 5, "endColumn": 18}
    assert "endLine" not in region


def test_sarif_region_emits_end_line_for_multi_line_constructs() -> None:
    """Multi-line violations emit region.endLine so endColumn is correctly anchored."""
    v = Violation(rule="function_length", code="SAFE101", filepath="src/foo.py", lineno=42, message="m", severity="error", column_start=1, column_end=9, end_lineno=68)
    out = format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1)
    doc = json.loads(out)
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region == {"startLine": 42, "startColumn": 1, "endLine": 68, "endColumn": 9}


def test_sarif_region_omits_columns_when_absent() -> None:
    """Violations without column data emit only startLine."""
    v = Violation(rule="parse", code="SAFE000", filepath="src/foo.py", lineno=0, message="m", severity="error")
    out = format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1)
    doc = json.loads(out)
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region == {"startLine": 0}


def test_sarif_artifact_uri_normalises_windows_separators() -> None:
    """Backslash-style filepaths are emitted as forward-slash POSIX URIs.

    Windows hosts otherwise produce ``src\\foo.py`` which fails SARIF
    consumers like GitHub code scanning that expect a URI reference.
    """
    v = Violation(rule="function_length", code="SAFE101", filepath="src\\sub\\foo.py", lineno=1, message="m", severity="error")
    out = format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1)
    doc = json.loads(out)
    uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "src/sub/foo.py"


def test_sarif_artifact_uri_makes_absolute_paths_repo_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absolute paths under cwd are emitted as cwd-relative POSIX URIs."""
    monkeypatch.chdir(tmp_path)
    abs_path = str(tmp_path / "pkg" / "foo.py")
    v = Violation(rule="function_length", code="SAFE101", filepath=abs_path, lineno=1, message="m", severity="error")
    out = format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1)
    doc = json.loads(out)
    uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "pkg/foo.py"


def test_sarif_artifact_uri_falls_back_for_paths_outside_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absolute paths outside cwd fall back to the absolute POSIX form."""
    monkeypatch.chdir(tmp_path)
    elsewhere = str(tmp_path.parent / "outside" / "foo.py")
    v = Violation(rule="function_length", code="SAFE101", filepath=elsewhere, lineno=1, message="m", severity="error")
    out = format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1)
    doc = json.loads(out)
    uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    # No drive letter, no backslashes — but it's still absolute (starts with /).
    assert uri.startswith("/")
    assert "\\" not in uri


def test_sarif_artifact_uri_percent_encodes_special_chars() -> None:
    """Spaces and other special URI characters are percent-encoded; ``/`` is preserved."""
    v = Violation(rule="r", code="SAFE001", filepath="src/has space/file#1.py", lineno=1, message="m", severity="error")
    out = format_sarif([v], [], blocking_count=1, fail_on="error", files_checked=1)
    doc = json.loads(out)
    uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "src/has%20space/file%231.py"


def test_sarif_rules_descriptor_deduplicates() -> None:
    """Each unique ``ruleId`` appears once in ``tool.driver.rules``, sorted."""
    violations = [_v(code="SAFE101"), _v(code="SAFE101"), _v(code="SAFE304")]
    suppressed = [_v(code="SAFE501")]
    out = format_sarif(violations, suppressed, blocking_count=2, fail_on="error", files_checked=1)
    doc = json.loads(out)
    rule_ids = [r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]]
    assert rule_ids == ["SAFE101", "SAFE304", "SAFE501"]
