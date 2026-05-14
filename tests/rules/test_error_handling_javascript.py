"""Tests for ``empty_except`` (SAFE202) and ``logging_on_error`` (SAFE203) on JavaScript files."""

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
# empty_except (SAFE202) - JS empty catch block
# ---------------------------------------------------------------------------


def test_js_empty_catch_body_fires_safe202(tmp_path: Path) -> None:
    """``catch (e) {}`` with no statements fires SAFE202."""
    sample = tmp_path / "empty.js"
    sample.write_text(
        "try { foo(); } catch (e) {}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE202" for v in result.violations)


def test_js_catch_no_binding_empty_fires(tmp_path: Path) -> None:
    """``catch {}`` (ES2019 optional binding form) fires SAFE202 too."""
    sample = tmp_path / "nobinding.js"
    sample.write_text(
        "try { foo(); } catch {}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE202" for v in result.violations)


def test_js_catch_with_only_empty_statement_fires(tmp_path: Path) -> None:
    """``catch (e) { ; }`` (single empty_statement) fires SAFE202."""
    sample = tmp_path / "semi.js"
    sample.write_text(
        "try { foo(); } catch (e) { ; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE202" for v in result.violations)


def test_js_catch_with_only_literal_fires(tmp_path: Path) -> None:
    """``catch (e) { 0; }`` / ``catch (e) { null; }`` / ``catch (e) { "TODO"; }`` all fire."""
    for body in ("0", "null", "true", "false", "undefined", '"TODO"', "`hello`"):
        sample = tmp_path / f"lit_{body}.js".replace('"', "_").replace("`", "_")
        sample.write_text(
            f"try {{ foo(); }} catch (e) {{ {body}; }}\n",
            encoding="utf-8",
        )
        result = _engine().check_file(str(sample))
        assert any(v.code == "SAFE202" for v in result.violations), f"Expected SAFE202 for body {body!r}"


def test_js_catch_with_real_handling_does_not_fire(tmp_path: Path) -> None:
    """A catch block with at least one real statement does not fire SAFE202."""
    sample = tmp_path / "handled.js"
    sample.write_text(
        "try { foo(); } catch (e) { console.error(e); }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE202" for v in result.violations)


def test_js_catch_with_template_string_interpolation_does_not_fire(tmp_path: Path) -> None:
    """Template strings with ``${expr}`` interpolation are NOT treated as empty (the expr has side effects)."""
    sample = tmp_path / "interp.js"
    sample.write_text(
        "try { foo(); } catch (e) { `${e.message}`; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE202" for v in result.violations)


# ---------------------------------------------------------------------------
# logging_on_error (SAFE203) - JS catch must call console.* / logger.*
# ---------------------------------------------------------------------------


def test_js_catch_with_no_logging_fires_safe203(tmp_path: Path) -> None:
    """A catch block that handles the error without logging fires SAFE203."""
    sample = tmp_path / "silent.js"
    sample.write_text(
        "try { foo(); } catch (e) { state.failed = true; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE203" for v in result.violations)


def test_js_catch_with_console_error_does_not_fire(tmp_path: Path) -> None:
    """``console.error(e)`` inside catch satisfies SAFE203."""
    sample = tmp_path / "logged.js"
    sample.write_text(
        "function f() { try { foo(); } catch (e) { console.error(e); state.failed = true; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE203" for v in result.violations)


def test_js_catch_with_console_warn_does_not_fire(tmp_path: Path) -> None:
    """``console.warn`` / ``console.log`` / ``console.info`` all satisfy SAFE203."""
    for verb in ("warn", "log", "info", "debug", "trace"):
        sample = tmp_path / f"{verb}.js"
        sample.write_text(
            f"function f() {{ try {{ foo(); }} catch (e) {{ console.{verb}(e); state.failed = true; }} }}\n",
            encoding="utf-8",
        )
        result = _engine().check_file(str(sample))
        assert not any(v.code == "SAFE203" for v in result.violations), f"console.{verb}() should satisfy SAFE203"


def test_js_catch_with_logger_library_does_not_fire(tmp_path: Path) -> None:
    """Generic logger libraries (``logger.error``, ``pino.warn``) are recognised via call name."""
    sample = tmp_path / "logger.js"
    sample.write_text(
        "function f() { try { foo(); } catch (e) { logger.error('failed', e); throw e; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE203" for v in result.violations)


def test_js_catch_with_only_throw_does_not_fire(tmp_path: Path) -> None:
    """A catch that just rethrows is exempt - the error isn't being swallowed."""
    sample = tmp_path / "rethrow.js"
    sample.write_text(
        "function f() { try { foo(); } catch (e) { throw e; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE203" for v in result.violations)


def test_js_logging_in_nested_function_does_not_satisfy_outer(tmp_path: Path) -> None:
    """A logging call inside a nested function within a catch block does NOT satisfy the outer catch.

    The nested function isn't actually invoked when the catch fires -
    so it doesn't log the caught error.
    """
    sample = tmp_path / "nested.js"
    sample.write_text(
        "function f() { try { foo(); } catch (e) { const helper = () => { console.error('would log'); }; state.failed = true; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe203 = [v for v in result.violations if v.code == "SAFE203"]
    assert len(safe203) == 1


def test_js_catch_throw_different_identifier_requires_logging(tmp_path: Path) -> None:
    """``catch (e) { throw freshError; }`` is NOT a re-raise - logging still required.

    The original ``e`` is still in scope and could be lost; the rule
    must require logging unless the throw operand is exactly the
    caught binding.
    """
    sample = tmp_path / "throw_other.js"
    sample.write_text(
        "function f() {\n  try {\n    risky();\n  } catch (e) {\n    throw freshError;\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE203" for v in result.violations)


def test_js_catch_no_binding_throw_requires_logging(tmp_path: Path) -> None:
    """``catch { throw e; }`` - no caught binding, so any throw is a fresh error."""
    sample = tmp_path / "throw_no_binding.js"
    sample.write_text(
        "function f() {\n  try {\n    risky();\n  } catch {\n    throw outerErr;\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE203" for v in result.violations)


def test_js_catch_throw_caught_binding_does_not_fire(tmp_path: Path) -> None:
    """``catch (e) { throw e; }`` - exact binding match is the only legit re-raise."""
    sample = tmp_path / "throw_caught.js"
    sample.write_text(
        "function f() {\n  try {\n    risky();\n  } catch (e) {\n    throw e;\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE203" for v in result.violations)
