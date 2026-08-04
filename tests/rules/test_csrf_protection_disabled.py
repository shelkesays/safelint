"""Tests for SAFE908 csrf_protection_disabled (Django + Laravel presets)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path


def _codes(src: Path) -> list[str]:
    """Run the engine with SAFE908 enabled and return the SAFE908 codes fired on *src*."""
    cfg = deep_merge(DEFAULTS, {"rules": {"csrf_protection_disabled": {"enabled": True}}})
    return [v.code for v in SafetyEngine(cfg).check_file(str(src)).violations if v.code == "SAFE908"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Python (Django)
# ---------------------------------------------------------------------------


def test_python_bare_csrf_exempt(tmp_path: Path) -> None:
    """``@csrf_exempt`` on a view fires."""
    src = _write(tmp_path, "views.py", "@csrf_exempt\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_called_csrf_exempt(tmp_path: Path) -> None:
    """``@csrf_exempt()`` (called form) fires."""
    src = _write(tmp_path, "views.py", "@csrf_exempt()\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_method_decorator_csrf_exempt(tmp_path: Path) -> None:
    """``@method_decorator(csrf_exempt)`` (class-based-view form) fires."""
    src = _write(tmp_path, "views.py", "@method_decorator(csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_unrelated_decorator_is_clean(tmp_path: Path) -> None:
    """An unrelated decorator (``@login_required``) does not fire."""
    src = _write(tmp_path, "views.py", "@login_required\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_csrf_exempt_kwarg_name_is_clean(tmp_path: Path) -> None:
    """``csrf_exempt`` as an unrelated keyword-argument NAME does not fire -
    ``@foo(csrf_exempt=True)`` configures ``foo``; it does not apply the
    ``csrf_exempt`` decorator."""
    src = _write(tmp_path, "views.py", "@foo(csrf_exempt=True)\ndef v(request):\n    return None\n")
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# PHP (Laravel)
# ---------------------------------------------------------------------------


def test_php_nonempty_except_fires(tmp_path: Path) -> None:
    """A non-empty ``$except`` route allow-list fires."""
    src = _write(tmp_path, "VerifyCsrfToken.php", "<?php\nclass VerifyCsrfToken { protected $except = ['stripe/*', 'webhook']; }\n")
    assert _codes(src) == ["SAFE908"]


def test_php_empty_except_is_clean(tmp_path: Path) -> None:
    """An empty ``$except = []`` exempts nothing and does not fire."""
    src = _write(tmp_path, "VerifyCsrfToken.php", "<?php\nclass VerifyCsrfToken { protected $except = []; }\n")
    assert _codes(src) == []


def test_php_unrelated_property_is_clean(tmp_path: Path) -> None:
    """A non-``except`` property initialised to a non-empty array does not fire."""
    src = _write(tmp_path, "M.php", "<?php\nclass M { protected $fillable = ['name', 'email']; }\n")
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_disabled_by_default(tmp_path: Path) -> None:
    """With the rule at its default (disabled), nothing fires even on @csrf_exempt."""
    src = _write(tmp_path, "views.py", "@csrf_exempt\ndef v(request):\n    return None\n")
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE908"] == []
