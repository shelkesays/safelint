"""Tests for ``test_existence`` (SAFE701) and ``test_coupling`` (SAFE702) on Rust files.

Rust has two distinct test-placement conventions, both of which the
rule must recognise:

* **Inline tests** (idiomatic): a ``#[cfg(test)] mod tests { }``
  block inside the source file itself, or any ``#[test]``-attributed
  function. The rule treats either marker as "this file already
  carries its tests" and clears the violation - no external test
  file is demanded.
* **External integration tests** (Cargo convention): bare
  ``<stem>.rs`` (matching the source stem exactly) placed under the
  workspace ``tests/`` directory. Also ``<stem>_test.rs`` as an
  alternative.
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


@contextmanager
def _cd(path: Path) -> Iterator[None]:
    """Change cwd inside the block so the rule's ``Path("tests")`` resolves correctly."""
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


def _enabled_engine(overrides: dict | None = None, changed_files: list[str] | None = None) -> SafetyEngine:
    """SafetyEngine with both test-coverage rules enabled (off by default).

    ``changed_files`` opts into the diff-aware path SAFE702 needs - the
    engine only flags coupling violations when the list is present.
    """
    base = {
        "rules": {
            "test_existence": {"enabled": True},
            "test_coupling": {"enabled": True},
        },
    }
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config, changed_files=changed_files)


# ---------------------------------------------------------------------------
# SAFE701 - test_existence
# ---------------------------------------------------------------------------


def test_rust_no_test_file_fires_safe701(tmp_path: Path) -> None:
    """A ``.rs`` source with no inline tests and no external pair fires SAFE701."""
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    safe701 = [v for v in result.violations if v.code == "SAFE701"]
    assert len(safe701) == 1
    assert "foo.rs" in safe701[0].message


def test_rust_inline_test_module_satisfies_safe701(tmp_path: Path) -> None:
    """``#[cfg(test)] mod tests { }`` inline clears SAFE701 without an external file."""
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text(
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn it_works() {\n        assert_eq!(super::add(2, 2), 4);\n    }\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_rust_tokio_test_fn_satisfies_safe701(tmp_path: Path) -> None:
    """``#[tokio::test]`` (scoped path attribute) clears SAFE701.

    Files whose test markers are scoped framework macros - tokio,
    actix_web, async_std, smol_potat, etc. - should not be told to
    add an external paired test file. The detection looks at the
    trailing identifier of the scoped path and recognises any
    ``::test``-suffixed attribute as a test marker.
    """
    src = tmp_path / "src" / "tokio_handler.rs"
    src.parent.mkdir(parents=True)
    src.write_text(
        "pub async fn handle() -> i32 { 1 }\n\n#[tokio::test]\nasync fn it_handles() {\n    assert_eq!(handle().await, 1);\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_rust_free_test_fn_satisfies_safe701(tmp_path: Path) -> None:
    """A free-standing ``#[test] fn`` (no enclosing mod) also clears SAFE701."""
    src = tmp_path / "src" / "bar.rs"
    src.parent.mkdir(parents=True)
    src.write_text(
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n\n#[test]\nfn it_works() {\n    assert_eq!(add(2, 2), 4);\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_rust_external_integration_test_satisfies_safe701(tmp_path: Path) -> None:
    """Cargo's ``tests/<stem>.rs`` integration test satisfies SAFE701."""
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.rs"
    test.parent.mkdir(parents=True)
    test.write_text("#[test]\nfn it() {}\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_rust_test_suffix_pair_satisfies_safe701(tmp_path: Path) -> None:
    """The alternative ``<stem>_test.rs`` colocated convention satisfies SAFE701."""
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo_test.rs"
    test.parent.mkdir(parents=True)
    test.write_text("#[test]\nfn it() {}\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_rust_test_under_tests_dir_is_test_file(tmp_path: Path) -> None:
    """A file under ``tests/`` is itself a test file - SAFE701 must not fire on it."""
    test_src = tmp_path / "tests" / "foo.rs"
    test_src.parent.mkdir(parents=True)
    test_src.write_text("#[test]\nfn it() { assert!(true); }\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(test_src))
    assert not any(v.code == "SAFE701" for v in result.violations)


def test_rust_non_test_attributes_do_not_satisfy_safe701(tmp_path: Path) -> None:
    """``#[derive(...)]`` and ``#[cfg(unix)]`` etc. must NOT clear SAFE701.

    Guards the marker detector against falsely accepting any
    attributed file as having tests. Exercises the rejection paths
    in ``_rust_has_test_marker`` for attributes whose first identifier
    is neither ``"test"`` nor ``"cfg"``, and for ``cfg`` attributes
    whose argument doesn't contain ``test``.
    """
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text(
        "#[derive(Debug, Clone)]\npub struct Foo { pub x: i32 }\n\n#[cfg(unix)]\npub fn unix_only() -> i32 { 1 }\n\n#[inline]\npub fn add(a: i32, b: i32) -> i32 { a + b }\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(src))
    safe701 = [v for v in result.violations if v.code == "SAFE701"]
    assert len(safe701) == 1, "non-test attributes should NOT satisfy SAFE701"


def test_rust_filename_with_test_suffix_is_test_file(tmp_path: Path) -> None:
    """``foo_test.rs`` outside ``tests/`` is recognised as a test file by suffix."""
    test_src = tmp_path / "src" / "foo_test.rs"
    test_src.parent.mkdir(parents=True)
    test_src.write_text("#[test]\nfn it() { assert!(true); }\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine().check_file(str(test_src))
    assert not any(v.code == "SAFE701" for v in result.violations)


# ---------------------------------------------------------------------------
# SAFE702 - test_coupling
# ---------------------------------------------------------------------------


def test_rust_coupling_inline_tests_satisfies_safe702(tmp_path: Path) -> None:
    """Source with inline tests trivially satisfies SAFE702 (the file IS its test).

    When the source file itself carries the tests, editing the source
    necessarily edits the test - the diff-aware coupling guarantee is
    satisfied by definition, no separate test-file edit required.
    """
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text(
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn it() { assert_eq!(super::add(1, 1), 2); }\n}\n",
        encoding="utf-8",
    )

    with _cd(tmp_path):
        result = _enabled_engine(changed_files=[str(src)]).check_file(str(src))
    assert not any(v.code == "SAFE702" for v in result.violations)


def test_rust_coupling_external_test_changed_satisfies_safe702(tmp_path: Path) -> None:
    """When the external paired test was also changed, SAFE702 clears."""
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.rs"
    test.parent.mkdir(parents=True)
    test.write_text("#[test]\nfn it() {}\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine(changed_files=[str(src), str(test)]).check_file(str(src))
    assert not any(v.code == "SAFE702" for v in result.violations)


def test_rust_coupling_skipped_on_test_file_itself(tmp_path: Path) -> None:
    """SAFE702 must not fire on a file that *is* a test file (under ``tests/``)."""
    test_src = tmp_path / "tests" / "foo.rs"
    test_src.parent.mkdir(parents=True)
    test_src.write_text("#[test]\nfn it() { assert!(true); }\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine(changed_files=[str(test_src)]).check_file(str(test_src))
    assert not any(v.code == "SAFE702" for v in result.violations)


def test_rust_coupling_external_test_not_changed_fires_safe702(tmp_path: Path) -> None:
    """When source changed but the external test didn't, SAFE702 fires."""
    src = tmp_path / "src" / "foo.rs"
    src.parent.mkdir(parents=True)
    src.write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8")
    test = tmp_path / "tests" / "foo.rs"
    test.parent.mkdir(parents=True)
    test.write_text("#[test]\nfn it() {}\n", encoding="utf-8")

    with _cd(tmp_path):
        result = _enabled_engine(changed_files=[str(src)]).check_file(str(src))
    safe702 = [v for v in result.violations if v.code == "SAFE702"]
    assert len(safe702) == 1
