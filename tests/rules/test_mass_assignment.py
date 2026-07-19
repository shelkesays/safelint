"""Tests for SAFE906 mass_assignment (Django / Pydantic / Laravel)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path


def _codes(src: Path) -> list[str]:
    cfg = deep_merge(DEFAULTS, {"rules": {"mass_assignment": {"enabled": True}}})
    return [v.code for v in SafetyEngine(cfg).check_file(str(src)).violations if v.code == "SAFE906"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_django_modelform_all_fields(tmp_path: Path) -> None:
    """``fields = "__all__"`` fires."""
    src = _write(tmp_path, "forms.py", 'class Meta:\n    fields = "__all__"\n')
    assert _codes(src) == ["SAFE906"]


def test_pydantic_extra_allow_class_config(tmp_path: Path) -> None:
    """``class Config: extra = "allow"`` fires (Pydantic v1)."""
    src = _write(tmp_path, "models.py", 'class Config:\n    extra = "allow"\n')
    assert _codes(src) == ["SAFE906"]


def test_pydantic_extra_allow_configdict_and_dict(tmp_path: Path) -> None:
    """``ConfigDict(extra="allow")`` and ``{"extra": "allow"}`` both fire (Pydantic v2)."""
    src = _write(tmp_path, "models.py", 'a = ConfigDict(extra="allow")\nb = {"extra": "allow"}\n')
    assert _codes(src) == ["SAFE906", "SAFE906"]


def test_django_explicit_fields_clean(tmp_path: Path) -> None:
    """An explicit ``fields`` list and ``extra = "forbid"`` do not fire."""
    src = _write(tmp_path, "forms.py", 'fields = ["a", "b"]\nextra = "forbid"\n')
    assert _codes(src) == []


def test_laravel_guarded_empty(tmp_path: Path) -> None:
    """Eloquent ``$guarded = []`` fires."""
    src = _write(tmp_path, "Model.php", "<?php class M { protected $guarded = []; } ?>")
    assert _codes(src) == ["SAFE906"]


def test_laravel_fillable_clean(tmp_path: Path) -> None:
    """``$fillable`` (allow-list) and a non-empty ``$guarded`` do not fire."""
    src = _write(tmp_path, "Model.php", "<?php class M { protected $fillable = ['a']; protected $guarded = ['x']; } ?>")
    assert _codes(src) == []


def test_disabled_by_default(tmp_path: Path) -> None:
    """At the default (disabled) nothing fires."""
    src = _write(tmp_path, "forms.py", 'class Meta:\n    fields = "__all__"\n')
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE906"] == []
