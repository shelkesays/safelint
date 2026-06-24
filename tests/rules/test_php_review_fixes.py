"""Regression tests for PHP review-cycle fixes.

Each test pins a behaviour corrected after the initial PHP port landed:

* SAFE105 - a bare ``foo()`` inside a class method is a global call, not
  method self-recursion (PHP resolves unqualified calls to global functions).
* SAFE501 - PHP boolean literals are case-insensitive, so ``while (TRUE)``
  and ``while (True)`` must fire.
* SAFE203 - a re-raise preceded by a comment (``{ /* why */ throw $e; }``)
  is still a re-raise, not an unlogged swallow (comments are named children).
* SAFE302 - an increment / decrement of a declared global (``$c++``) is a
  mutation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _codes(tmp_path: Path, body: str, rule: str) -> set[str]:
    """Return the violation codes from running *body* with *rule* enabled."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n" + body, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {rule: {"enabled": True}}}))
    return {v.code for v in engine.check_file(str(sample)).violations}


def test_bare_call_in_method_is_not_self_recursion(tmp_path: Path) -> None:
    """A bare ``foo()`` inside method ``foo`` denotes a global function, not recursion."""
    assert "SAFE105" not in _codes(tmp_path, "class C { function foo() { return foo(); } }", "no_recursion")


def test_top_level_bare_call_is_self_recursion(tmp_path: Path) -> None:
    """A bare ``foo()`` inside a top-level ``function foo`` IS recursion (control)."""
    assert "SAFE105" in _codes(tmp_path, "function foo() { return foo(); }", "no_recursion")


def test_this_qualified_method_call_is_recursion(tmp_path: Path) -> None:
    """``$this->foo()`` inside method ``foo`` is still recursion (control)."""
    assert "SAFE105" in _codes(tmp_path, "class C { function foo() { return $this->foo(); } }", "no_recursion")


def test_nullsafe_this_call_is_recursion(tmp_path: Path) -> None:
    """``$this?->foo()`` recurses too (``$this`` is never null), so it fires SAFE105."""
    assert "SAFE105" in _codes(tmp_path, "class C { function foo() { return $this?->foo(); } }", "no_recursion")


def test_uppercase_while_true_fires(tmp_path: Path) -> None:
    """PHP booleans are case-insensitive: ``while (TRUE)`` fires SAFE501."""
    assert "SAFE501" in _codes(tmp_path, "while (TRUE) { work(); }", "unbounded_loops")


def test_titlecase_while_true_fires(tmp_path: Path) -> None:
    """``while (True)`` fires SAFE501 too."""
    assert "SAFE501" in _codes(tmp_path, "while (True) { work(); }", "unbounded_loops")


def test_rethrow_with_leading_comment_is_clean(tmp_path: Path) -> None:
    """A re-raise preceded by a comment is recognised, not flagged as unlogged."""
    assert "SAFE203" not in _codes(tmp_path, "try { x(); } catch (\\E $e) { /* why */ throw $e; }", "logging_on_error")


def test_increment_of_declared_global_is_mutation(tmp_path: Path) -> None:
    """``global $c; $c++;`` is a write to shared global state (SAFE302)."""
    assert "SAFE302" in _codes(tmp_path, "function f() { global $c; $c++; }", "global_mutation")


def test_docblock_blanket_suppression_fires(tmp_path: Path) -> None:
    """A docblock ``/** @psalm-suppress all */`` is recognised despite the continuation ``*``."""
    assert "SAFE603" in _codes(tmp_path, "/** @psalm-suppress all */\n$x = 1;", "blanket_suppression")


def test_scoped_docblock_suppression_is_clean(tmp_path: Path) -> None:
    """A scoped ``/** @psalm-suppress SomeIssue */`` targets a named check and is clean (control)."""
    assert "SAFE603" not in _codes(tmp_path, "/** @psalm-suppress SomeIssue */\n$x = 1;", "blanket_suppression")


def test_multiline_docblock_blanket_suppression_fires(tmp_path: Path) -> None:
    """A directive on any line of a multi-line docblock is recognised (SAFE603)."""
    body = "/**\n * Does a thing.\n * @psalm-suppress all\n */\n$x = 1;"
    assert "SAFE603" in _codes(tmp_path, body, "blanket_suppression")
