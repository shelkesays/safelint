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
    config_file = tmp_path / ".safelint.yaml"
    config_file.write_text("rules:\n  function_length:\n    max_lines: 5\n", encoding="utf-8")
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    results = run(sample, config_path=config_file)

    assert len(results) == 1


def test_run_files_param_checks_exactly_those_files(tmp_path: Path) -> None:
    """run() with files= skips discovery and checks only the specified files."""
    checked = tmp_path / "checked.py"
    skipped = tmp_path / "skipped.py"
    checked.write_text("x = 1\n", encoding="utf-8")
    skipped.write_text("y = 2\n", encoding="utf-8")

    results = run(tmp_path, files=[str(checked)])

    assert len(results) == 1
    assert results[0].path == str(checked)


def test_run_changed_files_takes_precedence_over_files(tmp_path: Path) -> None:
    """run() passes changed_files to the engine when both changed_files and files are given."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    sample = src_dir / "mymod.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    test_file = test_dir / "test_mymod.py"
    test_file.write_text("def test_x(): pass\n", encoding="utf-8")

    # files= lists only the source file; changed_files= includes the test file too.
    # test_coupling should NOT fire because changed_files signals the test was updated.
    config_file = tmp_path / "pyproject.toml"
    config_file.write_text(
        f"[tool.safelint.rules.test_coupling]\nenabled = true\ntest_dirs = ['{test_dir}']\n",
        encoding="utf-8",
    )
    results = run(
        tmp_path,
        config_path=config_file,
        files=[str(sample)],
        changed_files=[str(sample), str(test_file)],
    )

    paths = [r.path for r in results]
    assert str(sample) in paths
    coupling_violations = [v for r in results for v in r.violations if v.rule == "test_coupling"]
    assert not coupling_violations


# ---------------------------------------------------------------------------
# load_config - invalid YAML falls back to defaults
# ---------------------------------------------------------------------------


def test_load_config_bad_yaml_falls_back_to_defaults(tmp_path: Path) -> None:
    """A malformed .safelint.yaml is skipped and defaults are returned."""
    (tmp_path / ".safelint.yaml").write_text(":\n  bad: [yaml", encoding="utf-8")

    config = load_config(tmp_path)

    assert config["mode"] == DEFAULTS["mode"]


# ---------------------------------------------------------------------------
# SafetyEngine - rule-specific scenarios
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
        Violation(rule="r1", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error"),
        Violation(rule="r2", code="SAFE002", filepath="f.py", lineno=2, message="m", severity="warning"),
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


# ---------------------------------------------------------------------------
# LintResult.has_violations
# ---------------------------------------------------------------------------


def test_lint_result_has_violations_true() -> None:
    """LintResult.has_violations returns True when violations list is non-empty."""
    from safelint.core.engine import LintResult
    from safelint.rules.base import Violation

    v = Violation(rule="r", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error")
    result = LintResult(path="f.py", violations=[v])
    assert result.has_violations is True


def test_lint_result_has_violations_false() -> None:
    """LintResult.has_violations returns False when violations list is empty."""
    from safelint.core.engine import LintResult

    result = LintResult(path="f.py")
    assert result.has_violations is False


# ---------------------------------------------------------------------------
# Engine: changed_files injection into TestCouplingRule
# ---------------------------------------------------------------------------


def test_engine_injects_changed_files_for_test_coupling(tmp_path: Path) -> None:
    """SafetyEngine injects changed_files into TestCouplingRule config."""
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sample = src_dir / "mymod.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    (test_dir / "test_mymod.py").write_text("def test_x(): pass\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {"rules": {"test_coupling": {"enabled": True, "test_dirs": [str(test_dir)]}}},
    )
    engine = SafetyEngine(config, changed_files=[str(sample)])
    violations = engine.check_file(str(sample))
    assert any(v.rule == "test_coupling" for v in violations)


# ---------------------------------------------------------------------------
# BaseRule._call_name returns None for non-Name/Attribute func nodes
# ---------------------------------------------------------------------------


def test_base_rule_call_name_returns_none_for_subscript() -> None:
    """BaseRule._call_name returns None when the func node is a Subscript."""
    import ast

    from safelint.rules.side_effects import SideEffectsRule

    rule = SideEffectsRule(
        {"enabled": True, "severity": "warning", "io_functions": ["open"], "io_name_keywords": []}
    )
    tree = ast.parse("func_map['key']()")
    call = tree.body[0].value
    assert rule._call_name(call.func) is None


# ---------------------------------------------------------------------------
# ComplexityRule: BoolOp and comprehension-with-ifs branches
# ---------------------------------------------------------------------------


def test_complexity_bool_op_increments_cc(tmp_path: Path) -> None:
    """ComplexityRule counts 'and'/'or' operators as branch points."""
    source = "def foo(a, b, c):\n    return a and b and c\n"
    sample = tmp_path / "bool_op.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine({"rules": {"complexity": {"max_complexity": 1}}}).check_file(str(sample))
    assert any(v.rule == "complexity" for v in violations)


def test_complexity_comprehension_with_condition(tmp_path: Path) -> None:
    """ComplexityRule counts comprehension `if` conditions as branch points."""
    source = "def foo(items):\n    return [x for x in items if x > 0 if x < 100]\n"
    sample = tmp_path / "comp_ifs.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine({"rules": {"complexity": {"max_complexity": 1}}}).check_file(str(sample))
    assert any(v.rule == "complexity" for v in violations)


# ---------------------------------------------------------------------------
# TaintedSinkRule: *args and **kwargs parameter names
# ---------------------------------------------------------------------------


def test_tainted_sink_with_vararg_param(tmp_path: Path) -> None:
    """TaintedSinkRule marks *args as a tainted parameter."""
    source = textwrap.dedent("""\
        def process(*args):
            cmd = args
            eval(cmd)
    """)
    sample = tmp_path / "vararg.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    violations = SafetyEngine(config).check_file(str(sample))
    assert any(v.rule == "tainted_sink" for v in violations)


def test_tainted_sink_with_kwarg_param(tmp_path: Path) -> None:
    """TaintedSinkRule marks **kwargs as a tainted parameter."""
    source = textwrap.dedent("""\
        def process(**kwargs):
            cmd = kwargs
            eval(cmd)
    """)
    sample = tmp_path / "kwarg.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    violations = SafetyEngine(config).check_file(str(sample))
    assert any(v.rule == "tainted_sink" for v in violations)


# ---------------------------------------------------------------------------
# ReturnValueIgnoredRule: non-Call Expr node is silently skipped
# ---------------------------------------------------------------------------


def test_return_value_ignored_non_call_expr(tmp_path: Path) -> None:
    """ReturnValueIgnoredRule does not flag bare non-call expressions."""
    source = "x = 1\nx + 1\n"
    sample = tmp_path / "bexpr.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"return_value_ignored": {"enabled": True}}})
    violations = SafetyEngine(config).check_file(str(sample))
    assert not any(v.rule == "return_value_ignored" for v in violations)


# ---------------------------------------------------------------------------
# NullDereferenceRule: subscript on non-nullable call is safe
# ---------------------------------------------------------------------------


def test_null_deref_subscript_non_nullable_call(tmp_path: Path) -> None:
    """NullDereferenceRule does not flag subscript access on a non-nullable call."""
    source = "result = str(42)[0]\n"
    sample = tmp_path / "nd_sub.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"null_dereference": {"enabled": True}}})
    violations = SafetyEngine(config).check_file(str(sample))
    assert not any(v.rule == "null_dereference" for v in violations)


# ---------------------------------------------------------------------------
# LoggingOnErrorRule: bare Name logger call (e.g. error("msg")) is sufficient
# ---------------------------------------------------------------------------


def test_logging_on_error_bare_name_logger_is_exempt(tmp_path: Path) -> None:
    """logging_on_error is not raised when the except block calls a bare log function."""
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except ValueError:
                error("something went wrong")
    """)
    sample = tmp_path / "bare_log.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert not any(v.rule == "logging_on_error" for v in violations)


# ---------------------------------------------------------------------------
# UnboundedLoopRule: while <variable> fires (non-comparison condition)
# ---------------------------------------------------------------------------


def test_loop_safety_while_variable_condition_fires(tmp_path: Path) -> None:
    """unbounded_loops fires when the while condition is a bare variable (not a comparison)."""
    source = textwrap.dedent("""\
        def poll(flag):
            while flag:
                pass
    """)
    sample = tmp_path / "while_var.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert any(v.rule == "unbounded_loops" for v in violations)


# ---------------------------------------------------------------------------
# MaxArgumentsRule: self/cls is excluded from the count
# ---------------------------------------------------------------------------


def test_max_arguments_self_excluded_from_count(tmp_path: Path) -> None:
    """max_arguments strips 'self' before counting, so 8 real args still fires."""
    source = "class Foo:\n    def bar(self, a, b, c, d, e, f, g, h):\n        pass\n"
    sample = tmp_path / "method.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert any(v.rule == "max_arguments" for v in violations)


# ---------------------------------------------------------------------------
# NestingDepthRule: elif chains are at the same depth as the parent if
# ---------------------------------------------------------------------------


def test_nesting_depth_elif_chain_not_deeper(tmp_path: Path) -> None:
    """elif chains do not increase nesting depth beyond the initial if."""
    source = textwrap.dedent("""\
        def foo(x):
            if x == 1:
                pass
            elif x == 2:
                pass
            elif x == 3:
                pass
    """)
    sample = tmp_path / "elif.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert not any(v.rule == "nesting_depth" for v in violations)


# ---------------------------------------------------------------------------
# SideEffectsHiddenRule: subscript call and no-io-call paths
# ---------------------------------------------------------------------------


def test_side_effects_hidden_subscript_call_not_flagged(tmp_path: Path) -> None:
    """side_effects_hidden ignores calls via subscript (call_name is None)."""
    source = textwrap.dedent("""\
        def get_data():
            handlers["open"]()
    """)
    sample = tmp_path / "sub_call.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert not any(v.rule == "side_effects_hidden" for v in violations)


def test_side_effects_hidden_pure_func_no_io_is_clean(tmp_path: Path) -> None:
    """side_effects_hidden does not flag a pure-named function with no I/O calls."""
    source = textwrap.dedent("""\
        def get_value():
            return 42
    """)
    sample = tmp_path / "pure.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert not any(v.rule == "side_effects_hidden" for v in violations)


# ---------------------------------------------------------------------------
# SideEffectsRule: function name contains I/O keyword → exempt
# ---------------------------------------------------------------------------


def test_side_effects_rule_io_keyword_in_name_exempt(tmp_path: Path) -> None:
    """side_effects does not flag functions whose name contains an I/O keyword."""
    source = textwrap.dedent("""\
        def log_data():
            open("x.txt")
    """)
    sample = tmp_path / "log_func.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert not any(v.rule == "side_effects" for v in violations)


# ---------------------------------------------------------------------------
# TestExistenceRule: clean case - test file found
# ---------------------------------------------------------------------------


def test_test_existence_returns_empty_when_test_found(tmp_path: Path) -> None:
    """test_existence returns no violations when a matching test file exists."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    sample = src_dir / "mymod.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    (test_dir / "test_mymod.py").write_text("def test_x(): pass\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(test_dir)]}}},
    )
    violations = SafetyEngine(config).check_file(str(sample))
    assert not any(v.rule == "test_existence" for v in violations)


# ---------------------------------------------------------------------------
# TestCouplingRule: defer when no test file exists; clean when test updated
# ---------------------------------------------------------------------------


def test_test_coupling_defers_when_no_test_file(tmp_path: Path) -> None:
    """test_coupling returns [] when no test file exists (defers to test_existence)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sample = src_dir / "notest.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {
            "rules": {
                "test_coupling": {
                    "enabled": True,
                    "test_dirs": [str(tmp_path / "tests")],
                    "_changed_files": [str(sample)],
                }
            }
        },
    )
    violations = SafetyEngine(config).check_file(str(sample))
    assert not any(v.rule == "test_coupling" for v in violations)


def test_test_coupling_clean_when_test_updated(tmp_path: Path) -> None:
    """test_coupling returns [] when both source and test file are in changed_files."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    sample = src_dir / "mymod2.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    test_file = test_dir / "test_mymod2.py"
    test_file.write_text("def test_x(): pass\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {
            "rules": {
                "test_coupling": {
                    "enabled": True,
                    "test_dirs": [str(test_dir)],
                    "_changed_files": [str(sample), str(test_file)],
                }
            }
        },
    )
    violations = SafetyEngine(config).check_file(str(sample))
    assert not any(v.rule == "test_coupling" for v in violations)


# ---------------------------------------------------------------------------
# CLI: _run_check with advisory-only violations, main(), _build_common_args
# ---------------------------------------------------------------------------


def test_cli_run_check_advisory_only_returns_0(tmp_path: Path) -> None:
    """_run_check returns 0 when violations are all advisory (below fail_on threshold)."""
    import argparse

    from safelint.cli import _run_check

    # logging_on_error fires at warning severity when an except block has no log call
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except ValueError as e:
                x = 1
    """)
    (tmp_path / "warn.py").write_text(source, encoding="utf-8")

    args = argparse.Namespace(target=tmp_path, config=None, fail_on="error", mode=None)
    result = _run_check(args)

    assert result == 0


def test_cli_main_check_mode_exits_0(tmp_path: Path, monkeypatch) -> None:
    """main() routes to check mode when 'check' is the first positional arg."""
    import sys

    from safelint.cli import main

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["safelint", "check", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_cli_main_hook_mode_exits_0(tmp_path: Path, monkeypatch) -> None:
    """main() routes to hook mode when no 'check' subcommand is present."""
    import sys

    from safelint.cli import main

    sample = tmp_path / "clean.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["safelint", str(sample)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_build_common_args_adds_fail_on_and_mode() -> None:
    """_build_common_args registers --fail-on and --mode arguments."""
    import argparse

    from safelint.cli import _build_common_args

    parser = argparse.ArgumentParser()
    _build_common_args(parser)
    args = parser.parse_args(["--fail-on=warning", "--mode=ci"])

    assert args.fail_on == "warning"
    assert args.mode == "ci"


# ---------------------------------------------------------------------------
# MissingAssertionsRule: clean path - function has assertions
# ---------------------------------------------------------------------------


def test_missing_assertions_no_violation_when_assert_present(tmp_path: Path) -> None:
    """missing_assertions does not fire when the function contains an assert."""
    source = "def foo(x):\n    assert x > 0\n    return x\n"
    sample = tmp_path / "with_assert.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True}}})
    violations = SafetyEngine(config).check_file(str(sample))
    assert not any(v.rule == "missing_assertions" for v in violations)


# ---------------------------------------------------------------------------
# LoggingOnErrorRule: Attribute-based logger and non-log Name call
# ---------------------------------------------------------------------------


def test_logging_on_error_attribute_logger_is_exempt(tmp_path: Path) -> None:
    """logging_on_error is not raised when the except block uses log.error(...)."""
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except ValueError:
                log.error("something went wrong")
    """)
    sample = tmp_path / "attr_log.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert not any(v.rule == "logging_on_error" for v in violations)


def test_logging_on_error_non_log_name_call_fires(tmp_path: Path) -> None:
    """logging_on_error fires when the except block calls a non-log-method function."""
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except ValueError as e:
                handle_error(e)
    """)
    sample = tmp_path / "non_log.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample))
    assert any(v.rule == "logging_on_error" for v in violations)


# ---------------------------------------------------------------------------
# CLI: git-based file selection (_get_git_modified_python_files branches)
# ---------------------------------------------------------------------------


def _make_proc(mocker, returncode: int = 0, stdout: str = ""):
    m = mocker.MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


def test_cli_check_git_unavailable_falls_back_to_full_scan(tmp_path: Path, mocker) -> None:
    """_run_check falls back to a full scan and exits 0 when git is not installed."""
    import argparse

    from safelint.cli import _run_check

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    mocker.patch("safelint.cli.subprocess.run", side_effect=FileNotFoundError)

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=False)
    assert _run_check(args) == 0


def test_cli_check_git_diff_failure_falls_back_to_full_scan(tmp_path: Path, mocker) -> None:
    """_run_check falls back to a full scan when git diff returns a non-zero exit code."""
    import argparse

    from safelint.cli import _run_check

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    rev_parse = _make_proc(mocker, returncode=0, stdout=str(tmp_path) + "\n")
    diff_fail = _make_proc(mocker, returncode=128, stdout="")
    mocker.patch("safelint.cli.subprocess.run", side_effect=[rev_parse, diff_fail, diff_fail])

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=False)
    assert _run_check(args) == 0


def test_cli_check_no_modified_files_exits_0(tmp_path: Path, mocker) -> None:
    """_run_check exits 0 with a status message when git reports no modified Python files."""
    import argparse

    from safelint.cli import _run_check

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    rev_parse = _make_proc(mocker, returncode=0, stdout=str(tmp_path) + "\n")
    empty_diff = _make_proc(mocker, returncode=0, stdout="")
    mocker.patch("safelint.cli.subprocess.run", side_effect=[rev_parse, empty_diff, empty_diff])

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=False)
    assert _run_check(args) == 0


def test_cli_check_all_files_bypasses_git(tmp_path: Path, mocker) -> None:
    """_run_check does not invoke git when --all-files is set."""
    import argparse

    from safelint.cli import _run_check

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    spy = mocker.patch("safelint.cli.subprocess.run")

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=True)
    result = _run_check(args)

    spy.assert_not_called()
    assert result == 0


def test_cli_check_only_in_target_files_linted(tmp_path: Path, mocker) -> None:
    """_run_check lints only in-target files; out-of-target diffs are not linted."""
    import argparse

    from safelint.cli import _run_check

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()

    (src_dir / "mod.py").write_text("x = 1\n", encoding="utf-8")
    # Violation in the out-of-target test file: bare except
    (test_dir / "test_mod.py").write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    # git root is tmp_path; both files are in the diff
    rev_parse = _make_proc(mocker, returncode=0, stdout=str(tmp_path) + "\n")
    diff_stdout = "src/mod.py\ntests/test_mod.py\n"
    diff_proc = _make_proc(mocker, returncode=0, stdout=diff_stdout)
    mocker.patch("safelint.cli.subprocess.run", side_effect=[rev_parse, diff_proc, diff_proc])

    # Target is src/ only — test_mod.py must not be linted
    args = argparse.Namespace(
        target=src_dir, config=None, fail_on="error", mode=None, all_files=False
    )
    assert _run_check(args) == 0
