"""Additional tests to reach the 80% coverage threshold."""

from __future__ import annotations

import argparse
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest
import tree_sitter
import tree_sitter_python

from safelint.cli import _build_common_args, _run_check, _run_hook, main
from safelint.core.config import DEFAULTS, deep_merge, load_config
from safelint.core.engine import LintResult, SafetyEngine
from safelint.core.runner import run
from safelint.languages._node_utils import call_name, walk
from safelint.rules.base import Violation


if TYPE_CHECKING:
    from pathlib import Path


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
    config_file = tmp_path / "pyproject.toml"
    config_file.write_text(
        "[tool.safelint.rules.function_length]\nmax_lines = 5\n",
        encoding="utf-8",
    )
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

    violations = _engine().check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

    assert not any(v.rule == "unbounded_loops" for v in violations)


def test_max_arguments_fires_when_exceeded(tmp_path: Path) -> None:
    """max_arguments fires when a function has too many parameters."""
    source = "def many(a, b, c, d, e, f, g, h):\n    pass\n"
    sample = tmp_path / "args.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations

    assert any(v.rule == "max_arguments" for v in violations)


def test_complexity_does_not_double_count_if_branches(tmp_path: Path) -> None:
    """Lock in McCabe semantics: each if/elif counts exactly once.

    Tree-sitter-python's ``if_statement`` does *not* contain an ``if_clause``
    child (its named children are identifier/block/elif_clause/else_clause).
    ``if_clause`` only appears inside comprehensions like
    ``[x for x in y if z]``. The rule's set therefore must include
    ``IF_STATEMENT`` to count plain ``if`` branches at all — removing it
    would silently undercount.

    Assertions below use ``max_complexity`` boundaries that fail loudly if
    counts drift in either direction:

    * Plain ``if``:        CC = 2 (1 base + 1 if). Must fire at max=1, not at max=2.
    * if+elif:             CC = 3 (1 + if + elif). Must fire at max=2, not at max=3.
    * Comprehension ``if``: CC = 2 (1 + comprehension if_clause). Must fire at max=1.
    """
    cases = [
        ("plain_if.py", "def f(x):\n    if x: return 1\n", 2, 1),
        ("if_elif.py", "def f(x):\n    if x: return 1\n    elif y: return 2\n", 3, 2),
        ("comp_if.py", "def f(items):\n    return [i for i in items if i > 0]\n", 2, 1),
        # Nested ifs: each ``if_statement`` is its own node (inner lives
        # inside outer's ``block``), so each contributes exactly +1.
        # Two nested ifs → CC = 3, three nested → CC = 4.
        (
            "nested_if.py",
            "def f(x, y):\n    if x:\n        if y:\n            return 1\n",
            3,
            2,
        ),
        (
            "deep_nested_if.py",
            "def f(a, b, c):\n    if a:\n        if b:\n            if c:\n                return 1\n",
            4,
            3,
        ),
    ]
    for name, source, expected_cc, threshold in cases:
        sample = tmp_path / name
        sample.write_text(source, encoding="utf-8")

        cfg_at = deep_merge(DEFAULTS, {"rules": {"complexity": {"max_complexity": expected_cc}}})
        violations_at_limit = SafetyEngine(cfg_at).check_file(str(sample)).violations
        assert not any(v.rule == "complexity" for v in violations_at_limit), f"{name}: must NOT fire at max_complexity={expected_cc} (CC={expected_cc})"

        cfg_below = deep_merge(DEFAULTS, {"rules": {"complexity": {"max_complexity": threshold}}})
        violations_below = SafetyEngine(cfg_below).check_file(str(sample)).violations
        assert any(v.rule == "complexity" for v in violations_below), f"{name}: must fire at max_complexity={threshold} (CC={expected_cc})"


def test_complexity_fires_on_high_cyclomatic_complexity(tmp_path: Path) -> None:
    """complexity fires when cyclomatic complexity exceeds max_complexity."""
    # Build a function with CC > 10 by chaining many if statements
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    source = f"def complex_func(x):\n{branches}\n    return -1\n"
    sample = tmp_path / "complex.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations

    assert any(v.rule == "complexity" for v in violations)


def test_violation_fields_are_populated(tmp_path: Path) -> None:
    """Violations carry rule, filepath, lineno, message, and severity."""
    sample = tmp_path / "v.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    violations = _engine().check_file(str(sample)).violations
    bare = next(v for v in violations if v.rule == "bare_except")

    assert bare.filepath == str(sample)
    assert bare.lineno > 0
    assert bare.message
    assert bare.severity in {"error", "warning"}


def test_partition_violations_splits_by_threshold() -> None:
    """partition_violations correctly separates blocking from advisory violations."""
    engine = _engine()
    violations = [
        Violation(rule="r1", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error"),
        Violation(rule="r2", code="SAFE002", filepath="f.py", lineno=2, message="m", severity="warning"),
    ]

    blocking, advisory = engine.partition_violations(violations, fail_threshold=1)

    assert len(blocking) == 1
    assert blocking[0].severity == "error"
    assert len(advisory) == 1
    assert advisory[0].severity == "warning"


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

    violations = _engine().check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

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
    violations = engine.check_file(str(sample)).violations

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

    violations = _engine().check_file(str(sample)).violations

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
    violations = engine.check_file(str(sample)).violations

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
    violations = engine.check_file(str(sample)).violations

    assert any(v.rule == "test_coupling" for v in violations)


# ---------------------------------------------------------------------------
# CLI entry points (tested via the underlying functions, not subprocess)
# ---------------------------------------------------------------------------


def test_cli_hook_mode_exits_0_on_clean_file(tmp_path: Path) -> None:
    """_run_hook returns 0 when the given files have no violations."""
    sample = tmp_path / "clean.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    args = argparse.Namespace(fail_on=None, mode=None, ignore=None)
    result = _run_hook(args, [str(sample)])

    assert result == 0


def test_cli_hook_mode_exits_1_on_violation(tmp_path: Path) -> None:
    """_run_hook returns 1 when a blocking violation is found."""
    sample = tmp_path / "bad.py"
    sample.write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(fail_on="error", mode=None, ignore=None)
    result = _run_hook(args, [str(sample)])

    assert result == 1


def test_cli_hook_mode_empty_files_list_exits_0() -> None:
    """_run_hook returns 0 immediately when no files are provided."""

    args = argparse.Namespace(fail_on=None, mode=None, ignore=None)
    assert _run_hook(args, []) == 0


def test_cli_check_mode_exits_0_on_clean_directory(tmp_path: Path) -> None:
    """_run_check returns 0 when the scanned directory has no violations."""

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, ignore=None)
    result = _run_check(args)

    assert result == 0


def test_cli_check_mode_exits_1_on_violation(tmp_path: Path) -> None:
    """_run_check returns 1 when violations are found."""

    (tmp_path / "bad.py").write_text(
        "def foo():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(target=tmp_path, config=None, fail_on="error", mode=None, ignore=None)
    result = _run_check(args)

    assert result == 1


# ---------------------------------------------------------------------------
# LintResult.has_violations
# ---------------------------------------------------------------------------


def test_lint_result_has_violations_true() -> None:
    """LintResult.has_violations returns True when violations list is non-empty."""

    v = Violation(rule="r", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error")
    result = LintResult(path="f.py", violations=[v])
    assert result.has_violations is True


def test_lint_result_has_violations_false() -> None:
    """LintResult.has_violations returns False when violations list is empty."""

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
    violations = engine.check_file(str(sample)).violations
    assert any(v.rule == "test_coupling" for v in violations)


# ---------------------------------------------------------------------------
# BaseRule._call_name returns None for non-Name/Attribute func nodes
# ---------------------------------------------------------------------------


def test_base_rule_call_name_returns_none_for_subscript() -> None:
    """call_name returns None when the function expression is not identifier or attribute."""
    language = tree_sitter.Language(tree_sitter_python.language())
    tree = tree_sitter.Parser(language).parse(b"func_map['key']()")
    call_node = next(n for n in walk(tree.root_node) if n.type == "call")
    assert call_name(call_node) is None


# ---------------------------------------------------------------------------
# ComplexityRule: BoolOp and comprehension-with-ifs branches
# ---------------------------------------------------------------------------


def test_complexity_bool_op_increments_cc(tmp_path: Path) -> None:
    """ComplexityRule counts 'and'/'or' operators as branch points."""
    source = "def foo(a, b, c):\n    return a and b and c\n"
    sample = tmp_path / "bool_op.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine({"rules": {"complexity": {"max_complexity": 1}}}).check_file(str(sample)).violations
    assert any(v.rule == "complexity" for v in violations)


def test_complexity_comprehension_with_condition(tmp_path: Path) -> None:
    """ComplexityRule counts comprehension `if` conditions as branch points."""
    source = "def foo(items):\n    return [x for x in items if x > 0 if x < 100]\n"
    sample = tmp_path / "comp_ifs.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine({"rules": {"complexity": {"max_complexity": 1}}}).check_file(str(sample)).violations
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
    violations = SafetyEngine(config).check_file(str(sample)).violations
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
    violations = SafetyEngine(config).check_file(str(sample)).violations
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
    violations = SafetyEngine(config).check_file(str(sample)).violations
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
    violations = SafetyEngine(config).check_file(str(sample)).violations
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

    violations = _engine().check_file(str(sample)).violations
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

    violations = _engine().check_file(str(sample)).violations
    assert any(v.rule == "unbounded_loops" for v in violations)


# ---------------------------------------------------------------------------
# MaxArgumentsRule: self/cls is excluded from the count
# ---------------------------------------------------------------------------


def test_max_arguments_self_excluded_from_count(tmp_path: Path) -> None:
    """max_arguments strips 'self' before counting, so 8 real args still fires."""
    source = "class Foo:\n    def bar(self, a, b, c, d, e, f, g, h):\n        pass\n"
    sample = tmp_path / "method.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    assert any(v.rule == "max_arguments" for v in violations)


def test_max_arguments_counts_args_kwargs_splats(tmp_path: Path) -> None:
    """*args and **kwargs each count as a parameter; 6 regular + *a + **k = 8 fires."""
    source = "def many(a, b, c, d, e, f, *args, **kwargs):\n    pass\n"
    sample = tmp_path / "splats.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    assert any(v.rule == "max_arguments" for v in violations)


def test_max_arguments_args_only_does_not_fire_under_limit(tmp_path: Path) -> None:
    """A single *args with no other params is one parameter — should not fire."""
    source = "def variadic(*args):\n    pass\n"
    sample = tmp_path / "variadic.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    assert not any(v.rule == "max_arguments" for v in violations)


def test_max_arguments_keyword_only_separator_not_counted(tmp_path: Path) -> None:
    """The bare `*` keyword-only separator must not be counted as a parameter.

    `def f(a, b, c, d, e, f, g, *, h):` has 8 named parameters but no splat;
    the bare `*` is just a separator. Without correct handling we would either
    miss the violation (if treated as a separator that drops following names)
    or over-count (if treated as a parameter). 8 named params should fire.
    """
    source = "def f(a, b, c, d, e, ff, g, *, h):\n    pass\n"
    sample = tmp_path / "kwonly.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    assert any(v.rule == "max_arguments" for v in violations)


# ---------------------------------------------------------------------------
# Nested-def isolation: per-function rules must not aggregate metrics from
# nested ``def`` / ``async def`` bodies into their enclosing function.
# ---------------------------------------------------------------------------


def test_complexity_does_not_count_branches_in_nested_defs(tmp_path: Path) -> None:
    """An outer function whose own body is simple must not be flagged just
    because a nested helper has many branches. The inner def is its own
    function and is checked separately."""
    branches = "\n".join(f"        if x == {i}: return {i}" for i in range(15))
    source = "def outer():\n    def inner(x):\n" + branches + "\n        return -1\n    return inner\n"
    sample = tmp_path / "nested_complexity.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    # `inner` should fire (cc > 10); `outer` must not.
    flagged = [v for v in violations if v.rule == "complexity"]
    assert any('"inner"' in v.message for v in flagged)
    assert not any('"outer"' in v.message for v in flagged)


def test_nesting_depth_does_not_count_nested_def_bodies(tmp_path: Path) -> None:
    """A deeply-nested helper inside an otherwise-flat outer function must
    not push the outer function over the depth limit."""
    source = textwrap.dedent("""\
        def outer():
            def inner():
                if True:
                    if True:
                        if True:
                            if True:
                                return 1
            return inner
    """)
    sample = tmp_path / "nested_depth.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "nesting_depth"]
    assert any('"inner"' in v.message for v in flagged)
    assert not any('"outer"' in v.message for v in flagged)


def test_missing_assertions_does_not_credit_outer_for_inner_assert(tmp_path: Path) -> None:
    """An assert inside a nested def must not count toward the outer
    function's assertion check."""
    source = textwrap.dedent("""\
        def outer(x):
            def inner(y):
                assert y > 0
                return y
            return inner(x)
    """)
    sample = tmp_path / "nested_assert.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "missing_assertions"]
    # `outer` has no assert of its own; `inner` does.
    assert any('"outer"' in v.message for v in flagged)
    assert not any('"inner"' in v.message for v in flagged)


def test_unbounded_loops_break_inside_nested_for_does_not_count(tmp_path: Path) -> None:
    """A break inside a nested for-loop exits the inner loop, not the
    outer ``while True``. The outer while is still infinite."""
    source = textwrap.dedent("""\
        def watch():
            while True:
                for item in [1, 2, 3]:
                    if item == 99:
                        break
    """)
    sample = tmp_path / "nested_break.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    assert any(v.rule == "unbounded_loops" for v in violations)


def test_logging_on_error_ignores_log_call_inside_nested_def(tmp_path: Path) -> None:
    """A logging call buried inside a nested ``def`` defined in the except
    body must not satisfy SAFE203 — that helper isn't executed when the
    exception fires, so the caller is still effectively swallowing the
    error silently."""
    source = textwrap.dedent("""\
        import logging

        log = logging.getLogger(__name__)

        def fetch():
            try:
                do_work()
            except ValueError:
                def _later_helper():
                    log.error("would log if called")
                pass
    """)
    sample = tmp_path / "fake_log.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"logging_on_error": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert any(v.rule == "logging_on_error" for v in violations)


def test_logging_on_error_accepts_real_log_call_in_body(tmp_path: Path) -> None:
    """Sanity check: a logging call directly in the except body still passes."""
    source = textwrap.dedent("""\
        import logging

        log = logging.getLogger(__name__)

        def fetch():
            try:
                do_work()
            except ValueError:
                log.error("real log call")
    """)
    sample = tmp_path / "real_log.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"logging_on_error": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert not any(v.rule == "logging_on_error" for v in violations)


def test_global_state_does_not_attribute_nested_def_global_to_outer(tmp_path: Path) -> None:
    """A ``global`` declared in a nested function belongs to the inner
    scope; the outer function must not be flagged for it."""
    source = textwrap.dedent("""\
        counter = 0
        def outer():
            def inner():
                global counter
                return counter
            return inner
    """)
    sample = tmp_path / "nested_global.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "global_state"]
    assert any('"inner"' in v.message for v in flagged)
    assert not any('"outer"' in v.message for v in flagged)


def test_parse_error_reports_location_and_kind(tmp_path: Path) -> None:
    """Parse failures should report a non-zero line and a kind hint, not just a generic message.

    A function header missing its colon is a clear case where Tree-sitter
    flags a missing-token error. We expect the violation to point at the
    line where the syntax breaks, not lineno=0.
    """
    # `def foo()` without the closing `:` and a body — Tree-sitter cannot
    # complete the function_definition rule and reports a missing token.
    source = "x = 1\ndef foo()\n    pass\n"
    sample = tmp_path / "broken.py"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))

    parse_violations = [v for v in result.violations if v.code == "SAFE000"]
    assert len(parse_violations) == 1
    v = parse_violations[0]
    assert v.lineno >= 2  # error is on the def line or later, not line 0
    # Message should mention "Parse error" and either "missing" or "syntax error".
    assert "Parse error" in v.message
    assert "line" in v.message
    assert ("missing" in v.message) or ("syntax error" in v.message)


def test_function_length_counts_inclusively(tmp_path: Path) -> None:
    """A function spanning N lines (including its def line) should report length N.

    Previously the calculation was ``end_lineno - lineno`` which under-reported
    by 1 — a 60-line function read as 59. The fix is ``+ 1`` for inclusive
    line counting.
    """
    # 5-line function (def + 4 body lines), max_lines=4 → must fire.
    body = "\n".join(f"    x{i} = {i}" for i in range(4))
    source = f"def f():\n{body}\n"
    sample = tmp_path / "len5.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"function_length": {"max_lines": 4}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "function_length"]
    assert flagged
    assert "5 lines" in flagged[0].message


def test_side_effects_io_keyword_match_is_case_insensitive(tmp_path: Path) -> None:
    """A function whose name contains an io keyword in mixed case should be exempt.

    Without lowercasing, ``writeLog`` would not match the lowercase keywords
    ``write`` / ``log`` and would incorrectly fire SAFE304.
    """
    source = "def writeLog(msg):\n    print(msg)\n"
    sample = tmp_path / "mixed.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    assert not any(v.rule == "side_effects" for v in violations)


def test_state_purity_does_not_attribute_class_body_global_to_outer(tmp_path: Path) -> None:
    """A ``global`` declared inside a nested class body lives in the class's
    own scope and must not be attributed to the enclosing function."""
    source = textwrap.dedent("""\
        counter = 0
        def outer():
            class Inner:
                global counter
                counter = 1
            return Inner
    """)
    sample = tmp_path / "nested_class_global.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "global_state"]
    # outer() doesn't declare a global itself; only Inner's body does.
    assert not any('"outer"' in v.message for v in flagged)


def test_taint_tracker_handles_keyword_argument(tmp_path: Path) -> None:
    """``eval(code=user_input)`` should be flagged: the keyword-argument
    wrapper must not hide the tainted value from the sink check."""
    source = textwrap.dedent("""\
        def run(user_input):
            eval(code=user_input)
    """)
    sample = tmp_path / "kwarg_taint.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert any(v.rule == "tainted_sink" for v in violations)


def test_taint_tracker_propagates_through_tuple_destructure(tmp_path: Path) -> None:
    """``a, b = user_input`` must mark both ``a`` and ``b`` as tainted, so
    a later ``eval(a)`` is caught."""
    source = textwrap.dedent("""\
        def run(user_input):
            a, b = user_input
            eval(a)
    """)
    sample = tmp_path / "tuple_destructure.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert any(v.rule == "tainted_sink" for v in violations)


def test_taint_tracker_propagates_through_list_destructure(tmp_path: Path) -> None:
    """List-pattern destructure should also propagate taint to every name."""
    source = textwrap.dedent("""\
        def run(user_input):
            [a, b] = user_input
            eval(b)
    """)
    sample = tmp_path / "list_destructure.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert any(v.rule == "tainted_sink" for v in violations)


def test_taint_tracker_propagates_through_starred_destructure(tmp_path: Path) -> None:
    """``a, *rest = tainted`` should taint both ``a`` and ``rest``."""
    source = textwrap.dedent("""\
        def run(user_input):
            a, *rest = user_input
            eval(rest)
    """)
    sample = tmp_path / "starred_destructure.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert any(v.rule == "tainted_sink" for v in violations)


def test_taint_tracker_propagates_through_chained_assignment(tmp_path: Path) -> None:
    """``a = b = user_input`` must taint both ``a`` and ``b``, so an ``eval``
    on the *outer* target (``a``, the one furthest from the RHS) is flagged."""
    source = textwrap.dedent("""\
        def run(user_input):
            a = b = user_input
            eval(a)
    """)
    sample = tmp_path / "chained_assign.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert any(v.rule == "tainted_sink" for v in violations)


def test_per_file_ignores_rejects_non_string_entries(tmp_path: Path) -> None:
    """A list containing a non-string entry should fail loud at engine init,
    not crash later when ``.upper()`` is called on it."""
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": {"tests/**": ["SAFE101", 42]}})
    with pytest.raises(TypeError, match="must contain only strings"):
        SafetyEngine(cfg)


def test_ignore_rejects_non_string_entries(tmp_path: Path) -> None:
    """Top-level ``ignore`` list — same contract as per_file_ignores: every
    entry must be a string. A non-string entry would crash on ``.upper()``
    inside the unknown-entries filter, so we surface the type error early."""
    cfg = deep_merge(DEFAULTS, {"ignore": ["SAFE101", 42]})
    with pytest.raises(TypeError, match="must contain only strings"):
        SafetyEngine(cfg)


def test_ignore_rejects_non_list_value(tmp_path: Path) -> None:
    """``ignore`` must be a list/tuple, not a bare string or scalar."""
    cfg = deep_merge(DEFAULTS, {"ignore": "SAFE101"})
    with pytest.raises(TypeError, match="must be a list"):
        SafetyEngine(cfg)


def test_load_config_returns_isolated_copy(tmp_path: Path) -> None:
    """Mutating the result of load_config() must not leak into DEFAULTS."""
    config = load_config(tmp_path)
    config["ignore"] = ["SAFE101"]
    config.setdefault("rules", {}).setdefault("function_length", {})["max_lines"] = 999

    fresh = load_config(tmp_path)
    assert fresh["ignore"] == DEFAULTS["ignore"]
    assert fresh["rules"]["function_length"]["max_lines"] == DEFAULTS["rules"]["function_length"]["max_lines"]


def test_load_config_treats_empty_standalone_safelint_toml_as_present(tmp_path: Path) -> None:
    """An empty ``safelint.toml`` next to a populated ``[tool.safelint]`` blocks
    fallback to pyproject.toml — the standalone file is the chosen source even
    if it has nothing to say."""
    (tmp_path / "pyproject.toml").write_text("[tool.safelint]\nmode = 'ci'\n", encoding="utf-8")
    (tmp_path / "safelint.toml").write_text("", encoding="utf-8")

    config = load_config(tmp_path)
    # safelint.toml wins; with nothing in it, defaults apply (mode != 'ci').
    assert config["mode"] == DEFAULTS["mode"]


def test_load_config_treats_empty_safelint_section_as_present(tmp_path: Path) -> None:
    """An empty ``[tool.safelint]`` is a *present* config — the loader must
    stop at the first directory containing one, not fall through to an
    ancestor's config."""
    # Parent has a real config, child has an empty section. Loader is
    # invoked from the child. It should return DEFAULTS (the empty section
    # has nothing to merge), not the parent's config.
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    (parent / "pyproject.toml").write_text(
        "[tool.safelint]\nmode = 'ci'\n",
        encoding="utf-8",
    )
    (child / "pyproject.toml").write_text(
        "[tool.safelint]\n",
        encoding="utf-8",
    )

    config = load_config(child)
    assert config["mode"] == DEFAULTS["mode"]


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

    violations = _engine().check_file(str(sample)).violations
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

    violations = _engine().check_file(str(sample)).violations
    assert not any(v.rule == "side_effects_hidden" for v in violations)


def test_side_effects_hidden_pure_func_no_io_is_clean(tmp_path: Path) -> None:
    """side_effects_hidden does not flag a pure-named function with no I/O calls."""
    source = textwrap.dedent("""\
        def get_value():
            return 42
    """)
    sample = tmp_path / "pure.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
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

    violations = _engine().check_file(str(sample)).violations
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
    violations = SafetyEngine(config).check_file(str(sample)).violations
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
    violations = SafetyEngine(config).check_file(str(sample)).violations
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
    violations = SafetyEngine(config).check_file(str(sample)).violations
    assert not any(v.rule == "test_coupling" for v in violations)


# ---------------------------------------------------------------------------
# CLI: _run_check with advisory-only violations, main(), _build_common_args
# ---------------------------------------------------------------------------


def test_cli_run_check_advisory_only_returns_0(tmp_path: Path) -> None:
    """_run_check returns 0 when violations are all advisory (below fail_on threshold)."""

    # logging_on_error fires at warning severity when an except block has no log call
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except ValueError as e:
                x = 1
    """)
    (tmp_path / "warn.py").write_text(source, encoding="utf-8")

    args = argparse.Namespace(target=tmp_path, config=None, fail_on="error", mode=None, ignore=None)
    result = _run_check(args)

    assert result == 0


def test_cli_main_check_mode_exits_0(tmp_path: Path, monkeypatch) -> None:
    """main() routes to check mode when 'check' is the first positional arg."""

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["safelint", "check", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_cli_main_hook_mode_exits_0(tmp_path: Path, monkeypatch) -> None:
    """main() routes to hook mode when no 'check' subcommand is present."""

    sample = tmp_path / "clean.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["safelint", str(sample)])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_build_common_args_adds_fail_on_and_mode() -> None:
    """_build_common_args registers --fail-on and --mode arguments."""

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
    violations = SafetyEngine(config).check_file(str(sample)).violations
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

    violations = _engine().check_file(str(sample)).violations
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

    violations = _engine().check_file(str(sample)).violations
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

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    mocker.patch("safelint.cli.subprocess.run", side_effect=FileNotFoundError)

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=False, ignore=None)
    assert _run_check(args) == 0


def test_cli_check_git_diff_failure_falls_back_to_full_scan(tmp_path: Path, mocker) -> None:
    """_run_check falls back to a full scan when git diff returns a non-zero exit code."""

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    rev_parse = _make_proc(mocker, returncode=0, stdout=str(tmp_path) + "\n")
    diff_fail = _make_proc(mocker, returncode=128, stdout="")
    ok_proc = _make_proc(mocker, returncode=0, stdout="")
    mocker.patch("safelint.cli.subprocess.run", side_effect=[rev_parse, diff_fail, ok_proc, ok_proc])

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=False, ignore=None)
    assert _run_check(args) == 0


def test_cli_check_no_modified_files_exits_0(tmp_path: Path, mocker, capsys) -> None:
    """_run_check exits 0 with a status message when git reports no modified Python files."""

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    rev_parse = _make_proc(mocker, returncode=0, stdout=str(tmp_path) + "\n")
    empty_diff = _make_proc(mocker, returncode=0, stdout="")
    mocker.patch("safelint.cli.subprocess.run", side_effect=[rev_parse, empty_diff, empty_diff, empty_diff])

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=False, ignore=None)
    assert _run_check(args) == 0
    assert "No modified Python files detected" in capsys.readouterr().out


def test_cli_check_all_files_bypasses_git(tmp_path: Path, mocker) -> None:
    """_run_check does not invoke git when --all-files is set."""

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    spy = mocker.patch("safelint.cli.subprocess.run")

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=True, ignore=None)
    result = _run_check(args)

    spy.assert_not_called()
    assert result == 0


def test_cli_check_only_in_target_files_linted(tmp_path: Path, mocker) -> None:
    """_run_check lints only in-target files; out-of-target diffs are not linted."""

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
    empty_proc = _make_proc(mocker, returncode=0, stdout="")
    mocker.patch("safelint.cli.subprocess.run", side_effect=[rev_parse, diff_proc, diff_proc, empty_proc])

    # Target is src/ only — test_mod.py must not be linted
    args = argparse.Namespace(target=src_dir, config=None, fail_on="error", mode=None, all_files=False, ignore=None)
    assert _run_check(args) == 0
