"""Function-shape rules (SAFE101-105) on C++ files.

C++-specific cases beyond C's:

* ``FUNCTION_TYPES`` adds ``lambda_expression`` alongside ``function_definition``.
* SAFE102 counts ``try_statement`` toward nesting depth.
* SAFE105 resolves the enclosing name from a ``field_identifier`` (in-class
  method) or ``qualified_identifier`` (``S::m`` out-of-line), and detects a
  ``this->m()`` self-call - neither exists in C.
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


def test_cpp_long_function_fires_safe101(tmp_path: Path) -> None:
    """A function over the 60-line cap fires SAFE101."""
    body = "\n".join(f"    x += {i};" for i in range(70))
    assert "SAFE101" in _codes(f"int longFn() {{\n    int x = 0;\n{body}\n    return x;\n}}\n", tmp_path)


def test_cpp_short_function_is_clean_for_safe101(tmp_path: Path) -> None:
    """A small function does not fire SAFE101."""
    assert "SAFE101" not in _codes("int add(int a, int b) { return a + b; }\n", tmp_path)


def test_cpp_try_block_counts_toward_nesting_safe102(tmp_path: Path) -> None:
    """A ``try`` inside an ``if`` inside a ``for`` exceeds the depth-2 cap (SAFE102)."""
    src = "void f() {\n    for (int i = 0; i < 3; i++) {\n        if (i) {\n            try { g(); } catch (...) { h(); }\n        }\n    }\n}\n"
    assert "SAFE102" in _codes(src, tmp_path)


def test_cpp_shallow_nesting_is_clean_for_safe102(tmp_path: Path) -> None:
    """Nesting within the depth-2 cap does not fire SAFE102."""
    assert "SAFE102" not in _codes("void f() {\n    if (a) {\n        g();\n    }\n}\n", tmp_path)


def test_cpp_too_many_arguments_fires_safe103(tmp_path: Path) -> None:
    """A function with more than the default max args (7) fires SAFE103."""
    assert "SAFE103" in _codes("void f(int a, int b, int c, int d, int e, int g, int h, int i) {}\n", tmp_path)


def test_cpp_high_complexity_function_fires_safe104(tmp_path: Path) -> None:
    """Cyclomatic complexity over the default 10 fires SAFE104; a ``catch`` clause counts."""
    branches = "\n".join(f"    if (x == {i}) return {i};" for i in range(10))
    src = f"int classify(int x) {{\n{branches}\n    try {{ risky(); }} catch (const std::exception& e) {{ return -1; }}\n    return 0;\n}}\n"
    assert "SAFE104" in _codes(src, tmp_path)


def test_cpp_simple_function_is_clean_for_safe104(tmp_path: Path) -> None:
    """A low-complexity function does not fire SAFE104."""
    assert "SAFE104" not in _codes("int add(int a, int b) {\n    return a + b;\n}\n", tmp_path)


def test_cpp_free_function_direct_recursion_fires_safe105(tmp_path: Path) -> None:
    """A free function calling itself by bare name fires SAFE105."""
    assert "SAFE105" in _codes("int fact(int n) { return n * fact(n - 1); }\n", tmp_path)


def test_cpp_method_this_recursion_fires_safe105(tmp_path: Path) -> None:
    """A method calling ``this->m()`` is detected as self-recursion (SAFE105)."""
    assert "SAFE105" in _codes("struct S {\n    int m() { return this->m(); }\n};\n", tmp_path)


def test_cpp_out_of_line_method_recursion_fires_safe105(tmp_path: Path) -> None:
    """An out-of-line ``S::m`` definition that calls itself fires SAFE105."""
    assert "SAFE105" in _codes("struct S { int m(); };\nint S::m() { return m(); }\n", tmp_path)


def test_cpp_non_recursive_is_clean_for_safe105(tmp_path: Path) -> None:
    """A method that calls a different function is clean for SAFE105."""
    assert "SAFE105" not in _codes("struct S {\n    int m() { return helper(); }\n};\n", tmp_path)


def test_cpp_namespace_qualified_self_call_fires_safe105(tmp_path: Path) -> None:
    """A namespace-qualified self-call (`ns::f()` inside `f`) is detected as recursion."""
    assert "SAFE105" in _codes("namespace ns {\n    void f() { ns::f(); }\n}\n", tmp_path)


def test_cpp_nested_range_for_loops_fire_safe102(tmp_path: Path) -> None:
    """Three nested range-based `for (auto x : v)` loops exceed the depth-2 cap (SAFE102)."""
    src = "void f() {\n    for (auto a : v) {\n        for (auto b : v) {\n            for (auto c : v) { g(a, b, c); }\n        }\n    }\n}\n"
    assert "SAFE102" in _codes(src, tmp_path)


def test_cpp_many_range_for_loops_fire_safe104(tmp_path: Path) -> None:
    """A function dominated by range-based for loops still trips the complexity cap (SAFE104)."""
    loops = "".join(f"    for (auto x{i} : v) {{ g(x{i}); }}\n" for i in range(12))
    assert "SAFE104" in _codes(f"void f() {{\n{loops}}}\n", tmp_path)


def test_cpp_over_parameterised_lambda_fires_safe103(tmp_path: Path) -> None:
    """A lambda with more than the default max args (7) fires SAFE103."""
    assert "SAFE103" in _codes("auto f = [](int a, int b, int c, int d, int e, int g, int h, int i) { return 0; };\n", tmp_path)


def test_cpp_small_lambda_is_clean_for_safe103(tmp_path: Path) -> None:
    """A two-parameter comparator lambda does not fire SAFE103."""
    assert "SAFE103" not in _codes("auto cmp = [](int a, int b) { return a < b; };\n", tmp_path)
