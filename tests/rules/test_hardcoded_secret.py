"""Tests for SAFE909 hardcoded_secret (Django / Flask + Laravel presets)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path


def _codes(src: Path) -> list[str]:
    """Run the engine with SAFE909 enabled and return the SAFE909 codes fired on *src*."""
    cfg = deep_merge(DEFAULTS, {"rules": {"hardcoded_secret": {"enabled": True}}})
    return [v.code for v in SafetyEngine(cfg).check_file(str(src)).violations if v.code == "SAFE909"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Python (Django SECRET_KEY / Flask app.secret_key)
# ---------------------------------------------------------------------------


def test_python_django_secret_key_literal(tmp_path: Path) -> None:
    """``SECRET_KEY = "..."`` (string literal) fires."""
    src = _write(tmp_path, "settings.py", "SECRET_KEY = 'django-insecure-abc123'\n")
    assert _codes(src) == ["SAFE909"]


def test_python_flask_secret_key_attribute(tmp_path: Path) -> None:
    """``app.secret_key = "..."`` fires."""
    src = _write(tmp_path, "app.py", "app.secret_key = 'super-secret'\n")
    assert _codes(src) == ["SAFE909"]


def test_python_secret_key_from_env_is_clean(tmp_path: Path) -> None:
    """Reading the secret from the environment (a call, not a literal) does not fire."""
    src = _write(tmp_path, "settings.py", "import os\nSECRET_KEY = os.environ['SECRET_KEY']\nkey2 = env('SECRET_KEY')\n")
    assert _codes(src) == []


def test_python_empty_secret_is_clean(tmp_path: Path) -> None:
    """An empty-string placeholder (``SECRET_KEY = ""``) does not fire."""
    src = _write(tmp_path, "settings.py", "SECRET_KEY = ''\n")
    assert _codes(src) == []


def test_python_unrelated_literal_is_clean(tmp_path: Path) -> None:
    """An unrelated string assignment does not fire."""
    src = _write(tmp_path, "settings.py", "APP_NAME = 'myapp'\n")
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# PHP (Laravel APP_KEY)
# ---------------------------------------------------------------------------


def test_php_base64_key_literal(tmp_path: Path) -> None:
    """A hardcoded ``base64:`` app-key literal fires."""
    src = _write(tmp_path, "app.php", "<?php return ['key' => 'base64:AAAABBBBCCCCDDDD']; ?>")
    assert _codes(src) == ["SAFE909"]


def test_php_env_key_is_clean(tmp_path: Path) -> None:
    """``'key' => env('APP_KEY')`` (no literal) does not fire."""
    src = _write(tmp_path, "app.php", "<?php return ['key' => env('APP_KEY')]; ?>")
    assert _codes(src) == []


def test_php_unrelated_base64_literal_is_clean(tmp_path: Path) -> None:
    """A ``base64:`` literal that is NOT a ``'key'`` config value must not fire (no false positive)."""
    src = _write(
        tmp_path,
        "misc.php",
        "<?php\n$x = 'base64:justsomedata';\nreturn ['token' => 'base64:notthekey', 'name' => 'base64:x'];\n",
    )
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_disabled_by_default(tmp_path: Path) -> None:
    """With the rule at its default (disabled), nothing fires even on a hardcoded SECRET_KEY."""
    src = _write(tmp_path, "settings.py", "SECRET_KEY = 'abc'\n")
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE909"] == []
