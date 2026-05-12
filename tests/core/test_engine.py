"""Tests for safelint.core.engine - SafetyEngine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path

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


# ---------------------------------------------------------------------------
# Default exclude_paths defaults: prune common vendor / generated dirs
# ---------------------------------------------------------------------------


def test_engine_default_excludes_prune_venv_during_discovery(tmp_path: Path) -> None:
    """Default ``exclude_paths`` skip ``.venv/`` during file discovery.

    Regression guard for the rc2 papercut: a fresh
    ``safelint check --all-files`` from a project root with a Python
    virtualenv at ``.venv/`` should not lint third-party files inside
    the venv. Without the built-in default excludes the engine would
    walk in and report violations on packaged code the user didn't
    author.
    """
    # Create a "project" layout: src/ with one real file, plus a fake
    # .venv with a deliberately-violating file that must NOT be reported.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("def f(): return 1\n", encoding="utf-8")

    venv = tmp_path / ".venv" / "lib" / "python3.11" / "site-packages"
    venv.mkdir(parents=True)
    bad = venv / "vendor.py"
    bad.write_text(
        # Deliberately-violating: bare except + empty body would normally fire SAFE201/202.
        "def vendor_func():\n    try:\n        do()\n    except:\n        pass\n",
        encoding="utf-8",
    )

    # Use the engine's default exclude_paths (don't override with config).
    engine = SafetyEngine(DEFAULTS)
    discovered = engine.check_path(str(tmp_path))
    discovered_paths = {r.path for r in discovered}

    assert str(src_dir / "app.py") in discovered_paths
    assert not any(".venv" in p for p in discovered_paths), f".venv leaked into discovery: {[p for p in discovered_paths if '.venv' in p]}"


def test_engine_default_excludes_prune_node_modules(tmp_path: Path) -> None:
    """Default ``exclude_paths`` also skip ``node_modules/`` (JS vendor dir)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.js").write_text("function f() { return 1; }\n", encoding="utf-8")

    vendor = tmp_path / "node_modules" / "some-lib"
    vendor.mkdir(parents=True)
    (vendor / "index.js").write_text(
        # Deliberate SAFE501: bare while(true) with no break.
        "function loop() { while (true) { work(); } }\n",
        encoding="utf-8",
    )

    engine = SafetyEngine(DEFAULTS)
    discovered = engine.check_path(str(tmp_path))
    discovered_paths = {r.path for r in discovered}

    assert str(src_dir / "app.js") in discovered_paths
    assert not any("node_modules" in p for p in discovered_paths)


def test_engine_explicit_empty_exclude_paths_clears_defaults(tmp_path: Path) -> None:
    """Setting ``exclude_paths = []`` is the documented escape hatch — defaults dropped."""
    venv = tmp_path / ".venv"
    venv.mkdir()
    inside = venv / "vendor.py"
    inside.write_text("x = 1\n", encoding="utf-8")

    # Empty list explicitly overrides defaults. The .venv file is now discovered.
    config = deep_merge(DEFAULTS, {"exclude_paths": []})
    engine = SafetyEngine(config)
    discovered = engine.check_path(str(tmp_path))
    discovered_paths = {r.path for r in discovered}

    assert str(inside) in discovered_paths, "exclude_paths=[] should clear vendor-dir defaults"


def test_engine_extend_exclude_paths_appends_to_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``extend_exclude_paths`` appends without losing the vendor-dir defaults.

    Runs from cwd=tmp_path (matching real CLI usage where users invoke
    ``safelint check .`` from the project root) so single-component
    patterns like ``legacy_vendor/**`` match the relative paths
    discovery produces.
    """
    # .venv (would be pruned by defaults), legacy_vendor (project-specific extra)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "vendor.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "legacy_vendor").mkdir()
    (tmp_path / "legacy_vendor" / "old.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    config = deep_merge(DEFAULTS, {"extend_exclude_paths": ["legacy_vendor/**"]})
    engine = SafetyEngine(config)
    discovered = engine.check_path(".")
    discovered_paths = {r.path for r in discovered}

    assert any("app.py" in p for p in discovered_paths), f"expected app.py in: {discovered_paths}"
    assert not any(".venv" in p for p in discovered_paths), "vendor defaults must still be active"
    assert not any("legacy_vendor" in p for p in discovered_paths), "extend_exclude_paths must be applied"


def test_engine_extend_exclude_paths_combines_with_explicit_exclude_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``extend_exclude_paths`` appends to a user-set ``exclude_paths`` too (not just defaults).

    Same cwd-based setup as the previous test — exclude patterns
    are matched against walked paths, which are relative when the
    target is relative.
    """
    # User wants tight control: no defaults, but two custom dirs.
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def f(): return 1\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    config = deep_merge(
        DEFAULTS,
        {
            "exclude_paths": ["build/**"],  # replaces defaults entirely
            "extend_exclude_paths": ["generated/**"],  # appended on top
        },
    )
    engine = SafetyEngine(config)
    discovered = engine.check_path(".")
    discovered_paths = {r.path for r in discovered}

    assert any("app.py" in p for p in discovered_paths)
    assert not any("build" in p for p in discovered_paths)
    assert not any("generated" in p for p in discovered_paths)


def test_engine_extend_exclude_paths_must_be_list_not_string() -> None:
    """Bare-string typo for ``extend_exclude_paths`` raises TypeError, not silently coerce."""
    config = deep_merge(DEFAULTS, {"extend_exclude_paths": "build/**"})
    with pytest.raises(TypeError, match="extend_exclude_paths"):
        SafetyEngine(config)


def test_engine_exclude_paths_must_be_list_not_string() -> None:
    """Bare-string typo for ``exclude_paths`` raises TypeError, not silently coerce."""
    config = deep_merge(DEFAULTS, {"exclude_paths": "build/**"})
    with pytest.raises(TypeError, match="exclude_paths"):
        SafetyEngine(config)


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
        # Cross-language rules: ``language`` should be exactly
        # ``("python", "javascript")``. Silent drift past this
        # allow-list (a half-ported rule, or a rule unintentionally
        # narrowing back to Python-only) is what the assertion catches.
        "FunctionLengthRule",
        "NestingDepthRule",
        "MaxArgumentsRule",
        "ComplexityRule",
        "EmptyExceptRule",
        "LoggingOnErrorRule",
        "SideEffectsHiddenRule",
        "SideEffectsRule",
        "UnboundedLoopRule",
        "MissingAssertionsRule",
        "TestExistenceRule",
        "TestCouplingRule",
        "TaintedSinkRule",
        "ReturnValueIgnoredRule",
        "NullDereferenceRule",
        "GlobalMutationRule",
        "ResourceLifecycleRule",
    }
)

_RULES_JAVASCRIPT_ONLY: frozenset[str] = frozenset(
    {
        # JS-only rules (``language=("javascript",)``) — the JS hazard
        # has no useful Python translation. Listed explicitly so the
        # allow-list test catches accidental drift either way.
        "WideScopeDeclarationRule",  # SAFE305: ``var`` keyword (no Python equivalent)
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
    cross_lang_actual = {cls.__name__ for cls in ALL_RULES if cls.language == ("python", "javascript")}
    js_only_actual = {cls.__name__ for cls in ALL_RULES if cls.language == ("javascript",)}
    assert cross_lang_actual == _RULES_WIDENED_FOR_JAVASCRIPT, (
        f"Cross-language allow-list out of sync. Actually ('python', 'javascript'): {sorted(cross_lang_actual)}; documented: {sorted(_RULES_WIDENED_FOR_JAVASCRIPT)}"
    )
    assert js_only_actual == _RULES_JAVASCRIPT_ONLY, f"JS-only allow-list out of sync. Actually ('javascript',): {sorted(js_only_actual)}; documented: {sorted(_RULES_JAVASCRIPT_ONLY)}"

    for cls in ALL_RULES:
        if cls.__name__ in _RULES_WIDENED_FOR_JAVASCRIPT:
            assert cls.language == ("python", "javascript"), f"{cls.__name__} should be ('python', 'javascript'); got {cls.language}"
        elif cls.__name__ in _RULES_JAVASCRIPT_ONLY:
            assert cls.language == ("javascript",), f"{cls.__name__} should be ('javascript',); got {cls.language}"
        else:
            assert cls.language == ("python",), f"{cls.__name__} has unexpected language={cls.language}; add it to _RULES_WIDENED_FOR_JAVASCRIPT or _RULES_JAVASCRIPT_ONLY if intentional"
