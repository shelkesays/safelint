"""Tests for ``missing_assertions`` (SAFE601) method-call recognition on Python files.

Python has always counted the built-in ``assert`` keyword. These tests cover the
2.12.0 addition: unittest / Django ``TestCase`` and pytest bodies that assert only
via method calls (``self.assertEqual(...)`` / ``pytest.raises(...)``) are now
recognised instead of being flagged as assertion-less.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _enabled_engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with ``missing_assertions`` enabled (it's off by default)."""
    base = {"rules": {"missing_assertions": {"enabled": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config)


def _safe601(engine: SafetyEngine, path: str) -> list:
    """Return the SAFE601 violations for *path*."""
    return [v for v in engine.check_file(path).violations if v.code == "SAFE601"]


def _write(tmp_path: Path, rel: str, src: str) -> Path:
    """Write *src* to ``tmp_path/rel``, creating parent dirs."""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return p


def _scoped_engine() -> SafetyEngine:
    """Engine with ``missing_assertions`` enabled and ``test_functions_only`` on."""
    return _enabled_engine({"rules": {"missing_assertions": {"test_functions_only": True}}})


def test_unittest_method_call_asserts_do_not_fire(tmp_path: Path) -> None:
    """A unittest body whose only assertions are ``self.assertEqual`` is clean."""
    sample = tmp_path / "test_case.py"
    sample.write_text(
        "class T:\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
        encoding="utf-8",
    )
    assert _safe601(_enabled_engine(), str(sample)) == []


def test_pytest_raises_is_recognised(tmp_path: Path) -> None:
    """``pytest.raises(...)`` counts as an assertion (receiver stripped to ``raises``)."""
    sample = tmp_path / "test_pytest.py"
    sample.write_text(
        "def test_boom():\n    with pytest.raises(ValueError):\n        boom()\n",
        encoding="utf-8",
    )
    assert _safe601(_enabled_engine(), str(sample)) == []


def test_assertionless_function_still_fires(tmp_path: Path) -> None:
    """A function with neither the keyword nor a matching call still fires."""
    sample = tmp_path / "no_assert.py"
    sample.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    hits = _safe601(_enabled_engine(), str(sample))
    assert len(hits) == 1
    assert "add" in hits[0].message


def test_bare_assert_keyword_still_counts(tmp_path: Path) -> None:
    """The original ``assert`` keyword path is unchanged by the call addition."""
    sample = tmp_path / "keyword.py"
    sample.write_text("def add(a, b):\n    assert a > 0\n    return a + b\n", encoding="utf-8")
    assert _safe601(_enabled_engine(), str(sample)) == []


def test_unknown_method_call_does_not_count(tmp_path: Path) -> None:
    """A call not in ``assertion_calls`` (``self.helper(...)``) is not an assertion."""
    sample = tmp_path / "helper.py"
    sample.write_text(
        "class T:\n    def test_add(self):\n        self.helper(1, 2)\n",
        encoding="utf-8",
    )
    assert len(_safe601(_enabled_engine(), str(sample))) == 1


def test_project_validator_via_config_override(tmp_path: Path) -> None:
    """A project-specific assertion name added via ``assertion_calls`` is honoured."""
    sample = tmp_path / "custom.py"
    sample.write_text(
        "def test_thing():\n    verify_invariant(x)\n",
        encoding="utf-8",
    )
    engine = _enabled_engine({"rules": {"missing_assertions": {"assertion_calls": ["verify_invariant"]}}})
    assert _safe601(engine, str(sample)) == []


def test_assertion_calls_scalar_typo_raises(tmp_path: Path) -> None:
    """A bare-string typo for ``assertion_calls`` fails loud instead of matching characters."""
    sample = tmp_path / "typo.py"
    sample.write_text("def test_thing():\n    self.assertEqual(1, 1)\n", encoding="utf-8")
    engine = _enabled_engine({"rules": {"missing_assertions": {"assertion_calls": "assertEqual"}}})
    with pytest.raises(TypeError, match="assertion_calls"):
        engine.check_file(str(sample))


# ---------------------------------------------------------------------------
# test_functions_only scoping (2.12.0): only test_* functions in test files
# are required to assert; production code / fixtures / setUp are skipped.
# ---------------------------------------------------------------------------


def test_scope_fires_on_assertionless_test_but_not_setup(tmp_path: Path) -> None:
    """With scoping on, an assertion-less ``test_*`` fires; ``setUp`` is skipped."""
    src = "class T:\n    def setUp(self):\n        self.client = make_client()\n    def test_foo(self):\n        do_thing()\n"
    sample = _write(tmp_path, "tests/test_thing.py", src)
    hits = _safe601(_scoped_engine(), str(sample))
    assert len(hits) == 1
    assert "test_foo" in hits[0].message


def test_scope_setup_and_helpers_never_fire(tmp_path: Path) -> None:
    """``setUp`` / ``_helper`` with no assertions are clean when the test asserts."""
    src = "class T:\n    def setUp(self):\n        self.client = make_client()\n    def _helper(self):\n        return 1\n    def test_foo(self):\n        self.assertEqual(do_thing(), 1)\n"
    sample = _write(tmp_path, "tests/test_thing.py", src)
    assert _safe601(_scoped_engine(), str(sample)) == []


def test_scope_skips_production_file_entirely(tmp_path: Path) -> None:
    """A non-test file is skipped entirely when ``test_functions_only`` is on."""
    sample = _write(tmp_path, "src/service.py", "def process(x):\n    return x + 1\n")
    assert _safe601(_scoped_engine(), str(sample)) == []


def test_scope_off_by_default_still_checks_production(tmp_path: Path) -> None:
    """Without scoping, production functions are still checked (Holzmann default)."""
    sample = _write(tmp_path, "src/service.py", "def process(x):\n    return x + 1\n")
    assert len(_safe601(_enabled_engine(), str(sample))) == 1


def test_scope_test_dir_membership_via_explicit_test_dirs(tmp_path: Path) -> None:
    """A non-test-named file counts as a test file when it lives under ``test_dirs``."""
    sample = _write(tmp_path, "mytests/helpers.py", "def test_foo():\n    do_thing()\n")
    engine = _enabled_engine({"rules": {"missing_assertions": {"test_functions_only": True, "test_dirs": [str(tmp_path / "mytests")]}}})
    hits = _safe601(engine, str(sample))
    assert len(hits) == 1
    assert "test_foo" in hits[0].message


def test_scope_custom_prefix(tmp_path: Path) -> None:
    """``test_function_prefixes`` is honoured (``should_*`` marks a test)."""
    src = "def should_do_thing():\n    do_thing()\n"
    sample = _write(tmp_path, "tests/test_thing.py", src)
    engine = _enabled_engine({"rules": {"missing_assertions": {"test_functions_only": True, "test_function_prefixes": ["should"]}}})
    assert len(_safe601(engine, str(sample))) == 1
