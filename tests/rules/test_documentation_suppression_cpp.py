"""Documentation / suppression / test-coverage rules on C++ files.

* SAFE601 ``missing_assertions`` - the literal ``assert(...)`` macro.
* SAFE603 ``blanket_suppression`` - clang-tidy's bare ``// NOLINT`` family
  (C++ reuses C's detector).
* SAFE701 ``test_existence`` - a C++ source with no paired ``<stem>_test.cpp``.

All three are opt-in, so each test enables its rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _codes(filename: str, src: str, tmp_path: Path, overrides: dict | None = None) -> set[str]:
    """Return violation codes for *src* written as *filename*."""
    sample = tmp_path / filename
    sample.write_text(src, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides or {}))
    return {v.code for v in engine.check_file(str(sample)).violations}


# --- SAFE601 missing_assertions (opt-in) --------------------------------------

_ASSERT_ON = {"rules": {"missing_assertions": {"enabled": True, "min_assertions": 1}}}


def test_cpp_function_without_assert_fires_safe601(tmp_path: Path) -> None:
    """A function with no ``assert`` fires SAFE601 when enabled."""
    assert "SAFE601" in _codes("risky.cpp", "int risky(int x) {\n    return 100 / x;\n}\n", tmp_path, _ASSERT_ON)


def test_cpp_function_with_assert_is_clean_for_safe601(tmp_path: Path) -> None:
    """The literal ``assert(...)`` macro satisfies the rule."""
    assert "SAFE601" not in _codes("ok.cpp", "int ok(int x) {\n    assert(x != 0);\n    return 100 / x;\n}\n", tmp_path, _ASSERT_ON)


# --- SAFE603 blanket_suppression (opt-in) -------------------------------------

_SUPPRESS_ON = {"rules": {"blanket_suppression": {"enabled": True}}}


def test_cpp_bare_nolint_fires_safe603(tmp_path: Path) -> None:
    """A bare clang-tidy ``// NOLINT`` fires SAFE603."""
    assert "SAFE603" in _codes("n.cpp", "int f() { return bad(); } // NOLINT\n", tmp_path, _SUPPRESS_ON)


def test_cpp_scoped_nolint_is_clean_for_safe603(tmp_path: Path) -> None:
    """A scoped ``// NOLINT(check)`` targets a specific check and is not blanket."""
    assert "SAFE603" not in _codes("n.cpp", "int f() { return bad(); } // NOLINT(bugprone-foo)\n", tmp_path, _SUPPRESS_ON)


# --- SAFE701 test_existence (opt-in) ------------------------------------------


def test_cpp_source_without_test_fires_safe701(tmp_path: Path) -> None:
    """A C++ source with no paired test file fires SAFE701 when enabled."""
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    overrides = {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(test_dir)]}}}
    assert "SAFE701" in _codes("widget.cpp", "int widget() { return 1; }\n", tmp_path, overrides)


def test_cpp_source_with_sibling_test_is_clean_for_safe701(tmp_path: Path) -> None:
    """A ``<stem>_test.cpp`` under the configured test dir clears SAFE701."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "widget_test.cpp").write_text("void t() { assert(1); }\n", encoding="utf-8")
    overrides = {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(tmp_path / "tests")]}}}
    assert "SAFE701" not in _codes("widget.cpp", "int widget() { return 1; }\n", tmp_path, overrides)


def test_cpp_cc_source_with_cc_test_is_clean_for_safe701(tmp_path: Path) -> None:
    """A ``.cc`` source paired with ``<stem>_test.cc`` clears SAFE701 (not just ``.cpp``)."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "widget_test.cc").write_text("void t() { assert(1); }\n", encoding="utf-8")
    overrides = {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(tmp_path / "tests")]}}}
    assert "SAFE701" not in _codes("widget.cc", "int widget() { return 1; }\n", tmp_path, overrides)
