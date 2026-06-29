"""Tests for the documentation / suppression / test-coverage rules on C files.

Covers the C dispatch for:

* SAFE601 ``missing_assertions`` - the literal ``assert(...)`` macro.
* SAFE603 ``blanket_suppression`` - clang-tidy's bare ``// NOLINT`` family
  (scoped ``// NOLINT(check)`` is clean).
* SAFE701 / SAFE702 ``test_existence`` / ``test_coupling`` - the
  ``<stem>_test.c`` / ``test_<stem>.c`` filename conventions.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _codes(filename: str, src: str, tmp_path: Path, overrides: dict | None = None) -> set[str]:
    sample = tmp_path / filename
    sample.write_text(src, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides or {}))
    return {v.code for v in engine.check_file(str(sample)).violations}


@contextmanager
def _cd(path: Path) -> Iterator[None]:
    """Change cwd inside the block so the rule's ``Path("tests")`` resolves correctly."""
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


# --- SAFE601 missing_assertions (opt-in) ---------------------------------------

_ASSERT_ON = {"rules": {"missing_assertions": {"enabled": True, "min_assertions": 1}}}


def test_c_function_without_assert_fires_safe601(tmp_path: Path) -> None:
    """A function with no ``assert`` fires SAFE601 when the rule is enabled."""
    assert "SAFE601" in _codes("risky.c", "int risky(int x) {\n    return 100 / x;\n}\n", tmp_path, _ASSERT_ON)


def test_c_function_with_assert_is_clean_for_safe601(tmp_path: Path) -> None:
    """The literal ``assert(...)`` macro satisfies the rule."""
    assert "SAFE601" not in _codes("ok.c", "int ok(int x) {\n    assert(x != 0);\n    return 100 / x;\n}\n", tmp_path, _ASSERT_ON)


# --- SAFE603 blanket_suppression (opt-in) --------------------------------------

_SUPPRESS_ON = {"rules": {"blanket_suppression": {"enabled": True}}}


def test_c_bare_nolint_fires_safe603(tmp_path: Path) -> None:
    """A bare ``// NOLINT`` silences every clang-tidy check - blanket."""
    assert "SAFE603" in _codes("n.c", "int f(void) { return bad(); } // NOLINT\n", tmp_path, _SUPPRESS_ON)


def test_c_nolintnextline_fires_safe603(tmp_path: Path) -> None:
    """``// NOLINTNEXTLINE`` is also blanket."""
    assert "SAFE603" in _codes("n.c", "// NOLINTNEXTLINE\nint f(void) { return bad(); }\n", tmp_path, _SUPPRESS_ON)


def test_c_scoped_nolint_is_clean_for_safe603(tmp_path: Path) -> None:
    """A check-scoped ``// NOLINT(bugprone-foo)`` is auditable and clean."""
    assert "SAFE603" not in _codes("n.c", "int f(void) { return bad(); } // NOLINT(bugprone-foo)\n", tmp_path, _SUPPRESS_ON)


def test_c_wildcard_nolint_fires_safe603(tmp_path: Path) -> None:
    """``// NOLINT(*)`` is clang-tidy's "every check" wildcard - still blanket."""
    assert "SAFE603" in _codes("n.c", "int f(void) { return bad(); } // NOLINT(*)\n", tmp_path, _SUPPRESS_ON)


def test_c_prose_nolint_is_not_a_directive(tmp_path: Path) -> None:
    """Lowercase prose ``// nolint`` is not the clang-tidy keyword."""
    assert "SAFE603" not in _codes("n.c", "int f(void) { return bad(); } // nolint, just prose\n", tmp_path, _SUPPRESS_ON)


# --- SAFE701 test_existence (opt-in) -------------------------------------------


def test_c_source_without_test_fires_safe701(tmp_path: Path) -> None:
    """A C source with no paired test file fires SAFE701 when enabled."""
    overrides = {"rules": {"test_existence": {"enabled": True}}}
    assert "SAFE701" in _codes("widget.c", "int widget(void) { return 1; }\n", tmp_path, overrides)


def test_c_source_with_sibling_test_is_clean_for_safe701(tmp_path: Path) -> None:
    """A ``<stem>_test.c`` under the configured test dir clears SAFE701."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "widget_test.c").write_text("void t(void) { assert(1); }\n", encoding="utf-8")
    overrides = {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(tmp_path / "tests")]}}}
    assert "SAFE701" not in _codes("widget.c", "int widget(void) { return 1; }\n", tmp_path, overrides)


# --- SAFE702 test_coupling (opt-in) --------------------------------------------


def test_c_changed_source_without_test_fires_safe702(tmp_path: Path) -> None:
    """Changing ``widget.c`` without its ``tests/widget_test.c`` fires SAFE702."""
    src = tmp_path / "widget.c"
    src.write_text("int widget(void) { return 1; }\n", encoding="utf-8")
    test = tmp_path / "tests" / "widget_test.c"
    test.parent.mkdir(parents=True)
    test.write_text("void t(void) { assert(1); }\n", encoding="utf-8")

    overrides = {"rules": {"test_coupling": {"enabled": True, "_changed_files": [str(src)]}}}
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
    with _cd(tmp_path):
        result = engine.check_file(str(src))
    safe702 = [v for v in result.violations if v.code == "SAFE702"]
    assert len(safe702) == 1
    assert "widget_test.c" in safe702[0].message


def test_c_changed_source_with_test_is_clean_for_safe702(tmp_path: Path) -> None:
    """Changing both ``widget.c`` and its ``tests/widget_test.c`` clears SAFE702."""
    src = tmp_path / "widget.c"
    src.write_text("int widget(void) { return 1; }\n", encoding="utf-8")
    test = tmp_path / "tests" / "widget_test.c"
    test.parent.mkdir(parents=True)
    test.write_text("void t(void) { assert(1); }\n", encoding="utf-8")

    overrides = {"rules": {"test_coupling": {"enabled": True, "_changed_files": [str(src), str(test)]}}}
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
    with _cd(tmp_path):
        result = engine.check_file(str(src))
    assert not any(v.code == "SAFE702" for v in result.violations)
