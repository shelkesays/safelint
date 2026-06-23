"""Tests for missing_assertions (SAFE601), blanket_suppression (SAFE603) and the test-coverage rules (SAFE701/702) on PHP files."""

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


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


# ---------------------------------------------------------------------------
# missing_assertions (SAFE601)
#
# The default ``assertion_calls_php`` list covers PHPUnit's assertions
# (assert, assertSame, assertEquals, assertTrue, assertThat, expectException,
# fail, ...). ``call_name`` resolves ``$this->assertSame(...)`` to ``assertSame``.
# ---------------------------------------------------------------------------


def _cfg601() -> dict:
    """Config with missing_assertions enabled (off by default)."""
    return {"rules": {"missing_assertions": {"enabled": True}}}


def test_php_function_without_assertions_fires_safe601(tmp_path: Path) -> None:
    """A function with no assertion calls fires SAFE601 (when enabled)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction testFoo(){ $x = 1; }\n", encoding="utf-8")
    safe601 = [v for v in _engine(_cfg601()).check_file(str(sample)).violations if v.code == "SAFE601"]
    assert len(safe601) == 1
    assert "testFoo" in safe601[0].message


def test_php_function_with_assert_same_is_clean(tmp_path: Path) -> None:
    """A ``$this->assertSame(...)`` call satisfies the rule (call_name resolves to ``assertSame``)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction testFoo(){ $this->assertSame(1,1); }\n", encoding="utf-8")
    assert not any(v.code == "SAFE601" for v in _engine(_cfg601()).check_file(str(sample)).violations)


# ---------------------------------------------------------------------------
# blanket_suppression (SAFE603)
#
# PHP needs both a comment scan (bare ``phpcs:ignore`` / ``phpcs:disable``,
# ``@phpstan-ignore-line``, ``@psalm-suppress all``) and the ``@``
# error-suppression operator scan. Scoped directives are clean.
# ---------------------------------------------------------------------------


def _cfg603() -> dict:
    """Config with blanket_suppression enabled (off by default)."""
    return {"rules": {"blanket_suppression": {"enabled": True}}}


def test_php_error_suppression_operator_fires_safe603(tmp_path: Path) -> None:
    """The ``@`` error-suppression operator silences all errors - fires SAFE603."""
    sample = tmp_path / "x.php"
    sample.write_text('<?php\n$x = @file_get_contents("y");\n', encoding="utf-8")
    safe603 = [v for v in _engine(_cfg603()).check_file(str(sample)).violations if v.code == "SAFE603"]
    assert len(safe603) == 1
    assert "@" in safe603[0].message


def test_php_bare_phpcs_ignore_fires_safe603(tmp_path: Path) -> None:
    """A bare ``// phpcs:ignore`` (no sniff list) silences every PHP_CodeSniffer sniff - fires."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n// phpcs:ignore\nfunction f(){}\n", encoding="utf-8")
    safe603 = [v for v in _engine(_cfg603()).check_file(str(sample)).violations if v.code == "SAFE603"]
    assert len(safe603) == 1
    assert "phpcs:ignore" in safe603[0].message


def test_php_scoped_phpcs_ignore_is_clean(tmp_path: Path) -> None:
    """A scoped ``// phpcs:ignore Squiz.Foo.Bar`` targets a named sniff and is clean."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n// phpcs:ignore Squiz.Foo.Bar\nfunction f(){}\n", encoding="utf-8")
    assert not any(v.code == "SAFE603" for v in _engine(_cfg603()).check_file(str(sample)).violations)


def test_php_phpstan_ignore_line_fires_safe603(tmp_path: Path) -> None:
    """A ``// @phpstan-ignore-line`` (no identifier) suppresses every PHPStan error - fires."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n// @phpstan-ignore-line\nfunction f(){}\n", encoding="utf-8")
    assert any(v.code == "SAFE603" for v in _engine(_cfg603()).check_file(str(sample)).violations)


def test_php_psalm_suppress_all_fires_safe603(tmp_path: Path) -> None:
    """A ``// @psalm-suppress all`` silences every Psalm issue - fires."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n// @psalm-suppress all\nfunction f(){}\n", encoding="utf-8")
    assert any(v.code == "SAFE603" for v in _engine(_cfg603()).check_file(str(sample)).violations)


def test_php_hash_phpcs_disable_fires_safe603(tmp_path: Path) -> None:
    """A hash-comment ``# phpcs:disable`` is the same blanket directive - fires."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n# phpcs:disable\nfunction f(){}\n", encoding="utf-8")
    assert any(v.code == "SAFE603" for v in _engine(_cfg603()).check_file(str(sample)).violations)


def test_php_plain_comment_is_clean(tmp_path: Path) -> None:
    """A normal ``// just a note`` comment is not a directive and is clean."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n// just a note\nfunction f(){}\n", encoding="utf-8")
    assert not any(v.code == "SAFE603" for v in _engine(_cfg603()).check_file(str(sample)).violations)


# ---------------------------------------------------------------------------
# test_existence (SAFE701) / test_coupling (SAFE702)
#
# PHPUnit's convention is ``<ClassName>Test.php`` under ``test_dirs`` (default
# ``tests/``). The rule's ``Path("tests")`` resolves against the cwd, so the
# tests change into ``tmp_path`` via the ``_cd`` helper.
# ---------------------------------------------------------------------------


def _coverage_engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with both test-coverage rules enabled (off by default)."""
    base = {
        "rules": {
            "test_existence": {"enabled": True},
            "test_coupling": {"enabled": True},
        },
    }
    if overrides:
        base = deep_merge(base, overrides)
    return SafetyEngine(deep_merge(DEFAULTS, base))


def test_php_missing_test_fires_safe701(tmp_path: Path) -> None:
    """A ``Foo.php`` with no ``tests/FooTest.php`` fires SAFE701 (message mentions FooTest.php)."""
    src = tmp_path / "Foo.php"
    src.write_text("<?php\nclass Foo {}\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()  # empty tests dir

    with _cd(tmp_path):
        result = _coverage_engine().check_file(str(src))
    safe701 = [v for v in result.violations if v.code == "SAFE701"]
    assert len(safe701) == 1
    assert "FooTest.php" in safe701[0].message


def test_php_sibling_test_file_clears_safe701(tmp_path: Path) -> None:
    """A ``tests/FooTest.php`` paired with ``Foo.php`` clears SAFE701."""
    src = tmp_path / "Foo.php"
    src.write_text("<?php\nclass Foo {}\n", encoding="utf-8")
    test = tmp_path / "tests" / "FooTest.php"
    test.parent.mkdir(parents=True)
    test.write_text("<?php\nclass FooTest {}\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _coverage_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_php_test_file_itself_is_skipped(tmp_path: Path) -> None:
    """A ``FooTest.php`` is itself a test file and never fires SAFE701."""
    test = tmp_path / "tests" / "FooTest.php"
    test.parent.mkdir(parents=True)
    test.write_text("<?php\nclass FooTest {}\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _coverage_engine().check_file(str(test))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_php_changed_source_without_test_fires_safe702(tmp_path: Path) -> None:
    """Changing ``Foo.php`` without its ``tests/FooTest.php`` fires SAFE702."""
    src = tmp_path / "Foo.php"
    src.write_text("<?php\nclass Foo {}\n", encoding="utf-8")
    test = tmp_path / "tests" / "FooTest.php"
    test.parent.mkdir(parents=True)
    test.write_text("<?php\nclass FooTest {}\n", encoding="utf-8")

    overrides = {"rules": {"test_coupling": {"enabled": True, "_changed_files": [str(src)]}}}
    with _cd(tmp_path):
        result = _coverage_engine(overrides).check_file(str(src))
    safe702 = [v for v in result.violations if v.code == "SAFE702"]
    assert len(safe702) == 1
    assert "FooTest.php" in safe702[0].message


def test_php_changed_source_with_test_is_clean(tmp_path: Path) -> None:
    """Changing both ``Foo.php`` and its ``tests/FooTest.php`` clears SAFE702."""
    src = tmp_path / "Foo.php"
    src.write_text("<?php\nclass Foo {}\n", encoding="utf-8")
    test = tmp_path / "tests" / "FooTest.php"
    test.parent.mkdir(parents=True)
    test.write_text("<?php\nclass FooTest {}\n", encoding="utf-8")

    overrides = {"rules": {"test_coupling": {"enabled": True, "_changed_files": [str(src), str(test)]}}}
    with _cd(tmp_path):
        result = _coverage_engine(overrides).check_file(str(src))
    assert not any(v.code == "SAFE702" for v in result.violations)
