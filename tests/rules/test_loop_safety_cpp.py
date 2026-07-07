"""Unbounded-loop rule (SAFE501) on C++ files.

C++ reuses C's ``while (1)`` / ``while (true)`` and ``for (;;)`` handling; the
condition is wrapped in a ``condition_clause`` (not a ``parenthesized_expression``
as in C), which the rule unwraps. A ``break`` (or ``goto`` out of the loop)
clears the finding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS
from safelint.core.engine import SafetyEngine


def _codes(src: str, tmp_path: Path) -> set[str]:
    """Return violation codes for *src* written as a ``.cpp`` file."""
    sample = tmp_path / "sample.cpp"
    sample.write_text(src, encoding="utf-8")
    return {v.code for v in SafetyEngine(DEFAULTS).check_file(str(sample)).violations}


def test_cpp_while_true_without_break_fires_safe501(tmp_path: Path) -> None:
    """``while (true)`` with no break is an infinite loop (SAFE501)."""
    assert "SAFE501" in _codes("void f() {\n    while (true) {\n        g();\n    }\n}\n", tmp_path)


def test_cpp_while_one_without_break_fires_safe501(tmp_path: Path) -> None:
    """``while (1)`` (C-style) with no break also fires SAFE501."""
    assert "SAFE501" in _codes("void f() {\n    while (1) {\n        g();\n    }\n}\n", tmp_path)


def test_cpp_for_ever_without_break_fires_safe501(tmp_path: Path) -> None:
    """A headerless ``for (;;)`` with no break fires SAFE501."""
    assert "SAFE501" in _codes("void f() {\n    for (;;) {\n        g();\n    }\n}\n", tmp_path)


def test_cpp_while_true_with_break_is_clean(tmp_path: Path) -> None:
    """``while (true)`` with a reachable ``break`` is bounded - no SAFE501."""
    assert "SAFE501" not in _codes("void f() {\n    while (true) {\n        if (done()) break;\n    }\n}\n", tmp_path)


def test_cpp_break_inside_lambda_does_not_satisfy_outer_loop(tmp_path: Path) -> None:
    """A ``break`` inside a nested lambda does not count as exiting the outer loop."""
    src = "void f() {\n    while (true) {\n        auto g = [] { for (;;) { break; } };\n        g();\n    }\n}\n"
    assert "SAFE501" in _codes(src, tmp_path)
