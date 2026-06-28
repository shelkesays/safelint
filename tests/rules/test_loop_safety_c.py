"""Tests for SAFE501 unbounded_loops on C files.

C infinite-loop forms: ``while (1)``, ``while (true)`` (stdbool), and the
headerless ``for (;;)``. C has no labelled break, so a ``goto`` out of the loop
is treated as an exit (the C-specific wrinkle).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS
from safelint.core.engine import SafetyEngine


def _has_safe501(src: str, tmp_path: Path) -> bool:
    sample = tmp_path / "loop.c"
    sample.write_text(src, encoding="utf-8")
    return any(v.code == "SAFE501" for v in SafetyEngine(DEFAULTS).check_file(str(sample)).violations)


def test_c_while_one_without_break_fires_safe501(tmp_path: Path) -> None:
    assert _has_safe501("void f(int x) {\n    while (1) {\n        x++;\n    }\n}\n", tmp_path)


def test_c_while_true_without_break_fires_safe501(tmp_path: Path) -> None:
    assert _has_safe501("void f(int x) {\n    while (true) {\n        x++;\n    }\n}\n", tmp_path)


def test_c_headerless_for_without_break_fires_safe501(tmp_path: Path) -> None:
    assert _has_safe501("void f(int x) {\n    for (;;) {\n        x++;\n    }\n}\n", tmp_path)


def test_c_while_one_with_break_is_clean(tmp_path: Path) -> None:
    assert not _has_safe501("void f(int x) {\n    while (1) {\n        if (x) break;\n    }\n}\n", tmp_path)


def test_c_goto_out_of_loop_counts_as_an_exit(tmp_path: Path) -> None:
    """A ``goto`` leaving the loop body means it is not unbounded (the C wrinkle)."""
    src = "void f(int x) {\n    while (1) {\n        if (x) goto done;\n    }\ndone:\n    return;\n}\n"
    assert not _has_safe501(src, tmp_path)


def test_c_bounded_for_is_clean(tmp_path: Path) -> None:
    assert not _has_safe501("void f(int n) {\n    for (int i = 0; i < n; i++) {\n    }\n}\n", tmp_path)


def test_c_comparison_while_is_clean(tmp_path: Path) -> None:
    """A comparison-conditioned while is bounded; the non-comparison heuristic is Python-only."""
    assert not _has_safe501("void f(int x, int n) {\n    while (x < n) {\n        x++;\n    }\n}\n", tmp_path)
