"""Tests for SAFE905 debug_mode_enabled (Python + PHP framework presets)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path


def _codes(src: Path) -> list[str]:
    """Run the engine with SAFE905 enabled and return the SAFE905 codes fired on *src*."""
    cfg = deep_merge(DEFAULTS, {"rules": {"debug_mode_enabled": {"enabled": True}}})
    return [v.code for v in SafetyEngine(cfg).check_file(str(src)).violations if v.code == "SAFE905"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def test_python_django_debug_true(tmp_path: Path) -> None:
    """``DEBUG = True`` (Django settings) fires."""
    assert _codes(_write(tmp_path, "settings.py", "DEBUG = True\n")) == ["SAFE905"]


def test_python_flask_app_debug_attribute(tmp_path: Path) -> None:
    """``app.debug = True`` (Flask attribute) fires."""
    assert _codes(_write(tmp_path, "app.py", "app.debug = True\n")) == ["SAFE905"]


def test_python_debug_and_reload_kwargs(tmp_path: Path) -> None:
    """``app.run(debug=True)`` and ``uvicorn.run(..., reload=True)`` both fire."""
    src = _write(tmp_path, "main.py", "app.run(debug=True)\nuvicorn.run(app, reload=True)\n")
    assert _codes(src) == ["SAFE905", "SAFE905"]


def test_python_debug_false_is_clean(tmp_path: Path) -> None:
    """``DEBUG = False`` and ``debug=False`` do not fire."""
    src = _write(tmp_path, "settings.py", "DEBUG = False\napp.run(debug=False)\nOTHER = True\n")
    assert _codes(src) == []


def test_python_unrelated_true_is_clean(tmp_path: Path) -> None:
    """An unrelated ``= True`` / keyword does not fire."""
    src = _write(tmp_path, "settings.py", "ENABLED = True\nfoo(verbose=True)\n")
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------


def test_php_config_app_debug_true(tmp_path: Path) -> None:
    """A Laravel config array ``'app.debug' => true`` fires."""
    src = _write(tmp_path, "app.php", "<?php return ['app.debug' => true]; ?>")
    assert _codes(src) == ["SAFE905"]


def test_php_debug_false_is_clean(tmp_path: Path) -> None:
    """``'app.debug' => false`` and unrelated entries do not fire."""
    src = _write(tmp_path, "app.php", "<?php return ['app.debug' => false, 'name' => 'x']; ?>")
    assert _codes(src) == []


def test_php_non_debug_true_key_is_clean(tmp_path: Path) -> None:
    """A ``true`` value under a non-debug key (``'cache' => true``) does not fire."""
    src = _write(tmp_path, "app.php", "<?php return ['cache' => true]; ?>")
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_disabled_by_default(tmp_path: Path) -> None:
    """With the rule at its default (disabled), nothing fires even on DEBUG = True."""
    src = _write(tmp_path, "settings.py", "DEBUG = True\n")
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE905"] == []
