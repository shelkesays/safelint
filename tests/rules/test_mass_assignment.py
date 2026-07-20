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


def test_pydantic_extra_allow_configdict_and_model_config_dict(tmp_path: Path) -> None:
    """``ConfigDict(extra="allow")`` and ``model_config = {"extra": "allow"}`` both fire (Pydantic v2)."""
    src = _write(tmp_path, "models.py", 'a = ConfigDict(extra="allow")\nmodel_config = {"extra": "allow"}\n')
    assert _codes(src) == ["SAFE906", "SAFE906"]


def test_pydantic_extra_allow_outside_config_context_is_clean(tmp_path: Path) -> None:
    """``extra="allow"`` on an unrelated call / bare dict / non-Config class does not fire."""
    src = _write(
        tmp_path,
        "models.py",
        'foo(extra="allow")\nb = {"extra": "allow"}\nclass Foo:\n    extra = "allow"\n',
    )
    assert _codes(src) == []


def test_attribute_lhs_and_non_config_key_are_clean(tmp_path: Path) -> None:
    """An attribute-target assignment and a non-``extra`` ConfigDict key do not fire."""
    src = _write(tmp_path, "models.py", 'x.fields = "__all__"\na = ConfigDict(frozen=True)\n')
    assert _codes(src) == []


def test_unassigned_extra_allow_dict_is_clean(tmp_path: Path) -> None:
    """A ``{"extra": "allow"}`` dict not bound to ``model_config`` (returned) does not fire."""
    src = _write(tmp_path, "models.py", 'def build():\n    return {"extra": "allow"}\n')
    assert _codes(src) == []


def test_django_explicit_fields_clean(tmp_path: Path) -> None:
    """An explicit ``fields`` list and ``extra = "forbid"`` do not fire."""
    src = _write(tmp_path, "forms.py", 'fields = ["a", "b"]\nextra = "forbid"\n')
    assert _codes(src) == []


def test_python_unrelated_all_string_is_clean(tmp_path: Path) -> None:
    """An ``= "__all__"`` on a name other than ``fields`` (and non-``extra``) does not fire."""
    src = _write(tmp_path, "forms.py", 'columns = "__all__"\nmode = "allow"\n')
    assert _codes(src) == []


def test_python_module_level_fields_and_extra_are_clean(tmp_path: Path) -> None:
    """Bare module-level ``fields = "__all__"`` / ``extra = "allow"`` (no class) do not fire."""
    src = _write(tmp_path, "consts.py", 'fields = "__all__"\nextra = "allow"\n')
    assert _codes(src) == []


def test_laravel_guarded_empty(tmp_path: Path) -> None:
    """Eloquent ``$guarded = []`` fires."""
    src = _write(tmp_path, "Model.php", "<?php class M { protected $guarded = []; } ?>")
    assert _codes(src) == ["SAFE906"]


def test_laravel_fillable_clean(tmp_path: Path) -> None:
    """``$fillable`` (allow-list) and a non-empty ``$guarded`` do not fire."""
    src = _write(tmp_path, "Model.php", "<?php class M { protected $fillable = ['a']; protected $guarded = ['x']; } ?>")
    assert _codes(src) == []


def test_laravel_guarded_declared_without_value_clean(tmp_path: Path) -> None:
    """A ``$guarded`` property with no initialiser does not fire (no empty-array value)."""
    src = _write(tmp_path, "Model.php", "<?php class M { protected $guarded; } ?>")
    assert _codes(src) == []


def test_disabled_by_default(tmp_path: Path) -> None:
    """At the default (disabled) nothing fires."""
    src = _write(tmp_path, "forms.py", 'class Meta:\n    fields = "__all__"\n')
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE906"] == []
