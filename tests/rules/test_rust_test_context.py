"""SAFE208 / SAFE601: test context that an in-file search cannot see.

Two Rust layouts defeat an attribute search confined to the file being linted
(#172), and the Rust assertion list omitted the dominant modern idiom (#177).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules.rust_rules import _PARENT_GATE_CACHE, _declares_gated_module


def _codes(sample: Path, rule: str, code: str) -> list[int]:
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {rule: {"enabled": True}}}))
    return [v.lineno for v in engine.check_file(str(sample)).violations if v.code == code]


_UNWRAP_BODY = "fn helper() -> u32 {\n    let x: Result<u32, ()> = Ok(1);\n    x.unwrap()\n}\n"


def _crate(root: Path) -> Path:
    """Make *root* a cargo crate root by giving it a ``Cargo.toml``.

    Cargo's integration-test directory is defined relative to the crate root, so
    the fixtures have to BE crates: a bare ``tests/`` in a scratch directory is
    not cargo's ``tests/``, and treating it as one is what made the answer depend
    on where the repository happened to be checked out.
    """
    root.mkdir(parents=True, exist_ok=True)
    root.joinpath("Cargo.toml").write_text('[package]\nname = "fixture"\n', encoding="utf-8")
    return root


def test_cargo_integration_tests_are_test_context(tmp_path: Path) -> None:
    """Every ``.rs`` under a crate's ``tests/`` is a test binary by cargo convention.

    Such a file never carries ``#[cfg(test)]`` - the directory is the gate - so an
    in-file attribute search can never see it.
    """
    sample = _crate(tmp_path) / "tests" / "integration.rs"
    sample.parent.mkdir()
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []


def test_a_workspace_crates_tests_dir_is_recognised(tmp_path: Path) -> None:
    """A cargo workspace puts integration tests at ``crates/<name>/tests/``.

    Anchoring ``test_dirs`` at the project root - which the shared ``_is_test_file``
    helper does by design, for the rules that want project-relative semantics -
    matches ``tests/`` but misses every crate in a workspace. On ripgrep that is
    the larger share of the misreported findings.
    """
    _crate(tmp_path)  # the workspace root
    sample = _crate(tmp_path / "crates" / "matcher") / "tests" / "test_matcher.rs"
    sample.parent.mkdir()
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []


def test_a_module_gated_in_its_parent_is_test_context(tmp_path: Path) -> None:
    """``#[cfg(test)] mod testutil;`` gates the module where it is DECLARED.

    The definition file carries no attribute of its own, so the gate is invisible
    to a search of that file. ripgrep's ``crates/searcher/src/testutil.rs`` is
    gated at ``lib.rs:105``.
    """
    _PARENT_GATE_CACHE.clear()
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text("#[cfg(test)]\nmod testutil;\n", encoding="utf-8")
    sample = src / "testutil.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []


def test_an_ungated_sibling_module_is_still_production_code(tmp_path: Path) -> None:
    """The control: a plain ``mod helper;`` is not a test gate.

    Without this, "the parent mentions this module" would be mistaken for "the
    parent gates it", silencing real findings.
    """
    _PARENT_GATE_CACHE.clear()
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text("mod helper;\n", encoding="utf-8")
    sample = src / "helper.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


def test_a_file_with_no_parent_module_file_still_reports(tmp_path: Path) -> None:
    """No sibling ``lib.rs`` / ``main.rs`` / ``mod.rs`` means nothing gates it."""
    _PARENT_GATE_CACHE.clear()
    sample = tmp_path / "standalone.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


_SNAPSHOT_MACROS = [
    ["assert_snapshot", "assert_snapshot!(value);"],
    ["assert_debug_snapshot", 'assert_debug_snapshot!(value, @r#"Ok"#);'],
    ["assert_json_snapshot", "assert_json_snapshot!(value);"],
    ["assert_yaml_snapshot", "assert_yaml_snapshot!(value);"],
    ["assert_compact_debug_snapshot", "assert_compact_debug_snapshot!(value);"],
    ["assert_matches", "assert_matches!(value, Ok(_));"],
]


@pytest.mark.parametrize(["label", "call"], tuple(_SNAPSHOT_MACROS), ids=[case[0] for case in _SNAPSHOT_MACROS])
def test_snapshot_macros_count_as_assertions(tmp_path: Path, label: str, call: str) -> None:
    """Snapshot testing is the dominant assertion idiom in modern Rust (#177).

    A test whose only assertion is a snapshot read as having none: on Ruff, 557 of
    5412 sampled SAFE601 findings were ``#[test]`` functions that do assert, just
    not with a name on the list. Genuine assertion-free tests were 82.
    """
    sample = tmp_path / "snap.rs"
    sample.write_text(f"#[test]\nfn t() {{\n    let value = parse();\n    {call}\n}}\n", encoding="utf-8")
    assert _codes(sample, "missing_assertions", "SAFE601") == [], label


def test_a_test_with_no_assertion_at_all_still_reports(tmp_path: Path) -> None:
    """The control: adding the macros must not blanket-exempt every test."""
    sample = tmp_path / "noassert.rs"
    sample.write_text("#[test]\nfn t() {\n    let _value = parse();\n}\n", encoding="utf-8")
    assert _codes(sample, "missing_assertions", "SAFE601") == [2]


def test_a_tests_directory_inside_src_is_not_a_cargo_test_dir(tmp_path: Path) -> None:
    """``src/tests/helpers.rs`` is crate source in a module called ``tests``.

    Cargo's integration tests sit in a ``tests/`` that is a SIBLING of ``src``,
    never inside it. A module under ``src`` is compiled into the library unless
    something gates it, and when it is gated the ``#[cfg(test)] mod tests;`` in
    its parent says so - which the parent-gate check detects on its own. Matching
    any ``tests`` component suppressed every finding in such a file.
    """
    _PARENT_GATE_CACHE.clear()
    sample = _crate(tmp_path) / "src" / "tests" / "helpers.rs"
    sample.parent.mkdir(parents=True)
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


def test_a_parent_module_file_that_is_not_a_file_is_skipped(tmp_path: Path) -> None:
    """A directory named ``lib.rs`` is not a candidate, so nothing is read from it.

    The finding stays reported: failing to see a gate reports something a reader
    can dismiss, whereas inventing one would hide a real unwrap in production
    code.
    """
    _PARENT_GATE_CACHE.clear()
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").mkdir()
    sample = src / "mod_under_test.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


def test_an_unreadable_parent_module_file_is_treated_as_not_gated(tmp_path: Path) -> None:
    """A parent that exists but cannot be READ is treated as not gated.

    Exercised directly, because the caller skips any candidate failing
    ``is_file()`` and so never reaches the read: the earlier version of this test
    used a directory named ``lib.rs`` and therefore proved only that the
    ``is_file()`` guard works (kept above, under its own name).
    """
    parent = tmp_path / "lib.rs"
    parent.write_text("#[cfg(test)]\nmod helper;\n", encoding="utf-8")
    parent.chmod(0o000)
    try:
        # Permission bits do not stop root, and mean nothing on Windows. Where the
        # read still succeeds there is no OSError to exercise, so skip rather than
        # fail - a root container is an ordinary way to run this suite.
        if parent.read_bytes():
            pytest.skip("permissions do not block this reader (root, or a platform that ignores the bits)")
    except OSError:
        assert _declares_gated_module(parent, "helper") is False
    finally:
        parent.chmod(0o644)


def test_a_readable_parent_is_still_parsed(tmp_path: Path) -> None:
    """The control for the test above: the same call returns True when the read works."""
    parent = tmp_path / "lib.rs"
    parent.write_text("#[cfg(test)]\nmod helper;\n", encoding="utf-8")
    assert _declares_gated_module(parent, "helper") is True


def test_the_parent_gate_answer_is_cached_per_module(tmp_path: Path) -> None:
    """The lookup reads a sibling file, and a crate's modules all share one parent.

    Without the cache a 200-module crate would re-read and re-parse ``lib.rs`` 200
    times.
    """
    _PARENT_GATE_CACHE.clear()
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text("#[cfg(test)]\nmod testutil;\n", encoding="utf-8")
    sample = src / "testutil.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []
    # The key carries a signature of the parent module files so an edited parent
    # invalidates the entry; only the directory and stem are asserted here.
    assert [key[:2] for key in _PARENT_GATE_CACHE] == [(str(src), "testutil")]
    # Second call takes the cached path.
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []


def test_a_parent_gating_a_different_module_does_not_gate_this_one(tmp_path: Path) -> None:
    """``#[cfg(test)] mod other;`` in the parent says nothing about ``helper.rs``.

    Matching any gated ``mod`` in the parent, rather than the one named after this
    file, would suppress findings across the whole directory.
    """
    _PARENT_GATE_CACHE.clear()
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text("#[cfg(test)]\nmod other;\nmod helper;\n", encoding="utf-8")
    sample = src / "helper.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


def test_an_edited_parent_invalidates_the_cached_gate(tmp_path: Path) -> None:
    """The cache is process-global, and safelint runs as a library in long-lived hosts.

    Keyed on the path alone, removing the ``#[cfg(test)]`` from ``lib.rs`` would
    keep returning the stale "gated" answer and go on suppressing findings in what
    is now production code.
    """
    _PARENT_GATE_CACHE.clear()
    src = tmp_path / "src"
    src.mkdir()
    parent = src / "lib.rs"
    parent.write_text("#[cfg(test)]\nmod helper;\n", encoding="utf-8")
    sample = src / "helper.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []
    # The gate is removed: the module is now compiled into the library.
    parent.write_text("mod helper;\npub fn extra() {}\n", encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


def test_the_answer_does_not_depend_on_where_the_crate_is_checked_out(tmp_path: Path) -> None:
    """The same crate must give the same answer under ``~/src/...`` and ``~/tests/...``.

    An earlier lexical rule ("a ``tests`` component with no ``src`` before it")
    made both wrong: a developer keeping repositories under ``~/src`` saw every
    integration test still reported, cancelling #172 for them, while a checkout
    under ``~/tests`` had its production code silently exempted. Neither is a
    property of the crate, so neither can be the test.
    """
    for parent in ("src/work", "tests/work"):
        crate = _crate(tmp_path / parent)
        integration = crate / "tests" / "it.rs"
        integration.parent.mkdir()
        integration.write_text(_UNWRAP_BODY, encoding="utf-8")
        library = crate / "src" / "lib.rs"
        library.parent.mkdir()
        library.write_text(_UNWRAP_BODY, encoding="utf-8")
        assert _codes(integration, "result_unwrap_outside_tests", "SAFE208") == [], parent
        assert _codes(library, "result_unwrap_outside_tests", "SAFE208") == [3], parent


def test_a_file_outside_any_crate_is_not_test_context(tmp_path: Path) -> None:
    """With no ``Cargo.toml`` above it the crate root is unknown, so the finding stands.

    Reporting something a reader can dismiss beats inventing a crate layout and
    hiding a real unwrap.
    """
    sample = tmp_path / "tests" / "loose.rs"
    sample.parent.mkdir()
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


def test_a_nested_module_under_the_tests_dir_is_still_test_context(tmp_path: Path) -> None:
    """Cargo compiles ``tests/common/mod.rs`` into the integration-test binary."""
    sample = _crate(tmp_path) / "tests" / "common" / "mod.rs"
    sample.parent.mkdir(parents=True)
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []
