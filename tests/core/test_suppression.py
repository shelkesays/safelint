"""Tests for inline # nosafe suppression — parsing, filtering, and fail_fast interaction."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import tree_sitter
import tree_sitter_python

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine, _check_suppressed_marking_used, _parse_suppressions
from safelint.languages.python import PYTHON
from safelint.rules.base import Violation


if TYPE_CHECKING:
    from pathlib import Path

_PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())


def _parse_python(source: str) -> tree_sitter.Tree:
    return tree_sitter.Parser(_PYTHON_LANGUAGE).parse(source.encode("utf-8"))


def _suppressions(source: str) -> dict[int, set[str] | None]:
    return _parse_suppressions(
        _parse_python(source),
        PYTHON.comment_node_type,
        PYTHON.comment_prefix,
    )


# ---------------------------------------------------------------------------
# _parse_suppressions — unit tests against the Tree-sitter comment-node parser
# ---------------------------------------------------------------------------


def test_parse_bare_nosafe() -> None:
    """Bare # nosafe maps the line to None (suppress all)."""
    assert _suppressions("x = 1  # nosafe\n") == {1: None}


def test_parse_nosafe_single_code() -> None:
    """# nosafe: CODE maps the line to a set containing that code."""
    assert _suppressions("x = 1  # nosafe: SAFE101\n") == {1: {"SAFE101"}}


def test_parse_nosafe_rule_name() -> None:
    """# nosafe: rule_name maps the line to a set containing that name."""
    assert _suppressions("x = 1  # nosafe: function_length\n") == {1: {"function_length"}}


def test_parse_nosafe_multiple_codes() -> None:
    """# nosafe: A, B maps the line to a set containing both tokens."""
    assert _suppressions("x = 1  # nosafe: SAFE101, function_length\n") == {1: {"SAFE101", "function_length"}}


def test_parse_nosafe_empty_payload_ignored() -> None:
    """# nosafe: with no codes is treated as malformed and ignored."""
    assert _suppressions("x = 1  # nosafe:\n") == {}


def test_parse_nosafe_only_commas_ignored() -> None:
    """# nosafe: with no usable codes is treated as malformed and ignored."""
    assert _suppressions("x = 1  # nosafe: , ,  \n") == {}


def test_parse_nosafe_case_insensitive() -> None:
    """# NOSAFE and # NoSafe are treated identically to # nosafe."""
    assert _suppressions("x = 1  # NOSAFE\n") == {1: None}
    assert _suppressions("x = 1  # NoSafe: SAFE101\n") == {1: {"SAFE101"}}


def test_parse_nosafe_inside_string_literal_ignored() -> None:
    """# nosafe inside a string literal is not treated as a suppression."""
    assert _suppressions('x = "# nosafe"\ny = 1\n') == {}


def test_parse_nosafe_inside_docstring_ignored() -> None:
    """# nosafe inside a docstring is not treated as a suppression."""
    source = textwrap.dedent("""\
        def foo():
            \"\"\"Do not suppress: # nosafe\"\"\"
            pass
    """)
    assert _suppressions(source) == {}


def test_parse_nosafe_only_on_annotated_line() -> None:
    """Suppression applies only to the line carrying the comment, not adjacent lines."""
    result = _suppressions("x = 1\ny = 2  # nosafe\nz = 3\n")
    assert 1 not in result
    assert result[2] is None
    assert 3 not in result


# ---------------------------------------------------------------------------
# _check_suppressed_marking_used — unit tests for the matching predicate
#
# This is the single source of truth for inline-directive matching since
# the prior ``_is_suppressed`` helper was removed (it had no remaining
# production call sites). Tests pass a throwaway ``used = set()`` and
# discard it; the bookkeeping side effect is exercised separately through
# the SAFE004 integration tests later in this file.
# ---------------------------------------------------------------------------


def _v(rule: str, code: str, lineno: int, severity: str = "error") -> Violation:
    """Shorthand for constructing a test Violation."""
    return Violation(rule=rule, code=code, filepath="f.py", lineno=lineno, message="m", severity=severity)


def _matches(violation: Violation, suppressions: dict[int, set[str] | None]) -> bool:
    """Wrapper that returns just the bool — drops the bookkeeping side effect."""
    return _check_suppressed_marking_used(violation, suppressions, set())


def test_is_suppressed_bare_nosafe_matches_any_violation() -> None:
    """Bare # nosafe (None value) suppresses any violation on that line."""
    v = _v("function_length", "SAFE101", 3)
    assert _matches(v, {3: None}) is True


def test_is_suppressed_by_code() -> None:
    """Selective suppression by code suppresses matching violations."""
    v = _v("function_length", "SAFE101", 5)
    assert _matches(v, {5: {"SAFE101"}}) is True


def test_is_suppressed_by_rule_name() -> None:
    """Selective suppression by rule name suppresses matching violations."""
    v = _v("function_length", "SAFE101", 5)
    assert _matches(v, {5: {"function_length"}}) is True


def test_is_suppressed_does_not_match_different_code() -> None:
    """Selective suppression by code does not suppress violations with a different code."""
    v = _v("nesting_depth", "SAFE102", 5)
    assert _matches(v, {5: {"SAFE101"}}) is False


def test_is_suppressed_does_not_match_different_line() -> None:
    """Suppression on one line does not affect violations on other lines."""
    v = _v("function_length", "SAFE101", 7)
    assert _matches(v, {5: None}) is False


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
    assert len(result.suppressed) == 1


def test_selective_suppression_by_code_suppresses_that_code(tmp_path: Path) -> None:
    """Selective suppression by code suppresses violations with that specific code."""
    # bare except (SAFE201) on line 4 — should be suppressed due to the nosafe comment
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
    assert len(result.suppressed) >= 1


def test_selective_suppression_by_rule_name(tmp_path: Path) -> None:
    """# nosafe: rule_name suppresses violations identified by rule name."""
    source = "f = open('data.txt')  # nosafe: resource_lifecycle\n"
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    assert not any(v.rule == "resource_lifecycle" for v in result.violations)
    assert len(result.suppressed) >= 1


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
    assert len(result.suppressed) == 0


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

    assert len(result.suppressed) == 2
    assert not any(v.rule == "resource_lifecycle" for v in result.violations)


def test_nosafe_inside_string_does_not_suppress(tmp_path: Path) -> None:
    """# nosafe inside a string literal must not suppress real violations on that line."""
    source = 'f = open("# nosafe")\n'
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    result = SafetyEngine(DEFAULTS).check_file(str(sample))

    assert any(v.rule == "resource_lifecycle" for v in result.violations)
    assert len(result.suppressed) == 0


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
    source = ("def foo():  # nosafe: SAFE101\n    try:\n        pass\n    except:\n        pass\n") + long_body
    sample = tmp_path / "s.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"execution": {"fail_fast": True}})
    result = SafetyEngine(config).check_file(str(sample))

    # function_length suppressed — must not appear
    assert not any(v.rule == "function_length" for v in result.violations)
    # bare_except must still have been checked and reported
    assert any(v.rule == "bare_except" for v in result.violations)
    assert len(result.suppressed) >= 1


def test_fail_fast_stops_after_first_unsuppressed_rule(tmp_path: Path) -> None:
    """fail_fast stops the rule loop after the first rule with active violations.

    Ordering dependency: function_length is first in DEFAULTS['execution']['order'],
    so it fires before bare_except. fail_fast therefore stops after function_length
    and must not produce bare_except violations. Without fail_fast both rules fire.
    """
    lines = ["def foo():\n    try:\n        pass\n    except:\n        pass\n"]
    lines += ["    x = 1\n"] * 60  # push function_length over threshold
    source = "".join(lines)
    sample = tmp_path / "ff.py"
    sample.write_text(source, encoding="utf-8")

    config_ff = deep_merge(DEFAULTS, {"execution": {"fail_fast": True}})
    config_no = deep_merge(DEFAULTS, {"execution": {"fail_fast": False}})

    result_ff = SafetyEngine(config_ff).check_file(str(sample))
    result_no = SafetyEngine(config_no).check_file(str(sample))

    # fail_fast: function_length violation present, bare_except absent
    assert any(v.rule == "function_length" for v in result_ff.violations), "Expected function_length violation with fail_fast enabled"
    assert not any(v.rule == "bare_except" for v in result_ff.violations), "bare_except should be skipped by fail_fast after function_length fires"

    # without fail_fast: both rules must have fired
    assert any(v.rule == "function_length" for v in result_no.violations), "Expected function_length violation without fail_fast"
    assert any(v.rule == "bare_except" for v in result_no.violations), "Expected bare_except violation without fail_fast"


# ---------------------------------------------------------------------------
# SAFE004 — unused_suppression (1.8.0)
# ---------------------------------------------------------------------------


def test_safe004_fires_for_unused_directive(tmp_path: Path) -> None:
    """A `# nosafe: SAFE304` on a line with no SAFE304 violation triggers SAFE004."""
    sample = tmp_path / "u.py"
    sample.write_text("x = 1  # nosafe: SAFE304\n", encoding="utf-8")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert any(v.code == "SAFE004" for v in result.violations)


def test_safe004_silent_for_directive_that_caught_a_violation(tmp_path: Path) -> None:
    """A `# nosafe: SAFE201` on a real bare-except line does NOT trigger SAFE004."""
    sample = tmp_path / "u2.py"
    sample.write_text(
        "def f():\n    try:\n        pass\n    except:  # nosafe: SAFE201\n        pass\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert not any(v.code == "SAFE004" for v in result.violations)


def test_safe004_disabled_via_global_ignore(tmp_path: Path) -> None:
    """Adding SAFE004 to ignore silences unused-suppression warnings."""
    sample = tmp_path / "u3.py"
    sample.write_text("x = 1  # nosafe: SAFE304\n", encoding="utf-8")
    config = deep_merge(DEFAULTS, {"ignore": ["SAFE004"]})
    result = SafetyEngine(config).check_file(str(sample))
    assert not any(v.code == "SAFE004" for v in result.violations)


def test_safe004_disabled_via_global_ignore_by_name(tmp_path: Path) -> None:
    """``ignore = ["unused_suppression"]`` (rule name) also silences SAFE004.

    Engine-internal codes are now honoured by both their SAFE-code and
    their rule name, matching how BaseRule violations work.
    """
    sample = tmp_path / "u3_name.py"
    sample.write_text("x = 1  # nosafe: SAFE304\n", encoding="utf-8")
    config = deep_merge(DEFAULTS, {"ignore": ["unused_suppression"]})
    result = SafetyEngine(config).check_file(str(sample))
    assert not any(v.code == "SAFE004" for v in result.violations)


def test_safe000_disabled_via_global_ignore_by_code(tmp_path: Path) -> None:
    """``ignore = ["SAFE000"]`` suppresses parse-error violations from the engine."""
    sample = tmp_path / "broken.py"
    sample.write_text("def f(:\n    pass\n", encoding="utf-8")  # syntax error
    # Default config: SAFE000 fires
    default_result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert any(v.code == "SAFE000" for v in default_result.violations)
    # With SAFE000 in ignore: silent
    config = deep_merge(DEFAULTS, {"ignore": ["SAFE000"]})
    result = SafetyEngine(config).check_file(str(sample))
    assert not any(v.code == "SAFE000" for v in result.violations)


def test_safe000_disabled_via_global_ignore_by_name(tmp_path: Path) -> None:
    """``ignore = ["parse"]`` (rule name) also silences SAFE000."""
    sample = tmp_path / "broken_name.py"
    sample.write_text("def f(:\n    pass\n", encoding="utf-8")
    config = deep_merge(DEFAULTS, {"ignore": ["parse"]})
    result = SafetyEngine(config).check_file(str(sample))
    assert not any(v.code == "SAFE000" for v in result.violations)


def test_safe004_skips_self_referential_directive(tmp_path: Path) -> None:
    """`# nosafe: SAFE004` alone on a line never produces SAFE004 about itself."""
    sample = tmp_path / "u4.py"
    sample.write_text("x = 1  # nosafe: SAFE004\n", encoding="utf-8")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert not any(v.code == "SAFE004" for v in result.violations)


def test_safe004_partial_unused_in_multi_code_directive(tmp_path: Path) -> None:
    """`# nosafe: SAFE201, SAFE304` — if only SAFE201 fires, SAFE304 is flagged unused."""
    sample = tmp_path / "u5.py"
    sample.write_text(
        "def f():\n    try:\n        pass\n    except:  # nosafe: SAFE201, SAFE304\n        pass\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    safe004s = [v for v in result.violations if v.code == "SAFE004"]
    assert len(safe004s) == 1
    assert "SAFE304" in safe004s[0].message


def test_safe004_silent_when_directive_lists_both_code_and_rule_name_aliases(tmp_path: Path) -> None:
    """``# nosafe: SAFE201, bare_except`` consumes BOTH aliases when one violation matches.

    The directive uses both the SAFE-code and the rule-name forms of
    the same rule. When a SAFE201 violation fires on that line, the
    matcher must record both aliases as "used" — otherwise the
    alias that didn't trigger the early-return surfaces a false
    SAFE004. Regression for an early-return bug in
    ``_check_suppressed_marking_used`` that only marked the first
    matching alias.
    """
    sample = tmp_path / "alias_pair.py"
    sample.write_text(
        "def f():\n    try:\n        pass\n    except:  # nosafe: SAFE201, bare_except\n        pass\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    # bare_except violation is suppressed (so absent from active).
    assert not any(v.rule == "bare_except" for v in result.violations)
    # And no SAFE004 fires on either alias — both were consumed by
    # the matching violation.
    safe004s = [v for v in result.violations if v.code == "SAFE004"]
    assert not safe004s, f"unexpected SAFE004 emission(s): {[v.message for v in safe004s]}"


def test_safe004_multi_code_unused_directive_emits_in_sorted_order(tmp_path: Path) -> None:
    """Multiple unused codes on one line are reported alphabetically.

    ``set[str]`` iteration is hash-randomised across Python processes,
    so without explicit sorting the JSON / SARIF output order would
    drift between runs and break consumers that snapshot the result.
    """
    sample = tmp_path / "u6.py"
    sample.write_text("x = 1  # nosafe: SAFE304, SAFE101, SAFE201\n", encoding="utf-8")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    safe004s = [v for v in result.violations if v.code == "SAFE004"]
    # All three codes are unused (the line has no function-length /
    # bare-except / side-effects violation).
    assert len(safe004s) == 3
    # Messages embed the suppressed code; expect alphabetical order.
    extracted = [v.message for v in safe004s]
    assert "SAFE101" in extracted[0]
    assert "SAFE201" in extracted[1]
    assert "SAFE304" in extracted[2]


def test_safe004_not_emitted_when_fail_fast_short_circuits_rule_loop(tmp_path: Path) -> None:
    """fail_fast that breaks the rule loop must skip SAFE004 — used_suppressions is incomplete.

    With fail_fast on, ``_run_rules`` exits as soon as the first rule
    produces an active violation. Later rules never run, so
    ``used_suppressions`` doesn't yet know about *their* directives.
    Emitting SAFE004 in that state would falsely report directives
    for un-run rules as unused.

    Concrete shape: file triggers function_length (first rule, fires
    early) AND has a ``# nosafe: SAFE401`` for resource_lifecycle
    (later rule, never runs because fail_fast stops the loop). Without
    the stopped-early guard, SAFE004 would warn about the SAFE401
    directive — but resource_lifecycle didn't even get to evaluate it.
    """
    long_body = "    x = 1\n" * 65
    source = "def foo():\n" + long_body + "    f = open('x.txt')  # nosafe: SAFE401\n"
    sample = tmp_path / "ff_safe004.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"execution": {"fail_fast": True}})
    result = SafetyEngine(config).check_file(str(sample))

    # function_length (first rule) fires.
    assert any(v.rule == "function_length" for v in result.violations)
    # No SAFE004 — fail_fast made the SAFE401 directive's "usedness"
    # unknowable, so the engine intentionally stays silent.
    assert not any(v.code == "SAFE004" for v in result.violations)


def test_safe004_still_emitted_without_fail_fast(tmp_path: Path) -> None:
    """Without fail_fast, all rules run and SAFE004 fires normally on truly unused directives."""
    source = "x = 1  # nosafe: SAFE401\n"
    sample = tmp_path / "no_ff_safe004.py"
    sample.write_text(source, encoding="utf-8")

    config = deep_merge(DEFAULTS, {"execution": {"fail_fast": False}})
    result = SafetyEngine(config).check_file(str(sample))

    # SAFE401 didn't fire (no resource acquisition), so its directive
    # is genuinely unused — SAFE004 must surface it.
    assert any(v.code == "SAFE004" and "SAFE401" in v.message for v in result.violations)
