"""SAFE601: the shipped JavaScript list covers the whole ``node:assert`` surface (#256).

Reaching JS tests through their registration callback (#222) made the contents
of ``assertion_calls_javascript`` matter in a way they had not before: a test
whose only assertion is a ``node:assert`` function missing from the list now
reports, where previously the whole callback was skipped and the gap was
invisible. Four names were missing, so a test asserting with
``assert.notDeepEqual(...)`` was reported as having no assertions.

Every asserting export of ``node:assert`` is pinned here, not just the four, so
the list cannot drift away from the module again without a test saying so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


# Every asserting function ``node:assert`` exports, as of Node 24. ``strict`` /
# ``deepStrictEqual`` and friends are the same functions under the strict
# namespace, so the bareword name is all that is needed: ``call_name`` strips
# the receiver and ``assert.equal`` / ``assert.strict.equal`` both resolve to
# ``"equal"``. CallTracker is deliberately absent (deprecated, and
# ``tracker.verify()`` is not an assertion name).
_NODE_ASSERT_NAMES: list[str] = [
    "ok",
    "equal",
    "notEqual",
    "strictEqual",
    "notStrictEqual",
    "deepEqual",
    "notDeepEqual",
    "deepStrictEqual",
    "notDeepStrictEqual",
    "partialDeepStrictEqual",
    "match",
    "doesNotMatch",
    "throws",
    "doesNotThrow",
    "rejects",
    "doesNotReject",
    "ifError",
    "fail",
]

# The four that were missing before #256; kept as their own list so the
# regression is named rather than buried in the sweep above.
_ADDED_IN_2_17: list[str] = ["notDeepEqual", "notDeepStrictEqual", "doesNotMatch", "partialDeepStrictEqual"]


def _safe601(sample: Path) -> list[str]:
    """Return the SAFE601 messages for *sample* under the shipped defaults."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True}}}))
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE601"]


def _write_test(tmp_path: Path, call: str) -> Path:
    """Write an ``it`` test whose only assertion is *call*."""
    sample = tmp_path / "settings.test.js"
    body = 'import assert from "node:assert/strict";\nimport { it } from "node:test";\n\nit("refuses a setting of the wrong kind", () => {\n  ' + call + "\n});\n"
    sample.write_text(body, encoding="utf-8")
    return sample


@pytest.mark.parametrize("name", _NODE_ASSERT_NAMES)
def test_every_node_assert_function_counts(tmp_path: Path, name: str) -> None:
    """Each ``node:assert`` function satisfies the rule on its own."""
    sample = _write_test(tmp_path, f"assert.{name}(actual, expected);")
    assert _safe601(sample) == [], name


@pytest.mark.parametrize("name", _ADDED_IN_2_17)
def test_the_four_names_added_for_this_issue_are_in_the_shipped_defaults(name: str) -> None:
    """The fix is in DEFAULTS, not only in the behaviour a sample happens to exercise.

    Pinned against the config directly because the four were reported from a
    real project reading the published defaults, so the defaults are the
    contract: a sample could keep passing through the ``assert`` prefix route
    (#251) long after someone removed the name from the list.
    """
    assert name in DEFAULTS["rules"]["missing_assertions"]["assertion_calls_javascript"]


def test_the_reported_shape_is_clean(tmp_path: Path) -> None:
    """The exact sample from #256, which reported ``has no assertions`` at 2.16.0."""
    sample = _write_test(tmp_path, 'assert.notDeepEqual(validate({ interval: "30" }), []);')
    assert _safe601(sample) == []


def test_a_test_asserting_nothing_still_reports(tmp_path: Path) -> None:
    """The control: adding names can only suppress, so this pins the rule still fires."""
    sample = _write_test(tmp_path, "const parsed = validate({});")
    assert _safe601(sample) == ['Test "refuses a setting of the wrong kind" has no assertions']


def test_an_unrecognised_assertion_library_still_reports(tmp_path: Path) -> None:
    """A name that is neither shipped nor ``assert``-prefixed is not credited.

    The probe has to avoid a shipped name in EVERY link of the chain, not just
    the first: ``call_name`` keeps the trailing bareword, so a fluent
    ``.to.equal(expected)`` resolves to ``equal``, which is shipped, and the
    sample would read as clean for a reason that has nothing to do with the
    library being unrecognised.
    """
    sample = _write_test(tmp_path, "verify(actual).isEqualTo(expected);")
    assert _safe601(sample) == ['Test "refuses a setting of the wrong kind" has no assertions']
