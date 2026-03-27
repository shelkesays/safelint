"""Additional tests to reach the 80% coverage threshold."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge, load_config
from safelint.core.engine import SafetyEngine
from safelint.core.runner import run


# ---------------------------------------------------------------------------
# runner.run()
# ---------------------------------------------------------------------------


def test_run_without_config(tmp_path: Path) -> None:
    """run() with no config path uses defaults and returns lint results."""
    sample = tmp_path / "clean.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    results = run(sample)

    assert len(results) == 1
    assert results[0].path == str(sample)


def test_run_with_config_path(tmp_path: Path) -> None:
    """run() loads the config from the supplied path."""
    config_file = tmp_path / ".ai-safety.yaml"
    config_file.write_text("rules:\n  function_length:\n    max_lines: 5\n", encoding="utf-8")
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    results = run(sample, config_path=config_file)

    assert len(results) == 1


# ---------------------------------------------------------------------------
# load_config — invalid YAML falls back to defaults
# ---------------------------------------------------------------------------


def test_load_config_bad_yaml_falls_back_to_defaults(tmp_path: Path) -> None:
    """A malformed .ai-safety.yaml is skipped and defaults are returned."""
    (tmp_path / ".ai-safety.yaml").write_text(":\n  bad: [yaml", encoding="utf-8")

    config = load_config(tmp_path)

    assert config["mode"] == DEFAULTS["mode"]


# ---------------------------------------------------------------------------
# SafetyEngine — rule-specific scenarios
# ---------------------------------------------------------------------------


def _engine(overrides: dict | None = None) -> SafetyEngine:
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def test_resource_lifecycle_with_open_is_safe(tmp_path: Path) -> None:
    """open() inside a with statement does not trigger resource_lifecycle."""
    source = textwrap.dedent("""\
        with open('file.txt') as f:
            data = f.read()
    """)
    sample = tmp_path / "res.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert not any(v.rule == "resource_lifecycle" for v in violations)


def test_bare_except_is_flagged(tmp_path: Path) -> None:
    """bare_except fires on a bare except clause."""
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except:
                pass
    """)
    sample = tmp_path / "bare.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "bare_except" for v in violations)


def test_side_effects_hidden_flags_pure_named_io_function(tmp_path: Path) -> None:
    """side_effects_hidden fires when a get_* function calls open()."""
    source = textwrap.dedent("""\
        def get_data():
            f = open('x.txt')
            return f.read()
    """)
    sample = tmp_path / "se.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "side_effects_hidden" for v in violations)


def test_global_mutation_is_flagged(tmp_path: Path) -> None:
    """global_mutation fires when a function writes to a declared global."""
    source = textwrap.dedent("""\
        counter = 0

        def increment():
            global counter
            counter += 1
    """)
    sample = tmp_path / "gm.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "global_mutation" for v in violations)


def test_unbounded_loop_while_true_no_break(tmp_path: Path) -> None:
    """unbounded_loops fires on while True without a break."""
    source = textwrap.dedent("""\
        def poll():
            while True:
                pass
    """)
    sample = tmp_path / "loop.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "unbounded_loops" for v in violations)


def test_unbounded_loop_while_true_with_break_is_safe(tmp_path: Path) -> None:
    """while True with a break does not trigger unbounded_loops."""
    source = textwrap.dedent("""\
        def poll():
            while True:
                if done():
                    break
    """)
    sample = tmp_path / "safe_loop.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert not any(v.rule == "unbounded_loops" for v in violations)


def test_max_arguments_fires_when_exceeded(tmp_path: Path) -> None:
    """max_arguments fires when a function has too many parameters."""
    source = "def many(a, b, c, d, e, f, g, h):\n    pass\n"
    sample = tmp_path / "args.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "max_arguments" for v in violations)


def test_complexity_fires_on_high_cyclomatic_complexity(tmp_path: Path) -> None:
    """complexity fires when cyclomatic complexity exceeds max_complexity."""
    # Build a function with CC > 10 by chaining many if statements
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    source = f"def complex_func(x):\n{branches}\n    return -1\n"
    sample = tmp_path / "complex.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "complexity" for v in violations)


def test_violation_fields_are_populated(tmp_path: Path) -> None:
    """Violations carry rule, filepath, lineno, message, and severity."""
    sample = tmp_path / "v.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    violations = _engine().check_file(str(sample))
    bare = next(v for v in violations if v.rule == "bare_except")

    assert bare.filepath == str(sample)
    assert bare.lineno > 0
    assert bare.message
    assert bare.severity in {"error", "warning"}


def test_partition_violations_splits_by_threshold() -> None:
    """partition_violations correctly separates blocking from advisory violations."""
    from safelint.rules.base import Violation

    engine = _engine()
    violations = [
        Violation(rule="r1", filepath="f.py", lineno=1, message="m", severity="error"),
        Violation(rule="r2", filepath="f.py", lineno=2, message="m", severity="warning"),
    ]

    blocking, advisory = engine.partition_violations(violations, fail_threshold=1)

    assert len(blocking) == 1 and blocking[0].severity == "error"
    assert len(advisory) == 1 and advisory[0].severity == "warning"


# ---------------------------------------------------------------------------
# LoggingOnErrorRule
# ---------------------------------------------------------------------------


def test_logging_on_error_fires_when_no_log_call(tmp_path: Path) -> None:
    """logging_on_error fires when an except block swallows the error silently."""
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except ValueError as e:
                x = 1
    """)
    sample = tmp_path / "log.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "logging_on_error" for v in violations)


def test_logging_on_error_exempt_when_reraises(tmp_path: Path) -> None:
    """logging_on_error is not raised when the except block only re-raises."""
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except ValueError:
                raise
    """)
    sample = tmp_path / "reraise.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert not any(v.rule == "logging_on_error" for v in violations)


# ---------------------------------------------------------------------------
# MissingAssertionsRule (enable via config override)
# ---------------------------------------------------------------------------


def test_missing_assertions_fires_when_enabled(tmp_path: Path) -> None:
    """missing_assertions fires when the rule is enabled and a function has no asserts."""
    source = "def foo(x):\n    return x + 1\n"
    sample = tmp_path / "noassert.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True}}})
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample))

    assert any(v.rule == "missing_assertions" for v in violations)


# ---------------------------------------------------------------------------
# GlobalStateRule
# ---------------------------------------------------------------------------


def test_global_state_fires_on_global_keyword(tmp_path: Path) -> None:
    """global_state fires when a function uses the global keyword."""
    source = textwrap.dedent("""\
        _state = 0

        def set_state(value):
            global _state
            _state = value
    """)
    sample = tmp_path / "gs.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))

    assert any(v.rule == "global_state" for v in violations)


# ---------------------------------------------------------------------------
# TestExistenceRule / TestCouplingRule (enable via config override)
# ---------------------------------------------------------------------------


def test_test_existence_fires_when_no_test_file(tmp_path: Path) -> None:
    """test_existence fires when no corresponding test_<module>.py exists."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sample = src_dir / "mymodule.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(tmp_path / "tests")]}}},
    )
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample))

    assert any(v.rule == "test_existence" for v in violations)


def test_test_coupling_fires_when_test_not_updated(tmp_path: Path) -> None:
    """test_coupling fires when the paired test file exists but was not changed."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    sample = src_dir / "mymodule.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    (test_dir / "test_mymodule.py").write_text("def test_x(): pass\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {
            "rules": {
                "test_coupling": {
                    "enabled": True,
                    "test_dirs": [str(test_dir)],
                    "_changed_files": [str(sample)],
                }
            }
        },
    )
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample))

    assert any(v.rule == "test_coupling" for v in violations)


# ---------------------------------------------------------------------------
# CLI entry points (tested via the underlying functions, not subprocess)
# ---------------------------------------------------------------------------


def test_cli_hook_mode_exits_0_on_clean_file(tmp_path: Path) -> None:
    """_run_hook returns 0 when the given files have no violations."""
    import argparse

    from safelint.cli import _run_hook

    sample = tmp_path / "clean.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    args = argparse.Namespace(fail_on=None, mode=None)
    result = _run_hook(args, [str(sample)])

    assert result == 0


def test_cli_hook_mode_exits_1_on_violation(tmp_path: Path) -> None:
    """_run_hook returns 1 when a blocking violation is found."""
    import argparse

    from safelint.cli import _run_hook

    sample = tmp_path / "bad.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(fail_on="error", mode=None)
    result = _run_hook(args, [str(sample)])

    assert result == 1


def test_cli_hook_mode_empty_files_list_exits_0() -> None:
    """_run_hook returns 0 immediately when no files are provided."""
    import argparse

    from safelint.cli import _run_hook

    args = argparse.Namespace(fail_on=None, mode=None)
    assert _run_hook(args, []) == 0


def test_cli_check_mode_exits_0_on_clean_directory(tmp_path: Path) -> None:
    """_run_check returns 0 when the scanned directory has no violations."""
    import argparse

    from safelint.cli import _run_check

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None)
    result = _run_check(args)

    assert result == 0


def test_cli_check_mode_exits_1_on_violation(tmp_path: Path) -> None:
    """_run_check returns 1 when violations are found."""
    import argparse

    from safelint.cli import _run_check

    (tmp_path / "bad.py").write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(target=tmp_path, config=None, fail_on="error", mode=None)
    result = _run_check(args)

    assert result == 1
