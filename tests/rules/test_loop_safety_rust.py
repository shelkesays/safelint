"""Tests for ``unbounded_loops`` (SAFE501) on Rust files.

Rust-specific cases:

* ``loop { }`` is the idiomatic unconditional infinite loop and the
  headline SAFE501 case.
* ``while true { }`` (less common in Rust than in Python / JS, but
  legal) also fires.
* tree-sitter-rust uses ``boolean_literal`` (a single node type for
  both literals); the rule additionally checks the token text.
* Labels are direct named children of the loop node, NOT the
  ``labeled_statement`` parent that JS / Java use; tested via
  ``'outer: loop { loop { break 'outer; } }``.
* Break is ``break_expression`` (not ``break_statement``); the
  labelled form is ``break_expression`` with a ``label`` named child
  whose inner ``identifier`` carries the bare name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def _safe501_count(result) -> int:
    return sum(1 for v in result.violations if v.code == "SAFE501")


def test_rust_loop_without_break_fires(tmp_path: Path) -> None:
    """``loop { ... }`` with no break inside fires SAFE501."""
    sample = tmp_path / "infinite.rs"
    sample.write_text("fn f() {\n    loop {\n        work();\n    }\n}\nfn work() {}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) >= 1, "loop with no break should fire SAFE501"


def test_rust_loop_with_break_clean(tmp_path: Path) -> None:
    """``loop { ... break; ... }`` is bounded and clean."""
    sample = tmp_path / "bounded.rs"
    sample.write_text(
        "fn f() {\n    loop {\n        if done() { break; }\n        work();\n    }\n}\nfn done() -> bool { true }\nfn work() {}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) == 0


def test_rust_while_true_no_break_fires(tmp_path: Path) -> None:
    """``while true { ... }`` with no break fires SAFE501."""
    sample = tmp_path / "while_true.rs"
    sample.write_text("fn f() {\n    while true {\n        work();\n    }\n}\nfn work() {}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) >= 1


def test_rust_while_false_does_not_fire(tmp_path: Path) -> None:
    """``while false { }`` should NOT match the literal-``true`` branch.

    Guards against a Rust-specific regression where the rule used to
    match on ``boolean_literal`` alone (covering both ``true`` and
    ``false``). Now it requires the token text to be ``"true"``.
    """
    sample = tmp_path / "while_false.rs"
    sample.write_text("fn f() {\n    while false {\n        work();\n    }\n}\nfn work() {}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) == 0


def test_rust_labelled_break_exits_outer_loop(tmp_path: Path) -> None:
    """``'outer: loop { loop { break 'outer; } }`` is bounded."""
    sample = tmp_path / "labeled.rs"
    sample.write_text(
        "fn f() {\n    'outer: loop {\n        loop {\n            if done() { break 'outer; }\n        }\n    }\n}\nfn done() -> bool { true }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    # Outer ``'outer: loop`` has a labelled break exit, so it's clean.
    # Inner ``loop`` also gets the same break (which counts as inside it).
    # So the violation count should be 0.
    assert _safe501_count(result) == 0, "labelled break should clear the outer loop"


def test_rust_unlabelled_break_in_inner_loop_does_not_exit_outer(tmp_path: Path) -> None:
    """``loop { loop { break; } }`` - inner break does NOT exit outer."""
    sample = tmp_path / "nested.rs"
    sample.write_text(
        "fn f() {\n    loop {\n        loop {\n            break;\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    # Outer loop has no exiting break (the inner break exits only the
    # inner loop). Inner loop has a direct break. So one violation.
    assert _safe501_count(result) == 1


def test_rust_break_in_nested_function_does_not_clear_outer(tmp_path: Path) -> None:
    """A ``break`` in a nested closure / fn doesn't help the enclosing loop."""
    sample = tmp_path / "nested_fn.rs"
    sample.write_text(
        "fn f() {\n    loop {\n        let _g = || { for _ in 0..10 { break; } };\n    }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) >= 1, "break inside nested closure should not exit the outer loop"


def test_rust_for_loop_clean(tmp_path: Path) -> None:
    """``for x in 0..10 { }`` is iterator-bounded; SAFE501 does not fire."""
    sample = tmp_path / "for_clean.rs"
    sample.write_text('fn f() {\n    for x in 0..10 {\n        println!("{}", x);\n    }\n}\n', encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) == 0
