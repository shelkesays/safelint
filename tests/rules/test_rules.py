"""Additional tests to reach the 80% coverage threshold."""

from __future__ import annotations

import argparse
import os
from pathlib import Path as _Path
import signal
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


def test_resource_lifecycle_flags_socket_outside_with(tmp_path: Path) -> None:
    """Expanded defaults catch ``socket.socket()`` calls outside a ``with`` (1.8.0)."""
    source = textwrap.dedent("""\
        import socket
        s = socket.socket()
        s.send(b"hi")
    """)
    sample = tmp_path / "sock.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    assert any(v.rule == "resource_lifecycle" and "socket" in v.message for v in violations)


def test_resource_lifecycle_extend_tracked_functions(tmp_path: Path) -> None:
    """``extend_tracked_functions`` adds custom acquirers without losing defaults (1.8.0)."""
    source = textwrap.dedent("""\
        from mylib import acquire_widget
        w = acquire_widget()
        w.use()
    """)
    sample = tmp_path / "ext.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {"rules": {"resource_lifecycle": {"extend_tracked_functions": ["acquire_widget"]}}},
    )
    violations = SafetyEngine(config).check_file(str(sample)).violations
    assert any(v.rule == "resource_lifecycle" and "acquire_widget" in v.message for v in violations)
    # And the default ``open`` is still tracked - extension didn't displace it.
    src2 = "f = open('x.txt')\nf.read()\n"
    sample2 = tmp_path / "still_default.py"
    sample2.write_text(src2, encoding="utf-8")
    violations2 = SafetyEngine(config).check_file(str(sample2)).violations
    assert any(v.rule == "resource_lifecycle" and "open" in v.message for v in violations2)


def test_resource_lifecycle_rejects_string_tracked_functions(tmp_path: Path) -> None:
    """``tracked_functions = "open"`` (no brackets) is a typo, not a single-element config.

    Without explicit validation, ``list("open")`` would coerce to
    ``['o', 'p', 'e', 'n']`` and silently track those one-character
    function names. Validation surfaces the typo as a clear TypeError.
    """
    sample = tmp_path / "rl_bad.py"
    sample.write_text("f = open('x.txt')\nf.read()\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"resource_lifecycle": {"tracked_functions": "open"}}})
    with pytest.raises(TypeError, match="tracked_functions"):
        SafetyEngine(cfg).check_file(str(sample))


def test_resource_lifecycle_rejects_non_string_tracked_function_entries(tmp_path: Path) -> None:
    """Non-string entries in tracked_functions (e.g. ``[123]``) raise TypeError too."""
    sample = tmp_path / "rl_bad2.py"
    sample.write_text("f = open('x.txt')\nf.read()\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"resource_lifecycle": {"tracked_functions": ["open", 123]}}})
    with pytest.raises(TypeError, match="tracked_functions"):
        SafetyEngine(cfg).check_file(str(sample))


def test_resource_lifecycle_rejects_string_cleanup_patterns(tmp_path: Path) -> None:
    """``cleanup_patterns = "close"`` (no brackets) is a typo, not a single-element config.

    Without explicit validation, ``frozenset("close")`` would coerce to
    ``{'c', 'l', 'o', 's', 'e'}`` and the diagnostic text would render
    as ``c / e / l / o / s``. Validation surfaces the typo as TypeError.
    """
    sample = tmp_path / "rl_cleanup_bad.py"
    sample.write_text("f = open('x.txt')\nf.read()\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"resource_lifecycle": {"cleanup_patterns": "close"}}})
    with pytest.raises(TypeError, match="cleanup_patterns"):
        SafetyEngine(cfg).check_file(str(sample))


def test_empty_except_flags_pass_body(tmp_path: Path) -> None:
    """``except: pass`` is the canonical no-op handler - must fire SAFE202."""
    source = textwrap.dedent("""\
        def f():
            try:
                pass
            except Exception:
                pass
    """)
    sample = tmp_path / "ee_pass.py"
    sample.write_text(source, encoding="utf-8")
    violations = _engine().check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_empty_except_flags_ellipsis_body(tmp_path: Path) -> None:
    """``except: ...`` is also a no-op (Ellipsis literal)."""
    source = textwrap.dedent("""\
        def f():
            try:
                pass
            except Exception:
                ...
    """)
    sample = tmp_path / "ee_ellipsis.py"
    sample.write_text(source, encoding="utf-8")
    violations = _engine().check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_empty_except_flags_string_literal_body(tmp_path: Path) -> None:
    """``except: "TODO"`` - string-as-comment idiom is also a no-op."""
    source = textwrap.dedent("""\
        def f():
            try:
                pass
            except Exception:
                "TODO: handle this properly"
    """)
    sample = tmp_path / "ee_str.py"
    sample.write_text(source, encoding="utf-8")
    violations = _engine().check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_empty_except_flags_constant_literal_body(tmp_path: Path) -> None:
    """``except: 0`` / ``except: None`` / ``except: True`` are all no-ops."""
    for literal in ("0", "None", "True", "False"):
        source = textwrap.dedent(f"""\
            def f():
                try:
                    pass
                except Exception:
                    {literal}
        """)
        sample = tmp_path / f"ee_{literal}.py"
        sample.write_text(source, encoding="utf-8")
        violations = _engine().check_file(str(sample)).violations
        assert any(v.code == "SAFE202" for v in violations), f"failed for literal: {literal}"


def test_empty_except_does_not_flag_real_handler(tmp_path: Path) -> None:
    """A genuine handler with a logging call or re-raise must NOT trigger SAFE202."""
    source = textwrap.dedent("""\
        import logging
        def f():
            try:
                pass
            except Exception as e:
                logging.error("failed: %s", e)
    """)
    sample = tmp_path / "ee_real.py"
    sample.write_text(source, encoding="utf-8")
    violations = _engine().check_file(str(sample)).violations
    assert not any(v.code == "SAFE202" for v in violations)


def test_empty_except_does_not_flag_interpolated_fstring_body(tmp_path: Path) -> None:
    """``except E: f"got {e!r}"`` evaluates ``e!r`` - that's a real side effect.

    Regression: an earlier version had ``"string"`` in the literal-types
    set, which caused interpolated f-strings to short-circuit before the
    interpolation-aware check could run. The fix is to handle string
    nodes only via ``_is_string_literal_expression``, which inspects the
    children for ``interpolation`` markers.
    """
    source = textwrap.dedent("""\
        def f(e):
            try:
                pass
            except Exception as err:
                f"got {err!r}"
    """)
    sample = tmp_path / "ee_fstring.py"
    sample.write_text(source, encoding="utf-8")
    violations = _engine().check_file(str(sample)).violations
    assert not any(v.code == "SAFE202" for v in violations)


def test_empty_except_does_not_flag_multi_statement_body(tmp_path: Path) -> None:
    """Two statements in the body, even if both look trivial, isn't 'empty'."""
    source = textwrap.dedent("""\
        def f():
            try:
                pass
            except Exception:
                "log message"
                pass
    """)
    sample = tmp_path / "ee_multi.py"
    sample.write_text(source, encoding="utf-8")
    violations = _engine().check_file(str(sample)).violations
    # Multi-statement body - not flagged by SAFE202 (still flagged by SAFE203
    # for missing logging call, but that's a separate rule).
    assert not any(v.code == "SAFE202" for v in violations)


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


def test_bare_except_attaches_replace_with_exception_suggestion(tmp_path: Path) -> None:
    """SAFE201 attaches an advisory suggestion to replace ``except:`` with ``except Exception:`` (1.8.0)."""
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except:
                pass
    """)
    sample = tmp_path / "bare_sug.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "bare_except"]
    assert flagged
    v = flagged[0]
    assert len(v.suggestions) == 1
    suggestion = v.suggestions[0]
    assert "Exception" in suggestion.description
    assert len(suggestion.edits) == 1
    edit = suggestion.edits[0]
    assert edit.replacement == "except Exception:"
    # Range should cover the ``except:`` header on line 4.
    assert edit.start_line == 4
    assert edit.end_line == 4
    # Column precision: the edit must cover *exactly* the ``except:`` token -
    # not the indentation before it, not the trailing newline. Locked in
    # to catch any regression in the suggestion's range computation
    # (off-by-one on either side would break editor-applied edits).
    # On the dedented source, line 4 is ``    except:``; the ``e`` of
    # ``except`` is at 1-based column 5, and the half-open range ends
    # one past the closing colon - i.e. start_column + len("except:").
    assert edit.start_column == 5
    assert edit.end_column == edit.start_column + len("except:")


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


def test_global_mutation_flags_annotated_assignment(tmp_path: Path) -> None:
    """``x: int = 1`` inside a ``global x`` function fires global_mutation.

    Annotated assignments are a distinct Tree-sitter node type from
    regular assignments; the rule's target extractor has to handle them
    separately. This regression makes sure the bare-identifier branch
    of that extractor is exercised (``a[0]: int = …`` is the only path
    we don't cover, by design).
    """
    source = textwrap.dedent("""\
        counter = 0

        def increment():
            global counter
            counter: int = counter + 1
    """)
    sample = tmp_path / "gm_annotated.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations

    assert any(v.rule == "global_mutation" for v in violations)


def test_global_mutation_default_does_not_flag_read_only_global(tmp_path: Path) -> None:
    """Default mode allows ``global x; print(x)`` (read-only access)."""
    source = textwrap.dedent("""\
        VERSION = "1.0"
        def show():
            global VERSION
            print(VERSION)
    """)
    sample = tmp_path / "gm_readonly.py"
    sample.write_text(source, encoding="utf-8")
    violations = _engine().check_file(str(sample)).violations
    assert not any(v.rule == "global_mutation" for v in violations)


def test_global_mutation_strict_flags_read_only_global(tmp_path: Path) -> None:
    """``strict = true`` fires on the ``global`` declaration itself, mirroring PLW0603 (1.8.0)."""
    source = textwrap.dedent("""\
        VERSION = "1.0"
        def show():
            global VERSION
            print(VERSION)
    """)
    sample = tmp_path / "gm_strict.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"global_mutation": {"strict": True}}})
    violations = SafetyEngine(config).check_file(str(sample)).violations
    safe302 = [v for v in violations if v.rule == "global_mutation"]
    assert safe302
    assert "strict mode" in safe302[0].message


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


def test_unbounded_loop_while_true_message_uses_python_syntax(tmp_path: Path) -> None:
    """SAFE501 message on a Python file says ``while True``, not ``while (true)``.

    Per-language wording: the same hazard exists in JS but is written
    as ``while (true)``; the message must match the source file's
    language to avoid mixed-syntax messages in violation output.
    """
    source = textwrap.dedent("""\
        def poll():
            while True:
                pass
    """)
    sample = tmp_path / "msg.py"
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations
    safe501 = [v for v in violations if v.code == "SAFE501"]
    assert len(safe501) == 1
    assert "while True" in safe501[0].message
    assert "while (true)" not in safe501[0].message


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
    ``IF_STATEMENT`` to count plain ``if`` branches at all - removing it
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


def test_test_existence_skips_python_test_file_itself(tmp_path: Path) -> None:
    """SAFE701 doesn't fire on a Python test file passed as ``filepath``.

    Without the ``_is_test_file`` guard the rule would search for
    ``test_test_foo.py`` when handed ``tests/test_foo.py`` - pure
    noise. With ``files: ^src/`` dropped from the published
    pre-commit hook in v1.13.0, the rules now reach test files in
    projects that don't restore the filter locally, so the guard
    matters.
    """
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_foo.py"
    test_file.write_text("def test_x(): pass\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(test_dir)]}}},
    )
    engine = SafetyEngine(config)
    violations = engine.check_file(str(test_file)).violations

    assert not any(v.rule == "test_existence" for v in violations)


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


def test_test_coupling_ignores_same_basename_outside_test_dirs(tmp_path: Path) -> None:
    """SAFE702 must NOT be satisfied by a same-basename file changed outside ``test_dirs``.

    Without the test_dirs gate, a changed ``legacy/test_mymodule.py``
    (or any other file with the matching basename) would silently
    satisfy the coupling check even though the *actual* paired test
    under ``tests/`` wasn't touched. Restricting the basename match
    to changed paths under a configured test_dirs entry - the same
    path-component subsequence logic ``_is_test_file`` uses - fixes
    the false-negative.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()

    sample = src_dir / "mymodule.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    (test_dir / "test_mymodule.py").write_text("def test_x(): pass\n", encoding="utf-8")
    decoy = legacy_dir / "test_mymodule.py"  # same basename, outside test_dirs
    decoy.write_text("def test_legacy(): pass\n", encoding="utf-8")

    config = deep_merge(
        DEFAULTS,
        {
            "rules": {
                "test_coupling": {
                    "enabled": True,
                    "test_dirs": [str(test_dir)],
                    # Source changed; decoy changed; the REAL paired test was NOT.
                    "_changed_files": [str(sample), str(decoy)],
                }
            }
        },
    )
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample)).violations

    assert any(v.rule == "test_coupling" for v in violations), "Same-basename file outside test_dirs should not satisfy the coupling check"


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


def test_cli_hook_mode_clean_run_with_suppressions_is_silent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Hook mode prints NOTHING on a clean run, even when suppressions fired (issue #50).

    A clean ``# nosafe``-suppressed file used to print ``All checks
    passed. (N suppressed)``. Under pre-commit's file batching that
    became one such line per invocation, each showing a misleading
    *partial* count. ``silent_on_clean`` now suppresses the summary
    on any clean run regardless of suppressions - pre-commit already
    reports the hook as Passed, and the summed breakdown stays
    available via ``safelint check`` / ``--format json``.
    """
    sample = tmp_path / "suppressed.py"
    # 8 parameters trips SAFE103 (max_arguments, default cap 7); the inline
    # ``# nosafe`` moves it into ``suppressed`` so the run is otherwise clean -
    # no other rule fires on this body.
    sample.write_text(
        "def fn(a, b, c, d, e, g, h, i):  # nosafe: SAFE103\n    return a\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(fail_on=None, mode=None, ignore=None)
    result = _run_hook(args, [str(sample)])

    assert result == 0
    captured = capsys.readouterr()
    assert captured.out == "", f"hook-mode clean run must be silent on stdout; got {captured.out!r}"


def test_cli_check_mode_clean_run_with_suppressions_still_shows_breakdown(
    tmp_path: Path,
    mocker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Interactive ``safelint check`` still prints the aggregated ``(N suppressed)`` breakdown.

    Companion to the hook-mode silence test: ``_run_check`` leaves
    ``silent_on_clean=False``, so the interactive user who explicitly
    ran safelint still gets the summed-per-rule breakdown - issue #50's
    fix is scoped to hook / stdin mode only.
    """
    sample = tmp_path / "suppressed.py"
    sample.write_text(
        "def fn(a, b, c, d, e, g, h, i):  # nosafe: SAFE103\n    return a\n",
        encoding="utf-8",
    )
    from safelint import cli as _cli  # noqa: PLC0415 - local import keeps the module-level import list lean

    mocker.patch.object(_cli, "_get_git_modified_supported_files", return_value=None)
    args = argparse.Namespace(
        target=sample,
        config=None,
        all_files=True,
        fail_on=None,
        mode=None,
        ignore=None,
        output_format="pretty",
        no_cache=True,
        stdin=False,
        stdin_filename="",
    )
    rc = _run_check(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "All checks passed." in out
    assert "SAFE103 suppressed" in out, f"interactive check must keep the suppression breakdown; got {out!r}"


def test_cli_check_mode_suppression_breakdown_is_collective_and_language_agnostic(
    tmp_path: Path,
    mocker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``safelint check --all-files`` over a mixed Python + TypeScript tree prints ONE aggregated summary line.

    Issue #50 follow-up: confirm the suppression breakdown is collective
    (one line for the whole run, not one per file) AND language-agnostic
    (a ``# nosafe`` in Python and a ``// nosafe`` in TypeScript sum into
    a single per-rule count). ``_run_check`` accumulates ``all_suppressed``
    across every ``LintResult`` regardless of language, and
    ``_format_suppressed_breakdown`` keys the ``Counter`` on the rule
    code - so the aggregation is structural, not per-language.
    """
    py_file = tmp_path / "mod.py"
    py_file.write_text(
        "def fn(a, b, c, d, e, g, h, i):  # nosafe: SAFE103\n    return a\n",
        encoding="utf-8",
    )
    ts_file = tmp_path / "mod.ts"
    ts_file.write_text(
        "function gn(a, b, c, d, e, g, h, i) {  // nosafe: SAFE103\n  return a;\n}\n",
        encoding="utf-8",
    )
    from safelint import cli as _cli  # noqa: PLC0415 - local import keeps the module-level import list lean

    mocker.patch.object(_cli, "_get_git_modified_supported_files", return_value=None)
    args = argparse.Namespace(
        target=tmp_path,
        config=None,
        all_files=True,
        fail_on=None,
        mode=None,
        ignore=None,
        output_format="pretty",
        no_cache=True,
        stdin=False,
        stdin_filename="",
    )
    rc = _run_check(args)
    assert rc == 0
    out = capsys.readouterr().out
    # Exactly one summary line - not one per file.
    assert out.count("All checks passed.") == 1, f"expected a single collective summary line; got {out!r}"
    # The Python (.py) and TypeScript (.ts) SAFE103 suppressions sum to 2.
    assert "2 SAFE103 suppressed" in out, f"cross-language suppressions must aggregate into one count; got {out!r}"


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


def test_null_dereference_message_uses_python_syntax(tmp_path: Path) -> None:
    """SAFE803 message on a Python file says ``None check`` / ``is not None``, not JS's ``null check``.

    The same hazard exists in JS but is written as ``null`` /
    ``undefined`` + optional chaining; per-language wording keeps the
    recommended idiom matching the source file's language.
    """
    source = textwrap.dedent("""\
        def f(users):
            name = users.get("alice").upper()
            return name
    """)
    sample = tmp_path / "msg_nd.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"rules": {"null_dereference": {"enabled": True}}})
    violations = SafetyEngine(config).check_file(str(sample)).violations
    safe803 = [v for v in violations if v.code == "SAFE803"]
    assert len(safe803) == 1
    assert "None check" in safe803[0].message
    assert "is not None" in safe803[0].message
    assert "null check" not in safe803[0].message
    assert "?." not in safe803[0].message


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
    """A single *args with no other params is one parameter - should not fire."""
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
    body must not satisfy SAFE203 - that helper isn't executed when the
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
    # `def foo()` without the closing `:` and a body - Tree-sitter cannot
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
    by 1 - a 60-line function read as 59. The fix is ``+ 1`` for inclusive
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


def test_function_length_count_mode_logical_lines_excludes_blanks_and_comments(tmp_path: Path) -> None:
    """``count_mode = "logical_lines"`` ignores blanks and pure-comment lines (1.8.0)."""
    source = "def f():\n    # this is a comment\n    x = 1\n\n    # another comment\n    y = 2\n\n    return x + y\n"
    sample = tmp_path / "len_logical.py"
    sample.write_text(source, encoding="utf-8")

    # Total source lines: 8 (would trip max_lines=6)
    # Logical lines: 4 (def, x = 1, y = 2, return)
    cfg_logical = deep_merge(
        DEFAULTS,
        {"rules": {"function_length": {"max_lines": 6, "count_mode": "logical_lines"}}},
    )
    violations = SafetyEngine(cfg_logical).check_file(str(sample)).violations
    assert not any(v.rule == "function_length" for v in violations)

    # Same source under "lines" mode should fire (max_lines=6, total=8)
    cfg_lines = deep_merge(DEFAULTS, {"rules": {"function_length": {"max_lines": 6}}})
    violations_lines = SafetyEngine(cfg_lines).check_file(str(sample)).violations
    assert any(v.rule == "function_length" for v in violations_lines)


def test_function_length_count_mode_statements_ignores_formatting(tmp_path: Path) -> None:
    """``count_mode = "statements"`` is robust to formatting choices (1.8.0)."""
    # 4 statement nodes regardless of whitespace.
    source = "def f():\n\n    # blah\n    x = 1\n\n    y = (\n        x\n        + 1\n    )\n    if y > 0:\n        z = y\n    return z\n"
    sample = tmp_path / "len_stmts.py"
    sample.write_text(source, encoding="utf-8")

    # Statements: x=1, y=..., if, z=y, return → 5 statement nodes
    cfg_stmts = deep_merge(
        DEFAULTS,
        {"rules": {"function_length": {"max_lines": 4, "count_mode": "statements"}}},
    )
    violations = SafetyEngine(cfg_stmts).check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "function_length"]
    assert flagged
    assert "statements" in flagged[0].message


def test_function_length_count_mode_unknown_raises_value_error(tmp_path: Path) -> None:
    """An unknown ``count_mode`` (typo, etc.) raises ValueError on first lint.

    Previous behaviour silently fell back to ``"lines"``, which left the
    user wondering why their config didn't take effect. Surfacing as a
    ValueError matches how the rule's other type errors are reported.
    """
    sample = tmp_path / "fl_bad_mode.py"
    sample.write_text("def f():\n    pass\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"function_length": {"max_lines": 1, "count_mode": "line"}}})
    with pytest.raises(ValueError, match="count_mode"):
        SafetyEngine(cfg).check_file(str(sample))


def test_function_length_count_mode_statements_skips_nested_defs(tmp_path: Path) -> None:
    """Nested function bodies don't inflate the outer function's statement count.

    Note the deliberate asymmetry with
    :func:`test_function_length_statements_counts_nested_class_definition`:
    a nested ``def`` is *not* recursed into (its body is the inner
    function's own concern), but a nested ``class`` *is* counted (the
    class itself is a statement under Python's grammar, and its body
    contributes to the enclosing function's complexity-proxy total).
    The two tests together pin down both halves of that contract.
    """
    source = "def outer():\n    def inner():\n        a = 1\n        b = 2\n        c = 3\n        d = 4\n        e = 5\n        return a + b + c + d + e\n    return inner()\n"
    sample = tmp_path / "nested_stmts.py"
    sample.write_text(source, encoding="utf-8")

    # outer's own statement count: just the ``return`` (the def is not a stmt
    # we count) → 1.
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"function_length": {"max_lines": 3, "count_mode": "statements"}}},
    )
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    # outer should NOT fire (1 statement, max 3); inner should (8 stmts > 3).
    flagged_for_outer = [v for v in violations if v.rule == "function_length" and "outer" in v.message]
    flagged_for_inner = [v for v in violations if v.rule == "function_length" and "inner" in v.message]
    assert not flagged_for_outer
    assert flagged_for_inner


def test_function_length_statement_types_invariant() -> None:
    """``_STATEMENT_TYPES`` includes ``class_definition`` but excludes ``function_definition``.

    Locks in the asymmetry exercised by the two behavioural tests
    above. A future change that accidentally adds ``function_definition``
    (or removes ``class_definition``) would slip past the behavioural
    tests in subtle cases - e.g. a nested ``def`` adding 1 to the
    outer count would still leave outer under the test's max=3
    threshold. A direct membership assertion on the constant fails
    fast on either parity break.
    """
    from safelint.rules.function_length import _STATEMENT_TYPES_BY_LANG  # noqa: PLC0415

    py_stmts = _STATEMENT_TYPES_BY_LANG["python"]
    assert "class_definition" in py_stmts
    assert "function_definition" not in py_stmts
    assert "async_function_definition" not in py_stmts


def test_function_length_logical_lines_message_uses_logical_lines_unit(tmp_path: Path) -> None:
    """``count_mode = "logical_lines"`` reports unit as "logical lines", not "lines".

    Without the per-mode unit string, a small count under
    ``logical_lines`` could be misread as raw source lines (where
    blanks and comments would inflate the figure).
    """
    # 5 logical lines (blanks/comments would inflate raw line count past 5).
    source = "def foo():\n\n    # blank above\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return a + b + c + d\n"
    sample = tmp_path / "logical_unit.py"
    sample.write_text(source, encoding="utf-8")
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"function_length": {"max_lines": 3, "count_mode": "logical_lines"}}},
    )
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "function_length"]
    assert flagged
    assert "logical lines" in flagged[0].message


def test_function_length_statements_counts_nested_class_definition(tmp_path: Path) -> None:
    """A function containing a ``class Inner: ...`` counts the class as a statement.

    Without ``class_definition`` in ``_STATEMENT_TYPES``, a function
    whose body is dominated by a nested class would silently undercount
    - the rule could miss legitimately large functions in statement
    mode. Adding it ensures the class itself contributes 1 (and its
    body's statements also count, matching the complexity-proxy
    intent of the statements mode).
    """
    # Function body has 1 class_definition + 1 return = 2 statements at the
    # function level. Inside the class: 1 assignment + 1 (skipped) function_definition.
    # With class_definition counted: outer's count = at least 3 (class itself
    # + class body's assignment + return). Without: outer's count = 2
    # (just assignment + return; class itself contributes 0).
    source = "def outer():\n    class Inner:\n        x = 1\n        def m(self): pass\n    return Inner\n"
    sample = tmp_path / "nested_class.py"
    sample.write_text(source, encoding="utf-8")
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"function_length": {"max_lines": 2, "count_mode": "statements"}}},
    )
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    flagged = [v for v in violations if v.rule == "function_length" and "outer" in v.message]
    assert flagged, "outer() should exceed max_lines=2 once class_definition is counted"


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


def test_side_effects_uppercase_config_keyword_still_matches(tmp_path: Path) -> None:
    """A user-supplied keyword like ``"Write"`` (uppercase) must still exempt
    a function named ``writeLog``. Both sides of the substring check must be
    normalised, not just the function name."""
    source = "def writeLog(msg):\n    print(msg)\n"
    sample = tmp_path / "mixed_upper_kw.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"side_effects": {"io_name_keywords": ["Write", "Log"]}}},
    )
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert not any(v.rule == "side_effects" for v in violations)


def test_side_effects_hidden_uppercase_pure_prefix_still_matches(tmp_path: Path) -> None:
    """SideEffectsHiddenRule must also normalise user-supplied prefixes:
    ``"Get"`` in config should still flag ``get_data`` (which calls open)."""
    source = "def get_data():\n    f = open('x.txt')\n    return f.read()\n"
    sample = tmp_path / "upper_prefix.py"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"side_effects_hidden": {"pure_prefixes": ["Get"]}}},
    )
    violations = SafetyEngine(cfg).check_file(str(sample)).violations
    assert any(v.rule == "side_effects_hidden" for v in violations)


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
    """Top-level ``ignore`` list - same contract as per_file_ignores: every
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
    fallback to pyproject.toml - the standalone file is the chosen source even
    if it has nothing to say."""
    (tmp_path / "pyproject.toml").write_text("[tool.safelint]\nmode = 'ci'\n", encoding="utf-8")
    (tmp_path / "safelint.toml").write_text("", encoding="utf-8")

    config = load_config(tmp_path)
    # safelint.toml wins; with nothing in it, defaults apply (mode != 'ci').
    assert config["mode"] == DEFAULTS["mode"]


def test_discover_files_does_not_loop_on_symlink_cycle(tmp_path: Path) -> None:
    """A symlink cycle inside the target directory must not hang discovery
    (issue #19). ``os.walk(..., followlinks=False)`` does not follow
    symlinks to subdirectories during descent, breaking any cycle by
    construction.

    Build: target/a.py is a real file, target/loop/ is a symlink to target/.
    Without the fix, ``Path.rglob('*')`` would follow ``loop/`` back to
    ``target/`` and recurse forever.

    Wraps the discovery call in a ``signal.alarm``-based timeout so any
    hang from a regression is interrupted in-place (no leftover work
    or daemon thread continuing after the test fails). POSIX-only -
    Windows lacks ``SIGALRM`` and is skipped.
    """
    if not hasattr(os, "symlink"):
        pytest.skip("symlink not supported on this platform")
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("signal.SIGALRM not available (Windows)")
    target = tmp_path / "target"
    target.mkdir()
    real_file = target / "a.py"
    real_file.write_text("x = 1\n", encoding="utf-8")
    try:
        (target / "loop").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support directory symlinks")

    def _on_alarm(_signum: int, _frame: object) -> None:
        msg = "discovery did not finish within 5s - symlink-cycle protection regressed"
        raise TimeoutError(msg)

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(5)
    try:
        files = _engine()._discover_files(target)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    assert str(real_file) in files
    # And no infinite duplicates from symlink-following.
    assert len(files) == 1


def test_discover_files_prunes_excluded_subtrees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Excluded directories should be pruned during ``os.walk`` descent -
    not just filtered at the end. Verified by spying on ``Path.is_file``:
    if we ever query a file inside an excluded subtree, the prune logic
    broke and we did the wasted descent.
    """
    target = tmp_path / "root"
    (target / "src").mkdir(parents=True)
    (target / "src" / "good.py").write_text("x = 1\n", encoding="utf-8")
    excluded_dir = target / "node_modules"
    excluded_dir.mkdir()
    (excluded_dir / "evil.py").write_text("x = 2\n", encoding="utf-8")
    (excluded_dir / "deep").mkdir()
    (excluded_dir / "deep" / "deeper.py").write_text("x = 3\n", encoding="utf-8")

    queried: list[str] = []
    original_is_file = _Path.is_file

    def spy(self: _Path) -> bool:
        queried.append(str(self))
        return original_is_file(self)

    monkeypatch.setattr(_Path, "is_file", spy)

    # Pattern matches the excluded directory's exact path so `_is_excluded`
    # prunes it during descent. ``extend_exclude_paths`` is the documented
    # recommended form - the pattern goes through the same matcher as
    # ``exclude_paths``, so this exercises the descent-pruning path users
    # actually hit.
    cfg = deep_merge(DEFAULTS, {"extend_exclude_paths": [str(excluded_dir)]})
    files = SafetyEngine(cfg)._discover_files(target)

    assert any(f.endswith("good.py") for f in files), "real file should still be discovered"
    assert not any("evil.py" in f or "deeper.py" in f for f in files), "files inside excluded subtree must not appear in results"
    # Critical: is_file() must never have been called on anything inside
    # node_modules - the whole point of pruning is skipping the descent.
    assert not any("node_modules" in q for q in queried), f"discovery descended into excluded subtree; queried paths: {[q for q in queried if 'node_modules' in q]}"


def test_discover_files_prunes_glob_pattern_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patterns like ``tests/**`` must prune the matching directory during
    descent, not just filter at the end. ``fnmatch.fnmatchcase('tests',
    'tests/**')`` is False (the candidate has no trailing slash), so a
    naive ``_is_excluded(str(dir_path / d))`` check would still descend.
    The fix: compose a directory-form candidate with a trailing slash.

    Verified by spying on ``Path.is_file`` - files inside the
    ``tests/**``-pruned subtree must never be queried.
    """
    target = tmp_path / "root"
    (target / "src").mkdir(parents=True)
    (target / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    excluded = target / "tests"
    excluded.mkdir()
    (excluded / "test_a.py").write_text("x = 2\n", encoding="utf-8")
    (excluded / "deep").mkdir()
    (excluded / "deep" / "test_b.py").write_text("x = 3\n", encoding="utf-8")

    queried: list[str] = []
    original_is_file = _Path.is_file

    def spy(self: _Path) -> bool:
        queried.append(self.as_posix())
        return original_is_file(self)

    monkeypatch.setattr(_Path, "is_file", spy)

    # Run discovery from inside *target* so the patterns match relatively.
    # ``extend_exclude_paths`` is the recommended form (additive on top of
    # vendor-dir defaults); same matcher as ``exclude_paths``.
    monkeypatch.chdir(target)
    cfg = deep_merge(DEFAULTS, {"extend_exclude_paths": ["tests/**"]})
    files = SafetyEngine(cfg)._discover_files(_Path())

    assert any(f.endswith("main.py") for f in files), "real file should still be discovered"
    assert not any("test_a.py" in f or "test_b.py" in f for f in files), "files inside the tests/** subtree must not appear in results"
    # Critical: prune actually happened, not just final filter.
    assert not any("tests/test_a.py" in q or "tests/deep" in q for q in queried), (
        f"discovery descended into tests/ subtree despite tests/** pattern; queried paths: {[q for q in queried if 'tests' in q]}"
    )


def test_check_file_skips_non_regular_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``check_file`` is invoked directly by the CLI hook mode with an
    explicit file list - bypassing ``_discover_files``'s regular-file
    filter. Passing a FIFO straight in must not hang ``read_text``; the
    engine must skip it with a stderr warning and return an empty result.
    """
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo not available on this platform")
    fifo = tmp_path / "stuck.py"
    try:
        os.mkfifo(fifo)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support mkfifo")

    result = _engine().check_file(str(fifo))

    assert result.violations == []
    captured = capsys.readouterr()
    assert "safelint: warning:" in captured.err
    assert "not a regular file" in captured.err
    assert "stuck.py" in captured.err


def test_discover_files_skips_non_regular_entries(tmp_path: Path) -> None:
    """``os.walk`` lists FIFOs / device files / broken symlinks alongside
    regular files. Reading a FIFO with ``read_text()`` would block the
    process forever, so discovery must filter to ``is_file()`` matches
    only - preserving the safety guarantee from the previous
    ``Path.rglob('*') + is_file()`` implementation.
    """
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo not available on this platform")
    target = tmp_path / "target"
    target.mkdir()
    real_file = target / "good.py"
    real_file.write_text("x = 1\n", encoding="utf-8")
    fifo_path = target / "evil.py"
    try:
        os.mkfifo(fifo_path)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support mkfifo")

    files = _engine()._discover_files(target)
    assert str(real_file) in files
    # FIFO with a `.py` name must NOT be picked up - would block read_text.
    assert str(fifo_path) not in files


def test_check_file_skips_oversized_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file larger than ``max_file_size_bytes`` is skipped with a stderr
    diagnostic and produces no violations (issue #20).

    Defence-in-depth: monkeypatch ``Path.read_text`` to raise loudly if it
    is invoked. The whole point of the size guard is that the file's
    contents never enter the process - if we ever regressed and started
    reading the file before checking its size, this assertion would
    surface that immediately.
    """
    big = tmp_path / "huge.py"
    # 200 bytes, but we'll set max_file_size_bytes to 100 to trigger the bound.
    big.write_text("x = 1\n" * 40, encoding="utf-8")

    def _fail_if_read(*_args: object, **_kwargs: object) -> str:
        msg = "Path.read_text must not be called for an oversize file"
        raise AssertionError(msg)

    monkeypatch.setattr(_Path, "read_text", _fail_if_read)

    cfg = deep_merge(DEFAULTS, {"max_file_size_bytes": 100})
    result = SafetyEngine(cfg).check_file(str(big))

    assert result.violations == []
    captured = capsys.readouterr()
    assert "safelint: warning:" in captured.err
    assert "exceeds max_file_size_bytes" in captured.err
    assert "huge.py" in captured.err


def test_max_file_size_bytes_rejects_non_integer(tmp_path: Path) -> None:
    """A user typo'ing ``max_file_size_bytes = "5MB"`` in TOML should fail
    fast at engine init with a clear ``TypeError``, not crash later when
    ``check_file`` tries to compare the value against an int."""
    cfg = deep_merge(DEFAULTS, {"max_file_size_bytes": "5MB"})
    with pytest.raises(TypeError, match="max_file_size_bytes must be a non-negative integer"):
        SafetyEngine(cfg)


def test_max_file_size_bytes_rejects_bool(tmp_path: Path) -> None:
    """``bool`` is a subclass of ``int`` in Python - explicitly reject it
    so ``max_file_size_bytes = true`` doesn't silently coerce to ``1``."""
    cfg = deep_merge(DEFAULTS, {"max_file_size_bytes": True})
    with pytest.raises(TypeError, match="max_file_size_bytes must be a non-negative integer"):
        SafetyEngine(cfg)


def test_max_file_size_bytes_rejects_negative(tmp_path: Path) -> None:
    """A negative bound is nonsensical (``0`` is the documented opt-out).
    Reject it with a clear ``ValueError`` at engine init."""
    cfg = deep_merge(DEFAULTS, {"max_file_size_bytes": -1})
    with pytest.raises(ValueError, match="max_file_size_bytes must be >= 0"):
        SafetyEngine(cfg)


def test_check_file_size_bound_zero_falls_back_to_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``max_file_size_bytes = 0`` is rejected as a likely typo (it would
    disable the OOM guard entirely). Engine init must emit a stderr
    warning and replace the value with the built-in default, so the
    safety net stays in place."""
    cfg = deep_merge(DEFAULTS, {"max_file_size_bytes": 0})
    engine = SafetyEngine(cfg)

    # Init-time warning fires. Case-insensitive substring matches keep the
    # test resilient to small wording tweaks of the warning copy - only the
    # *behaviour* (warns + falls back) is what's contractually locked in.
    captured = capsys.readouterr()
    err_lower = captured.err.lower()
    assert "safelint: warning:" in err_lower
    assert "max_file_size_bytes = 0" in err_lower
    assert "falling back" in err_lower
    assert "default" in err_lower

    # The runtime value is the default, not 0.
    assert engine.max_file_size_bytes == DEFAULTS["max_file_size_bytes"]

    # And a normal-sized file is still parsed cleanly with that default.
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    result = engine.check_file(str(sample))
    assert result.violations == []


def test_load_config_treats_empty_safelint_section_as_present(tmp_path: Path) -> None:
    """An empty ``[tool.safelint]`` is a *present* config - the loader must
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


def test_nesting_depth_match_statement_counts(tmp_path: Path) -> None:
    """PEP 634 ``match`` is control-flow and contributes to nesting depth.

    A ``for`` containing a ``match`` containing an ``if`` is 3 levels
    deep - without ``match_statement`` in the depth-node set, the rule
    would silently miss this and let users exceed the configured depth.
    """
    source = textwrap.dedent("""\
        def foo(items):
            for item in items:
                match item:
                    case {"type": "x"}:
                        if item.get("ready"):
                            process(item)
    """)
    sample = tmp_path / "match.py"
    sample.write_text(source, encoding="utf-8")

    # max_depth default is 2; the for/match/if nesting reaches 3
    violations = _engine().check_file(str(sample)).violations
    assert any(v.rule == "nesting_depth" for v in violations)


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
# CLI: git-based file selection (_get_git_modified_supported_files branches)
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
    """_run_check exits 0 with a status message when git reports no modified source files."""

    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    rev_parse = _make_proc(mocker, returncode=0, stdout=str(tmp_path) + "\n")
    empty_diff = _make_proc(mocker, returncode=0, stdout="")
    mocker.patch("safelint.cli.subprocess.run", side_effect=[rev_parse, empty_diff, empty_diff, empty_diff])

    args = argparse.Namespace(target=tmp_path, config=None, fail_on=None, mode=None, all_files=False, ignore=None)
    assert _run_check(args) == 0
    assert "No modified supported source files detected" in capsys.readouterr().out


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

    # Target is src/ only - test_mod.py must not be linted
    args = argparse.Namespace(target=src_dir, config=None, fail_on="error", mode=None, all_files=False, ignore=None)
    assert _run_check(args) == 0


def test_test_coupling_handles_relative_changed_files_against_absolute_test_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SAFE702 must recognise paired-test updates when changed_files are relative but test_dirs is absolute.

    Real-world case: the CLI passes ``--changed-files`` relative-to-cwd
    (``tests/test_foo.py``), but the user's pyproject configures
    ``test_dirs = ["/abs/path/tests"]`` (absolute). Without normalising
    both sides via ``.absolute()`` before the path-component
    comparison, the test_dirs gate would reject the relative changed
    file and SAFE702 would falsely fire even though the paired test
    *was* updated in the same commit.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    sample = src_dir / "mymodule.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    test_file = test_dir / "test_mymodule.py"
    test_file.write_text("def test_x(): pass\n", encoding="utf-8")

    # changed_files passes the paired test as a RELATIVE path
    # (against tmp_path) while test_dirs is ABSOLUTE.
    monkeypatch.chdir(tmp_path)
    config = deep_merge(
        DEFAULTS,
        {
            "rules": {
                "test_coupling": {
                    "enabled": True,
                    "test_dirs": [str(test_dir)],  # absolute
                    "_changed_files": [str(sample), "tests/test_mymodule.py"],  # mixed
                }
            }
        },
    )
    engine = SafetyEngine(config)
    violations = engine.check_file(str(sample)).violations

    # The relative ``tests/test_mymodule.py`` must be recognised as
    # under the absolute ``test_dirs`` entry - coupling satisfied,
    # SAFE702 must NOT fire.
    assert not any(v.rule == "test_coupling" for v in violations)


def test_safe701_does_not_treat_test_prefixed_java_production_as_test(tmp_path: Path) -> None:
    """``src/main/java/TestDataFactory.java`` is NOT a test file.

    Pre-fix, the SAFE701 helper treated any Java stem starting with
    ``Test`` as a test file regardless of path. Production classes
    like ``TestDataFactory.java`` / ``TestConfig.java`` under
    ``src/main/java/`` then got silently skipped from coverage
    enforcement. Test passes an absolute ``test_dirs`` entry so the
    path-component matcher works against tmp_path-rooted paths.
    """
    from safelint.rules.test_coverage import _is_test_file  # noqa: PLC0415

    main_path = tmp_path / "src" / "main" / "java" / "TestDataFactory.java"
    main_path.parent.mkdir(parents=True)
    main_path.write_text("class TestDataFactory {}\n")
    # Not in test_dirs → must NOT be treated as a test file.
    test_dirs = [str(tmp_path / "src" / "test" / "java")]
    assert _is_test_file(str(main_path), test_dirs, "java") is False

    # When the same name lives under src/test/java, the path-component
    # check matches and it IS treated as a test.
    test_path = tmp_path / "src" / "test" / "java" / "TestDataFactory.java"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("class TestDataFactory {}\n")
    assert _is_test_file(str(test_path), test_dirs, "java") is True
