"""Cross-language tests for SAFE501 exits that are not ``break``.

Two gaps, both found against real projects:

* **#170** - a ``return`` terminates the enclosing function and so leaves every
  loop in it, but the rule searched only for ``break``. On ripgrep that was
  **7 of 7** SAFE501 findings, the rule's entire output there, and the blind spot
  was present in all eight languages the rule covers.
* **#179** - tree-sitter parses a Rust macro's arguments as an opaque
  ``token_tree``, so a ``break`` inside ``select!`` exists only as an anonymous
  token and no ``break_expression`` appears in the tree at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe501_lines(sample: Path) -> list[int]:
    """Return the lines SAFE501 fires on in *sample*."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {}))
    return [v.lineno for v in engine.check_file(str(sample)).violations if v.code == "SAFE501"]


# An infinite loop whose only exit is `return`, in every language the rule covers.
_RETURN_ONLY_EXITS = [
    ["rust", "poll.rs", "fn poll(done: bool) -> u32 {\n    loop {\n        if done { return 1; }\n    }\n}\n"],
    ["python", "poll.py", "def poll(done):\n    while True:\n        if done:\n            return 1\n"],
    ["javascript", "poll.js", "function poll(done) {\n  while (true) {\n    if (done) { return 1; }\n  }\n}\n"],
    ["typescript", "poll.ts", "function poll(done: boolean): number {\n  while (true) {\n    if (done) { return 1; }\n  }\n}\n"],
    ["java", "Poll.java", "class C {\n  int poll(boolean done) {\n    while (true) { if (done) { return 1; } }\n  }\n}\n"],
    ["go", "poll.go", "package m\nfunc poll(done bool) int {\n\tfor {\n\t\tif done { return 1 }\n\t}\n}\n"],
    ["php", "poll.php", "<?php\nfunction poll($done) {\n    for (;;) {\n        if ($done) { return 1; }\n    }\n}\n"],
    ["c", "poll.c", "int poll(int done) {\n    for (;;) {\n        if (done) { return 1; }\n    }\n}\n"],
    ["cpp", "poll.cpp", "int poll(bool done) {\n    for (;;) {\n        if (done) { return 1; }\n    }\n}\n"],
]


@pytest.mark.parametrize(["lang", "filename", "source"], _RETURN_ONLY_EXITS, ids=[case[0] for case in _RETURN_ONLY_EXITS])
def test_a_return_exits_an_infinite_loop_in_every_language(tmp_path: Path, lang: str, filename: str, source: str) -> None:
    """A loop whose only exit is ``return`` is not unbounded."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe501_lines(sample) == [], lang


# Shapes that must STILL report, so the new exits cannot swallow a real finding.
_STILL_UNBOUNDED = [
    ["no exit at all, rust", "spin.rs", "fn spin() {\n    loop {\n        tick();\n    }\n}\n", [2]],
    ["no exit at all, python", "spin.py", "def spin():\n    while True:\n        tick()\n", [2]],
    # A nested loop may run zero times, so its `return` is not guaranteed to be
    # reached and the outer loop really can spin forever.
    ["return inside a nested loop", "nested.rs", "fn f(items: Vec<u32>) {\n    loop {\n        for x in items {\n            return;\n        }\n    }\n}\n", [2]],
    # A `return` in a closure returns from the closure, not the enclosing fn.
    ["return inside a closure", "closure.rs", "fn f() {\n    loop {\n        let g = || { return 1; };\n        g();\n    }\n}\n", [2]],
    # The macro check looks for exit keywords, not for any macro at all: a
    # `println!` in a loop is ordinary Rust and the loop is still infinite.
    ["println! with no exit token", "print.rs", 'fn f() {\n    loop {\n        println!("x");\n    }\n}\n', [2]],
    # A token tree is still tokenised, so `break` in a string is a string literal.
    ["the word break inside a string", "strbreak.rs", 'fn f() {\n    loop {\n        println!("break");\n    }\n}\n', [2]],
    ["a macro carrying no exit keyword", "noexit.rs", "fn f(rx: R) {\n    loop {\n        select! {\n            recv(rx) -> m => { handle(m); }\n        }\n    }\n}\n", [2]],
]


@pytest.mark.parametrize(["label", "filename", "source", "expected"], _STILL_UNBOUNDED, ids=[str(case[0]) for case in _STILL_UNBOUNDED])
def test_genuinely_unbounded_loops_still_report(tmp_path: Path, label: str, filename: str, source: str, expected: list[int]) -> None:
    """Neither new exit may silence a loop that really has none."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe501_lines(sample) == expected, label


def test_rust_break_inside_a_macro_token_tree_counts(tmp_path: Path) -> None:
    """A ``break`` inside ``select!`` is an exit, even though it is not a typed node.

    The real instance is ty's ``crates/ty_project/src/watch/watcher.rs:44``: a
    ``loop`` with three literal ``break;`` statements, all inside
    ``crossbeam::select!``, reported as having none. Parsing that shape shows the
    loop's children as ``token_tree`` with the breaks present only as anonymous
    ``break`` tokens.
    """
    sample = tmp_path / "watcher.rs"
    sample.write_text(
        "fn watch(rx: Receiver<u32>) {\n    loop {\n        crossbeam::select! {\n            recv(rx) -> msg => {\n                if msg.is_err() { break; }\n            }\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    assert _safe501_lines(sample) == []


def test_rust_return_inside_a_macro_token_tree_counts(tmp_path: Path) -> None:
    """``return`` inside ``select_biased!`` is equally invisible to a typed search.

    ty's ``ty_project/src/uv/service.rs:285,288`` is the recorded instance. Both
    #170 and #179 have to land for that file to come out clean: the exit is a
    ``return``, *and* it is inside the token tree.
    """
    sample = tmp_path / "service.rs"
    sample.write_text(
        "fn s(rx: R) {\n    loop {\n        select_biased! {\n            recv(rx) -> m => { return; }\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    assert _safe501_lines(sample) == []


_SWITCH_ARM_RETURNS = [
    ["c", "sw.c", "int f(int x) {\n    for (;;) {\n        switch (x) {\n            case 1: return 1;\n        }\n    }\n}\n"],
    ["java", "Sw.java", "class C {\n  int f(int x) {\n    while (true) {\n      switch (x) { case 1: return 1; }\n    }\n  }\n}\n"],
    ["go", "sw.go", "package m\nfunc f(x int) int {\n\tfor {\n\t\tswitch x {\n\t\tcase 1:\n\t\t\treturn 1\n\t\t}\n\t}\n}\n"],
    ["javascript", "sw.js", "function f(x) {\n  while (true) {\n    switch (x) { case 1: return 1; }\n  }\n}\n"],
    ["php", "sw.php", "<?php\nfunction f($x) {\n    for (;;) {\n        switch ($x) { case 1: return 1; }\n    }\n}\n"],
]


@pytest.mark.parametrize(["lang", "filename", "source"], _SWITCH_ARM_RETURNS, ids=[case[0] for case in _SWITCH_ARM_RETURNS])
def test_a_return_in_a_switch_arm_exits_the_loop(tmp_path: Path, lang: str, filename: str, source: str) -> None:
    """A switch arm stops a ``break``, not a ``return``.

    The first cut reused the break boundaries wholesale, which skipped switch arms
    and so kept reporting these. Found in review of PR #226.
    """
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe501_lines(sample) == [], lang


def test_a_break_in_a_switch_arm_is_still_not_a_loop_exit(tmp_path: Path) -> None:
    """The negative control: a ``break`` there exits the switch, so the loop still reports."""
    sample = tmp_path / "swbreak.c"
    sample.write_text(
        "void f(int x) {\n    for (;;) {\n        switch (x) {\n            case 1: break;\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    assert _safe501_lines(sample) == [2]


def _macro_arm(body: str) -> str:
    """Wrap *body* as the arm of a ``select!`` inside a bare ``loop``."""
    return f"fn f(rx: R, xs: Vec<u32>) {{\n    loop {{\n        select! {{\n            recv(rx) -> m => {{\n{body}\n            }}\n        }}\n    }}\n}}\n"


_MACRO_NESTED_EXITS = [
    # A token tree has no structure, so a `break` there cannot be told apart from
    # one belonging to a loop the macro body itself writes.
    ["nested for owns the break", "mfor.rs", _macro_arm("                for x in xs { break; }")],
    # Likewise a `return` inside a closure written in the macro body. A
    # zero-argument closure is a single `||` token, not two `|`.
    ["zero-arg closure owns the return", "mclos.rs", _macro_arm("                let g = || { return 1; };\n                g();")],
    ["one-arg closure owns the return", "mclos1.rs", _macro_arm("                let g = |x: u32| { return x; };\n                g(1);")],
]


@pytest.mark.parametrize(["label", "filename", "source"], _MACRO_NESTED_EXITS, ids=[case[0] for case in _MACRO_NESTED_EXITS])
def test_an_exit_keyword_a_macro_body_may_own_is_not_credited(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """An exit keyword a nested construct in the macro could own is not the loop's.

    The whole macro invocation is the unit of judgement: one ``select!`` nests
    several ``token_tree`` nodes, so judging each separately let an inner tree
    holding just the ``break`` look free of the ``for`` around it. Found in review
    of PR #226.
    """
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe501_lines(sample) == [2], label


def test_rust_continue_inside_a_macro_is_not_an_exit(tmp_path: Path) -> None:
    """``continue`` re-enters the loop, so it must not be read as an exit."""
    sample = tmp_path / "cont.rs"
    sample.write_text(
        "fn f(rx: R) {\n    loop {\n        select! {\n            recv(rx) -> m => { continue; }\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    assert _safe501_lines(sample) == [2]
