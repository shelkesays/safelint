"""SAFE601 scopes to tests by default, and finds tests marked by an attribute (#163).

``test_functions_only`` ships ON since 2.16.0. The previous default demanded
assertions in every function, production code included, which made SAFE601
56-92% of all output on four real codebases.

The flip only works if every language's tests can actually be identified. Rust
and Java name their tests in free prose and mark them with ``#[test]`` /
``@Test``, and Rust's dominant idiom puts them inside the production file under
``#[cfg(test)] mod tests``, so neither the name nor the filename identifies
them. Without the marker route the new default would have silently removed
SAFE601 from both languages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with the rule enabled and everything else left at its default."""
    base = {"rules": {"missing_assertions": {"enabled": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    return SafetyEngine(deep_merge(DEFAULTS, base))


def _safe601(sample: Path, overrides: dict | None = None) -> list[str]:
    """Return the SAFE601 messages for *sample*."""
    result = _engine(overrides).check_file(str(sample))
    return [v.message for v in result.violations if v.code == "SAFE601"]


def _write(tmp_path: Path, rel: str, src: str) -> Path:
    """Write *src* to ``tmp_path/rel``, creating parent directories."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    return path


def test_the_shipped_default_is_scoped_to_tests() -> None:
    """Pin the default itself, so a future edit to DEFAULTS has to be deliberate."""
    assert DEFAULTS["rules"]["missing_assertions"]["test_functions_only"] is True


def test_a_production_python_function_is_not_reported(tmp_path: Path) -> None:
    """The case the flip exists for: a getter asserts nothing, by design."""
    sample = _write(tmp_path, "src/service.py", "def process(x):\n    return x + 1\n")
    assert _safe601(sample) == []


def test_a_python_test_without_assertions_is_reported(tmp_path: Path) -> None:
    """The signal that remains: a test that asserts nothing."""
    sample = _write(tmp_path, "tests/test_service.py", "def test_process():\n    process(1)\n")
    assert _safe601(sample) == ['Function "test_process" has no assertions']


def test_a_production_javascript_file_is_skipped(tmp_path: Path) -> None:
    """JS has no marker route, so a non-test file is skipped whole."""
    sample = _write(tmp_path, "src/add.js", "function add(a, b) { return a + b; }\n")
    assert _safe601(sample) == []


# ---------------------------------------------------------------------------
# Rust: #[test] in a production file, named in free prose.
# ---------------------------------------------------------------------------

_RUST_COLOCATED = """\
pub fn parse(s: &str) -> usize {
    s.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input_is_zero() {
        let _ = parse("");
    }

    #[cfg(test)]
    fn helper() -> usize {
        1
    }
}
"""


def test_a_rust_test_in_a_production_file_is_found(tmp_path: Path) -> None:
    """``#[test] fn empty_input_is_zero()`` in ``src/lib.rs``.

    No name prefix matches it and the file is not a test file, so the marker is
    the only thing that can identify it. This is Rust's dominant idiom; without
    it the new default gives Rust no coverage at all.
    """
    sample = _write(tmp_path, "src/lib.rs", _RUST_COLOCATED)
    assert _safe601(sample) == ['Function "empty_input_is_zero" has no assertions']


def test_a_rust_cfg_test_helper_is_not_a_test(tmp_path: Path) -> None:
    """``#[cfg(test)]`` marks test CONTEXT, not a test case.

    Covered by the assertion above: ``helper`` is in the same module and is not
    reported. Asserted separately so the reason is recorded.
    """
    sample = _write(tmp_path, "src/lib.rs", _RUST_COLOCATED)
    assert not any("helper" in message for message in _safe601(sample))


@pytest.mark.parametrize(
    "attribute",
    (
        "#[test]",
        "#[tokio::test]",
        "#[actix_web::test]",
        "#[async_std::test]",
        "#[rstest]",
        "#[rstest::rstest]",
    ),
)
def test_every_rust_test_attribute_shape_is_recognised(tmp_path: Path, attribute: str) -> None:
    """A qualified marker is matched on its trailing segment, so no entry per framework."""
    sample = _write(tmp_path, "src/lib.rs", f"{attribute}\nfn checks_nothing() {{\n    let _ = 1;\n}}\n")
    assert _safe601(sample) == ['Function "checks_nothing" has no assertions']


def test_stacked_rust_attributes_still_find_the_marker(tmp_path: Path) -> None:
    """``#[test]`` under ``#[should_panic]``: attributes stack as separate siblings."""
    sample = _write(tmp_path, "src/lib.rs", "#[test]\n#[should_panic]\nfn checks_nothing() {\n    let _ = 1;\n}\n")
    assert _safe601(sample) == ['Function "checks_nothing" has no assertions']


def test_an_unmarked_rust_function_is_not_reported(tmp_path: Path) -> None:
    """Control: the marker route must not pull in production code."""
    sample = _write(tmp_path, "src/lib.rs", "pub fn parse(s: &str) -> usize {\n    s.len()\n}\n")
    assert _safe601(sample) == []


def test_rust_markers_are_configurable(tmp_path: Path) -> None:
    """A project's own test attribute can be added."""
    sample = _write(tmp_path, "src/lib.rs", "#[my_test]\nfn checks_nothing() {\n    let _ = 1;\n}\n")
    assert _safe601(sample) == []
    overrides = {"rules": {"missing_assertions": {"test_markers_rust": ["my_test"]}}}
    assert _safe601(sample, overrides) == ['Function "checks_nothing" has no assertions']


# ---------------------------------------------------------------------------
# Java: @Test with a JUnit 5 descriptive name.
# ---------------------------------------------------------------------------

_JAVA_TEST_CLASS = """\
class PasswordTest {
    @Test
    void shouldRejectShortPassword() {
        int x = 1;
    }

    @BeforeEach
    void setUp() {
        int y = 2;
    }

    void plainHelper() {
        int z = 3;
    }
}
"""


def test_a_junit_test_with_a_descriptive_name_is_found(tmp_path: Path) -> None:
    """JUnit 5 names tests in prose, so no prefix matches ``shouldRejectShortPassword``."""
    sample = _write(tmp_path, "PasswordTest.java", _JAVA_TEST_CLASS)
    assert _safe601(sample) == ['Function "shouldRejectShortPassword" has no assertions']


def test_a_junit_fixture_and_a_helper_are_not_tests(tmp_path: Path) -> None:
    """``@BeforeEach`` legitimately asserts nothing, and a helper is not a test."""
    sample = _write(tmp_path, "PasswordTest.java", _JAVA_TEST_CLASS)
    messages = _safe601(sample)
    assert not any("setUp" in message or "plainHelper" in message for message in messages)


@pytest.mark.parametrize(
    "annotation",
    (
        "@Test",
        "@ParameterizedTest",
        "@RepeatedTest(3)",
        "@TestTemplate",
        "@org.junit.jupiter.api.Test",
    ),
)
def test_every_junit_test_annotation_shape_is_recognised(tmp_path: Path, annotation: str) -> None:
    """Both annotation shapes count, and a fully qualified one keeps its trailing name.

    ``@TestFactory`` is not in this list on purpose; see
    :func:`test_a_test_factory_is_not_a_marker`.
    """
    sample = _write(tmp_path, "Thing.java", f"class Thing {{\n    {annotation}\n    void checksNothing() {{\n        int x = 1;\n    }}\n}}\n")
    assert _safe601(sample) == ['Function "checksNothing" has no assertions']


def test_a_java_marker_outside_a_test_file_still_counts(tmp_path: Path) -> None:
    """``Thing.java`` is not a test file by name, but ``@Test`` is unambiguous."""
    sample = _write(tmp_path, "src/main/java/Thing.java", "class Thing {\n    @Test\n    void checksNothing() {\n        int x = 1;\n    }\n}\n")
    assert _safe601(sample) == ['Function "checksNothing" has no assertions']


def test_an_unannotated_java_method_is_not_reported(tmp_path: Path) -> None:
    """Control: a production method in a production file is out of scope."""
    sample = _write(tmp_path, "src/main/java/Thing.java", "class Thing {\n    int add(int a, int b) {\n        return a + b;\n    }\n}\n")
    assert _safe601(sample) == []


# ---------------------------------------------------------------------------
# The opt-out.
# ---------------------------------------------------------------------------


def test_a_quoted_boolean_opt_out_fails_loud(tmp_path: Path) -> None:
    """``test_functions_only = "false"`` is a non-empty string, so it would read as True.

    Silently keeping the behaviour someone just tried to opt out of is the trap
    the project's boolean validator exists for.
    """
    sample = _write(tmp_path, "src/service.py", "def process(x):\n    return x + 1\n")
    with pytest.raises(TypeError, match="test_functions_only"):
        _engine({"rules": {"missing_assertions": {"test_functions_only": "false"}}}).check_file(str(sample))


def test_a_comment_between_the_attribute_and_the_fn_does_not_lose_the_marker(tmp_path: Path) -> None:
    """``#[ignore] // flaky`` sits in the sibling chain as an extra node.

    tree-sitter puts comments among the preceding siblings, so a walk that stops
    at the first non-attribute sibling never reaches ``#[test]`` and the test is
    silently left out of the rule.
    """
    sample = _write(tmp_path, "src/lib.rs", "#[test]\n#[ignore] // flaky in CI\nfn checks_nothing() {\n    let _ = 1;\n}\n")
    assert _safe601(sample) == ['Function "checks_nothing" has no assertions']


def test_a_comment_line_directly_above_the_fn_does_not_lose_the_marker(tmp_path: Path) -> None:
    """The same chain, with the comment on its own line between attribute and ``fn``."""
    sample = _write(tmp_path, "src/lib.rs", "#[test]\n// what this covers\nfn checks_nothing() {\n    let _ = 1;\n}\n")
    assert _safe601(sample) == ['Function "checks_nothing" has no assertions']


def test_a_test_factory_is_not_a_marker(tmp_path: Path) -> None:
    """``@TestFactory`` is deliberately not in the shipped markers.

    A factory returns a stream of ``DynamicTest``s and its assertions live
    inside those lambdas. ``lambda_expression`` is a Java function type, so the
    counter stops at it by design, and treating the factory as a test reported
    every well-written one as assertion-free. #252 is the general case.
    """
    sample = _write(
        tmp_path,
        "FactoryTest.java",
        'class FactoryTest {\n    @TestFactory\n    Stream<DynamicTest> dynamicTests() {\n        return Stream.of(dynamicTest("1st", () -> assertTrue(true)));\n    }\n}\n',
    )
    assert _safe601(sample) == []
