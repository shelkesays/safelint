"""Cross-language tests for ``nesting_depth`` (SAFE102) and ``else if`` chains.

A flat ``if / else if / else if`` chain branches once, so it must score depth 1.
Seven of the nine languages over-counted a chain of N by N-1 because their
grammars express ``else if`` structurally rather than with a dedicated node type
(issue #154, which reported only JavaScript and TypeScript). Python and PHP were
always correct: their ``elif_clause`` / ``else_if_clause`` were never in the
depth set.

Two grammar shapes are covered. The continuation ``if`` either sits under an
``else_clause`` (JavaScript, TypeScript, Rust, C, C++) or is the ``alternative``
child of the enclosing ``if`` (Java, Go).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _depth(sample: Path) -> int:
    """Return the depth SAFE102 computed for *sample*, or 0 when it reports nothing.

    ``max_depth=0`` makes every function report, so the depth is always readable
    from the message. With the shipped default of 2 a true depth of 2 produces no
    violation at all, which would make the assertions below silently vacuous.
    """
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"nesting_depth": {"max_depth": 0}}}))
    messages = [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE102"]
    return max((int(m.split("depth is ")[1].split(" ")[0]) for m in messages), default=0)


_FLAT_CHAINS = [
    ["python", "chain.py", "def f(x):\n    if x == 1: a()\n    elif x == 2: b()\n    elif x == 3: c()\n    elif x == 4: d()\n"],
    ["javascript", "chain.js", "function f(x) {\n  if (x===1){a();} else if (x===2){b();} else if (x===3){c();} else if (x===4){d();}\n}\n"],
    ["typescript", "chain.ts", "function f(x: number) {\n  if (x===1){a();} else if (x===2){b();} else if (x===3){c();} else if (x===4){d();}\n}\n"],
    ["java", "Chain.java", "class C {\n  void f(int x){ if(x==1){a();} else if(x==2){b();} else if(x==3){c();} else if(x==4){d();} }\n}\n"],
    ["rust", "chain.rs", "fn f(x: u32) {\n  if x==1 {a();} else if x==2 {b();} else if x==3 {c();} else if x==4 {d();}\n}\n"],
    ["go", "chain.go", "package m\nfunc f(x int) { if x==1 { a() } else if x==2 { b() } else if x==3 { c() } else if x==4 { d() } }\n"],
    ["php", "chain.php", "<?php\nfunction f($x){ if($x==1){a();} elseif($x==2){b();} elseif($x==3){c();} elseif($x==4){d();} }\n"],
    ["c", "chain.c", "void f(int x){ if(x==1){a();} else if(x==2){b();} else if(x==3){c();} else if(x==4){d();} }\n"],
    ["cpp", "chain.cpp", "void f(int x){ if(x==1){a();} else if(x==2){b();} else if(x==3){c();} else if(x==4){d();} }\n"],
]


@pytest.mark.parametrize(["lang", "filename", "source"], _FLAT_CHAINS, ids=[case[0] for case in _FLAT_CHAINS])
def test_a_flat_else_if_chain_is_depth_one_in_every_language(tmp_path: Path, lang: str, filename: str, source: str) -> None:
    """A four-way ``else if`` chain branches once, so its depth is 1 everywhere."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _depth(sample) == 1, lang


_STILL_COUNTED = [
    # `else { if (..) }` written with braces IS a second level: the inner `if`'s
    # parent is the block, not the `else`.
    ["braced else-if, javascript", "braced.js", "function f(x) {\n  if (a) { p(); } else { if (b) { q(); } }\n}\n", 2],
    ["braced else-if, c", "braced.c", "void f(int x){ if(a){p();} else { if(b){q();} } }\n", 2],
    ["braced else-if, java", "Braced.java", "class C {\n  void f(int x){ if(a){p();} else { if(b){q();} } }\n}\n", 2],
    # Only `if` nodes are exempt. `else while (x);` is legal C and is a real level.
    ["else while, c", "elsewhile.c", "void f(int x){ if(a) p(); else while(b) q(); }\n", 2],
    # A genuine nested `if` inside an `else if` body still counts.
    ["nested if inside an else-if body", "nested.js", "function f(x) {\n  if (a){p();} else if (b) { if (c) { q(); } }\n}\n", 2],
    # Unrelated nesting is untouched.
    ["if / for / if", "deep.js", "function f(x) {\n  if (a) { for (;;) { if (b) { c(); } } }\n}\n", 3],
]


@pytest.mark.parametrize(["label", "filename", "source", "expected"], _STILL_COUNTED, ids=[case[0] for case in _STILL_COUNTED])
def test_real_nesting_is_still_counted(tmp_path: Path, label: str, filename: str, source: str, expected: int) -> None:
    """The exemption must not swallow genuine levels."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _depth(sample) == expected, label


def test_a_long_else_if_chain_does_not_fire_on_default_config(tmp_path: Path) -> None:
    """End to end on the shipped default: an eight-way chain reports nothing.

    `nesting_depth` is enabled by default, so before the fix any JavaScript using
    the most ordinary branching idiom produced findings out of the box.
    """
    arms = " ".join(f"else if (x==={n}){{f{n}();}}" for n in range(2, 10))
    sample = tmp_path / "long.js"
    sample.write_text(f"function f(x) {{\n  if (x===1){{f1();}} {arms}\n}}\n", encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {}))
    assert [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE102"] == []
