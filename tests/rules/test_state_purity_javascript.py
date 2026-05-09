"""Tests for ``global_mutation`` (SAFE302) on JavaScript files."""

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
# Default global namespaces fire when written to from inside a function.
# ---------------------------------------------------------------------------


def test_js_globalthis_assignment_fires_safe302(tmp_path: Path) -> None:
    """``globalThis.x = 1`` inside a function fires SAFE302."""
    sample = tmp_path / "g1.js"
    sample.write_text(
        "function setCounter(n) {\n  globalThis.counter = n;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe302 = [v for v in result.violations if v.code == "SAFE302"]
    assert len(safe302) == 1
    assert "globalThis.counter" in safe302[0].message
    assert "setCounter" in safe302[0].message


def test_js_window_assignment_fires(tmp_path: Path) -> None:
    """``window.config = ...`` inside a function fires."""
    sample = tmp_path / "g2.js"
    sample.write_text(
        "function configure(opts) { window.config = opts; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE302" for v in result.violations)


def test_js_global_assignment_fires(tmp_path: Path) -> None:
    """``global.cache = {}`` inside a function fires (Node convention)."""
    sample = tmp_path / "g3.js"
    sample.write_text(
        "function init() { global.cache = new Map(); }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE302" for v in result.violations)


def test_js_self_assignment_fires(tmp_path: Path) -> None:
    """``self.x = ...`` inside a function fires (Web Worker convention)."""
    sample = tmp_path / "g4.js"
    sample.write_text(
        "function setupWorker() { self.workerState = 'ready'; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE302" for v in result.violations)


def test_js_chained_process_env_fires(tmp_path: Path) -> None:
    """``process.env.NODE_ENV = '...'`` walks the receiver chain to the ``process`` root."""
    sample = tmp_path / "env.js"
    sample.write_text(
        "function configureEnv() { process.env.NODE_ENV = 'production'; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe302 = [v for v in result.violations if v.code == "SAFE302"]
    assert len(safe302) == 1
    assert "process.env.NODE_ENV" in safe302[0].message


def test_js_augmented_assignment_to_global_fires(tmp_path: Path) -> None:
    """``globalThis.counter += 1`` is also a write — fires."""
    sample = tmp_path / "aug.js"
    sample.write_text(
        "function inc() { globalThis.counter += 1; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE302" for v in result.violations)


def test_js_update_expression_on_global_fires(tmp_path: Path) -> None:
    """``globalThis.counter++`` and ``--window.x`` (update_expression) also fire — they mutate the global.

    Postfix and prefix ``++`` / ``--`` are unambiguously writes; without
    this branch the rule would silently miss the most concise form of
    global mutation.
    """
    for expr in ("globalThis.counter++", "--window.x", "process.exitCode++", "++self.tick"):
        sample = tmp_path / f"update_{hash(expr) & 0xffff:x}.js"
        sample.write_text(
            f"function bump() {{ {expr}; }}\n",
            encoding="utf-8",
        )
        result = _engine().check_file(str(sample))
        assert any(v.code == "SAFE302" for v in result.violations), f"Expected SAFE302 for: {expr}"


# ---------------------------------------------------------------------------
# Cases that should NOT fire.
# ---------------------------------------------------------------------------


def test_js_top_level_assignment_does_not_fire(tmp_path: Path) -> None:
    """Module-level ``globalThis.x = 1`` (outside any function) is module setup, not the bug."""
    sample = tmp_path / "top.js"
    sample.write_text(
        "globalThis.appConfig = {debug: true};\nglobalThis.startTime = Date.now();\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE302" for v in result.violations)


def test_js_local_namespace_assignment_does_not_fire(tmp_path: Path) -> None:
    """Writes to a non-global object (``state.x = ...``) don't fire."""
    sample = tmp_path / "local.js"
    sample.write_text(
        "function update(state) { state.value = 1; state.dirty = true; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE302" for v in result.violations)


def test_js_read_global_does_not_fire(tmp_path: Path) -> None:
    """Reading a global (no write) doesn't fire — only mutations do."""
    sample = tmp_path / "read.js"
    sample.write_text(
        "function getEnv() { return globalThis.env; }\nfunction getUserAgent() { return window.navigator.userAgent; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE302" for v in result.violations)


def test_js_nested_function_isolation(tmp_path: Path) -> None:
    """Inner function's globals don't get attributed to the outer function."""
    sample = tmp_path / "nested.js"
    sample.write_text(
        "function outer() {\n  function inner() { globalThis.x = 1; }\n  return inner;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe302 = [v for v in result.violations if v.code == "SAFE302"]
    # Exactly one violation, attributed to ``inner`` (not ``outer``).
    assert len(safe302) == 1
    assert "inner" in safe302[0].message


def test_js_user_can_extend_namespace_list(tmp_path: Path) -> None:
    """``global_namespaces_javascript`` is config-overridable."""
    sample = tmp_path / "custom.js"
    sample.write_text(
        "function f() { customGlobal.x = 1; }\n",
        encoding="utf-8",
    )
    # Default: ``customGlobal`` not in list — no fire.
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE302" for v in result.violations)

    # With override: fires.
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"global_mutation": {"global_namespaces_javascript": ["customGlobal"]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE302" for v in result.violations)


def test_js_arrow_function_fires(tmp_path: Path) -> None:
    """Arrow functions are also covered."""
    sample = tmp_path / "arrow.js"
    sample.write_text(
        "const setup = () => { globalThis.ready = true; };\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE302" for v in result.violations)
