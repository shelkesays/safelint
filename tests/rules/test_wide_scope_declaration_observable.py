"""SAFE305 reports a `var` only where its hoisting is observable (#201).

On Express, 1748 of 1960 default findings (89%) were SAFE305, across 136 of 141
files. Every one was technically true - the declaration is a `var` - but the rule
reported these two identically:

    var path = require("node:path");   // hoisting unobservable; `const` is the same

    function f(xs) {
      if (xs.length) { var found = xs[0]; }
      return found;                    // hoisting is what makes this work
    }

so the instance where the hazard applies was indistinguishable from the 1747
where it cannot. These tests pin the three shapes where `var` and `let` actually
differ, and the shapes where they do not.
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


def _write(tmp_path: Path, name: str, body: str) -> Path:
    sample = tmp_path / name
    sample.write_text(textwrap.dedent(body), encoding="utf-8")
    return sample


# (label, source, number of findings, a phrase the message must carry)
_CASES: list[tuple[str, str, int, str]] = [
    (
        "read outside the declaring block",
        """\
        function f(xs) {
          if (xs.length) {
            var found = xs[0];
          }
          return found;
        }
        """,
        1,
        "outside the block",
    ),
    (
        "read after the loop it is declared in",
        """\
        function f(arr) {
          for (var i = 0; i < arr.length; i++) {
            arr[i] = i * 2;
          }
          return i;
        }
        """,
        1,
        "outside the block",
    ),
    (
        "read before its declaration",
        """\
        function g() {
          console.log(early);
          var early = 1;
          return early;
        }
        """,
        1,
        "before its declaration",
    ),
    (
        "captured by a closure in the loop",
        """\
        function h(arr) {
          for (var i = 0; i < arr.length; i++) {
            setTimeout(function () { console.log(i); });
          }
        }
        """,
        1,
        "captured by a function",
    ),
    (
        "assigned, not just read, outside the block",
        """\
        function f(c) {
          if (c) {
            var state = 1;
          }
          state = 2;
          return c;
        }
        """,
        1,
        "outside the block",
    ),
    # --- quiet: `let` would behave identically ---
    (
        "module-scope require",
        """\
        var path = require("node:path");
        var express = require("express");
        module.exports = { path: path, express: express };
        """,
        0,
        "",
    ),
    (
        "function top level, used only inside",
        """\
        function alsoClean() {
          var local = 1;
          return local + 1;
        }
        """,
        0,
        "",
    ),
    (
        "loop counter used only inside the loop",
        """\
        function clean(arr) {
          var total = 0;
          for (var j = 0; j < arr.length; j++) {
            total += arr[j];
          }
          return total;
        }
        """,
        0,
        "",
    ),
    (
        "declared in a block and used only in that block",
        """\
        function f(c) {
          if (c) {
            var scoped = 1;
            console.log(scoped);
          }
        }
        """,
        0,
        "",
    ),
    (
        "never read at all",
        """\
        function f() {
          var unused = 1;
        }
        """,
        0,
        "",
    ),
    (
        "a nested function's own var does not escape the outer one",
        """\
        function outer() {
          function inner() {
            var x = 1;
            return x;
          }
          return inner();
        }
        """,
        0,
        "",
    ),
]


@pytest.mark.parametrize(["label", "source", "expected", "phrase"], _CASES, ids=[case[0] for case in _CASES])
def test_only_observable_hoisting_reports(tmp_path: Path, label: str, source: str, expected: int, phrase: str) -> None:
    """Each shape reports exactly when `var` and `let` would differ."""
    messages = _safe305(_write(tmp_path, "case.js", source))
    assert len(messages) == expected, f"{label}: {messages}"
    if phrase:
        assert phrase in messages[0], label


def test_destructuring_binding_is_tracked(tmp_path: Path) -> None:
    """`var {a} = o` binds through a pattern node, not a plain identifier.

    Without handling that shape the declaration would bind no names, the
    reference scan would find nothing, and every destructuring `var` would read
    as safe regardless of where it is used.
    """
    sample = _write(
        tmp_path,
        "destructure.js",
        """\
        function f(c, o) {
          if (c) {
            var { a, b } = o;
          }
          return a + b;
        }
        """,
    )
    assert len(_safe305(sample)) == 1


def test_a_class_static_block_is_its_own_scope(tmp_path: Path) -> None:
    """`var` in a `static {}` block does not hoist out of it, so a later read is
    a different binding and not evidence of hoisting.
    """
    sample = _write(
        tmp_path,
        "static.js",
        """\
        class C {
          static {
            var inStatic = 1;
            console.log(inStatic);
          }
        }
        """,
    )
    assert _safe305(sample) == []


def test_a_property_named_like_the_binding_is_not_a_reference(tmp_path: Path) -> None:
    """`obj.found` must not count as a read of `found`.

    Member properties parse as `property_identifier`, a different node type, so
    this holds by construction - the test pins it, because treating them as
    references would resurrect a chunk of the false positives.
    """
    sample = _write(
        tmp_path,
        "prop.js",
        """\
        function f(c, obj) {
          if (c) {
            var found = 1;
            console.log(found);
          }
          return obj.found;
        }
        """,
    )
    assert _safe305(sample) == []


# ---------------------------------------------------------------------------
# Shapes found by running the rule against the projects #201 measured. Each was
# a false positive at some point during the fix; these are the regression pins.
# ---------------------------------------------------------------------------


def test_a_nested_callback_parameter_is_not_a_read_of_the_var(tmp_path: Path) -> None:
    """Axios's shape. The earlier `error` identifiers are callback PARAMETERS.

    Read as uses of the later `var error`, they made it look like a binding used
    outside its block - the one SAFE305 finding left on Axios, and wrong.
    """
    sample = _write(
        tmp_path,
        "shadow.js",
        """\
        function run(pending) {
          const received = pending.then(
            function () { return null; },
            function (error) { return error; }
          );
          try {
            var error = received;
            return error.code;
          } catch (e) {
            return e;
          }
        }
        """,
    )
    assert _safe305(sample) == []


def test_a_nested_function_declaring_the_same_name_shadows_it(tmp_path: Path) -> None:
    """A nested function's own `var` of the same name is a different binding."""
    sample = _write(
        tmp_path,
        "shadow2.js",
        """\
        function outer(c) {
          function inner() {
            var value = 2;
            return value;
          }
          if (c) {
            var value = 1;
            return value + inner();
          }
          return inner();
        }
        """,
    )
    assert _safe305(sample) == []


def test_redeclaring_in_the_same_function_reports_as_a_redeclaration(tmp_path: Path) -> None:
    """Express's `lib/utils.js`: the same name declared twice in one function.

    `let` rejects this outright, so it is a real blocker for converting the
    file - but the earlier reads resolve to the earlier binding, so reporting it
    as "read before its declaration" was the wrong diagnosis. Both declarations
    report; either one is a valid place to rename.
    """
    sample = _write(
        tmp_path,
        "redeclare.js",
        """\
        function acceptParams(str) {
          var colonIndex = str.indexOf(';');
          var index = colonIndex === -1 ? str.length : colonIndex;
          while (index < str.length) {
            var colonIndex = str.indexOf(';', index);
            index = colonIndex + 1;
          }
          return index;
        }
        """,
    )
    messages = _safe305(sample)
    assert len(messages) == 2
    assert all("re-declares" in message for message in messages)


def test_a_var_over_a_parameter_reports_as_a_redeclaration(tmp_path: Path) -> None:
    """Express's `examples/mvc/lib/boot.js`: `var name` inside `function (name)`."""
    sample = _write(
        tmp_path,
        "over_param.js",
        """\
        function boot(files, obj) {
          files.forEach(function (name) {
            console.log(name);
            var name = obj.name || name;
            return name;
          });
        }
        """,
    )
    messages = _safe305(sample)
    assert len(messages) == 1
    assert "re-declares" in messages[0]


def test_shadowing_a_named_function_expressions_own_name_is_legal(tmp_path: Path) -> None:
    """Express's `lib/request.js`: `function range() { var range = ...; }`.

    The function expression's name is bound in a scope ENCLOSING its body, so a
    body-level declaration shadows it legally - no engine rejects it. Counting
    it reported a redeclaration that does not exist.
    """
    sample = _write(
        tmp_path,
        "fnname.js",
        """\
        const req = {};
        req.range = function range(size) {
          var range = size + 1;
          return range;
        };
        """,
    )
    assert _safe305(sample) == []


def test_a_redeclaration_nothing_reads_still_reports(tmp_path: Path) -> None:
    """A duplicate `var` with no reads at all is still a blocker for `let`.

    The other three hazards all need a reference to be observable, so the rule
    bails early when a declaration has none; a redeclaration does not. `let x`
    twice in one scope is rejected by the engine whether or not anything ever
    reads `x`, so the check runs before that guard.
    """
    sample = _write(
        tmp_path,
        "unread_redeclare.js",
        """\
        function f() {
          var only = 1;
          var only = 2;
        }
        """,
    )
    messages = _safe305(sample)
    assert len(messages) == 2
    assert all("re-declares" in message for message in messages)


def test_the_escape_message_covers_a_write_not_only_a_read(tmp_path: Path) -> None:
    """`state = 2` outside the block is a use, so the message must not say "read".

    An assignment target is not a binding position, so it counts as a reference
    like any other identifier; saying "read" about it was simply wrong.
    """
    sample = _write(
        tmp_path,
        "write_outside.js",
        """\
        function f(c) {
          if (c) {
            var state = 1;
          }
          state = 2;
          return c;
        }
        """,
    )
    messages = _safe305(sample)
    assert len(messages) == 1
    assert "is used outside the block" in messages[0]


def test_one_scope_is_indexed_once_for_many_declarations(tmp_path: Path) -> None:
    """Many `var`s in one scope must not cost a full scope walk each (#248 review).

    The per-declaration walks made the rule quadratic in the declaration count.
    Timing is too machine-dependent to assert on, so this pins the observable
    consequence instead: a file with many quiet declarations is analysed, stays
    quiet, and the one genuine hazard among them is still found.
    """
    quiet = "\n".join(f"  var v{n} = {n};\n  total += v{n};" for n in range(200))
    sample = _write(
        tmp_path,
        "many.js",
        f"""\
        function f(c) {{
          var total = 0;
        {quiet}
          if (c) {{
            var found = 1;
          }}
          return total + found;
        }}
        """,
    )
    messages = _safe305(sample)
    assert len(messages) == 1
    assert "is used outside the block" in messages[0]


_DISJOINT_SCOPES: list[tuple[str, str]] = [
    (
        "two sibling for loops reusing the counter",
        """\
        function f(a, b) {
          for (var i = 0; i < a.length; i++) { use(a[i]); }
          for (var i = 0; i < b.length; i++) { use(b[i]); }
        }
        """,
    ),
    (
        "both branches of an if/else declaring the same name",
        """\
        function g(c) {
          if (c) { var x = 1; use(x); } else { var x = 2; use(x); }
        }
        """,
    ),
]


@pytest.mark.parametrize(["label", "source"], _DISJOINT_SCOPES, ids=[case[0] for case in _DISJOINT_SCOPES])
def test_same_name_in_disjoint_blocks_is_quiet(tmp_path: Path, label: str, source: str) -> None:
    """Two bindings in blocks that do not contain one another never collide.

    `let` is legal in each of these, and each block only touches the name
    within itself, so converting both is behaviour-preserving - there is
    nothing to fix and nothing to report. Repeated `for (var i ...)` is common
    in the legacy code the rule is aimed at, so reporting it put back a slice of
    exactly the noise #201 removed.

    Both halves of the rule had to learn this. The redeclaration check saw two
    binders of one name and called it a collision; the reference scan matches by
    text across the whole hoisting scope, so with that fixed the second loop's
    `i` read as the first one's escaping its block, and the first loop's as the
    second being read before its declaration. Same noise, different story.
    """
    assert _safe305(_write(tmp_path, "disjoint.js", source)) == [], label


def test_a_nested_redeclaration_still_collides(tmp_path: Path) -> None:
    """The control for the test above: nesting is not disjointness.

    An inner block sits INSIDE the outer one, so both bindings would share a
    `let` scope and the duplicate is rejected. Without this, "scopes must
    overlap" could degenerate into "a second binder anywhere else is fine",
    which would drop the Express findings the rule was built to keep.
    """
    sample = _write(
        tmp_path,
        "nested_redeclare.js",
        """\
        function f(c, d) {
          if (c) {
            var x = 1;
            if (d) { var x = 2; }
            return x;
          }
          return 0;
        }
        """,
    )
    messages = _safe305(sample)
    assert len(messages) == 2
    assert all("re-declares" in message for message in messages)
