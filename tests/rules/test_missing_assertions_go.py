"""Tests for ``missing_assertions`` (SAFE601) on Go files (#221).

Go has no assertion keyword and no production assertion idiom, so the rule is
only meaningful there as a "tests must assert something" guard: a Go test fails
by calling a failure method on its ``*testing.T``, or through testify.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules import ALL_RULES


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with ``missing_assertions`` enabled and scoped to tests."""
    base = {"rules": {"missing_assertions": {"enabled": True, "test_functions_only": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    return SafetyEngine(deep_merge(DEFAULTS, base))


def _safe601(engine: SafetyEngine, sample: Path) -> list[str]:
    """Return the SAFE601 messages for *sample*."""
    result = engine.check_file(str(sample))
    return [v.message for v in result.violations if v.code == "SAFE601"]


def _write(tmp_path: Path, body: str, name: str = "thing_test.go") -> Path:
    """Write *body* into a Go test file, with the package clause prepended."""
    sample = tmp_path / name
    sample.write_text(f'package p\n\nimport "testing"\n\n{body}', encoding="utf-8")
    return sample


def test_go_is_registered_for_the_rule() -> None:
    """The rule's ``language`` tuple admits Go, so ``.go`` files are not skipped."""
    rule = next(r for r in ALL_RULES if r.code == "SAFE601")
    assert "go" in rule.language


def test_go_test_without_assertions_fires(tmp_path: Path) -> None:
    """The case from the issue: ``func TestNothing(t *testing.T) { _ = 1 }``."""
    sample = _write(tmp_path, "func TestNothing(t *testing.T) { _ = 1 }\n")
    assert _safe601(_engine(), sample) == ['Function "TestNothing" has no assertions']


@pytest.mark.parametrize(
    "call",
    (
        't.Error("bad")',
        't.Errorf("bad %d", 1)',
        't.Fatal("bad")',
        't.Fatalf("bad %d", 1)',
        "t.Fail()",
        "t.FailNow()",
    ),
)
def test_each_testing_failure_method_counts(tmp_path: Path, call: str) -> None:
    """Every shipped ``assertion_calls_go`` name satisfies the rule."""
    sample = _write(tmp_path, f"func TestX(t *testing.T) {{ {call} }}\n")
    assert _safe601(_engine(), sample) == []


@pytest.mark.parametrize(
    "call",
    (
        "assert.Equal(t, 1, 1)",
        "assert.NoError(t, nil)",
        "require.NoError(t, nil)",
        "require.Len(t, []int{1}, 1)",
        "assert.ErrorIs(t, nil, nil)",
    ),
)
def test_testify_counts_through_the_receiver(tmp_path: Path, call: str) -> None:
    """Any call on ``assert`` / ``require`` counts, without naming the function.

    This is why the receiver route exists: testify exposes dozens of assertion
    functions per package, and a name list would both go stale and collide with
    ordinary method names.
    """
    sample = _write(tmp_path, f"func TestX(t *testing.T) {{ {call} }}\n")
    assert _safe601(_engine(), sample) == []


def test_a_chained_receiver_is_not_credited(tmp_path: Path) -> None:
    """``s.deps.assert.Equal(...)`` is not a package-qualified testify call.

    Only an identifier operand counts, so the trailing name of a longer chain
    cannot pass an arbitrary method call off as an assertion.
    """
    sample = _write(tmp_path, "func TestX(t *testing.T) { s.deps.assert.Equal(1, 1) }\n")
    assert _safe601(_engine(), sample) == ['Function "TestX" has no assertions']


def test_table_driven_parent_is_not_reported_for_its_subtests(tmp_path: Path) -> None:
    """A ``t.Run`` parent delegates: its body asserts nothing by design.

    The assertion counter stops at the ``func_literal``, so without the
    delegation guard every table-driven test in the ecosystem would report.
    """
    sample = _write(
        tmp_path,
        'func TestTable(t *testing.T) {\n\tfor _, c := range cases {\n\t\tt.Run(c.name, func(t *testing.T) {\n\t\t\tif c.want != c.got {\n\t\t\t\tt.Errorf("bad")\n\t\t\t}\n\t\t})\n\t}\n}\n',
    )
    assert _safe601(_engine(), sample) == []


def test_an_assertion_free_subtest_is_reported_with_its_title(tmp_path: Path) -> None:
    """The subtest itself is still checked, and named by its ``t.Run`` title."""
    sample = _write(
        tmp_path,
        'func TestSubtest(t *testing.T) {\n\tt.Run("the empty one", func(t *testing.T) { _ = 2 })\n}\n',
    )
    assert _safe601(_engine(), sample) == ['Test "the empty one" has no assertions']


def test_a_fuzz_target_is_checked_and_its_parent_is_not(tmp_path: Path) -> None:
    """``f.Fuzz`` registers the target, so the ``FuzzXxx`` seed function delegates.

    The target has no string title (its first argument is the callback), so the
    label falls back rather than inventing one.
    """
    sample = _write(
        tmp_path,
        'func FuzzParse(f *testing.F) {\n\tf.Add("seed")\n\tf.Fuzz(func(t *testing.T, s string) {\n\t\t_ = s\n\t})\n}\n',
    )
    assert _safe601(_engine(), sample) == ['Function "<anonymous>" has no assertions']


def test_benchmarks_examples_and_helpers_are_out_of_scope(tmp_path: Path) -> None:
    """``test_function_prefixes_go`` admits ``Test`` and ``Fuzz`` only.

    A benchmark has no assertion to make, an example asserts through its
    ``// Output:`` comment, and a helper is not a test.
    """
    sample = _write(
        tmp_path,
        "func BenchmarkX(b *testing.B) { _ = 3 }\n\nfunc ExampleX() { _ = 4 }\n\nfunc helper() int { return 5 }\n",
    )
    assert _safe601(_engine(), sample) == []


def test_a_non_test_go_file_is_skipped_entirely(tmp_path: Path) -> None:
    """``test_functions_only`` keeps production Go out: it has no assertion idiom."""
    sample = _write(tmp_path, "func Parse(s string) int { return len(s) }\n", name="thing.go")
    assert _safe601(_engine(), sample) == []


def test_lowercase_prefixes_do_not_apply_to_go(tmp_path: Path) -> None:
    """Control for the per-language prefix chain.

    Without ``test_function_prefixes_go`` the shipped lowercase ``["test"]``
    would match no Go test at all, because the toolchain requires ``TestXxx``.
    """
    sample = _write(tmp_path, "func TestNothing(t *testing.T) { _ = 1 }\n")
    engine = _engine({"rules": {"missing_assertions": {"test_function_prefixes_go": ["test"]}}})
    assert _safe601(engine, sample) == []


def test_min_assertions_two_applies_to_go(tmp_path: Path) -> None:
    """The Holzmann-strict threshold counts Go assertions like any other language."""
    sample = _write(tmp_path, 'func TestOne(t *testing.T) { t.Errorf("one") }\n')
    engine = _engine({"rules": {"missing_assertions": {"min_assertions": 2}}})
    assert _safe601(engine, sample) == ['Function "TestOne" has 1 assertion(s), minimum is 2 (Holzmann rule 5 asks for two per function)']


def test_assertion_receivers_are_configurable(tmp_path: Path) -> None:
    """A project's own assertion package can be added by receiver."""
    sample = _write(tmp_path, "func TestX(t *testing.T) { must.BeTrue(t, true) }\n")
    engine = _engine({"rules": {"missing_assertions": {"assertion_receivers_go": ["must"]}}})
    assert _safe601(engine, sample) == []


def test_a_mistyped_receiver_list_fails_loud(tmp_path: Path) -> None:
    """A scalar instead of a list raises rather than iterating characters."""
    sample = _write(tmp_path, "func TestX(t *testing.T) { _ = 1 }\n")
    engine = _engine({"rules": {"missing_assertions": {"assertion_receivers_go": "assert"}}})
    with pytest.raises(TypeError, match="assertion_receivers_go"):
        engine.check_file(str(sample))
