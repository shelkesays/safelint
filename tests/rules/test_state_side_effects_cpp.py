"""State / side-effect rules on C++ files: SAFE302, SAFE303 / SAFE304, SAFE309.

C++-specific behaviour:

* SAFE302 (global_mutation) descends into ``namespace_definition`` bodies so a
  namespace-scoped global fires, not just translation-unit-scope ones.
* SAFE303 / SAFE304 (side effects) reuse C's I/O-primitive list (``printf`` /
  ``fopen`` / ...); ``std::cout`` stream I/O is a ``<<`` operator, not a call,
  so it is a documented non-catch.
* SAFE309 (dynamic_code_execution, opt-in) flags ``dlopen`` / ``dlsym``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _codes(src: str, tmp_path: Path, enable: list[str] | None = None) -> set[str]:
    """Return violation codes for *src* written as a ``.cpp`` file."""
    sample = tmp_path / "sample.cpp"
    sample.write_text(src, encoding="utf-8")
    rules = {r: {"enabled": True} for r in (enable or [])}
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": rules}))
    return {v.code for v in engine.check_file(str(sample)).violations}


def test_cpp_file_scope_global_fires_safe302(tmp_path: Path) -> None:
    """A file-scope mutable global fires SAFE302."""
    assert "SAFE302" in _codes("int counter = 0;\n", tmp_path)


def test_cpp_namespace_scope_global_fires_safe302(tmp_path: Path) -> None:
    """A namespace-scoped mutable global fires SAFE302 (the namespace descent)."""
    assert "SAFE302" in _codes("namespace app {\n    int state = 1;\n}\n", tmp_path)


def test_cpp_const_global_is_clean_for_safe302(tmp_path: Path) -> None:
    """A ``const`` file-scope global is immutable - no SAFE302."""
    assert "SAFE302" not in _codes("const int kMax = 10;\n", tmp_path)


def test_cpp_printf_in_pure_named_function_fires_safe304(tmp_path: Path) -> None:
    """A ``printf`` call inside a function fires SAFE304 (I/O in a would-be-pure function)."""
    assert "SAFE304" in _codes('void render() {\n    printf("x");\n}\n', tmp_path)


def test_cpp_qualified_system_call_reports_via_call_name(tmp_path: Path) -> None:
    """A ``std::printf`` qualified call resolves to ``printf`` and fires SAFE304."""
    assert "SAFE304" in _codes('void render() {\n    std::printf("x");\n}\n', tmp_path)


def test_cpp_no_io_is_clean_for_safe304(tmp_path: Path) -> None:
    """A pure computation is clean for SAFE304."""
    assert "SAFE304" not in _codes("int add(int a, int b) {\n    return a + b;\n}\n", tmp_path)


def test_cpp_dlopen_fires_safe309_when_enabled(tmp_path: Path) -> None:
    """``dlopen`` fires SAFE309 once dynamic_code_execution is enabled."""
    assert "SAFE309" in _codes('void f() {\n    dlopen("lib.so", 0);\n}\n', tmp_path, enable=["dynamic_code_execution"])


def test_cpp_safe309_silent_by_default(tmp_path: Path) -> None:
    """SAFE309 is opt-in: ``dlopen`` is silent without the override."""
    assert "SAFE309" not in _codes('void f() {\n    dlopen("lib.so", 0);\n}\n', tmp_path)
