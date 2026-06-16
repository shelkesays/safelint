"""Tests for the state / side-effect rules (SAFE302/303/304/309) on Go files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_go_package_var_fires_safe302(tmp_path: Path) -> None:
    """A package-level ``var`` is shared mutable state (SAFE302), even a sentinel error."""
    sample = tmp_path / "state.go"
    sample.write_text(
        'package main\nvar counter int\nvar ErrNF = errors.New("nf")\nconst Limit = 10\n',
        encoding="utf-8",
    )
    safe302 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302"]
    names = " ".join(v.message for v in safe302)
    assert len(safe302) == 2
    assert "counter" in names
    assert "ErrNF" in names  # sentinel errors are flagged too
    assert "Limit" not in names  # const is clean


def test_go_block_local_var_is_clean(tmp_path: Path) -> None:
    """Block-scoped ``var`` / ``:=`` inside a function is a local, not shared state."""
    sample = tmp_path / "local.go"
    sample.write_text("package main\nfunc f() {\n\tvar x int\n\ty := 1\n\t_ = x\n\t_ = y\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE302" for v in _engine().check_file(str(sample)).violations)


def test_go_grouped_var_block_fires_per_name(tmp_path: Path) -> None:
    """A grouped ``var ( a; b )`` block fires once per declared name."""
    sample = tmp_path / "grouped.go"
    sample.write_text("package main\nvar (\n\ta int\n\tb, c string\n)\n", encoding="utf-8")
    safe302 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302"]
    assert len(safe302) == 3


def test_go_pure_named_function_doing_io_fires_safe303(tmp_path: Path) -> None:
    """A ``get``-prefixed function that performs I/O fires SAFE303."""
    sample = tmp_path / "hidden.go"
    sample.write_text('package main\nfunc getName() {\n\tfmt.Println("io")\n}\n', encoding="utf-8")
    cfg = {"rules": {"side_effects_hidden": {"pure_prefixes": ["get"]}}}
    assert any(v.code == "SAFE303" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_io_call_fires_safe304(tmp_path: Path) -> None:
    """A non-I/O-named function calling ``fmt.Println`` fires SAFE304."""
    sample = tmp_path / "side.go"
    sample.write_text('package main\nfunc compute() {\n\tfmt.Println("x")\n}\n', encoding="utf-8")
    safe304 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE304"]
    assert len(safe304) == 1
    assert "Println" in safe304[0].message


def test_go_pure_function_is_clean(tmp_path: Path) -> None:
    """A function with no I/O calls fires neither SAFE303 nor SAFE304."""
    sample = tmp_path / "pure.go"
    sample.write_text("package main\nfunc add(a, b int) int {\n\treturn a + b\n}\n", encoding="utf-8")
    out = _engine().check_file(str(sample)).violations
    assert not any(v.code in ("SAFE303", "SAFE304") for v in out)


def test_go_reflection_fires_safe309_when_enabled(tmp_path: Path) -> None:
    """``v.MethodByName(...)`` fires SAFE309 (off by default, enabled here)."""
    sample = tmp_path / "reflect.go"
    sample.write_text('package main\nfunc f(v R) {\n\tv.MethodByName("X")\n}\n', encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_no_reflection_is_clean(tmp_path: Path) -> None:
    """A function without reflection / plugin calls is clean for SAFE309."""
    sample = tmp_path / "noreflect.go"
    sample.write_text("package main\nfunc f() {\n\tg()\n}\n", encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert not any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)
