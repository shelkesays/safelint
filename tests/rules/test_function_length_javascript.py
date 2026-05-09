"""Tests for ``function_length`` (SAFE101) on JavaScript files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


# ---------------------------------------------------------------------------
# Default mode (lines): all four function shapes count toward the limit.
# ---------------------------------------------------------------------------


def test_js_function_declaration_too_long_fires_safe101(tmp_path: Path) -> None:
    """A ``function`` declaration whose body exceeds ``max_lines`` fires SAFE101."""
    body = "    const x = 1;\n" * 65
    source = "function tooLong() {\n" + body + "}\n"
    sample = tmp_path / "long.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe101 = [v for v in result.violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "tooLong" in safe101[0].message


def test_js_arrow_function_too_long_fires_safe101(tmp_path: Path) -> None:
    """A long arrow function fires SAFE101.

    Arrow functions are anonymous from a name-binding perspective —
    the rule reports them as ``<anonymous>`` because there's no
    ``name`` field on the AST node.
    """
    body = "  const x = 1;\n" * 65
    source = "const tooLong = () => {\n" + body + "};\n"
    sample = tmp_path / "arrow.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe101 = [v for v in result.violations if v.code == "SAFE101"]
    assert len(safe101) == 1


def test_js_method_definition_too_long_fires_safe101(tmp_path: Path) -> None:
    """A long class method fires SAFE101 with the method name in the message."""
    body = "    this.x = 1;\n" * 65
    source = "class Widget {\n  longMethod() {\n" + body + "  }\n}\n"
    sample = tmp_path / "method.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe101 = [v for v in result.violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "longMethod" in safe101[0].message


def test_js_async_function_too_long_fires_safe101(tmp_path: Path) -> None:
    """``async function`` declarations are also covered."""
    body = "    await x();\n" * 65
    source = "async function tooLong() {\n" + body + "}\n"
    sample = tmp_path / "async.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    safe101 = [v for v in result.violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "tooLong" in safe101[0].message


def test_js_short_function_does_not_fire(tmp_path: Path) -> None:
    """A function under the default 60-line cap produces no SAFE101."""
    source = (
        "function short(a, b) {\n"
        "  if (a > b) return a;\n"
        "  return b;\n"
        "}\n"
    )
    sample = tmp_path / "short.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE101" for v in result.violations)


# ---------------------------------------------------------------------------
# Per-mode behaviour.
# ---------------------------------------------------------------------------


def test_js_logical_lines_mode_skips_blanks_and_comments(tmp_path: Path) -> None:
    """``count_mode = "logical_lines"`` strips blank lines and ``//``-prefixed lines.

    Raw line count would be over-cap; logical-line count is under, so
    no violation fires. Verifies the JS-specific ``//`` comment prefix
    is honoured (Python's ``#`` would falsely strip nothing here).
    """
    # 4 logical lines of code + many blanks + many ``//``-only lines.
    blank_filler = "\n" * 80
    comment_filler = ("// just a note\n" * 80)
    source = (
        "function f() {\n"
        + blank_filler
        + comment_filler
        + "  const a = 1;\n"
        + "  const b = 2;\n"
        + "  return a + b;\n"
        + "}\n"
    )
    sample = tmp_path / "logical.js"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"function_length": {"count_mode": "logical_lines", "max_lines": 60}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert not any(v.code == "SAFE101" for v in result.violations)


def test_js_statements_mode_raises_clear_error(tmp_path: Path) -> None:
    """``count_mode = "statements"`` is Python-only today — JS configs hit a clear error."""
    source = "function f() { return 1; }\n"
    sample = tmp_path / "stmt.js"
    sample.write_text(source, encoding="utf-8")

    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"function_length": {"count_mode": "statements", "max_lines": 1}}},
    )
    with pytest.raises(ValueError, match="not supported for 'javascript'"):
        SafetyEngine(cfg).check_file(str(sample))


# ---------------------------------------------------------------------------
# Suppression: line-style ``// nosafe`` directives work.
# ---------------------------------------------------------------------------


def test_js_nosafe_suppresses_safe101(tmp_path: Path) -> None:
    """``// nosafe: SAFE101`` on the function-definition line suppresses the violation."""
    body = "    const x = 1;\n" * 65
    source = "function tooLong() {  // nosafe: SAFE101\n" + body + "}\n"
    sample = tmp_path / "suppressed.js"
    sample.write_text(source, encoding="utf-8")

    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE101" for v in result.violations)
    # Suppressed violations are still tracked for the auditing summary.
    assert any(v.code == "SAFE101" for v in result.suppressed)
