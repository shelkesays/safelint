"""SAFE104: a ``match`` / ``switch`` construct counts once, in every language (#181).

McCabe counts hand-written control flow. A dispatch table is not that: its arms
are value comparisons or compiler-checked patterns, with no ordering dependency
and no fall-through, so a twenty-arm lookup carries a cognitive load nearer 1
than 20. Counting each arm made dispatch tables the dominant SAFE104 finding on
real code: ``match_arm`` was 50% of every counted decision point across
astral-sh/ty, and 54% of ruff's 656 findings fell to at or under the threshold
once arms stopped counting individually.

#181 required that the decision apply consistently rather than Rust-only, which
is what this file enforces. It also found safelint already inconsistent:
**Python never counted its ``match`` at all**, so the same dispatch table scored
0 in Python and N in Rust. Python now counts the construct, like everywhere
else, which makes Python marginally stricter rather than looser.

A **guarded** arm keeps its surcharge: ``case X if cond`` can fall through to a
later arm, so exhaustiveness proves nothing about it and the reader has to
follow a real condition. Only Rust and Java 21 need explicit handling for that;
Python's guard is an ``if_clause``, which the branch walk already counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import PYTHON
from safelint.languages._node_utils import walk
from safelint.rules.complexity import _BRANCHING_TYPES_BY_LANG, _FUNCTION_TYPES_BY_LANG, ComplexityRule


if TYPE_CHECKING:
    from pathlib import Path


_ARMS = 14  # comfortably past the default max_complexity of 10 under per-arm counting


def _engine() -> SafetyEngine:
    """Engine on stock defaults, where ``max_complexity`` is 10."""
    return SafetyEngine(deep_merge(DEFAULTS, {}))


def _dispatch_sources() -> dict[str, tuple[str, str]]:
    """Return ``{label: (filename, source)}`` for a flat N-arm dispatch per language."""
    rust_arms = "\n".join(f"        {i} => {i}," for i in range(_ARMS))
    py_arms = "\n".join(f"        case {i}:\n            return {i}" for i in range(_ARMS))
    js_arms = "\n".join(f"    case {i}: return {i};" for i in range(_ARMS))
    java_arms = "\n".join(f"      case {i}: return {i};" for i in range(_ARMS))
    go_arms = "\n".join(f"\tcase {i}:\n\t\treturn {i}" for i in range(_ARMS))
    php_arms = "\n".join(f"        case {i}: return {i};" for i in range(_ARMS))
    c_arms = "\n".join(f"    case {i}: return {i};" for i in range(_ARMS))
    php_match_arms = "\n".join(f"        {i} => {i}," for i in range(_ARMS))

    return {
        "rust": ("d.rs", f"fn d(x: i32) -> i32 {{\n    match x {{\n{rust_arms}\n        _ => 0,\n    }}\n}}\n"),
        "python": ("d.py", f'"""M."""\n\n\ndef d(x):\n    """D."""\n    match x:\n{py_arms}\n        case _:\n            return 0\n'),
        "javascript": ("d.js", f"function d(x) {{\n  switch (x) {{\n{js_arms}\n  }}\n  return 0;\n}}\n"),
        "typescript": ("d.ts", f"function d(x: number): number {{\n  switch (x) {{\n{js_arms}\n  }}\n  return 0;\n}}\n"),
        "java": ("D.java", f"class D {{\n  int d(int x) {{\n    switch (x) {{\n{java_arms}\n    }}\n    return 0;\n  }}\n}}\n"),
        "go": ("d.go", f"package p\nfunc d(x int) int {{\n\tswitch x {{\n{go_arms}\n\t}}\n\treturn 0\n}}\n"),
        "php": ("d.php", f"<?php\nfunction d($x) {{\n    switch ($x) {{\n{php_arms}\n    }}\n    return 0;\n}}\n"),
        "php-match": ("dm.php", f"<?php\nfunction dm($x) {{\n    return match ($x) {{\n{php_match_arms}\n        default => 0,\n    }};\n}}\n"),
        "c": ("d.c", f"int d(int x) {{\n    switch (x) {{\n{c_arms}\n    }}\n    return 0;\n}}\n"),
        "cpp": ("d.cpp", f"int d(int x) {{\n    switch (x) {{\n{c_arms}\n    }}\n    return 0;\n}}\n"),
    }


@pytest.mark.parametrize("label", list(_dispatch_sources()))
def test_a_flat_dispatch_table_is_not_over_the_cap(tmp_path: Path, label: str) -> None:
    """A 14-arm dispatch table stays clean in every registered language.

    Under per-arm counting each of these scored 15 and fired. The parametrised
    form is the point: a future language, or a future change to one language's
    node table, cannot quietly reintroduce per-arm counting for only some of
    them.
    """
    name, source = _dispatch_sources()[label]
    sample = tmp_path / name
    sample.write_text(source, encoding="utf-8")

    violations = _engine().check_file(str(sample)).violations

    assert not [v for v in violations if v.code == "SAFE104"], f"{label}: dispatch table scored over the cap"


def test_python_match_is_counted_at_all(tmp_path: Path) -> None:
    """Python's ``match`` used to add nothing; it is one decision point now.

    This is the direction nobody asked for but consistency demands: Python was
    the outlier that counted a dispatch construct as zero. Pinned with an
    explicit arithmetic check rather than a threshold, because the difference
    is one and a threshold test could not see it.
    """
    source = '"""M."""\n\n\ndef d(x):\n    """D."""\n    match x:\n        case 1:\n            return 1\n        case _:\n            return 0\n'
    tree = PYTHON.create_parser().parse(source.encode())
    functions = [n for n in walk(tree.root_node) if n.type in _FUNCTION_TYPES_BY_LANG["python"]]
    assert len(functions) == 1

    score = ComplexityRule._cyclomatic_complexity(functions[0], "python", _FUNCTION_TYPES_BY_LANG["python"], _BRANCHING_TYPES_BY_LANG["python"])

    assert score == 2  # 1 base + 1 for the match construct, arms contribute nothing


def test_guarded_arms_keep_their_surcharge(tmp_path: Path) -> None:
    """Rust: ten guarded arms still exceed the cap where ten plain arms do not."""
    guarded = "\n".join(f"        n if n == {i} => {i}," for i in range(10))
    plain = "\n".join(f"        {i} => {i}," for i in range(10))
    (tmp_path / "g.rs").write_text(f"fn g(x: i32) -> i32 {{\n    match x {{\n{guarded}\n        _ => 0,\n    }}\n}}\n", encoding="utf-8")
    (tmp_path / "p.rs").write_text(f"fn p(x: i32) -> i32 {{\n    match x {{\n{plain}\n        _ => 0,\n    }}\n}}\n", encoding="utf-8")

    engine = _engine()
    guarded_hits = [v for v in engine.check_file(str(tmp_path / "g.rs")).violations if v.code == "SAFE104"]
    plain_hits = [v for v in engine.check_file(str(tmp_path / "p.rs")).violations if v.code == "SAFE104"]

    assert guarded_hits, "a guard is a real branch and must still count"
    assert not plain_hits, "unguarded arms are compiler-checked dispatch"


def test_java_when_guard_counts(tmp_path: Path) -> None:
    """Java 21's ``case X when cond`` guard is reached through its child type.

    Unlike Rust and Python, the guard is neither a field nor a distinct arm
    node: it hangs off ``switch_label`` as a child of type ``guard``, so a
    field lookup finds nothing. Pinned because that asymmetry is easy to lose.
    """
    arms = "\n".join(f"      case Integer i{i} when i{i} > {i} -> {i};" for i in range(10))
    sample = tmp_path / "G.java"
    sample.write_text(f"class G {{\n  int g(Object o) {{\n    return switch (o) {{\n{arms}\n      default -> 0;\n    }};\n  }}\n}}\n", encoding="utf-8")

    assert [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE104"]


def test_genuine_control_flow_still_fires(tmp_path: Path) -> None:
    """The rule has to keep earning its place: real branches still report."""
    ifs = "\n".join(f"    if x == {i} && y > {i} {{ return {i}; }}" for i in range(6))
    sample = tmp_path / "branchy.rs"
    sample.write_text(f"fn branchy(x: i32, y: i32) -> i32 {{\n{ifs}\n    0\n}}\n", encoding="utf-8")

    assert [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE104"]
