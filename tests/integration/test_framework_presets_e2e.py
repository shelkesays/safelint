"""End-to-end integration test of the Python + PHP framework presets.

Runs the full ``SafetyEngine`` against representative Django / Flask /
FastAPI / Laravel fixtures under
``tests/fixtures/framework_presets/`` and asserts the expected
SAFE905-907 firing profile per framework. Mirrors
``test_spring_boot_e2e.py``: it is the v2.9.0 regression baseline for
the shared cross-framework rules and the preset wiring.

Each fixture is hand-crafted so every positive case (rule should fire)
has a matching negative control (rule should NOT fire) in the same
file - both for the test's clarity and as a "what does idiomatic
framework code look like under each rule?" reference.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING

from safelint.core.config import (
    DEFAULTS,
    _apply_php_framework_preset,
    _apply_python_framework_preset,
    _apply_python_pydantic_preset,
)
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from collections.abc import Iterable


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "framework_presets"


def _python_config(framework: str, *, pydantic: bool = False) -> dict:
    """Return DEFAULTS with the given Python framework (+ optional pydantic) preset applied."""
    cfg = copy.deepcopy(DEFAULTS)
    _apply_python_framework_preset(cfg, framework)
    _apply_python_pydantic_preset(cfg, enabled=pydantic)
    return cfg


def _php_config(framework: str) -> dict:
    """Return DEFAULTS with the given PHP framework preset applied."""
    cfg = copy.deepcopy(DEFAULTS)
    _apply_php_framework_preset(cfg, framework)
    return cfg


def _codes(cfg: dict, fixture: str) -> list[str]:
    """Lint one fixture and return all violation codes (blocking + advisory + suppressed)."""
    result = SafetyEngine(cfg).check_file(str(FIXTURES_DIR / fixture))
    return [v.code for v in result.violations + result.suppressed]


def _count(codes: Iterable[str], code: str) -> int:
    return list(codes).count(code)


# ---------------------------------------------------------------------------
# Django
# ---------------------------------------------------------------------------


def test_django_settings_debug_flag() -> None:
    """``DEBUG = True`` in settings fires SAFE905 exactly once."""
    codes = _codes(_python_config("django"), "django/settings.py")
    assert _count(codes, "SAFE905") == 1, codes


def test_django_modelform_mass_assignment() -> None:
    """``fields = "__all__"`` fires SAFE906 once; the explicit-list form is clean."""
    codes = _codes(_python_config("django"), "django/forms.py")
    assert _count(codes, "SAFE906") == 1, codes


def test_django_unvalidated_request() -> None:
    """The raw ``request.data`` bind fires SAFE907 once; the serializer view is clean."""
    codes = _codes(_python_config("django"), "django/views.py")
    assert _count(codes, "SAFE907") == 1, codes


# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------


def test_flask_debug_and_unvalidated() -> None:
    """Flask fires SAFE905 (app.run debug) and SAFE907 (raw request.json), but never SAFE906."""
    codes = _codes(_python_config("flask"), "flask/app.py")
    assert _count(codes, "SAFE905") == 1, codes
    assert _count(codes, "SAFE907") == 1, codes
    assert _count(codes, "SAFE906") == 0, "Flask preset must not enable mass_assignment"


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------


def test_fastapi_reload_and_unvalidated() -> None:
    """FastAPI fires SAFE905 (uvicorn reload) and SAFE907 (raw body); model_validate clears one view."""
    codes = _codes(_python_config("fastapi"), "fastapi/main.py")
    assert _count(codes, "SAFE905") == 1, codes
    assert _count(codes, "SAFE907") == 1, codes


# ---------------------------------------------------------------------------
# Laravel (PHP)
# ---------------------------------------------------------------------------


def test_laravel_mass_assignment() -> None:
    """Eloquent ``$guarded = []`` fires SAFE906 once; ``$fillable`` is clean."""
    codes = _codes(_php_config("laravel"), "laravel/Item.php")
    assert _count(codes, "SAFE906") == 1, codes


def test_laravel_unvalidated_request() -> None:
    """``$request->all()`` fires SAFE907 once; the ``validate()`` method is clean."""
    codes = _codes(_php_config("laravel"), "laravel/ItemController.php")
    assert _count(codes, "SAFE907") == 1, codes


def test_laravel_config_debug() -> None:
    """``'debug' => true`` in a Laravel config array fires SAFE905 once."""
    codes = _codes(_php_config("laravel"), "laravel/config.php")
    assert _count(codes, "SAFE905") == 1, codes


# ---------------------------------------------------------------------------
# Preset gating: SAFE905-907 stay silent under the vanilla baseline
# ---------------------------------------------------------------------------


def test_framework_rules_disabled_under_vanilla_python() -> None:
    """None of SAFE905-907 fire on the Python fixtures under the vanilla preset."""
    cfg = _python_config("vanilla")
    all_codes: list[str] = []
    for fixture in ("django/settings.py", "django/forms.py", "django/views.py", "flask/app.py", "fastapi/main.py"):
        all_codes.extend(_codes(cfg, fixture))
    nine_hundred = [c for c in all_codes if c in ("SAFE905", "SAFE906", "SAFE907")]
    assert nine_hundred == [], f"vanilla Python preset must not fire SAFE905-907, got {nine_hundred}"


def test_framework_rules_disabled_under_vanilla_php() -> None:
    """None of SAFE905-907 fire on the Laravel fixtures under the vanilla preset."""
    cfg = _php_config("vanilla")
    all_codes: list[str] = []
    for fixture in ("laravel/Item.php", "laravel/ItemController.php", "laravel/config.php"):
        all_codes.extend(_codes(cfg, fixture))
    nine_hundred = [c for c in all_codes if c in ("SAFE905", "SAFE906", "SAFE907")]
    assert nine_hundred == [], f"vanilla PHP preset must not fire SAFE905-907, got {nine_hundred}"


# ---------------------------------------------------------------------------
# Pydantic composes on top of a framework preset
# ---------------------------------------------------------------------------


def test_pydantic_enables_mass_assignment_under_fastapi() -> None:
    """``pydantic = true`` end-to-end: SAFE906 fires on ``extra = "allow"`` under FastAPI.

    The FastAPI preset alone does NOT enable mass_assignment, so the same
    fixture is clean without ``pydantic = true`` - proving the composable
    toggle, not just the config flag, drives the detection.
    """
    with_pydantic = _codes(_python_config("fastapi", pydantic=True), "fastapi/schemas.py")
    without_pydantic = _codes(_python_config("fastapi", pydantic=False), "fastapi/schemas.py")
    assert _count(with_pydantic, "SAFE906") == 1, with_pydantic
    assert _count(without_pydantic, "SAFE906") == 0, without_pydantic
    # The composable toggle also adds the validation-skipping constructors to
    # the SAFE801 sink list (used when the user opts into tainted_sink).
    assert "model_construct" in _python_config("fastapi", pydantic=True)["rules"]["tainted_sink"]["sinks"]
