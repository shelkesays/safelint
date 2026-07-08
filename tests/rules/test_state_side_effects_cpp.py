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


def test_cpp_constexpr_global_is_clean_for_safe302(tmp_path: Path) -> None:
    """A ``constexpr`` file-scope constant is immutable - no SAFE302."""
    assert "SAFE302" not in _codes("constexpr int kMax = 100;\n", tmp_path)


def test_cpp_extern_c_block_global_fires_safe302(tmp_path: Path) -> None:
    """A mutable global inside an ``extern \"C\"`` block is still shared state (SAFE302)."""
    assert "SAFE302" in _codes('extern "C" {\n    int shared_counter = 0;\n}\n', tmp_path)


def test_cpp_static_data_member_fires_safe302(tmp_path: Path) -> None:
    """A ``static`` class data member is translation-unit-shared mutable state (SAFE302)."""
    assert "SAFE302" in _codes("struct S {\n    static int counter;\n};\n", tmp_path)


def test_cpp_non_static_field_is_clean_for_safe302(tmp_path: Path) -> None:
    """A non-static field is per-instance state, not a global - no SAFE302."""
    assert "SAFE302" not in _codes("struct S {\n    int instance_value;\n};\n", tmp_path)


def test_cpp_static_const_member_is_clean_for_safe302(tmp_path: Path) -> None:
    """A ``static const`` member is immutable - no SAFE302."""
    assert "SAFE302" not in _codes("struct S {\n    static const int K = 1;\n};\n", tmp_path)


def test_cpp_static_constinit_member_fires_safe302(tmp_path: Path) -> None:
    """``constinit`` only fixes init timing - the variable is still mutable, so SAFE302 fires."""
    assert "SAFE302" in _codes("struct S {\n    static constinit int counter = 0;\n};\n", tmp_path)


def test_cpp_multi_declarator_static_member_fires_once_per_name(tmp_path: Path) -> None:
    """`static int a, b;` declares two shared members - both fire SAFE302."""
    sample = tmp_path / "sample.cpp"
    sample.write_text("struct S {\n    static int a, b;\n};\n", encoding="utf-8")
    from safelint.core.engine import SafetyEngine  # noqa: PLC0415

    safe302 = [v for v in SafetyEngine(DEFAULTS).check_file(str(sample)).violations if v.code == "SAFE302"]
    assert len(safe302) == 2


def test_cpp_static_function_pointer_member_fires_safe302(tmp_path: Path) -> None:
    """A `static` function-pointer data member (`static int (*fp)(int);`) is mutable shared state (SAFE302)."""
    assert "SAFE302" in _codes("struct S {\n    static int (*fp)(int);\n};\n", tmp_path)


def test_cpp_static_member_function_declaration_is_not_flagged(tmp_path: Path) -> None:
    """A `static` member *function* declaration is not data - it must not fire SAFE302."""
    assert "SAFE302" not in _codes("struct S {\n    static void m(int x);\n};\n", tmp_path)


def test_cpp_static_member_initializer_member_access_is_not_flagged(tmp_path: Path) -> None:
    """A member-access in a static member's initialiser / array size must not be reported as a member.

    `static int a = obj.field;` declares only `a`; the initialiser's `field`
    (and an array-size member like `arr[obj.n]`) must not produce a bogus SAFE302.
    """
    sample = tmp_path / "sample.cpp"
    sample.write_text("struct S {\n    static int a = obj.field;\n    static int arr[obj.n];\n};\n", encoding="utf-8")
    from safelint.core.engine import SafetyEngine  # noqa: PLC0415

    flagged = {v.message.split('"')[1] for v in SafetyEngine(DEFAULTS).check_file(str(sample)).violations if v.code == "SAFE302"}
    assert flagged == {"a", "arr"}


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
