"""Tests for the Java assertion vocabulary of ``missing_assertions`` (SAFE601).

The default ``assertion_calls_java`` list is what decides whether a JUnit,
AssertJ, Truth, Mockito or Spring MVC test reads as assertion-free. Measured
while verifying #163: on spring-petclinic every single remaining finding was a
MockMvc test, because the assertion in a ``@WebMvcTest`` is the chained
``.andExpect(...)`` and the name was not in the list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _write(tmp_path: Path, body: str) -> Path:
    """Write a ``@Test`` method with *body* into a Java test class."""
    sample = tmp_path / "ThingTest.java"
    sample.write_text(f"class ThingTest {{\n    @Test\n    void checksSomething() {{\n        {body}\n    }}\n}}\n", encoding="utf-8")
    return sample


def _messages(sample: Path, overrides: dict | None = None) -> list[str]:
    """Return the SAFE601 messages for *sample*."""
    base = overrides or {"rules": {"missing_assertions": {"enabled": True}}}
    engine = SafetyEngine(deep_merge(DEFAULTS, base))
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE601"]


def _safe601(tmp_path: Path, body: str) -> list[str]:
    """Return the SAFE601 messages for a ``@Test`` method with *body*."""
    return _messages(_write(tmp_path, body))


_JAVA_ASSERTION_FORMS: list[tuple[str, str]] = [
    ("JUnit assertEquals", "assertEquals(1, 1);"),
    ("JUnit assertThrows", "assertThrows(IllegalStateException.class, () -> thing());"),
    ("AssertJ assertThat", "assertThat(value).isEqualTo(1);"),
    ("AssertJ assertThatThrownBy", "assertThatThrownBy(() -> thing()).isInstanceOf(IllegalStateException.class);"),
    ("AssertJ assertThatExceptionOfType", "assertThatExceptionOfType(IllegalStateException.class).isThrownBy(() -> thing());"),
    ("AssertJ assertThatNoException", "assertThatNoException().isThrownBy(() -> thing());"),
    ("AssertJ assertThatCode", "assertThatCode(() -> thing()).doesNotThrowAnyException();"),
    ("Truth assertWithMessage", 'assertWithMessage("radix %s", radix).that(value).isNull();'),
    ("Mockito verify", "verify(repository).save(owner);"),
    ("Mockito verifyNoInteractions", "verifyNoInteractions(repository);"),
    ("Mockito verifyNoMoreInteractions", "verifyNoMoreInteractions(repository);"),
    ("Spring MockMvc andExpect", 'mockMvc.perform(get("/owners/new")).andExpect(status().isOk());'),
    ("Spring MockMvc andExpectAll", 'mockMvc.perform(get("/owners/new")).andExpectAll(status().isOk());'),
    ("JUnit fail", 'fail("unreachable");'),
]


@pytest.mark.parametrize(["label", "call"], _JAVA_ASSERTION_FORMS, ids=[case[0] for case in _JAVA_ASSERTION_FORMS])
def test_each_default_java_assertion_form_counts(tmp_path: Path, label: str, call: str) -> None:
    """Each shipped name satisfies the rule; ``call_name`` strips any receiver."""
    assert _safe601(tmp_path, call) == [], label


def test_a_java_test_with_no_assertion_still_reports(tmp_path: Path) -> None:
    """The control: adding names can only ever suppress, so this pins the rule still fires."""
    assert _safe601(tmp_path, "int x = 1;") == ['Function "checksSomething" has no assertions']


def test_a_project_assertion_helper_counts_by_prefix(tmp_path: Path) -> None:
    """A project's own ``assert*`` helper counts inside a test, without being enumerated (#251).

    ``assertIllegalArgumentException(...)`` is commons-lang's own helper and the
    test that calls it asserts. Exact-name matching read it as assertion-free,
    which was 53% of commons-lang's and 34% of Guava's findings once the rule
    was scoped to tests. ``extend_assertion_calls_java`` still works and is
    still the way to add a helper that is NOT ``assert``-prefixed.
    """
    sample = _write(tmp_path, "assertIllegalArgumentException(() -> thing());")
    assert _messages(sample) == []
    # Turning the prefix route off restores exact matching, and then the helper
    # has to be named.
    exact = {"rules": {"missing_assertions": {"enabled": True, "assertion_call_prefixes_java": []}}}
    assert _messages(sample, exact) == ['Function "checksSomething" has no assertions']
    extended = {"rules": {"missing_assertions": {"enabled": True, "assertion_call_prefixes_java": [], "extend_assertion_calls_java": ["assertIllegalArgumentException"]}}}
    assert _messages(sample, extended) == []


def test_a_non_assert_prefixed_helper_still_needs_naming(tmp_path: Path) -> None:
    """The prefix route is not a licence to count anything: ``verify*`` is not ``assert*``.

    Guava and commons-lang name their helpers ``assert*``, which is what makes
    the prefix worth having. A helper named anything else is exactly as
    unrecognised as before, so ``extend_assertion_calls_java`` keeps its job.
    """
    sample = _write(tmp_path, "checkRoundTrip(value);")
    assert _messages(sample) == ['Function "checksSomething" has no assertions']
    extended = {"rules": {"missing_assertions": {"enabled": True, "extend_assertion_calls_java": ["checkRoundTrip"]}}}
    assert _messages(sample, extended) == []


def _write_factory(tmp_path: Path, body: str) -> Path:
    """Write a ``@TestFactory`` method with *body* into a Java test class."""
    sample = tmp_path / "FactoryTest.java"
    sample.write_text(f"class FactoryTest {{\n    @TestFactory\n    Stream<DynamicTest> makesTests() {{\n        {body}\n    }}\n}}\n", encoding="utf-8")
    return sample


def test_a_test_factory_whose_lambdas_assert_is_clean(tmp_path: Path) -> None:
    """``@TestFactory`` is a default marker again, now that #252 makes it work.

    2.16.0 excluded it because a factory's assertions live inside the
    ``DynamicTest`` lambdas it returns and the counters stopped at nested
    functions, so every well-written factory reported. A factory IS a test, so
    #252 counts its lambdas and the exclusion buys nothing. Measured on
    commons-lang's four factories: zero new findings.
    """
    sample = _write_factory(tmp_path, 'return Stream.of("racecar").map(s -> DynamicTest.dynamicTest(s, () -> assertTrue(isPalindrome(s))));')
    assert _messages(sample) == []


def test_a_test_factory_that_asserts_nothing_is_reported(tmp_path: Path) -> None:
    """The coverage the exclusion used to give up: a factory that never asserts.

    The reason for reversing the exclusion rather than leaving it. While
    ``@TestFactory`` was not a marker, a factory was not a test at all, so one
    producing ``DynamicTest``s that assert nothing was invisible to the rule.
    """
    sample = _write_factory(tmp_path, 'return Stream.of("a").map(s -> DynamicTest.dynamicTest(s, () -> compute(s)));')
    assert _messages(sample) == ['Function "makesTests" has no assertions']


def test_the_java_marker_defaults_carry_test_factory() -> None:
    """Pinned against DEFAULTS, because the behaviour above rides on the default list."""
    assert "TestFactory" in DEFAULTS["rules"]["missing_assertions"]["test_markers_java"]
