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
from safelint.rules.rust_rules import _PARENT_GATE_CACHE


def _codes(sample: Path, rule: str, code: str) -> list[int]:
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {rule: {"enabled": True}}}))
    return [v.lineno for v in engine.check_file(str(sample)).violations if v.code == code]


_UNWRAP_BODY = "fn helper() -> u32 {\n    let x: Result<u32, ()> = Ok(1);\n    x.unwrap()\n}\n"


def test_cargo_integration_tests_are_test_context(tmp_path: Path) -> None:
    """Every ``.rs`` under a crate's ``tests/`` is a test binary by cargo convention.

    Such a file never carries ``#[cfg(test)]`` - the directory is the gate - so an
    in-file attribute search can never see it.
    """
    sample = tmp_path / "tests" / "integration.rs"
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
    sample = tmp_path / "crates" / "matcher" / "tests" / "test_matcher.rs"
    sample.parent.mkdir(parents=True)
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


def test_an_unreadable_parent_module_file_is_treated_as_not_gated(tmp_path: Path) -> None:
    """A parent that cannot be read leaves the finding reported, not silently cleared.

    Deliberately the safe direction: failing to see a gate reports something a
    reader can dismiss, whereas inventing one would hide a real unwrap in
    production code.
    """
    _PARENT_GATE_CACHE.clear()
    src = tmp_path / "src"
    src.mkdir()
    # A directory where the parser expects a file: ``read_bytes`` raises
    # IsADirectoryError, which is an OSError.
    (src / "lib.rs").mkdir()
    sample = src / "mod_under_test.rs"
    sample.write_text(_UNWRAP_BODY, encoding="utf-8")
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == [3]


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
    assert (str(src), "testutil") in _PARENT_GATE_CACHE
    # Second call takes the cached path.
    assert _codes(sample, "result_unwrap_outside_tests", "SAFE208") == []
