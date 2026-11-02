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


def test_a_project_assertion_helper_is_not_recognised_by_default(tmp_path: Path) -> None:
    """A project's own ``assert*`` helper does not count, and ``extend_assertion_calls_java`` is the answer.

    Matching is by exact name, not by an ``assert`` prefix, so
    ``assertIllegalArgumentException(...)`` (commons-lang's own helper) reads as
    assertion-free. Measured on the corpus: 53% of commons-lang's and 34% of
    Guava's remaining findings call such a helper. Pinned here as the shipped
    behaviour rather than left implicit, because it is the main class of finding
    a Java project will still see.
    """
    sample = _write(tmp_path, "assertIllegalArgumentException(() -> thing());")
    assert _messages(sample) == ['Function "checksSomething" has no assertions']
    extended = {"rules": {"missing_assertions": {"enabled": True, "extend_assertion_calls_java": ["assertIllegalArgumentException"]}}}
    assert _messages(sample, extended) == []
