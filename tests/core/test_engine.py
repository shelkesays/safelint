"""Tests for safelint.core.engine - SafetyEngine."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from safelint import languages as lang_module
from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import PYTHON
from safelint.languages._types import LanguageDefinition
from safelint.rules import ALL_RULES
from safelint.rules.base import BaseRule


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

    violations = _engine().check_file(str(sample)).violations

    rules = {v.rule for v in violations}
    assert "bare_except" in rules


def test_engine_detects_function_length(tmp_path: Path) -> None:
    """function_length rule fires when a function body exceeds max_lines."""
    lines = ["def long_func():\n"] + ["    x = 1\n"] * 65
    sample = tmp_path / "long.py"
    sample.write_text("".join(lines), encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations

    assert any(v.rule == "function_length" for v in violations)


def test_engine_detects_nesting_depth(tmp_path: Path) -> None:
    """nesting_depth rule fires on deeply nested control flow."""
    sample = tmp_path / "nested.py"
    sample.write_text(
        "def deep():\n    if True:\n        for x in []:\n            while True:\n                break\n",
        encoding="utf-8",
    )

    violations = _engine().check_file(str(sample)).violations

    assert any(v.rule == "nesting_depth" for v in violations)


def test_engine_detects_resource_lifecycle(tmp_path: Path) -> None:
    """resource_lifecycle rule fires on open() outside a with block."""
    sample = tmp_path / "res.py"
    sample.write_text("f = open('data.txt')\n", encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations

    assert any(v.rule == "resource_lifecycle" for v in violations)


def test_engine_clean_file_produces_no_violations(tmp_path: Path) -> None:
    """A clean, simple file produces no violations."""
    sample = tmp_path / "clean.py"
    sample.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations

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
    violations = engine.check_file(str(sample)).violations

    assert violations == []


def test_engine_disabled_rule_not_applied(tmp_path: Path) -> None:
    """A rule disabled in config is not applied."""
    sample = tmp_path / "long.py"
    sample.write_text("def foo():\n" + "    x = 1\n" * 65, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"function_length": {"enabled": False}}})
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample)).violations

    assert not any(v.rule == "function_length" for v in violations)


def test_engine_fail_fast_stops_after_first_rule_with_violations(tmp_path: Path) -> None:
    """fail_fast=True stops after the first rule that produces violations."""
    sample = tmp_path / "multi.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n" + "    x = 1\n" * 65,
        encoding="utf-8",
    )

    config_ff = deep_merge(DEFAULTS, {"execution": {"fail_fast": True}})
    config_no = deep_merge(DEFAULTS, {"execution": {"fail_fast": False}})

    viol_ff = SafetyEngine(config_ff).check_file(str(sample)).violations
    viol_no = SafetyEngine(config_no).check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

    assert len(violations) == 1
    assert violations[0].rule == "parse"
    assert violations[0].severity == "error"


# ---------------------------------------------------------------------------
# Per-language rule dispatch (engine._run_rules filter on rule.language)
#
# Today every registered rule defaults to ``language = ("python",)`` and
# Python is the only registered language, so the filter is a no-op for
# real usage. The tests below construct a *fake* LanguageDefinition
# (non-Python name, but Python's parser internals so the source still
# parses) and verify the engine skips Python-only rules for files
# routed through it. This is pre-emptive infrastructure for the
# second-language work — when TypeScript / Go / … land, contributors
# widen each rule's ``language`` tuple per-rule; this engine plumbing
# doesn't need further changes.
# ---------------------------------------------------------------------------


def _hypothetical_lang_definition() -> LanguageDefinition:
    """Build a LanguageDefinition with a non-python name but Python's parser internals."""
    return LanguageDefinition(
        name="hypothetical",
        file_extensions=frozenset({".hypothetical"}),
        comment_node_type=PYTHON.comment_node_type,
        comment_prefix=PYTHON.comment_prefix,
        create_parser=PYTHON.create_parser,
    )


def test_engine_skips_python_only_rules_when_file_language_differs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule defaulting to ``language=("python",)`` must NOT fire on a file routed through a non-Python LanguageDefinition."""
    fake_lang = _hypothetical_lang_definition()
    monkeypatch.setitem(lang_module._REGISTRY, ".hypothetical", fake_lang)

    # Source that *would* trigger function_length on a Python file.
    long_body = "    x = 1\n" * 65
    source = "def too_long():\n" + long_body
    sample = tmp_path / "fake.hypothetical"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))

    # function_length defaults to ``language=("python",)``; the engine
    # filters it out for the hypothetical-language file. Result: zero
    # violations even though the source content would otherwise match.
    assert not any(v.rule == "function_length" for v in result.violations)
    assert not any(v.rule == "function_length" for v in result.suppressed)


def test_engine_runs_python_rules_on_python_files_unchanged(tmp_path: Path) -> None:
    """Filter must not accidentally skip Python rules on Python files (regression guard)."""
    long_body = "    x = 1\n" * 65
    source = "def too_long():\n" + long_body
    sample = tmp_path / "real.py"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    assert any(v.rule == "function_length" for v in result.violations)


def test_base_rule_default_language_is_python_only() -> None:
    """``BaseRule.language`` default must be ``("python",)`` — every existing rule inherits it."""
    assert BaseRule.language == ("python",)


_RULES_WIDENED_FOR_JAVASCRIPT: frozenset[str] = frozenset(
    {
        # Slice 2: structural rules ported to JavaScript. Each one's
        # ``language`` tuple should be exactly ``("python", "javascript")``;
        # silent drift past this allow-list is what the assertion catches.
        "FunctionLengthRule",
        "NestingDepthRule",
        "MaxArgumentsRule",
        "ComplexityRule",
        # Slice 3: error-handling and side-effects rules.
        "EmptyExceptRule",
        "LoggingOnErrorRule",
        "SideEffectsHiddenRule",
        "SideEffectsRule",
        # Slice 4: loop safety, missing assertions, test-coverage rules.
        "UnboundedLoopRule",
        "MissingAssertionsRule",
        "TestExistenceRule",
        "TestCouplingRule",
    }
)


def test_widened_rules_match_the_documented_allow_list() -> None:
    """The set of rules with non-default ``language`` matches the documented allow-list.

    Catches two failure modes:

    * A rule silently grows its language tuple (e.g. someone adds
      ``"typescript"`` mid-port without finishing the work). The allow-list
      surfaces that as a test failure rather than letting half-ported
      behaviour ship.
    * A rule listed here regresses to the default ``("python",)`` —
      the test fails too, prompting the contributor to remove the entry
      from the allow-list along with the deliberate scope reduction.
    """
    widened_actual = {cls.__name__ for cls in ALL_RULES if cls.language != ("python",)}
    assert widened_actual == _RULES_WIDENED_FOR_JAVASCRIPT, (
        f"Widened-rules allow-list out of sync. "
        f"Actually widened: {sorted(widened_actual)}; "
        f"documented: {sorted(_RULES_WIDENED_FOR_JAVASCRIPT)}"
    )

    for cls in ALL_RULES:
        if cls.__name__ in _RULES_WIDENED_FOR_JAVASCRIPT:
            assert cls.language == ("python", "javascript"), (
                f"{cls.__name__} should be ('python', 'javascript'); got {cls.language}"
            )
        else:
            assert cls.language == ("python",), (
                f"{cls.__name__} has unexpected language={cls.language}; "
                f"add it to _RULES_WIDENED_FOR_JAVASCRIPT if intentional"
            )
