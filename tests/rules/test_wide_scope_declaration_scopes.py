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


_CROSS_CASE = (
    "`var` declared in one `switch` clause is read from a later one - entering the switch "
    "there skips the declaration, so `var` reads `undefined` while `let` / `const` throw; "
    "declare it above the `switch`"
)


_CROSS_CLAUSE_SHAPES: list[tuple[str, str]] = [
    (
        "case declares, later case reads",
        """\
        function f(k) {
          switch (k) {
            case 1: var w = 1; break;
            case 2: use(w); break;
          }
        }
        """,
    ),
    (
        "default declares, later case reads",
        """\
        function f(k) {
          switch (k) {
            default: var d = 0; break;
            case 2: use(d); break;
          }
        }
        """,
    ),
    (
        "case declares, default reads",
        """\
        function f(k) {
          switch (k) {
            case 1: var w = 1; break;
            default: use(w); break;
          }
        }
        """,
    ),
    (
        "no break between them",
        """\
        function f(k) {
          switch (k) {
            case 1: var w = 1;
            case 2: use(w); break;
          }
        }
        """,
    ),
    (
        "nested switch, both sites in the inner one",
        """\
        function f(k, j) {
          switch (k) {
            case 1:
              switch (j) {
                case 3: var w = 1; break;
                case 4: use(w); break;
              }
              break;
          }
        }
        """,
    ),
]


@pytest.mark.parametrize(["label", "source"], _CROSS_CLAUSE_SHAPES, ids=[case[0] for case in _CROSS_CLAUSE_SHAPES])
def test_a_var_read_from_a_later_switch_clause_is_reported(tmp_path: Path, label: str, source: str) -> None:
    """The fifth shape (#255). This test asserted the opposite until 2.17.1.

    Each of these runs as `var` and throws ``Cannot access 'w' before
    initialization`` as `let`, verified against ``node``: entering the switch at
    the reading clause skips the declaration entirely. So the `var` genuinely
    blocks the conversion, and the four earlier shapes each miss it for a
    different reason - source order puts the declaration first, and a case
    clause is not a lexical scope, so both sites share the one the braces open.

    ``default:`` is covered in both directions because it is a distinct node
    type, not a case with no value, and the two have disagreed about which
    scope they live in before.

    The no-break row matters: fall-through would initialise `w` when entering at
    `case 1`, but `case 2` carries a label and so is directly reachable whenever
    the discriminant matches it. The hazard does not depend on the `break`, and
    the discriminant's value is exactly what cannot be known here.
    """
    assert _safe305(_write(tmp_path, source)) == [_CROSS_CASE], label


def test_a_read_inside_the_declaring_clause_is_still_clean(tmp_path: Path) -> None:
    """The boundary. Within one clause the declaration always runs before the read."""
    source = """\
    function f(k) {
      switch (k) {
        case 1: var w = 1; use(w); break;
      }
    }
    """
    assert _safe305(_write(tmp_path, source)) == []


def test_an_earlier_clause_reading_it_keeps_the_read_before_wording(tmp_path: Path) -> None:
    """A read in an EARLIER clause is before the declaration in source order too.

    That shape was already reported, and its own message describes it better, so
    the new check must not take it over.
    """
    source = """\
    function f(k) {
      switch (k) {
        case 1: use(w); break;
        case 2: var w = 1; break;
      }
    }
    """
    assert _safe305(_write(tmp_path, source)) == ["`var` is read before its declaration - hoisting makes that `undefined` instead of an error; `let` / `const` would reject it"]


def test_a_read_outside_the_switch_keeps_the_escape_wording(tmp_path: Path) -> None:
    """Both hazards hold here; the escape message is the more useful one, so it wins.

    This is why the new check is last in the hazard table rather than first.
    """
    source = """\
    function f(k) {
      switch (k) {
        case 1: var w = 1; break;
      }
      return w;
    }
    """
    assert _safe305(_write(tmp_path, source)) == ["`var` is used outside the block it is declared in - function-scope hoisting is what makes that work; `let` / `const` would be a ReferenceError"]


def test_declaring_above_the_switch_is_the_fix_the_message_suggests(tmp_path: Path) -> None:
    """The advice has to leave the code clean, or the message sends the reader in circles."""
    source = """\
    function f(k) {
      var w;
      switch (k) {
        case 1: w = 1; break;
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
        "a named class expression in the initialiser",
        # The inner `Foo` is scoped to the class body, so `let Foo = class Foo
        # {}` parses and there is nothing to rename. Found by review on the fix
        # above: testing for "somewhere inside a `var` declaration" counted
        # bindings in the INITIALISER, which belong to their own construct.
        """\
        function f() {
          var Foo = class Foo {};
          return Foo;
        }
        """,
    ),
    (
        "a named function expression in the initialiser",
        # The same shape, already excluded by the nested-function filter rather
        # than by the declarator test; here as a control that it stays quiet.
        """\
        function f() {
          var bar = function bar() {};
          return bar;
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
