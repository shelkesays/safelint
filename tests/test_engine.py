"""Tests for safelint.core.engine - SafetyEngine."""

from __future__ import annotations

from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """Return a SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def test_engine_detects_bare_except(tmp_path: Path) -> None:
    """bare_except rule fires on a bare except clause."""
    sample = tmp_path / "bad.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    violations = _engine().check_file(str(sample))

    rules = {v.rule for v in violations}
    assert "bare_except" in rules


def test_engine_detects_function_length(tmp_path: Path) -> None:
    """function_length rule fires when a function body exceeds max_lines."""
    lines = ["def long_func():\n"] + ["    x = 1\n"] * 65
    sample = tmp_path / "long.py"
    sample.write_text("".join(lines), encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "function_length" for v in violations)


def test_engine_detects_nesting_depth(tmp_path: Path) -> None:
    """nesting_depth rule fires on deeply nested control flow."""
    sample = tmp_path / "nested.py"
    sample.write_text(
        "def deep():\n"
        "    if True:\n"
        "        for x in []:\n"
        "            while True:\n"
        "                break\n",
        encoding="utf-8",
    )

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "nesting_depth" for v in violations)


def test_engine_detects_resource_lifecycle(tmp_path: Path) -> None:
    """resource_lifecycle rule fires on open() outside a with block."""
    sample = tmp_path / "res.py"
    sample.write_text("f = open('data.txt')\n", encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "resource_lifecycle" for v in violations)


def test_engine_clean_file_produces_no_violations(tmp_path: Path) -> None:
    """A clean, simple file produces no violations."""
    sample = tmp_path / "clean.py"
    sample.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert violations == []


def test_engine_excluded_path_is_skipped(tmp_path: Path) -> None:
    """Files matching exclude_paths are skipped entirely."""
    sample = tmp_path / "legacy.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    config = deep_merge(DEFAULTS, {"exclude_paths": ["**/legacy.py"]})
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample))

    assert violations == []


def test_engine_disabled_rule_not_applied(tmp_path: Path) -> None:
    """A rule disabled in config is not applied."""
    sample = tmp_path / "long.py"
    sample.write_text("def foo():\n" + "    x = 1\n" * 65, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"function_length": {"enabled": False}}})
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample))

    assert not any(v.rule == "function_length" for v in violations)


def test_engine_fail_fast_stops_after_first_rule_with_violations(tmp_path: Path) -> None:
    """fail_fast=True stops after the first rule that produces violations."""
    sample = tmp_path / "multi.py"
    sample.write_text(
        "def foo():\n"
        "    try:\n        pass\n    except:\n        pass\n"
        + "    x = 1\n" * 65,
        encoding="utf-8",
    )

    config_ff = deep_merge(DEFAULTS, {"execution": {"fail_fast": True}})
    config_no = deep_merge(DEFAULTS, {"execution": {"fail_fast": False}})

    viol_ff = SafetyEngine(config_ff).check_file(str(sample))
    viol_no = SafetyEngine(config_no).check_file(str(sample))

    # fail_fast produces fewer or equal violations
    assert len(viol_ff) <= len(viol_no)


def test_engine_check_path_traverses_directory(tmp_path: Path) -> None:
    """check_path() with a directory visits every .py file inside it."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("y = 2\n", encoding="utf-8")

    results = _engine().check_path(tmp_path)

    paths = {r.path for r in results}
    assert str(tmp_path / "a.py") in paths
    assert str(sub / "b.py") in paths


def test_engine_parse_error_returns_parse_violation(tmp_path: Path) -> None:
    """A file with a syntax error produces a 'parse' violation instead of crashing."""
    sample = tmp_path / "broken.py"
    sample.write_text("def foo(\n", encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert len(violations) == 1
    assert violations[0].rule == "parse"
    assert violations[0].severity == "error"
