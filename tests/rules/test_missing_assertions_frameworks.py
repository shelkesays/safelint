"""SAFE601: mock and Django assertions count, and ``extend_assertion_calls`` (#220).

With ``test_functions_only = true`` a Django codebase of about 3,300 files still
reported 100 test functions as assertion-free. 55 of them asserted only through
``unittest.mock`` (``assert_called_once_with`` and friends) and several more
through Django's ``TestCase`` API. ``mock`` is in the standard library, so its
assertions are as standard as ``assertEqual``.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe601(sample: Path, overrides: dict | None = None) -> list[str]:
    """Return the names of the functions SAFE601 reports, in file order."""
    rule: dict[str, object] = {"enabled": True}
    if overrides:
        rule.update(overrides)
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"missing_assertions": rule}}))
    violations = [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE601"]
    # The message names the function; pull it out rather than asserting on line
    # numbers, which shift whenever a case is added to a sample.
    return [v.message.split('"')[1] for v in violations]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    sample = tmp_path / name
    sample.write_text(textwrap.dedent(body), encoding="utf-8")
    return sample


_ASSERTION_FORMS: list[tuple[str, str]] = [
    # unittest.mock, sync.
    ("mock assert_called_once_with", 'client.get.assert_called_once_with("/x")'),
    ("mock assert_called", "client.get.assert_called()"),
    ("mock assert_not_called", "client.get.assert_not_called()"),
    ("mock assert_has_calls", "client.get.assert_has_calls([])"),
    ("mock assert_any_call", 'client.get.assert_any_call("/x")'),
    # unittest.mock, async mirrors.
    ("mock assert_awaited_once_with", 'client.get.assert_awaited_once_with("/x")'),
    ("mock assert_not_awaited", "client.get.assert_not_awaited()"),
    ("mock assert_has_awaits", "client.get.assert_has_awaits([])"),
    # Django SimpleTestCase / TestCase.
    ("django assertContains", 'self.assertContains(response, "ok")'),
    ("django assertRedirects", 'self.assertRedirects(response, "/next/")'),
    ("django assertTemplateUsed", 'self.assertTemplateUsed(response, "a.html")'),
    # Two of the Django names are context managers: a bare call builds one and
    # asserts nothing, so the samples use the form that actually asserts.
    ("django assertNumQueries", 'with self.assertNumQueries(1):\n        client.get("/x")'),
    ("django assertRaisesMessage", 'with self.assertRaisesMessage(ValueError, "no"):\n        client.get("/x")'),
    ("django assertFormError", 'self.assertFormError(form, "field", "bad")'),
    ("django assertJSONEqual", 'self.assertJSONEqual(response.content, "{}")'),
    ("django assertHTMLEqual", 'self.assertHTMLEqual(a, "<p>x</p>")'),
    ("django assertInHTML", 'self.assertInHTML("<p>x</p>", html)'),
    ("django assertQuerySetEqual", "self.assertQuerySetEqual(qs, [])"),
]


@pytest.mark.parametrize(["label", "call"], _ASSERTION_FORMS, ids=[case[0] for case in _ASSERTION_FORMS])
def test_stdlib_mock_and_django_assertions_count(tmp_path: Path, label: str, call: str) -> None:
    """A test whose only assertion is one of these is not assertion-free."""
    sample = _write(tmp_path, "t.py", f"def test_it(self, client, response, form, qs, html, a):\n    {call}\n")
    assert _safe601(sample) == [], label


def test_a_test_with_no_assertion_at_all_still_reports(tmp_path: Path) -> None:
    """The control: adding names must not turn the rule off.

    Every name added can only ever suppress a finding, so without this the
    whole change could pass while reporting nothing at all.
    """
    sample = _write(
        tmp_path,
        "t.py",
        """\
        def test_calls_without_asserting(client):
            client.get("/x")

        def test_builds_only(factory):
            factory.create()
        """,
    )
    assert _safe601(sample) == ["test_calls_without_asserting", "test_builds_only"]


def test_a_mock_call_that_is_not_an_assertion_does_not_count(tmp_path: Path) -> None:
    """``assert_called_once_with`` asserts; ``called_once_with`` does not exist, and
    plain mock bookkeeping (``reset_mock`` / ``called``) is not an assertion.

    Pins that the additions are the ``assert*`` names specifically, rather than
    "anything on a mock".
    """
    sample = _write(
        tmp_path,
        "t.py",
        """\
        def test_resets(client):
            client.get.reset_mock()
            client.get.call_count
        """,
    )
    assert _safe601(sample) == ["test_resets"]


def test_extend_assertion_calls_appends_to_the_defaults(tmp_path: Path) -> None:
    """A project helper counts without re-listing the default names.

    The point of the key: ``assertion_calls`` replaces, so adding one helper
    through it meant copying the whole default list and maintaining it against
    future releases.
    """
    sample = _write(
        tmp_path,
        "t.py",
        """\
        def test_helper_only(state):
            verify_invariant(state)

        def test_default_still_works(self, response):
            self.assertContains(response, "ok")
        """,
    )
    assert _safe601(sample, {"extend_assertion_calls": ["verify_invariant"]}) == []
    # Without the extension the helper is not an assertion, but the default is.
    assert _safe601(sample) == ["test_helper_only"]


def test_assertion_calls_still_replaces(tmp_path: Path) -> None:
    """``assertion_calls`` keeps its replace semantics; only the extend key appends.

    Narrowing the list is a supported thing to want, so the two keys must stay
    distinguishable: this sample asserts only via a default name, and setting
    ``assertion_calls`` to something else must make it report.
    """
    sample = _write(
        tmp_path,
        "t.py",
        """\
        def test_django_only(self, response):
            self.assertContains(response, "ok")
        """,
    )
    assert _safe601(sample, {"assertion_calls": ["verify_invariant"]}) == ["test_django_only"]


def test_extend_assertion_calls_is_per_language_and_typescript_inherits(tmp_path: Path) -> None:
    """The extend key uses the same key chain as the base list.

    A TS file reads ``extend_assertion_calls_javascript`` when no
    ``_typescript`` key is set, exactly as it inherits ``assertion_calls``.
    """
    js = _write(tmp_path, "a.js", "function test_it(state) {\n  verifyInvariant(state);\n}\n")
    ts = _write(tmp_path, "a.ts", "function test_it(state: State) {\n  verifyInvariant(state);\n}\n")
    overrides = {"extend_assertion_calls_javascript": ["verifyInvariant"]}
    assert _safe601(js, overrides) == []
    assert _safe601(ts, overrides) == []
    assert _safe601(js) == ["test_it"]


def test_a_mistyped_extend_value_fails_loud(tmp_path: Path) -> None:
    """A bare string must raise, not degrade into a set of single characters.

    ``extend_assertion_calls = "verify"`` would otherwise add the names
    ``v``, ``e``, ``r``, ``i``, ``f``, ``y`` and silently credit any one-letter
    call as an assertion.
    """
    sample = _write(tmp_path, "t.py", "def test_it(state):\n    verify(state)\n")
    with pytest.raises(TypeError, match="extend_assertion_calls"):
        _safe601(sample, {"extend_assertion_calls": "verify"})
