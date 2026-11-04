"""SAFE601: a project's own ``assert*`` helper counts inside a test (#251).

The rule matched an assertion by exact name, so a test whose only assertion
went through the project's own helper read as assertion-free. Measured on the
validation corpus once the rule was scoped to tests: 53% of commons-lang's
findings and 34% of Guava's called something named ``assert*``. Enumerating
them does not scale, so a name that STARTS with an ``assertion_call_prefixes``
entry counts.

The route is live only inside a function the rule identified as a test, which
is the whole reason it is safe: inside a test an ``assert``-prefixed call is an
assertion, while a production method named ``assertValid()`` is nobody's
assertion and must stay uncredited. Both halves are pinned here, per language,
because this is a change to the rule's matching contract rather than a
per-language list edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe601(sample: Path, overrides: dict | None = None) -> list[str]:
    """Return the SAFE601 messages for *sample*, scoped to tests by default."""
    rule: dict[str, object] = {"enabled": True}
    if overrides:
        rule.update(overrides)
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"missing_assertions": rule}}))
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE601"]


# (label, filename, source). Each sample is one test, identified by whichever
# route that language uses (name prefix, marker, registration callback), whose
# only assertion is a helper the shipped lists do not name.
_HELPER_IN_A_TEST: list[tuple[str, str, str]] = [
    (
        "python name prefix",
        "test_thing.py",
        "def test_rejects_a_short_password():\n    assert_rejected(validate('abc'))\n",
    ),
    (
        "javascript registration callback",
        "thing.test.js",
        'it("rejects a short password", () => {\n  assertRejected(validate("abc"));\n});\n',
    ),
    (
        "typescript registration callback",
        "thing.test.ts",
        'it("rejects a short password", (): void => {\n  assertRejected(validate("abc"));\n});\n',
    ),
    (
        "java marker",
        "ThingTest.java",
        'class ThingTest {\n    @Test\n    void rejectsAShortPassword() {\n        assertIllegalArgumentException(() -> validate("abc"));\n    }\n}\n',
    ),
    (
        "rust marker",
        "thing_test.rs",
        '#[test]\nfn rejects_a_short_password() {\n    assert_rejected(validate("abc"));\n}\n',
    ),
    (
        "go name prefix",
        "thing_test.go",
        'func TestRejectsAShortPassword(t *testing.T) {\n\tassertRejected(t, validate("abc"))\n}\n',
    ),
    (
        "php name prefix",
        "ThingTest.php",
        "<?php\nclass ThingTest {\n    public function test_rejects_a_short_password() {\n        $this->assertRejected(validate('abc'));\n    }\n}\n",
    ),
]


@pytest.mark.parametrize(["label", "filename", "source"], _HELPER_IN_A_TEST, ids=[case[0] for case in _HELPER_IN_A_TEST])
def test_an_assert_prefixed_helper_counts_in_every_language(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """The helper satisfies the rule wherever the language puts its tests."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe601(sample) == [], label


@pytest.mark.parametrize(["label", "filename", "source"], _HELPER_IN_A_TEST, ids=[case[0] for case in _HELPER_IN_A_TEST])
def test_switching_the_prefix_route_off_restores_exact_matching(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """``assertion_call_prefixes = []`` goes back to naming every helper.

    The same samples, so this cannot pass by the sample being clean for some
    other reason: each one reports as soon as the route is off. Per language,
    because the key resolves through the usual chain and a language whose key
    was never wired would silently keep the prefix behaviour.
    """
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    overrides: dict[str, object] = {f"assertion_call_prefixes_{lang}": [] for lang in ("javascript", "typescript", "java", "rust", "go", "php")}
    overrides["assertion_call_prefixes"] = []
    assert len(_safe601(sample, overrides)) == 1, label


def test_a_production_assert_named_method_is_not_credited(tmp_path: Path) -> None:
    """The guard the prefix route depends on: outside a test, ``assert*`` means nothing.

    With ``test_functions_only = false`` the rule checks every function, and a
    production method happening to be named ``assertValid`` must leave its
    function answerable. This is the risk the issue called out, and the reason
    the route is scoped to tests rather than applied everywhere.
    """
    sample = tmp_path / "service.py"
    sample.write_text("def handle(payload):\n    assertValid(payload)\n    return payload\n", encoding="utf-8")
    assert _safe601(sample, {"test_functions_only": False}) == ['Function "handle" has no assertions']


def test_a_test_in_the_same_mode_still_gets_the_prefix(tmp_path: Path) -> None:
    """``test_functions_only = false`` checks more functions; it does not un-identify a test.

    Test identity decides whether the prefix applies, and that is resolved
    independently of the scoping flag. Before #251 the flag short-circuited the
    test-file lookup, so turning scoping off also turned the prefix off for
    genuine tests - two unrelated behaviours on one switch.
    """
    sample = tmp_path / "test_thing.py"
    sample.write_text("def test_rejects():\n    assert_rejected(validate('abc'))\n", encoding="utf-8")
    assert _safe601(sample, {"test_functions_only": False}) == []


def test_a_rust_helper_function_counts_though_rust_asserts_with_macros(tmp_path: Path) -> None:
    """Rust's own assertions are macros, but a project's helper is a function.

    ``assertion_calls_rust`` is matched against macro names only, deliberately:
    a function literally named ``panic`` is not an assertion. The prefix route
    is the one thing that reaches a plain call, so ``assert_roundtrip(&value)``
    counts while the macro list stays macro-only.
    """
    sample = tmp_path / "thing_test.rs"
    sample.write_text("#[test]\nfn round_trips() {\n    assert_roundtrip(&value);\n}\n", encoding="utf-8")
    assert _safe601(sample) == []
    off = {"assertion_call_prefixes_rust": []}
    assert _safe601(sample, off) == ['Function "round_trips" has no assertions']


def test_a_rust_call_named_after_a_configured_macro_is_not_an_assertion(tmp_path: Path) -> None:
    """Only the prefix route reaches a call, so the macro list does not leak into one.

    ``panic`` is in ``assertion_calls_rust`` as the macro ``panic!``. A function
    call of that name is not an assertion, and crediting it would be a false
    negative introduced by the very fix that reaches helper functions.
    """
    sample = tmp_path / "thing_test.rs"
    sample.write_text("#[test]\nfn round_trips() {\n    panic(&value);\n}\n", encoding="utf-8")
    assert _safe601(sample) == ['Function "round_trips" has no assertions']


def test_a_go_helper_counts_whatever_its_receiver(tmp_path: Path) -> None:
    """Go's receiver conditions do not have to be satisfied by a helper.

    ``assertEqual(t, ...)``, ``h.assertEqual(...)`` and
    ``testutil.assertEqual(...)`` are one helper written three ways, and none of
    them is a ``testing``-typed receiver or a testify package. The names that
    forced the receiver condition in the first place (``fmt.Errorf``,
    ``err.Error``) are not ``assert``-prefixed, so that tightening still holds -
    pinned by the last case here.
    """
    cases = ["assertEqual(t, got, want)", "h.assertEqual(got, want)", "testutil.assertEqual(t, got, want)"]
    for call in cases:
        sample = tmp_path / "thing_test.go"
        sample.write_text(f"func TestThing(t *testing.T) {{\n\t{call}\n}}\n", encoding="utf-8")
        assert _safe601(sample) == [], call
    sample = tmp_path / "thing_test.go"
    sample.write_text('func TestThing(t *testing.T) {\n\tfmt.Errorf("nope")\n}\n', encoding="utf-8")
    assert _safe601(sample) == ['Function "TestThing" has no assertions']


def test_the_prefix_list_is_configurable_per_language(tmp_path: Path) -> None:
    """A project writing ``mustEqual`` can say so without losing ``assert``."""
    sample = tmp_path / "thing_test.go"
    sample.write_text("func TestThing(t *testing.T) {\n\tmustEqual(t, got, want)\n}\n", encoding="utf-8")
    assert _safe601(sample) == ['Function "TestThing" has no assertions']
    assert _safe601(sample, {"assertion_call_prefixes_go": ["assert", "must"]}) == []


def test_a_mistyped_prefix_list_fails_loud(tmp_path: Path) -> None:
    """A scalar typo must raise, not degrade into a set of single characters.

    ``assertion_call_prefixes = "assert"`` would otherwise be iterated as
    ``("a", "s", ...)`` and match essentially every call name, silently turning
    the rule off. Same guard as every other list key on this rule.
    """
    sample = tmp_path / "test_thing.py"
    sample.write_text("def test_rejects():\n    nothing()\n", encoding="utf-8")
    with pytest.raises(TypeError, match="assertion_call_prefixes"):
        _safe601(sample, {"assertion_call_prefixes": "assert"})


def test_an_empty_prefix_entry_is_dropped_rather_than_matching_everything(tmp_path: Path) -> None:
    """``""`` is a prefix of every name, so it would credit every call in every test.

    ``"compute".startswith("")`` is True, so one empty entry turned the rule
    off wherever it is scoped to tests - the worst shape for a safety rule,
    because the run stays green and says nothing. Dropping the entry lands on
    whichever of the two plausible intentions the user had: on its own it
    leaves the empty tuple, which is how the route is switched off, and beside
    a real prefix it leaves that prefix doing its job.
    """
    sample = tmp_path / "test_thing.py"
    sample.write_text("def test_computes():\n    compute(1)\n", encoding="utf-8")
    reported = ['Function "test_computes" has no assertions']
    assert _safe601(sample) == reported
    assert _safe601(sample, {"assertion_call_prefixes": [""]}) == reported
    assert _safe601(sample, {"assertion_call_prefixes": ["assert", ""]}) == reported
    # The surviving prefix still counts what it should.
    helper = tmp_path / "test_helper.py"
    helper.write_text("def test_computes():\n    assert_computed(1)\n", encoding="utf-8")
    assert _safe601(helper, {"assertion_call_prefixes": ["assert", ""]}) == []


def test_the_bare_key_switches_the_route_off_for_python_only(tmp_path: Path) -> None:
    """The bare key is Python's, so every other language needs its own suffixed key.

    ``lang_config_key_chain`` deliberately keeps the bare key out of the chain
    for non-Python languages: in a user's TOML it is Python's key, and letting
    a ``.java`` file inherit a bare list would silently widen every language at
    once. So ``assertion_call_prefixes = []`` is NOT a global off switch, which
    is what the 2.17.0 docs claimed. Pinned here because the claim is easy to
    reintroduce and nothing else would catch it.
    """
    python_sample = tmp_path / "test_thing.py"
    python_sample.write_text("def test_computes():\n    assert_computed(1)\n", encoding="utf-8")
    java_sample = tmp_path / "ThingTest.java"
    java_sample.write_text("class ThingTest {\n    @Test\n    void checks() {\n        assertComputed(1);\n    }\n}\n", encoding="utf-8")
    bare_off: dict[str, object] = {"assertion_call_prefixes": []}
    assert _safe601(python_sample, bare_off) == ['Function "test_computes" has no assertions']
    assert _safe601(java_sample, bare_off) == []
    assert _safe601(java_sample, {"assertion_call_prefixes_java": []}) == ['Function "checks" has no assertions']
