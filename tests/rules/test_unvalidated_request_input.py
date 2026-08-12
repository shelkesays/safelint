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


def _codes_with(src: Path, rule_overrides: dict) -> list[str]:
    """SAFE907 codes with extra ``unvalidated_request_input`` config merged in."""
    cfg = deep_merge(DEFAULTS, {"rules": {"unvalidated_request_input": {"enabled": True, **rule_overrides}}})
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


def test_python_non_request_base_data_is_clean(tmp_path: Path) -> None:
    """A ``.data`` read whose base is not a ``request`` (a call result) does not fire."""
    src = _write(tmp_path, "views.py", "def one():\n    return save(get_payload().data)\n")
    assert _codes(src) == []


def test_python_flask_request_json_flagged(tmp_path: Path) -> None:
    """Flask ``request.json`` consumed whole with no schema fires."""
    src = _write(tmp_path, "app.py", "def handler(request):\n    return save(request.json)\n")
    assert _codes(src) == ["SAFE907"]


def test_python_fastapi_await_request_json_flagged(tmp_path: Path) -> None:
    """FastAPI ``await request.json()`` bound whole with no validation fires."""
    src = _write(tmp_path, "main.py", "async def create(request):\n    return Item(**await request.json())\n")
    assert _codes(src) == ["SAFE907"]


def test_python_serializer_name_without_validation_still_flagged(tmp_path: Path) -> None:
    """A bare ``Serializer`` name (no ``is_valid()`` call) does NOT clear the finding."""
    src = _write(tmp_path, "views.py", "def create(request):\n    s = FooSerializer\n    return Model(**request.data)\n")
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


def test_php_builtin_validate_only_clears_for_request_receiver(tmp_path: Path) -> None:
    """The built-in ``validate`` clears ONLY as ``$request->validate(...)``.

    An unrelated ``$other->validate(...)`` or static ``Validator::validate(...)``
    does not validate the request, so it must not suppress SAFE907 (a security
    false negative). Configured project validators keep their any-call-form match.
    """
    other = _write(tmp_path, "A.php", "<?php class A { function store($request){ $other->validate($x); return M::create($request->all()); } } ?>")
    assert _codes(other) == ["SAFE907"]
    static = _write(tmp_path, "B.php", "<?php class B { function store($request){ Validator::validate($x); return M::create($request->all()); } } ?>")
    assert _codes(static) == ["SAFE907"]
    # A merely request-*suffixed* variable is a different object - its validate()
    # must not clear the real $request read (case-sensitive suffix false negative).
    suffixed = _write(tmp_path, "C.php", "<?php class C { function store($request){ $otherrequest->validate($x); return M::create($request->all()); } } ?>")
    assert _codes(suffixed) == ["SAFE907"]
    # An arbitrary object's ``request`` property (``$foo->request``) is not the
    # framework request either, so its validate() must not clear the read.
    prop = _write(tmp_path, "F.php", "<?php class F { function store($request){ $foo->request->validate($x); return M::create($request->all()); } } ?>")
    assert _codes(prop) == ["SAFE907"]
    # The genuine request receivers still clear.
    ok = _write(tmp_path, "D.php", "<?php class D { function store($request){ $request->validate([]); return M::create($request->all()); } } ?>")
    assert _codes(ok) == []
    this_req = _write(tmp_path, "E.php", "<?php class E { function store(){ $this->request->validate([]); return M::create($this->request->all()); } } ?>")
    assert _codes(this_req) == []


def test_disabled_by_default(tmp_path: Path) -> None:
    """At the default (disabled) nothing fires."""
    src = _write(tmp_path, "views.py", "def create(request):\n    return Model(**request.data)\n")
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE907"] == []


# ---------------------------------------------------------------------------
# request_validators: extensible project validator names (2.12.0)
# ---------------------------------------------------------------------------


def test_python_project_validator_clears(tmp_path: Path) -> None:
    """A project validator named in ``request_validators`` clears the read."""
    src = _write(tmp_path, "api.py", "def export(request):\n    validate_export_request(request.data)\n    return Model(**request.data)\n")
    assert _codes(src) == ["SAFE907"]  # not cleared with default (empty) list
    assert _codes_with(src, {"request_validators": ["validate_export_request"]}) == []


def test_python_unlisted_helper_still_fires(tmp_path: Path) -> None:
    """A helper NOT in ``request_validators`` does not clear the read."""
    src = _write(tmp_path, "api.py", "def export(request):\n    massage(request.data)\n    return Model(**request.data)\n")
    assert _codes_with(src, {"request_validators": ["validate_export_request"]}) == ["SAFE907"]


def test_php_project_validator_clears(tmp_path: Path) -> None:
    """A Laravel project validator named in ``request_validators_php`` clears the read."""
    src = _write(tmp_path, "C.php", "<?php class C { function store($request){ $request->allowlist(); return M::create($request->all()); } } ?>")
    assert _codes(src) == ["SAFE907"]
    assert _codes_with(src, {"request_validators_php": ["allowlist"]}) == []


def test_php_global_function_validator_clears(tmp_path: Path) -> None:
    """A GLOBAL-function validator (not a ``$request->`` member call) also clears the read.

    ``call_name`` resolves the bareword across all PHP call forms, so a configured
    validator invoked as a plain function (``allowlist(...)``), static
    (``Validator::validate(...)``), or nullsafe call must be honoured - not only
    the ``$request->validate(...)`` member form.
    """
    src = _write(tmp_path, "C.php", "<?php class C { function store($request){ allowlist($request->all()); return M::create($request->all()); } } ?>")
    assert _codes(src) == ["SAFE907"]
    assert _codes_with(src, {"request_validators_php": ["allowlist"]}) == []


def test_php_static_call_validator_clears(tmp_path: Path) -> None:
    """A configured validator invoked as a STATIC call (``Validator::allowlist(...)``) clears.

    Covers the ``scoped_call_expression`` branch of ``CALL_TYPES`` independently.
    """
    src = _write(tmp_path, "C.php", "<?php class C { function store($request){ Validator::allowlist($request); return M::create($request->all()); } } ?>")
    assert _codes(src) == ["SAFE907"]
    assert _codes_with(src, {"request_validators_php": ["allowlist"]}) == []


def test_php_nullsafe_call_validator_clears(tmp_path: Path) -> None:
    """A configured validator invoked as a NULLSAFE call (``$request?->allowlist(...)``) clears.

    Covers the ``nullsafe_member_call_expression`` branch of ``CALL_TYPES``.
    """
    src = _write(tmp_path, "C.php", "<?php class C { function store($request){ $request?->allowlist(); return M::create($request->all()); } } ?>")
    assert _codes(src) == ["SAFE907"]
    assert _codes_with(src, {"request_validators_php": ["allowlist"]}) == []


def test_request_validators_scalar_typo_raises(tmp_path: Path) -> None:
    """A bare-string typo for ``request_validators`` fails loud."""
    import pytest  # noqa: PLC0415

    src = _write(tmp_path, "api.py", "def export(request):\n    return Model(**request.data)\n")
    with pytest.raises(TypeError, match="request_validators"):
        _codes_with(src, {"request_validators": "validate_export_request"})
