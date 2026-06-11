"""Tests for ``global_mutation`` (SAFE302) on Java files.

Java semantics differ from Python / JavaScript: there is no ``global``
keyword and no ``globalThis`` namespace. The Java analogue of shared
mutable state is a **non-final static field**, so SAFE302 fires at the
field declaration site. ``static final`` fields are clean (even when the
referent is interiorly mutable - a documented v1 exclusion).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def _safe302(result) -> list:
    return [v for v in result.violations if v.code == "SAFE302"]


def test_java_non_final_static_field_fires(tmp_path: Path) -> None:
    """A non-final ``static`` field fires SAFE302."""
    sample = tmp_path / "Counter.java"
    sample.write_text("class Counter {\n  static int count = 0;\n}\n", encoding="utf-8")
    hits = _safe302(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert "count" in hits[0].message


def test_java_static_final_is_clean(tmp_path: Path) -> None:
    """``static final`` is an immutable constant - no violation."""
    sample = tmp_path / "Config.java"
    sample.write_text('class Config {\n  static final String NAME = "x";\n}\n', encoding="utf-8")
    assert _safe302(_engine().check_file(str(sample))) == []


def test_java_instance_field_is_clean(tmp_path: Path) -> None:
    """A non-static instance field is not shared state - no violation."""
    sample = tmp_path / "Bean.java"
    sample.write_text("class Bean {\n  private int value = 0;\n}\n", encoding="utf-8")
    assert _safe302(_engine().check_file(str(sample))) == []


def test_java_local_variable_is_clean(tmp_path: Path) -> None:
    """A local variable inside a method is not a field - no violation."""
    sample = tmp_path / "Local.java"
    sample.write_text("class Local {\n  void run() {\n    int x = 1;\n    x++;\n  }\n}\n", encoding="utf-8")
    assert _safe302(_engine().check_file(str(sample))) == []


def test_java_non_final_static_in_nested_class_fires(tmp_path: Path) -> None:
    """A non-final static field inside a nested class still fires."""
    sample = tmp_path / "Outer.java"
    sample.write_text(
        "class Outer {\n  static class Inner {\n    static boolean flag = false;\n  }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe302(_engine().check_file(str(sample)))) == 1


def test_java_public_static_non_final_fires(tmp_path: Path) -> None:
    """Modifier order / extra modifiers do not hide the static-non-final shape."""
    sample = tmp_path / "Globals.java"
    sample.write_text("class Globals {\n  public static int counter = 0;\n}\n", encoding="utf-8")
    assert len(_safe302(_engine().check_file(str(sample)))) == 1


def test_java_multi_declarator_static_fires_per_variable(tmp_path: Path) -> None:
    """`static int a = 1, b = 2;` is two shared-mutable-state violations, not one."""
    sample = tmp_path / "Multi.java"
    sample.write_text("class Multi {\n  static int a = 1, b = 2;\n}\n", encoding="utf-8")
    hits = _safe302(_engine().check_file(str(sample)))
    assert len(hits) == 2
    names = " ".join(h.message for h in hits)
    assert '"a"' in names
    assert '"b"' in names
