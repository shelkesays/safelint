"""Tests for ``unbounded_loops`` (SAFE501) on Java files.

Java-specific cases that exercise the SAFE501 branches added for
``next/java``:

* tree-sitter-java emits ``true`` (lowercase) for the boolean
  literal, NOT ``true_literal`` like JS does.
* Java's label-token type is bare ``identifier`` (NOT JS's
  ``statement_identifier``).
* Break-scope boundaries for Java include ``enhanced_for_statement``
  (for-each) and ``switch_expression`` (Java 14+ unified switch);
  a ``break`` inside those constructs exits THEM, not an enclosing
  ``while (true)``.

Each branch needs at least one positive and one negative case so
regressions in tree-sitter-java's grammar shape (or in our
per-language node-type tables) are caught at the test layer rather
than via a CI safelint-check regression in a downstream Java project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def _safe501_count(result) -> int:
    """Return the SAFE501 violation count for *result*."""
    return sum(1 for v in result.violations if v.code == "SAFE501")


# ---------------------------------------------------------------------------
# Basic while (true) - positive + negative
# ---------------------------------------------------------------------------


def test_java_while_true_no_break_fires_safe501(tmp_path: Path) -> None:
    """``while (true) { ... }`` with no break inside fires SAFE501.

    Guards against the ``"true"`` literal-type wiring in
    ``_BOOLEAN_TRUE_TYPE_BY_LANG`` - if tree-sitter-java's grammar
    ever changes the literal type, this test catches it.
    """
    sample = tmp_path / "Infinite.java"
    sample.write_text(
        "class Infinite {\n    void f() {\n        while (true) {\n            work();\n        }\n    }\n    void work() {}\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) >= 1, "while (true) with no break should fire SAFE501"


def test_java_while_true_with_unlabelled_break_does_not_fire(tmp_path: Path) -> None:
    """``while (true) { ... break; }`` is bounded and clean."""
    sample = tmp_path / "Bounded.java"
    sample.write_text(
        "class Bounded {\n"
        "    void f(java.util.Queue<String> q) {\n"
        "        while (true) {\n"
        "            String item = q.poll();\n"
        "            if (item == null) break;\n"
        "            work(item);\n"
        "        }\n"
        "    }\n"
        "    void work(String s) {}\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) == 0


# ---------------------------------------------------------------------------
# Labelled break - the reviewer's headline case
# ---------------------------------------------------------------------------


def test_java_labeled_break_exits_outer_while(tmp_path: Path) -> None:
    """``outer: while (true) { for (...) { break outer; } }`` is bounded.

    The labelled break exits the outer ``while (true)``. The rule
    must walk ``labeled_statement`` ancestors and recognise the
    bare ``identifier`` token as the label-token (NOT JS's
    ``statement_identifier``).
    """
    sample = tmp_path / "LabelOuter.java"
    sample.write_text(
        "class LabelOuter {\n"
        "    void f(java.util.List<String> items) {\n"
        "        outer: while (true) {\n"
        "            for (String item : items) {\n"
        "                if (item.isEmpty()) {\n"
        "                    break outer;\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) == 0, "labelled break should exit the outer while (true) and clear SAFE501"


def test_java_unlabeled_break_in_nested_for_does_not_exit_outer_while(tmp_path: Path) -> None:
    """``while (true) { for (...) { break; } }`` (no label) still fires.

    The unlabelled ``break`` only exits the inner ``for``;
    ``enhanced_for_statement`` is a break-scope boundary, so the
    outer ``while (true)`` is still unbounded.
    """
    sample = tmp_path / "NestedForBreak.java"
    sample.write_text(
        "class NestedForBreak {\n"
        "    void f(java.util.List<String> items) {\n"
        "        while (true) {\n"
        "            for (String item : items) {\n"
        "                if (item.isEmpty()) {\n"
        "                    break;\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) >= 1, "unlabelled break inside enhanced_for should not exit the enclosing while (true)"


# ---------------------------------------------------------------------------
# switch_expression as a break-scope boundary
# ---------------------------------------------------------------------------


def test_java_break_in_switch_expression_does_not_exit_outer_while(tmp_path: Path) -> None:
    """``while (true) { switch (x) { case 1 -> { break; } } }`` still fires.

    Both Java switch shapes (classic colon-form and Java 14+ arrow
    form) parse as ``switch_expression``. A ``break`` inside the
    arms of either form exits the switch, NOT the enclosing while.
    """
    sample = tmp_path / "SwitchBreak.java"
    sample.write_text(
        "class SwitchBreak {\n"
        "    void f(int x) {\n"
        "        while (true) {\n"
        "            switch (x) {\n"
        "                case 1: { break; }\n"
        "                case 2: { break; }\n"
        "                default: { break; }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) >= 1, "break inside switch arms should not exit the enclosing while (true)"


# ---------------------------------------------------------------------------
# Function boundary - break inside a nested method/lambda should not count
# ---------------------------------------------------------------------------


def test_java_break_in_nested_method_does_not_clear_outer_while(tmp_path: Path) -> None:
    """A ``break`` in a different method doesn't affect the outer ``while (true)``.

    Function boundaries (method_declaration, lambda_expression,
    etc.) are in ``_JAVA_BREAK_SCOPE_BOUNDARIES``, so the
    label-resolution walk stops at the enclosing method.
    """
    sample = tmp_path / "NestedMethod.java"
    sample.write_text(
        "class NestedMethod {\n"
        "    void outer() {\n"
        "        while (true) {\n"
        "            inner(0);\n"
        "        }\n"
        "    }\n"
        "    void inner(int n) {\n"
        "        for (int i = 0; i < n; i++) {\n"
        "            break;\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _safe501_count(result) >= 1, "outer method's while (true) should fire; nested method's break is in a different scope"
