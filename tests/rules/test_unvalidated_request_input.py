"""Tests for SAFE907 unvalidated_request_input (Django / Flask / FastAPI / Laravel)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path


def _codes(src: Path) -> list[str]:
    cfg = deep_merge(DEFAULTS, {"rules": {"unvalidated_request_input": {"enabled": True}}})
    return [v.code for v in SafetyEngine(cfg).check_file(str(src)).violations if v.code == "SAFE907"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_python_raw_request_data_flagged(tmp_path: Path) -> None:
    """A view binding ``request.data`` whole with no validation fires once."""
    src = _write(tmp_path, "views.py", "def create(request):\n    return Model(**request.data)\n")
    assert _codes(src) == ["SAFE907"]


def test_python_validated_is_clean(tmp_path: Path) -> None:
    """A serializer with ``.is_valid()`` clears the function."""
    src = _write(
        tmp_path,
        "views.py",
        "def create(request):\n    s = FooSerializer(data=request.data)\n    s.is_valid()\n    return s\n",
    )
    assert _codes(src) == []


def test_python_targeted_field_access_is_clean(tmp_path: Path) -> None:
    """``request.POST.get('x')`` is a targeted read, not a whole-body consume."""
    src = _write(tmp_path, "views.py", "def one(request):\n    return request.POST.get('x')\n")
    assert _codes(src) == []


def test_python_flask_request_json_flagged(tmp_path: Path) -> None:
    """Flask ``request.json`` consumed whole with no schema fires."""
    src = _write(tmp_path, "app.py", "def handler(request):\n    return save(request.json)\n")
    assert _codes(src) == ["SAFE907"]


def test_python_self_request_data_flagged(tmp_path: Path) -> None:
    """A class-based view reading ``self.request.data`` whole fires (self.request base)."""
    src = _write(tmp_path, "views.py", "def post(self):\n    return Model(**self.request.data)\n")
    assert _codes(src) == ["SAFE907"]


def test_php_request_all_flagged(tmp_path: Path) -> None:
    """Laravel ``$request->all()`` with no ``validate`` fires."""
    src = _write(tmp_path, "C.php", "<?php class C { function store($request){ return M::create($request->all()); } } ?>")
    assert _codes(src) == ["SAFE907"]


def test_php_input_single_field_is_clean(tmp_path: Path) -> None:
    """``$request->input('name')`` is a targeted single-field read, not a bulk consume."""
    src = _write(tmp_path, "C.php", "<?php class C { function s($request){ return $request->input('name'); } } ?>")
    assert _codes(src) == []


def test_php_validated_is_clean(tmp_path: Path) -> None:
    """A ``$request->validate([...])`` call clears the method."""
    src = _write(
        tmp_path,
        "C.php",
        "<?php class C { function store($request){ $request->validate([]); return $request->all(); } } ?>",
    )
    assert _codes(src) == []


def test_disabled_by_default(tmp_path: Path) -> None:
    """At the default (disabled) nothing fires."""
    src = _write(tmp_path, "views.py", "def create(request):\n    return Model(**request.data)\n")
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE907"] == []
