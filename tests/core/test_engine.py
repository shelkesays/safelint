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
    """Files matching an exclude pattern are skipped entirely.

    Uses ``extend_exclude_paths`` (the documented recommended form)
    so it models real-world usage. The
    ``test_engine_exclude_paths_must_be_list_not_string`` and
    ``test_engine_explicit_empty_exclude_paths_clears_defaults``
    tests further down still exercise the ``exclude_paths`` key
    directly for its replace-defaults semantics.
    """
    sample = tmp_path / "legacy.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    config = deep_merge(DEFAULTS, {"extend_exclude_paths": ["**/legacy.py"]})
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
    """Setting ``exclude_paths = []`` is the documented escape hatch - defaults dropped."""
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

    Same cwd-based setup as the previous test - exclude patterns
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


def test_engine_discovery_lints_in_tree_symlink_but_skips_escaping_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Follow-if-resolved-within-tree: an in-tree symlink is linted, an escaping one is not.

    ``os.walk(followlinks=False)`` lists symlinked *files*; the guard follows one
    only when its real path stays inside the repo root (cwd). A monorepo's
    ``app/config.py -> ../shared/config.py`` (shared under the repo) is linted;
    ``evil.py -> <out-of-tree secret>`` is dropped and never read.
    """
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "shared").mkdir()
    monkeypatch.chdir(repo)
    (repo / "shared" / "config.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "app" / "config.py").symlink_to(repo / "shared" / "config.py")  # in-tree symlink
    outside = tmp_path / "outside_secret.py"
    outside.write_text("SECRET = 'do-not-read'\n", encoding="utf-8")
    (repo / "app" / "evil.py").symlink_to(outside)  # escaping symlink

    paths = {r.path for r in _engine().check_path(repo)}

    assert str(repo / "app" / "config.py") in paths  # in-tree symlink linted
    assert str(repo / "app" / "evil.py") not in paths  # escaping symlink skipped
    assert str(outside) not in paths


def test_engine_discovery_skips_escaping_symlinked_directory_target(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlinked directory target that escapes the repo is rejected, not walked into.

    ``os.walk(followlinks=False)`` still walks *into* a symlinked top target, so
    ``safelint check reports`` where ``reports -> /outside`` would read out-of-tree
    files. An escaping top target is rejected outright.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text("SECRET = 1\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    (repo / "reports").symlink_to(outside, target_is_directory=True)

    results = _engine().check_path(repo / "reports")

    assert results == []  # nothing discovered, nothing read
    assert "symlink" in capsys.readouterr().err


def test_engine_symlink_skip_warning_sanitises_control_chars(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlink whose name carries an ANSI escape is neutralised in the stderr warning.

    The skip warning echoes the repo-controlled filepath; without sanitisation a
    crafted symlink name would inject terminal escapes via stderr (the channel the
    pretty-renderer sanitiser does not cover).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    outside = tmp_path / "target.py"  # out of tree -> escapes -> skipped + warned
    outside.write_text("x = 1\n", encoding="utf-8")
    link = repo / "evil\x1b[2J.py"
    link.symlink_to(outside)

    _engine().check_file(str(link))

    err = capsys.readouterr().err
    assert "\x1b[2J" not in err
    assert "\\x1b" in err


def test_engine_check_file_skips_escaping_symlink_explicit_path(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """check_file() on a symlink escaping the repo is skipped without reading the target.

    Covers CLI hook mode and a single-file check_path target, which reach
    check_file directly (bypassing discovery). A committed ``evil.py -> secret``
    pointing out of tree must not have its target read.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    outside = tmp_path / "secret.py"
    outside.write_text("def (:  # a parse error the linter would report if read\n", encoding="utf-8")
    link = repo / "evil.py"
    link.symlink_to(outside)

    result = _engine().check_file(str(link))

    assert result.violations == []  # nothing read, nothing reported
    assert "symlink" in capsys.readouterr().err


def test_engine_symlink_escapes_helper_fails_closed_on_oserror() -> None:
    """_symlink_escapes returns True (skip) when is_symlink() raises OSError, not crash.

    ``Path.is_symlink()`` re-raises OSError on a non-ignored errno (e.g. EACCES on
    a parent dir); the helper must fail closed rather than propagate and crash
    discovery / the pre-read guard.
    """
    from pathlib import Path  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    from safelint.core.engine import _symlink_escapes  # noqa: PLC0415

    with patch.object(Path, "is_symlink", side_effect=PermissionError("EACCES")):
        assert _symlink_escapes(Path("/anything.py"), Path.cwd()) is True


def test_engine_symlink_escapes_helper_rejects_real_symlink_loop(tmp_path: Path) -> None:
    """_symlink_escapes returns True for a real two-link symlink loop (a -> b -> a).

    Complements the mocked-OSError test with a genuine loop: on Python <=3.12
    ``resolve()`` raises RuntimeError (caught -> True); on 3.13+ it returns a
    still-symlink path caught by the ``real.is_symlink()`` check. Either way the
    unresolvable loop fails closed.
    """
    from safelint.core.engine import _symlink_escapes  # noqa: PLC0415

    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.symlink_to(b)
    b.symlink_to(a)
    assert _symlink_escapes(a, tmp_path.resolve()) is True


def test_engine_check_file_lints_in_tree_symlink_explicit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """check_file() on an in-tree symlink follows it and reports the target's violations."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    (repo / "real.py").write_text("def foo(\n", encoding="utf-8")  # parse error
    link = repo / "link.py"
    link.symlink_to(repo / "real.py")  # in-tree symlink

    result = _engine().check_file(str(link))

    assert any(v.code == "SAFE000" for v in result.violations)  # followed + linted


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
# second-language work - when TypeScript / Go / … land, contributors
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
    """``BaseRule.language`` default must be ``("python",)`` - every existing rule inherits it."""
    assert BaseRule.language == ("python",)


# Expected ``language`` tuple for every rule whose scope differs from the
# default ``("python",)``. Keyed by class name. The test asserts BOTH
# directions: every rule's ``.language`` matches its entry here (or the
# ``("python",)`` default when absent), AND every non-default rule appears
# here exactly once - so a silent widening or an accidental scope regression
# both fail CI. Grouped by the distinct scope tuples; the comments record why
# each rule sits where it does.
_ALL_SEVEN = ("python", "javascript", "typescript", "java", "rust", "go", "php")
_ALL_EIGHT = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c")
_ALL_NINE = (*_ALL_EIGHT, "cpp")

_EXPECTED_LANGUAGES: dict[str, tuple[str, ...]] = {
    # Cross-language structural / dataflow rules ported to EVERY registered
    # language (all nine, C and C++ included).
    "FunctionLengthRule": _ALL_NINE,  # SAFE101
    "NestingDepthRule": _ALL_NINE,  # SAFE102
    "MaxArgumentsRule": _ALL_NINE,  # SAFE103
    "ComplexityRule": _ALL_NINE,  # SAFE104
    "NoRecursionRule": _ALL_NINE,  # SAFE105
    "UnboundedLoopRule": _ALL_NINE,  # SAFE501
    "BlanketSuppressionRule": _ALL_NINE,  # SAFE603
    "TestExistenceRule": _ALL_NINE,  # SAFE701
    "TestCouplingRule": _ALL_NINE,  # SAFE702
    "SideEffectsHiddenRule": _ALL_NINE,  # SAFE303
    "SideEffectsRule": _ALL_NINE,  # SAFE304
    "TaintedSinkRule": _ALL_NINE,  # SAFE801
    "ReturnValueIgnoredRule": _ALL_NINE,  # SAFE802
    # Ported everywhere EXCEPT Rust (Rust covers these via RAII / SAFE602 /
    # SAFE307, or its rule-8 analogue is the opaque macro system). C / C++ in.
    "GlobalMutationRule": ("python", "javascript", "typescript", "java", "go", "php", "c", "cpp"),  # SAFE302
    "DynamicCodeExecutionRule": ("python", "javascript", "typescript", "java", "go", "php", "c", "cpp"),  # SAFE309
    # SAFE401 resource_lifecycle is NOT ported to C / C++ (cleanup needs flow
    # analysis; C's allocation discipline is SAFE310's job, C++'s is RAII -
    # same rationale as Rust - documented gap).
    "ResourceLifecycleRule": ("python", "javascript", "typescript", "java", "go", "php"),  # SAFE401
    # Ported everywhere EXCEPT Go (no production assertion idiom). C / C++ are
    # included (the ``assert`` macro). SAFE803 stays without C / C++ / Go (nil
    # analysis needs types).
    "MissingAssertionsRule": ("python", "javascript", "typescript", "java", "rust", "php", "c", "cpp"),  # SAFE601
    "NullDereferenceRule": ("python", "javascript", "typescript", "java", "rust", "php"),  # SAFE803
    # try/catch rules: the languages with try/catch (Rust / Go have neither;
    # their analogues SAFE206/207 / SAFE209 are separate rule designs). C++
    # adds ``try`` / ``catch`` / ``throw``.
    "EmptyExceptRule": ("python", "javascript", "typescript", "java", "php", "cpp"),  # SAFE202
    "LoggingOnErrorRule": ("python", "javascript", "typescript", "java", "php", "cpp"),  # SAFE203
    # SAFE201 bare_except: Python's bare ``except:`` and C++'s ``catch (...)``
    # catch-all - its first non-Python home.
    "BareExceptRule": ("python", "cpp"),  # SAFE201
    # The literal ``global`` keyword: Python and PHP only (PHP is SAFE301's
    # first non-Python registration).
    "GlobalStateRule": ("python", "php"),  # SAFE301
    # JS-family-only: the ``var`` hoisting hazard has no Python / Java / Rust /
    # Go / PHP analogue.
    "WideScopeDeclarationRule": ("javascript", "typescript"),  # SAFE305
    # Java-only Spring Boot framework rules (SAFE9xx band).
    "SpringFieldInjectionRule": ("java",),  # SAFE901
    "SpringMissingTransactionalRule": ("java",),  # SAFE902
    "SpringUnvalidatedInputRule": ("java",),  # SAFE903
    "SpringAsyncCheckedExceptionRule": ("java",),  # SAFE904
    # Shared cross-framework rules (SAFE9xx) - Python + PHP, enabled by the
    # framework presets.
    "DebugModeEnabledRule": ("python", "php"),  # SAFE905
    "MassAssignmentRule": ("python", "php"),  # SAFE906
    "UnvalidatedRequestInputRule": ("python", "php"),  # SAFE907
    # Rust-only language-idiom rules (slotted into category bands).
    "NeedlessMutRule": ("rust",),  # SAFE110
    "UncheckedArithmeticOnInputRule": ("rust",),  # SAFE112
    "PanicMacrosOutsideTestsRule": ("rust",),  # SAFE204
    "LockPoisoningIgnoredRule": ("rust",),  # SAFE205
    "SilentResultDiscardRule": ("rust",),  # SAFE206
    "UnloggedErrorBranchRule": ("rust",),  # SAFE207
    "ResultUnwrapOutsideTestsRule": ("rust",),  # SAFE208
    "DangerousMemOpsRule": ("rust",),  # SAFE306
    "InteriorMutableStaticRule": ("rust",),  # SAFE307
    "TruncatingAsCastRule": ("rust",),  # SAFE308
    "UndocumentedUnsafeRule": ("rust",),  # SAFE602
    # Go-only language-idiom rules.
    "EmptyErrorCheckRule": ("go",),  # SAFE209
    "PanicCallsOutsideTestsRule": ("go",),  # SAFE211
    # C-family rules - the "Power of Ten homecoming" (1xx / 3xx bands). All
    # five widen to ``("c", "cpp")`` (tree-sitter-cpp is a superset of
    # tree-sitter-c, so the structural checks carry over unchanged).
    "NonlocalJumpsRule": ("c", "cpp"),  # SAFE106
    "DynamicAllocationRule": ("c", "cpp"),  # SAFE310
    "ComplexMacroRule": ("c", "cpp"),  # SAFE311
    "ConditionalCompilationRule": ("c", "cpp"),  # SAFE312
    "RestrictedPointersRule": ("c", "cpp"),  # SAFE313
    # C++-only rules (modern-C++ idiom discipline, 3xx band).
    "RawNewDeleteRule": ("cpp",),  # SAFE315
    "DangerousCastsRule": ("cpp",),  # SAFE316
}


def test_widened_rules_match_the_documented_allow_list() -> None:
    """Every rule's ``language`` tuple matches its documented expectation exactly.

    Catches two failure modes in both directions:

    * A rule silently grows or shrinks its language tuple (e.g. a new language
      added mid-port, or an accidental scope regression to ``("python",)``):
      the per-rule assertion fails.
    * The allow-list drifts from the registry (a rule renamed / removed, or a
      stale entry left behind): the set-equality assertion fails.
    """
    for cls in ALL_RULES:
        expected = _EXPECTED_LANGUAGES.get(cls.__name__, ("python",))
        assert cls.language == expected, f"{cls.__name__}: language {cls.language} != expected {expected} (update _EXPECTED_LANGUAGES in this test if the change is intentional)"
    documented = set(_EXPECTED_LANGUAGES)
    non_default = {cls.__name__ for cls in ALL_RULES if cls.language != ("python",)}
    assert documented == non_default, f"allow-list out of sync with ALL_RULES; symmetric difference: {sorted(documented ^ non_default)}"
