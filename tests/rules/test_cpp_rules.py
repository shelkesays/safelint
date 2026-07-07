"""C++-only rules: SAFE315 raw_new_delete, SAFE316 dangerous_casts (both opt-in).

Also covers the C++ side of the widened SAFE313 (restricted_pointers): a smart
pointer (``std::unique_ptr<T>``) is a class template, not a ``pointer_declarator``,
so it never trips the raw multi-level-pointer check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules.cpp_rules import DangerousCastsRule, RawNewDeleteRule


def _codes(src: str, tmp_path: Path, enable: list[str] | None = None, config: dict | None = None) -> set[str]:
    """Return violation codes for *src* written as a ``.cpp`` file."""
    sample = tmp_path / "sample.cpp"
    sample.write_text(src, encoding="utf-8")
    rules = {r: {"enabled": True} for r in (enable or [])}
    rules.update(config or {})
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": rules}))
    return {v.code for v in engine.check_file(str(sample)).violations}


def test_cpp_opt_in_rules_are_silent_by_default(tmp_path: Path) -> None:
    """SAFE315 / SAFE316 are opt-in: source that would trip both reports neither by default."""
    src = "void f() {\n    int* a = new int(5);\n    delete a;\n    int* b = reinterpret_cast<int*>(a);\n}\n"
    codes = _codes(src, tmp_path)
    assert RawNewDeleteRule.code not in codes
    assert DangerousCastsRule.code not in codes


# --- SAFE315 raw_new_delete ---------------------------------------------------


def test_cpp_new_fires_safe315(tmp_path: Path) -> None:
    """A raw ``new`` fires SAFE315 when enabled."""
    assert "SAFE315" in _codes("void f() {\n    int* a = new int(5);\n}\n", tmp_path, enable=["raw_new_delete"])


def test_cpp_delete_fires_safe315(tmp_path: Path) -> None:
    """A raw ``delete`` fires SAFE315 when enabled."""
    assert "SAFE315" in _codes("void f(int* a) {\n    delete a;\n}\n", tmp_path, enable=["raw_new_delete"])


def test_cpp_new_inside_unique_ptr_still_fires_safe315(tmp_path: Path) -> None:
    """A raw ``new`` inside a ``unique_ptr<T>(new T)`` argument still fires."""
    assert "SAFE315" in _codes("void f() {\n    auto v = std::unique_ptr<int>(new int());\n}\n", tmp_path, enable=["raw_new_delete"])


def test_cpp_make_unique_is_clean_for_safe315(tmp_path: Path) -> None:
    """``std::make_unique`` contains no ``new`` expression - clean for SAFE315."""
    assert "SAFE315" not in _codes("void f() {\n    auto u = std::make_unique<int>(1);\n}\n", tmp_path, enable=["raw_new_delete"])


# --- SAFE316 dangerous_casts --------------------------------------------------


def test_cpp_reinterpret_cast_fires_safe316(tmp_path: Path) -> None:
    """``reinterpret_cast`` fires SAFE316 when enabled."""
    assert "SAFE316" in _codes("void f(void* p) {\n    int* a = reinterpret_cast<int*>(p);\n}\n", tmp_path, enable=["dangerous_casts"])


def test_cpp_const_cast_fires_safe316(tmp_path: Path) -> None:
    """``const_cast`` fires SAFE316 when enabled."""
    assert "SAFE316" in _codes("void f(const int* p) {\n    int* a = const_cast<int*>(p);\n}\n", tmp_path, enable=["dangerous_casts"])


def test_cpp_static_and_dynamic_cast_are_clean_for_safe316(tmp_path: Path) -> None:
    """``static_cast`` / ``dynamic_cast`` are compiler-checked - clean for SAFE316."""
    src = "void f(double d, Base* b) {\n    int i = static_cast<int>(d);\n    auto* p = dynamic_cast<Derived*>(b);\n}\n"
    assert "SAFE316" not in _codes(src, tmp_path, enable=["dangerous_casts"])


def test_cpp_plain_call_is_clean_for_safe316(tmp_path: Path) -> None:
    """A plain (non-template) function call is not a cast - clean for SAFE316."""
    assert "SAFE316" not in _codes("void f() {\n    helper(1, 2);\n}\n", tmp_path, enable=["dangerous_casts"])


def test_cpp_safe316_custom_cast_list_replaces_defaults(tmp_path: Path) -> None:
    """A custom ``dangerous_casts_cpp`` list wins: a listed cast fires, a default one no longer does."""
    config = {"dangerous_casts": {"enabled": True, "dangerous_casts_cpp": ["static_cast"]}}
    codes = _codes("void f(double d, void* p) {\n    int i = static_cast<int>(d);\n    int* a = reinterpret_cast<int*>(p);\n}\n", tmp_path, config=config)
    assert "SAFE316" in codes  # static_cast now flagged
    # reinterpret_cast is no longer in the list, so if only it were present it would not fire:
    only_reinterpret = _codes("void f(void* p) {\n    int* a = reinterpret_cast<int*>(p);\n}\n", tmp_path, config=config)
    assert "SAFE316" not in only_reinterpret


# --- SAFE313 restricted_pointers: C++ smart-pointer exemption -----------------


def test_cpp_smart_pointer_is_clean_for_safe313(tmp_path: Path) -> None:
    """A ``std::unique_ptr<T>`` is a class template, not a multi-level pointer - no SAFE313."""
    assert "SAFE313" not in _codes("void f() {\n    std::unique_ptr<int> p;\n}\n", tmp_path, enable=["restricted_pointers"])


def test_cpp_raw_double_pointer_fires_safe313(tmp_path: Path) -> None:
    """A raw ``int** pp`` (two pointer levels) still fires SAFE313 in C++."""
    assert "SAFE313" in _codes("int** pp;\n", tmp_path, enable=["restricted_pointers"])
