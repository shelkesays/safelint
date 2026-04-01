"""Tests for inline # nosafe suppression — parsing, filtering, and fail_fast interaction."""

from __future__ import annotations

import textwrap
from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine, _is_suppressed, _parse_suppressions
from safelint.rules.base import Violation


# ---------------------------------------------------------------------------
# _parse_suppressions — unit tests against the tokenizer-based parser
# ---------------------------------------------------------------------------


def test_parse_bare_nosafe() -> None:
    """Bare # nosafe maps the line to None (suppress all)."""
    result = _parse_suppressions("x = 1  # nosafe\n")
    assert result == {1: None}


def test_parse_nosafe_single_code() -> None:
    """# nosafe: CODE maps the line to a set containing that code."""
    result = _parse_suppressions("x = 1  # nosafe: SAFE101\n")
    assert result == {1: {"SAFE101"}}


def test_parse_nosafe_rule_name() -> None:
    """# nosafe: rule_name maps the line to a set containing that name."""
    result = _parse_suppressions("x = 1  # nosafe: function_length\n")
    assert result == {1: {"function_length"}}


def test_parse_nosafe_multiple_codes() -> None:
    """# nosafe: A, B maps the line to a set containing both tokens."""
    result = _parse_suppressions("x = 1  # nosafe: SAFE101, function_length\n")
    assert result == {1: {"SAFE101", "function_length"}}


def test_parse_nosafe_case_insensitive() -> None:
    """# NOSAFE and # NoSafe are treated identically to # nosafe."""
    assert _parse_suppressions("x = 1  # NOSAFE\n") == {1: None}
    assert _parse_suppressions("x = 1  # NoSafe: SAFE101\n") == {1: {"SAFE101"}}


def test_parse_nosafe_inside_string_literal_ignored() -> None:
    """# nosafe inside a string literal is not treated as a suppression."""
    source = 'x = "# nosafe"\ny = 1\n'
    assert _parse_suppressions(source) == {}


def test_parse_nosafe_inside_docstring_ignored() -> None:
    """# nosafe inside a docstring is not treated as a suppression."""
    source = textwrap.dedent("""\
        def foo():
            \"\"\"Do not suppress: # nosafe\"\"\"
            pass
    """)
    assert _parse_suppressions(source) == {}


def test_parse_nosafe_only_on_annotated_line() -> None:
    """Suppression applies only to the line carrying the comment, not adjacent lines."""
    source = "x = 1\ny = 2  # nosafe\nz = 3\n"
    result = _parse_suppressions(source)
    assert 1 not in result
    assert result[2] is None
    assert 3 not in result


def test_parse_incomplete_source_returns_empty() -> None:
    """Tokenize failure on malformed source returns an empty suppression map."""
    assert _parse_suppressions("def foo(\n") == {}


# ---------------------------------------------------------------------------
# _is_suppressed — unit tests for the matching predicate
# ---------------------------------------------------------------------------


def _v(rule: str, code: str, lineno: int, severity: str = "error") -> Violation:
    """Shorthand for constructing a test Violation."""
    return Violation(rule=rule, code=code, filepath="f.py", lineno=lineno, message="m", severity=severity)


def test_is_suppressed_bare_nosafe_matches_any_violation() -> None:
    """Bare # nosafe (None value) suppresses any violation on that line."""
    v = _v("function_length", "SAFE101", 3)
    assert _is_suppressed(v, {3: None}) is True


def test_is_suppressed_by_code() -> None:
    """Selective suppression by code suppresses matching violations."""
    v = _v("function_length", "SAFE101", 5)
    assert _is_suppressed(v, {5: {"SAFE101"}}) is True


def test_is_suppressed_by_rule_name() -> None:
    """Selective suppression by rule name suppresses matching violations."""
    v = _v("function_length", "SAFE101", 5)
    assert _is_suppressed(v, {5: {"function_length"}}) is True


def test_is_suppressed_does_not_match_different_code() -> None:
    """Selective suppression by code does not suppress violations with a different code."""
    v = _v("nesting_depth", "SAFE102", 5)
    assert _is_suppressed(v, {5: {"SAFE101"}}) is False


def test_is_suppressed_does_not_match_different_line() -> None:
    """Suppression on one line does not affect violations on other lines."""
    v = _v("function_length", "SAFE101", 7)
    assert _is_suppressed(v, {5: None}) is False


# ---------------------------------------------------------------------------
# Integration: suppression applied during check_file
# ---------------------------------------------------------------------------


def test_bare_nosafe_suppresses_violation_on_that_line(tmp_path: Path) -> None:
    """A bare # nosafe comment suppresses all violations reported on that line."""
    source = "f = open('data.txt')  # nosafe\n"
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    assert not any(v.rule == "resource_lifecycle" for v in result.violations)
    assert result.suppressed == 1


def test_selective_suppression_by_code_leaves_other_violations(tmp_path: Path) -> None:
    """Suppressing SAFE101 on a line does not suppress a different rule on that line."""
    # bare except (SAFE201) on line 2 — suppressed
    # nesting violation would be on a different line; here we verify
    # that a rule whose code is NOT in the nosafe list still fires.
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except:  # nosafe: SAFE201
                pass
    """)
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    # bare_except (SAFE201) on line 4 should be suppressed
    assert not any(v.rule == "bare_except" for v in result.violations)
    assert result.suppressed >= 1


def test_selective_suppression_by_rule_name(tmp_path: Path) -> None:
    """# nosafe: rule_name suppresses violations identified by rule name."""
    source = "f = open('data.txt')  # nosafe: resource_lifecycle\n"
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    assert not any(v.rule == "resource_lifecycle" for v in result.violations)
    assert result.suppressed >= 1


def test_unsuppressed_violations_still_reported(tmp_path: Path) -> None:
    """Violations on lines without # nosafe are reported normally."""
    # bare except with no nosafe comment — must remain in violations
    source = textwrap.dedent("""\
        def foo():
            try:
                pass
            except:
                pass
    """)
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    assert any(v.rule == "bare_except" for v in result.violations)
    assert result.suppressed == 0


def test_suppressed_count_reflects_number_of_suppressed_violations(tmp_path: Path) -> None:
    """LintResult.suppressed counts exactly the violations filtered out by # nosafe."""
    # Two violations on two separate lines, both suppressed
    source = textwrap.dedent("""\
        f = open('a.txt')  # nosafe
        g = open('b.txt')  # nosafe
    """)
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    assert result.suppressed == 2
    assert not any(v.rule == "resource_lifecycle" for v in result.violations)


def test_nosafe_inside_string_does_not_suppress(tmp_path: Path) -> None:
    """# nosafe inside a string literal must not suppress real violations on that line."""
    source = 'f = open("# nosafe")\n'
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    assert any(v.rule == "resource_lifecycle" for v in result.violations)
    assert result.suppressed == 0


# ---------------------------------------------------------------------------
# fail_fast interaction: suppressed violations must not trigger early exit
# ---------------------------------------------------------------------------


def test_fail_fast_does_not_stop_on_suppressed_violation(tmp_path: Path) -> None:
    """fail_fast only stops after a rule produces active (unsuppressed) violations.

    If a rule's entire output is suppressed, the loop must continue so that
    later rules still run and their violations are reported.

    Default execution order: function_length (1st) → … → bare_except (4th).
    The function_length violation on line 1 is suppressed; fail_fast must NOT
    break there, allowing bare_except to run and report its violation.
    """
    # Build a function that is too long (function_length fires, line 1) AND
    # has a bare except (bare_except fires, line ~4).  Suppress function_length
    # by code so the loop should continue to bare_except.
    long_body = "    x = 1\n" * 61
    source = (
        "def foo():  # nosafe: SAFE101\n"
        "    try:\n"
        "        pass\n"
        "    except:\n"
        "        pass\n"
    ) + long_body
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"execution": {"fail_fast": True}})
    result = SafetyEngine(config).check_file(str(sample))

    # function_length suppressed — must not appear
    assert not any(v.rule == "function_length" for v in result.violations)
    # bare_except must still have been checked and reported
    assert any(v.rule == "bare_except" for v in result.violations)
    assert result.suppressed >= 1


def test_fail_fast_stops_after_first_unsuppressed_rule(tmp_path: Path) -> None:
    """fail_fast stops the rule loop after the first rule with active violations."""
    # bare_except fires early in rule order; function_length fires later.
    # With fail_fast only bare_except violations should be present.
    lines = ["def foo():\n    try:\n        pass\n    except:\n        pass\n"]
    lines += ["    x = 1\n"] * 60  # push function_length over threshold
    source = "".join(lines)
    sample = tmp_path / "ff.py"
    sample.write_text(source, encoding="utf-8")

    config_ff = deep_merge(DEFAULTS, {"execution": {"fail_fast": True}})
    config_no = deep_merge(DEFAULTS, {"execution": {"fail_fast": False}})

    result_ff = SafetyEngine(config_ff).check_file(str(sample))
    result_no = SafetyEngine(config_no).check_file(str(sample))

    assert len(result_ff.violations) < len(result_no.violations)
