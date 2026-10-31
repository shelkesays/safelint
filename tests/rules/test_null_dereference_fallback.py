"""SAFE803: a call that passes a fallback cannot return None (#155).

``d.get(k, {}).x`` is *the* Python safe-navigation idiom, so a rule that matches
on the call name alone fires hardest on the code written to be safe. On the
project where this was found, the defaulting form was the large majority of the
31 SAFE803 findings.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe803(sample: Path, extra_names: list[str] | None = None) -> list[int]:
    overrides: dict[str, object] = {"enabled": True}
    if extra_names is not None:
        overrides["nullable_methods"] = extra_names
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"null_dereference": overrides}}))
    return [v.lineno for v in engine.check_file(str(sample)).violations if v.code == "SAFE803"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    sample = tmp_path / name
    sample.write_text(textwrap.dedent(body), encoding="utf-8")
    return sample


# Each entry is one expression dereferenced on line 2, and the lines it reports
# on. A list rather than a flag so the table says what it expects to see, and
# because a boolean parameter is a positional trap (ruff FBT001).
_FALLBACK_FORMS: list[tuple[str, str, list[int]]] = [
    # A non-None fallback rules None out, for every default name that has one.
    ("dict.get with a fallback", 'd.get("k", {}).x', []),
    ("dict.get with a named fallback", 'd.get("k", fallback).x', []),
    ("dict.pop with a fallback", 'd.pop("k", {}).x', []),
    ("next with a fallback", "next(d, {}).x", []),
    # No fallback: the original hazard, untouched.
    ("dict.get with no fallback", 'd.get("k").x', [2]),
    ("dict.pop with no fallback", 'd.pop("k").x', [2]),
    ("next with no fallback", "next(d).x", [2]),
    # The fallback IS None, so None is still what comes back.
    ("dict.get defaulting to None", 'd.get("k", None).x', [2]),
    ("dict.pop defaulting to None", 'd.pop("k", None).x', [2]),
    # The positional count is unknowable, so the finding stands.
    ("positional splat", "d.get(*args).x", [2]),
    ("keyword splat in the fallback slot", 'd.get("k", **kw).x', [2]),
    ("keyword argument in the fallback slot", 'd.get("k", default=fallback).x', [2]),
    # Subscript dereference, not attribute - same rule, same suppression.
    ("subscript on a fallback form", 'd.get("k", {})["id"]', []),
    ("subscript with no fallback", 'd.get("k")["id"]', [2]),
]


@pytest.mark.parametrize(["label", "expression", "expected"], _FALLBACK_FORMS, ids=[case[0] for case in _FALLBACK_FORMS])
def test_fallback_argument_decides_whether_none_is_possible(tmp_path: Path, label: str, expression: str, expected: list[int]) -> None:
    """Only a provably non-None fallback suppresses; every unknown shape reports.

    The suppression is deliberately one-directional. ``d.get(*args)`` may well
    pass a fallback, but nothing in the syntax says so, and a rule that guessed
    would trade a noisy false positive for a silent false negative.
    """
    sample = _write(tmp_path, "fallback.py", f"def f(d, args, kw, fallback):\n    return {expression}\n")
    assert _safe803(sample) == expected, label


def test_the_issue_reproduction(tmp_path: Path) -> None:
    """#155's own sample: the safe line goes quiet, the unsafe one still reports."""
    sample = _write(
        tmp_path,
        "g.py",
        """\
        def f(config):
            return config.get("a", {}).get("b", "x").strip()

        def g(d):
            return d.get("k")["id"]
        """,
    )
    assert _safe803(sample) == [5]


def test_suppression_is_scoped_to_names_that_have_a_fallback(tmp_path: Path) -> None:
    """A second argument is not a fallback on every nullable method.

    Without this control the fix could degenerate into "two arguments means
    safe", which would silence the genuine hazards: ``find`` and ``fetchone``
    take arguments that are not fallbacks and still return None on a miss.
    """
    sample = _write(
        tmp_path,
        "scoped.py",
        """\
        def f(session, cursor):
            return session.find("Model", 42).name + cursor.fetchone(1, 2).value
        """,
    )
    assert _safe803(sample) == [2, 2]


def test_getattr_fallback_is_the_third_argument(tmp_path: Path) -> None:
    """``getattr(o, name, fallback)`` puts its fallback one position later.

    Not a default ``nullable_methods`` entry, so this also covers a user adding
    a name whose fallback is not in the second slot.
    """
    sample = _write(
        tmp_path,
        "ga.py",
        """\
        def f(o):
            return getattr(o, "a", {}).x

        def g(o):
            return getattr(o, "a").x

        def h(o):
            return getattr(o, "a", None).x
        """,
    )
    assert _safe803(sample, extra_names=["getattr"]) == [5, 8]


def test_javascript_get_is_unaffected(tmp_path: Path) -> None:
    """``Map.prototype.get`` has no defaulting form, so JS keeps reporting.

    The fallback table is Python-only on purpose: a second argument to JS's
    ``get`` is ignored at runtime rather than returned, so treating it as a
    fallback would hide a real null dereference.
    """
    sample = _write(
        tmp_path,
        "m.js",
        """\
        function f(map) {
          return map.get("k", {}).x;
        }
        """,
    )
    assert _safe803(sample) == [2]


def test_two_dereferences_on_one_line_are_distinct_findings(tmp_path: Path) -> None:
    """Two reports on one line are two dereferences, not one reported twice.

    #155 recorded four wild cases that looked like exact duplicates and asked
    whether the worklist was visiting a node twice. It is not: the rule makes a
    single pass, and these differ by column. The CLI gutter is line-addressed,
    which is what makes them look identical.
    """
    sample = _write(
        tmp_path,
        "two.py",
        """\
        def f(d, args, kw):
            return d.get(*args).x + d.get("k", **kw).y
        """,
    )
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"null_dereference": {"enabled": True}}}))
    found = [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE803"]
    assert [v.lineno for v in found] == [2, 2]
    assert len({v.column_start for v in found}) == 2
