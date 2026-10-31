"""Tests for ``wide_scope_declaration`` (SAFE305) on JavaScript files."""

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


# ---------------------------------------------------------------------------
# Cases that fire.
# ---------------------------------------------------------------------------


def test_js_var_read_outside_its_block_fires_safe305(tmp_path: Path) -> None:
    """A ``var`` whose hoisting is OBSERVABLE fires: read outside its own block.

    Rewritten in 2.16.0. This used to be ``function f() { var x = 1; return x; }``
    and asserted a hit, which is the shape #201 is about: ``let x`` there behaves
    identically, so there was nothing to fix and nothing to report.
    """
    sample = tmp_path / "var.js"
    sample.write_text(
        "function f(c) {\n  if (c) {\n    var x = 1;\n  }\n  return x;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe305 = [v for v in result.violations if v.code == "SAFE305"]
    assert len(safe305) == 1
    assert "var" in safe305[0].message


def test_js_top_level_var_does_not_fire(tmp_path: Path) -> None:
    """Module-scope ``var`` is quiet: there is no block for it to hoist out of.

    This is the 89% case from #201 - ``var path = require("node:path")`` at the
    top of a pre-ES6 module, where ``const`` would behave identically. 1748 of
    Express's 1960 default findings were this.
    """
    sample = tmp_path / "top.js"
    sample.write_text(
        'var path = require("node:path");\nmodule.exports = path;\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)


def test_js_var_in_block_fires(tmp_path: Path) -> None:
    """``var`` declared inside a block still fires - the hazard is the function-scope hoisting."""
    sample = tmp_path / "block.js"
    sample.write_text(
        "function f(items) {\n"
        "  if (items.length > 0) {\n"
        "    var first = items[0];\n"  # hoists to top of f, visible after the if
        "  }\n"
        "  return first;\n"  # accidentally accessible - exactly the bug SAFE305 guards
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE305" for v in result.violations)


def test_js_var_multi_binding_fires_once(tmp_path: Path) -> None:
    """``var x = 1, y = 2;`` is a single ``variable_declaration`` node - fires once.

    Treating each binding as a separate violation would over-report on a
    line that's a single fix unit (replace the leading ``var`` with
    ``let`` / ``const``).
    """
    sample = tmp_path / "multi.js"
    sample.write_text(
        "function f(c) {\n  if (c) {\n    var x = 1, y = 2, z = 3;\n  }\n  return x + y + z;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe305 = [v for v in result.violations if v.code == "SAFE305"]
    assert len(safe305) == 1


def test_js_var_in_for_loop_fires(tmp_path: Path) -> None:
    """``for (var i = 0; ...)`` fires - ``i`` leaks out of the loop into the function."""
    sample = tmp_path / "forloop.js"
    sample.write_text(
        "function f(arr) {\n"
        "  for (var i = 0; i < arr.length; i++) {\n"
        "    arr[i] = i * 2;\n"
        "  }\n"
        "  return i;\n"  # ``i`` is still accessible - that's the bug
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE305" for v in result.violations)


# ---------------------------------------------------------------------------
# Cases that do NOT fire.
# ---------------------------------------------------------------------------


def test_js_let_does_not_fire(tmp_path: Path) -> None:
    """``let x = 1;`` is block-scoped - clean."""
    sample = tmp_path / "let.js"
    sample.write_text(
        "function f() { let x = 1; return x; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)


def test_js_const_does_not_fire(tmp_path: Path) -> None:
    """``const x = 1;`` is block-scoped - clean."""
    sample = tmp_path / "const.js"
    sample.write_text(
        "function f() { const x = 1; return x; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)


def test_js_for_let_does_not_fire(tmp_path: Path) -> None:
    """``for (let i = 0; ...)`` is the safe form - ``i`` is block-scoped to the loop."""
    sample = tmp_path / "for_let.js"
    sample.write_text(
        "function f(arr) {\n  for (let i = 0; i < arr.length; i++) {\n    arr[i] = i * 2;\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)


def test_js_pure_function_does_not_fire(tmp_path: Path) -> None:
    """A function with no declarations at all is clean."""
    sample = tmp_path / "pure.js"
    sample.write_text(
        "function add(a, b) { return a + b; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)


def test_js_disabled_via_config(tmp_path: Path) -> None:
    """Setting ``enabled = false`` silences the rule entirely."""
    sample = tmp_path / "var.js"
    sample.write_text(
        "function f(c) {\n  if (c) {\n    var x = 1;\n  }\n  return x;\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"wide_scope_declaration": {"enabled": False}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)
    # ...and the same file DOES report with the rule on, so this asserts the
    # switch rather than a sample that was already quiet.
    assert any(v.code == "SAFE305" for v in _engine().check_file(str(sample)).violations)


# ---------------------------------------------------------------------------
# Python files don't fire SAFE305.
# ---------------------------------------------------------------------------


def test_python_file_does_not_fire_safe305(tmp_path: Path) -> None:
    """SAFE305 is JS-only - Python files don't trigger it (engine's per-language dispatch)."""
    sample = tmp_path / "code.py"
    sample.write_text(
        "x = 1\ndef f():\n    return x\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)


def test_js_var_inline_suppression(tmp_path: Path) -> None:
    """``// nosafe: SAFE305`` on the same line suppresses the violation."""
    sample = tmp_path / "suppressed.js"
    sample.write_text(
        "function f(c) {\n  if (c) {\n    var legacy = 1;  // nosafe: SAFE305\n  }\n  return legacy;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE305" for v in result.violations)
    assert any(v.code == "SAFE305" for v in result.suppressed)
