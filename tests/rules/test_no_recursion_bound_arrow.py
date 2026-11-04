"""SAFE105 sees recursion through a ``const``/``let``-bound function (#259).

``no_recursion`` matched the called name against the function's own ``name``
field, and an arrow function has none: the name sits on the enclosing
``variable_declarator``. So the rule was silent on the form most of the
JavaScript and TypeScript ecosystem now uses to declare a function, while
firing correctly on ``function fact() {}`` beside it. A rule whose whole
purpose is to find unbounded stack growth reading clean on
``const fact = (n) => n * fact(n - 1)`` is worse than no rule, because the
clean run is taken as reassurance.

The widening is deliberately narrow in two ways, both pinned here, because
each is a shape that LOOKS like recursion and is not:

* only a **variable declarator** licenses a bare self-call. An object-literal
  entry and a class field are not lexical bindings, so a bare call to their
  name raises ``ReferenceError`` rather than recursing. Verified against
  ``node`` rather than reasoned about.
* a name taken from a binding licenses only **bare** calls. An arrow does not
  bind its own ``this``, so ``this.walk(...)`` inside an object-literal arrow
  is not a self-call; inside a class field it is, and telling those apart is
  the half #259 leaves for later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


_RECURSION_MESSAGE = 'Function "{name}" calls itself; recursion has no guaranteed stack bound (Power of Ten rule 1) - refactor to an explicit loop or worklist'


def _safe105(sample: Path) -> list[str]:
    """Return every SAFE105 message for *sample* under stock defaults."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {}))
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE105"]


_NOW_REPORTED: list[tuple[str, str, str, str]] = [
    ("const arrow, block body", "r.js", "const fact = (n) => {\n  return n <= 1 ? 1 : n * fact(n - 1);\n};\n", "fact"),
    ("const arrow, concise body", "r.js", "const fact = (n) => (n <= 1 ? 1 : n * fact(n - 1));\n", "fact"),
    ("let arrow", "r.js", "let walk = (node) => {\n  return node ? walk(node.next) : 0;\n};\n", "walk"),
    ("var arrow", "r.js", "var walk = (node) => {\n  return node ? walk(node.next) : 0;\n};\n", "walk"),
    (
        "anonymous function expression",
        "r.js",
        "const fact = function (n) {\n  return n <= 1 ? 1 : n * fact(n - 1);\n};\n",
        "fact",
    ),
    ("async arrow", "r.js", "const load = async (id) => {\n  return id ? load(id - 1) : null;\n};\n", "load"),
    ("TypeScript arrow", "r.ts", "const fact = (n: number): number => (n <= 1 ? 1 : n * fact(n - 1));\n", "fact"),
    (
        "TypeScript arrow behind a cast",
        "r.ts",
        "const fact = ((n: number): number => (n <= 1 ? 1 : n * fact(n - 1))) as Fn;\n",
        "fact",
    ),
]


@pytest.mark.parametrize(["label", "filename", "source", "name"], _NOW_REPORTED, ids=[case[0] for case in _NOW_REPORTED])
def test_a_bound_function_that_calls_its_own_binding_is_reported(tmp_path: Path, label: str, filename: str, source: str, name: str) -> None:
    """The point of the issue: these are genuine unbounded recursion and read clean before."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe105(sample) == [_RECURSION_MESSAGE.format(name=name)], label


_STILL_REPORTED: list[tuple[str, str, str, str]] = [
    ("function declaration", "r.js", "function fact(n) {\n  return n <= 1 ? 1 : n * fact(n - 1);\n}\n", "fact"),
    (
        "named function expression",
        "r.js",
        "const f = function fact(n) {\n  return n <= 1 ? 1 : n * fact(n - 1);\n};\n",
        "fact",
    ),
    (
        "class method via this",
        "r.js",
        "class T {\n  fact(n) {\n    return n <= 1 ? 1 : n * this.fact(n - 1);\n  }\n}\n",
        "fact",
    ),
    (
        "object shorthand method via this",
        "r.js",
        "const api = {\n  walk(n) {\n    return n ? this.walk(n - 1) : 0;\n  },\n};\n",
        "walk",
    ),
]


@pytest.mark.parametrize(["label", "filename", "source", "name"], _STILL_REPORTED, ids=[case[0] for case in _STILL_REPORTED])
def test_every_shape_that_already_fired_is_unchanged(tmp_path: Path, label: str, filename: str, source: str, name: str) -> None:
    """The control. Widening a rule must not move what it already got right."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe105(sample) == [_RECURSION_MESSAGE.format(name=name)], label


_NOT_RECURSION: list[tuple[str, str, str]] = [
    # The 140-vs-39 trap from the issue: a resolver that strips the receiver
    # reads every delegating wrapper as recursion.
    ("method sharing the binding's name", "r.js", "const trim = (s) => s.trim();\n"),
    ("global sharing the binding's name", "r.js", "const getComputedStyle = (el) => window.getComputedStyle(el);\n"),
    # Not lexical bindings: a bare call to either name raises ReferenceError.
    ("object-literal entry, bare call", "r.js", "const api = {\n  walk: (n) => (n ? walk(n - 1) : 0),\n};\n"),
    ("class field, bare call", "r.js", "class T {\n  fact = (n) => (n <= 1 ? 1 : n * fact(n - 1));\n}\n"),
    # An arrow does not bind its own ``this``, so this receiver is not the object.
    ("object-literal entry, this call", "r.js", "const api = {\n  walk: (n) => (n ? this.walk(n - 1) : 0),\n};\n"),
    # The deferred half: genuine recursion, but reaching it means matching the
    # enclosing class against the receiver. Recorded, not claimed.
    ("class field, this call", "r.js", "class T {\n  fact = (n) => (n <= 1 ? 1 : n * this.fact(n - 1));\n}\n"),
    # No statically spelled name, so no verdict may rest on it.
    ("computed key", "r.js", "const api = {\n  [walk]: (n) => (n ? walk(n - 1) : 0),\n};\n"),
    ("unbound function expression", "r.js", "(function (n) {\n  return n ? fact(n - 1) : 0;\n})(3);\n"),
    # An inner binding of the same name is what a bare call resolves to.
    ("nested binding shadows the outer", "r.js", "const walk = (n) => {\n  const walk = (m) => m;\n  return walk(n);\n};\n"),
    ("calls a different function", "r.js", "const walk = (n) => visit(n);\n"),
    ("iterative equivalent", "r.js", "const fact = (n) => {\n  let acc = 1;\n  for (let i = 2; i <= n; i += 1) acc *= i;\n  return acc;\n};\n"),
]


@pytest.mark.parametrize(["label", "filename", "source"], _NOT_RECURSION, ids=[case[0] for case in _NOT_RECURSION])
def test_a_shape_that_cannot_recurse_stays_clean(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """Each of these looks like self-recursion by name and is not one."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe105(sample) == [], label


def test_the_widening_is_javascript_and_typescript_only(tmp_path: Path) -> None:
    """Java puts a lambda in a ``variable_declarator`` too, and is deliberately left alone.

    The node type string is shared between the grammars, so the binder table
    would have matched Java for free. It is gated instead: a Java lambda cannot
    call its own variable before the assignment completes, so reporting one
    would be a new claim rather than this fix, and a new claim needs its own
    evidence.
    """
    sample = tmp_path / "Thing.java"
    sample.write_text(
        "class Thing {\n  void run() {\n    Runnable r = () -> r.run();\n  }\n}\n",
        encoding="utf-8",
    )
    assert _safe105(sample) == []


def test_a_recursive_binding_inside_a_function_is_attributed_to_itself(tmp_path: Path) -> None:
    """A bound arrow declared inside another function is the common real shape.

    Both of the hand-verified corpus findings look like this (``axios``'s
    ``const visit = (source) => { ... visit(value) ... }`` inside a helper), so
    the inner function must be reported and the outer one must not be.
    """
    sample = tmp_path / "utils.js"
    sample.write_text(
        "export function merge(obj) {\n  const visit = (source) => {\n    for (const value of source) visit(value);\n  };\n  visit(obj);\n  return obj;\n}\n",
        encoding="utf-8",
    )
    assert _safe105(sample) == [_RECURSION_MESSAGE.format(name="visit")]
