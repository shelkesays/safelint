"""SAFE305 scopes a `switch` by its body, and only merging bindings collide (#201 review).

Two defects found by review on the production PR, both in what counts as a
scope:

* A `switch` case clause was treated as its own lexical scope. It is not: every
  `case` and the `default` share the one scope that the switch's braces open, so
  two `var y` in different cases are a redeclaration that `let` rejects
  outright, and that went unreported.
* A redeclaration candidate was any other binding of the name, including a
  `let` / `const` in a nested block, a catch parameter and a class name. Each of
  those is its own binding that `let` may legally shadow, so the rule demanded a
  rename that nothing requires.

Every `let` / SyntaxError claim below was checked against `node --check`.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS
from safelint.core.engine import SafetyEngine


def _safe305(sample: Path) -> list[str]:
    engine = SafetyEngine(DEFAULTS)
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE305"]


def _write(tmp_path: Path, body: str) -> Path:
    sample = tmp_path / "sample.js"
    sample.write_text(textwrap.dedent(body), encoding="utf-8")
    return sample


# ---------------------------------------------------------------------------
# A switch's cases share one scope.
# ---------------------------------------------------------------------------

# (label, source, expected findings)
_SWITCH_CASES: list[tuple[str, str, int]] = [
    (
        "same name in two cases is a redeclaration",
        # `let y` in both cases is "SyntaxError: Identifier 'y' has already
        # been declared" - the cases share the switch's scope. Scoping per case
        # read them as disjoint and reported nothing.
        """\
        function f(k) {
          switch (k) {
            case 1: var y = 1; use(y); break;
            case 2: var y = 2; use(y); break;
          }
        }
        """,
        2,
    ),
    (
        "a case and the default share the scope too",
        # `switch_default` is its own grammar node and was in no scope table, so
        # it resolved to function top level while its sibling `case` resolved to
        # itself. Same scope now, and the pair still reports.
        """\
        function f(k) {
          switch (k) {
            case 1: var z = 1; use(z); break;
            default: var z = 2; use(z);
          }
        }
        """,
        2,
    ),
    (
        "one var per case is not a redeclaration",
        # Different names, so nothing collides; `let` in each case is legal.
        """\
        function f(k) {
          switch (k) {
            case 1: var a = 1; use(a); break;
            case 2: var b = 2; use(b); break;
          }
        }
        """,
        0,
    ),
    (
        "a var used after the switch still escapes",
        # The switch body IS the declaring block, so a read after it is the
        # ordinary escape shape and must survive the scope change.
        """\
        function f(k) {
          switch (k) {
            case 1: var found = 1; break;
          }
          return found;
        }
        """,
        1,
    ),
]


@pytest.mark.parametrize(["label", "source", "expected"], _SWITCH_CASES, ids=[case[0] for case in _SWITCH_CASES])
def test_switch_cases_share_one_scope(tmp_path: Path, label: str, source: str, expected: int) -> None:
    """A case clause is not a lexical scope; the switch body is."""
    assert len(_safe305(_write(tmp_path, source))) == expected, label


def test_cross_case_read_is_a_known_limit(tmp_path: Path) -> None:
    """A read in a LATER case than the declaration is not reported, and that is a gap.

    `var w` in `case 1` read from `case 2` runs today, and as `let` it throws
    "Cannot access 'w' before initialization" whenever case 2 is entered without
    case 1 - a real blocker for the conversion. It is not any of the rule's four
    shapes though: source order has the declaration first, so it is not a
    read-before-declaration, and both sites are in the one switch scope, so it
    is not an escape.

    Scoping per case used to report it as an escape, which was the right answer
    for the wrong reason and cost the redeclaration shape above. Pinned here so
    the gap is recorded rather than rediscovered; filed as #255.
    """
    source = """\
    function f(k) {
      switch (k) {
        case 1: var w = 1; break;
        case 2: use(w); break;
      }
    }
    """
    assert _safe305(_write(tmp_path, source)) == []


# ---------------------------------------------------------------------------
# Only a binding that MERGES with the var collides with it.
# ---------------------------------------------------------------------------

# (label, source) - each is legal once the `var` becomes `let`, so there is
# nothing for the rule to ask for.
_SHADOWING_BINDINGS: list[tuple[str, str]] = [
    (
        "a catch parameter of the same name",
        """\
        function f() {
          var err = null;
          try { run(); } catch (err) { log(err); }
          return err;
        }
        """,
    ),
    (
        "a const in a nested block",
        """\
        function g(c) {
          var x = 1;
          if (c) { const x = 2; use(x); }
          return x;
        }
        """,
    ),
    (
        "a let in a nested block",
        """\
        function h(c) {
          var x = 1;
          while (c) { let x = 2; use(x); }
          return x;
        }
        """,
    ),
    (
        "a class declaration of the same name",
        """\
        function i(c) {
          var Thing = null;
          if (c) { class Thing {} ; use(Thing); }
          return Thing;
        }
        """,
    ),
]


@pytest.mark.parametrize(["label", "source"], _SHADOWING_BINDINGS, ids=[case[0] for case in _SHADOWING_BINDINGS])
def test_a_shadowing_binding_is_not_a_redeclaration(tmp_path: Path, label: str, source: str) -> None:
    """A `let` / `const` / catch parameter / class name binds separately, so `let` may shadow it."""
    assert _safe305(_write(tmp_path, source)) == [], label


# (label, source, expected) - the bindings that genuinely merge with a `var`.
_MERGING_BINDINGS: list[tuple[str, str, int]] = [
    (
        "a second var at the same scope",
        """\
        function f() {
          var dup = 1;
          use(dup);
          var dup = 2;
          return dup;
        }
        """,
        2,
    ),
    (
        "a var over a parameter",
        """\
        function f(name) {
          var name = name || "anon";
          return name;
        }
        """,
        1,
    ),
    (
        "a var over an unparenthesised arrow parameter",
        """\
        const f = x => {
          var x = 1;
          return x;
        };
        """,
        1,
    ),
]


@pytest.mark.parametrize(["label", "source", "expected"], _MERGING_BINDINGS, ids=[case[0] for case in _MERGING_BINDINGS])
def test_a_merging_binding_is_still_a_redeclaration(tmp_path: Path, label: str, source: str, expected: int) -> None:
    """Another `var`, or a parameter, is the same binding; `let` rejects the pair."""
    messages = _safe305(_write(tmp_path, source))
    assert len(messages) == expected, label
    assert all("re-declares" in message for message in messages), messages
