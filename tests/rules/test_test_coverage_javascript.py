"""Tests for ``test_existence`` (SAFE701) and ``test_coupling`` (SAFE702) on JavaScript files."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


@contextmanager
def _cd(path: Path) -> Iterator[None]:
    """Change cwd inside the block so the rule's ``Path("tests")`` resolves correctly."""
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


def _enabled_engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with both test-coverage rules enabled (off by default)."""
    base = {
        "rules": {
            "test_existence": {"enabled": True},
            "test_coupling": {"enabled": True},
        },
    }
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config)


# ---------------------------------------------------------------------------
# test_existence (SAFE701)
# ---------------------------------------------------------------------------


def test_js_no_test_file_fires_safe701(tmp_path: Path) -> None:
    """A ``.js`` source without a corresponding ``foo.test.js`` / ``foo.spec.js`` fires SAFE701."""
    src = tmp_path / "src" / "foo.js"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()  # empty tests dir

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    safe701 = [v for v in result.violations if v.code == "SAFE701"]
    assert len(safe701) == 1
    assert "foo.test.js" in safe701[0].message


def test_js_jest_test_file_satisfies_safe701(tmp_path: Path) -> None:
    """``foo.test.js`` (Jest convention) satisfies the rule."""
    src = tmp_path / "src" / "foo.js"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1;\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.test.js"
    test.parent.mkdir(parents=True)
    test.write_text("test('x', () => {});\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_js_mocha_spec_file_satisfies_safe701(tmp_path: Path) -> None:
    """``foo.spec.js`` (Mocha / Karma convention) also satisfies the rule."""
    src = tmp_path / "src" / "foo.js"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1;\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.spec.js"
    test.parent.mkdir(parents=True)
    test.write_text("describe('x', () => {});\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_js_mjs_source_with_mjs_test_satisfies_safe701(tmp_path: Path) -> None:
    """``.mjs`` source pairs with ``foo.test.mjs``."""
    src = tmp_path / "src" / "foo.mjs"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1;\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.test.mjs"
    test.parent.mkdir(parents=True)
    test.write_text("test('x', () => {});\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


# ---------------------------------------------------------------------------
# test_coupling (SAFE702)
# ---------------------------------------------------------------------------


def test_js_changed_source_unchanged_test_fires_safe702(tmp_path: Path) -> None:
    """When the source is in the changed set but its test file isn't, SAFE702 fires."""
    src = tmp_path / "src" / "foo.js"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1;\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.test.js"
    test.parent.mkdir(parents=True)
    test.write_text("test('x', () => {});\n", encoding="utf-8")

    overrides = {
        "rules": {
            "test_coupling": {
                "enabled": True,
                "_changed_files": [str(src)],  # only src/foo.js changed; test untouched
            },
        },
    }
    with _cd(tmp_path):
        result = _enabled_engine(overrides).check_file(str(src))
    safe702 = [v for v in result.violations if v.code == "SAFE702"]
    assert len(safe702) == 1
    assert "foo.test.js" in safe702[0].message


def test_js_changed_source_changed_jest_test_does_not_fire(tmp_path: Path) -> None:
    """When both source and Jest-style test file are in the changed set, no violation."""
    src = tmp_path / "src" / "foo.js"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1;\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.test.js"
    test.parent.mkdir(parents=True)
    test.write_text("test('x', () => {});\n", encoding="utf-8")

    overrides = {
        "rules": {
            "test_coupling": {
                "enabled": True,
                "_changed_files": [str(src), str(test)],
            },
        },
    }
    with _cd(tmp_path):
        result = _enabled_engine(overrides).check_file(str(src))
    assert not any(v.code == "SAFE702" for v in result.violations)


def test_js_changed_source_changed_spec_test_does_not_fire(tmp_path: Path) -> None:
    """A ``.spec.js`` change in the changed set also satisfies coupling."""
    src = tmp_path / "src" / "foo.js"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1;\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.spec.js"
    test.parent.mkdir(parents=True)
    test.write_text("describe('x', () => {});\n", encoding="utf-8")

    overrides = {
        "rules": {
            "test_coupling": {
                "enabled": True,
                "_changed_files": [str(src), str(test)],
            },
        },
    }
    with _cd(tmp_path):
        result = _enabled_engine(overrides).check_file(str(src))
    assert not any(v.code == "SAFE702" for v in result.violations)
