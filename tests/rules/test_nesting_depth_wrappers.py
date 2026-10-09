"""Cross-language tests for SAFE102 and resource / error-handling wrappers.

`with`, `try` and `try`-with-resources add indentation without adding a branch,
so they are not nesting steps (#166). The rule exists to keep *decisions*
shallow; counting a wrapper produced findings that were literally correct and
practically unactionable, because reducing nesting in
``with session: for x: if y:`` means restructuring resource handling.

This extends a principle the depth table already applied rather than introducing
one: Java's ``synchronized_statement`` and Rust's ``unsafe_block`` were excluded
on exactly this reasoning. Rust, Go and C had nothing to remove.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules.nesting_depth import _DEPTH_NODE_TYPES_BY_LANG


def _depth(sample: Path) -> int:
    """Return the depth SAFE102 computed, or 0 when it reports nothing.

    ``max_depth=0`` makes every function report so the depth is always readable
    from the message. With the shipped default of 2, a true depth of 2 produces no
    violation at all, which would make most assertions below silently vacuous.
    """
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"nesting_depth": {"max_depth": 0}}}))
    messages = [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE102"]
    return max((int(m.split("depth is ")[1].split(" ")[0]) for m in messages), default=0)


_WRAPPED_TWO_DEEP = [
    [
        "python with",
        "w.py",
        'def f(data):\n    with open("f") as fh:\n        for row in data:\n            if row:\n                pass\n',
    ],
    [
        "python try",
        "t.py",
        "def f(data):\n    try:\n        for row in data:\n            if row:\n                pass\n    except Exception:\n        pass\n",
    ],
    [
        "java try-with-resources",
        "T.java",
        "class C {\n  void f(int[] d) {\n    try (var r = open()) {\n      for (int x : d) {\n        if (x > 0) { g(); }\n      }\n    }\n  }\n}\n",
    ],
    [
        "javascript try",
        "t.js",
        "function f(d) {\n  try {\n    for (const x of d) {\n      if (x) { g(); }\n    }\n  } catch (e) {}\n}\n",
    ],
    [
        "typescript try",
        "t.ts",
        "function f(d: number[]) {\n  try {\n    for (const x of d) {\n      if (x) { g(); }\n    }\n  } catch (e) {}\n}\n",
    ],
    [
        "php try",
        "t.php",
        "<?php\nfunction f($d) {\n    try {\n        foreach ($d as $x) {\n            if ($x) { g(); }\n        }\n    } catch (Exception $e) {}\n}\n",
    ],
    [
        "cpp try",
        "t.cpp",
        "void f(int* d) {\n    try {\n        for (int i=0;i<3;i++) {\n            if (d[i]) { g(); }\n        }\n    } catch (...) {}\n}\n",
    ],
]


@pytest.mark.parametrize(["label", "filename", "source"], tuple(_WRAPPED_TWO_DEEP), ids=[case[0] for case in _WRAPPED_TWO_DEEP])
def test_a_wrapper_around_two_real_levels_scores_two(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """A wrapper around ``for`` + ``if`` is depth 2, not 3 - so it clears max_depth=2."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _depth(sample) == 2, label


def test_a_wrapper_alone_is_depth_zero(tmp_path: Path) -> None:
    """A ``with`` body containing no branch has no control-flow depth at all."""
    sample = tmp_path / "alone.py"
    sample.write_text('def f():\n    with open("f") as fh:\n        pass\n', encoding="utf-8")
    assert _depth(sample) == 0


_STILL_COUNTED = [
    ["three real levels", "deep.py", "def f(a, b):\n    if a:\n        for x in b:\n            if x:\n                pass\n", 3],
    # `switch` and `match` branch, so they remain steps.
    ["javascript switch", "sw.js", "function f(x) {\n  if (x) {\n    switch (x) {\n      case 1: g(); break;\n    }\n  }\n}\n", 2],
    ["python match", "m.py", "def f(x):\n    if x:\n        match x:\n            case 1:\n                pass\n", 2],
]


@pytest.mark.parametrize(["label", "filename", "source", "expected"], tuple(_STILL_COUNTED), ids=[case[0] for case in _STILL_COUNTED])
def test_real_branching_is_unaffected(tmp_path: Path, label: str, filename: str, source: str, expected: int) -> None:
    """Removing the wrappers must not change what a decision costs."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _depth(sample) == expected, label


def test_no_language_counts_a_resource_wrapper(tmp_path: Path) -> None:
    """The depth table itself carries no ``with`` / ``try`` entry, in any language.

    Asserted against the table rather than through a sample so a language added
    later cannot quietly reintroduce one.
    """
    offenders = {lang: sorted(node_type for node_type in types if "try" in node_type or "with" in node_type) for lang, types in _DEPTH_NODE_TYPES_BY_LANG.items()}
    assert not any(offenders.values()), f"resource wrappers still counted: { {k: v for k, v in offenders.items() if v} }"


def test_a_deliberately_deep_wrapped_function_still_reports_on_the_default(tmp_path: Path) -> None:
    """End to end on the shipped `max_depth=2`: a wrapper plus three decisions still fires."""
    sample = tmp_path / "real.py"
    sample.write_text(
        'def f(data):\n    with open("f") as fh:\n        for row in data:\n            if row:\n                while row:\n                    pass\n',
        encoding="utf-8",
    )
    engine = SafetyEngine(deep_merge(DEFAULTS, {}))
    found = [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE102"]
    assert len(found) == 1
    assert "depth is 3" in found[0].message
