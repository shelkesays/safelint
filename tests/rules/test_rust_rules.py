"""Tests for the four Rust-idiom rules: SAFE204 / SAFE205 / SAFE306 / SAFE602."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _enabled_engine(rule: str, overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with the given rule enabled (off by default)."""
    base = {"rules": {rule: {"enabled": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config)


def _violations(result, code: str) -> list:
    """Return violations of *code* in *result*."""
    return [v for v in result.violations if v.code == code]


# ---------------------------------------------------------------------------
# SAFE204 - panic_macros_outside_tests
# ---------------------------------------------------------------------------


def test_rust_panic_in_prod_function_fires_safe204(tmp_path: Path) -> None:
    """``panic!()`` in a non-test function fires SAFE204."""
    sample = tmp_path / "prod.rs"
    sample.write_text(
        'fn run() {\n    panic!("oops");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    fired = _violations(result, "SAFE204")
    assert len(fired) == 1
    assert "panic" in fired[0].message


def test_rust_todo_in_prod_function_fires_safe204(tmp_path: Path) -> None:
    """``todo!()`` is also flagged."""
    sample = tmp_path / "todo.rs"
    sample.write_text("fn run() -> i32 {\n    todo!()\n}\n", encoding="utf-8")
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert len(_violations(result, "SAFE204")) == 1


def test_rust_unimplemented_in_prod_function_fires_safe204(tmp_path: Path) -> None:
    """``unimplemented!()`` is also flagged."""
    sample = tmp_path / "unimpl.rs"
    sample.write_text("fn run() -> i32 {\n    unimplemented!()\n}\n", encoding="utf-8")
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert len(_violations(result, "SAFE204")) == 1


def test_rust_panic_in_test_function_does_not_fire(tmp_path: Path) -> None:
    """``panic!()`` inside a ``#[test]`` function does NOT fire."""
    sample = tmp_path / "test_fn.rs"
    sample.write_text(
        '#[test]\nfn test_it() {\n    panic!("in a test");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE204") == []


def test_rust_panic_inside_cfg_test_mod_does_not_fire(tmp_path: Path) -> None:
    """``panic!()`` inside a ``#[cfg(test)] mod`` does NOT fire."""
    sample = tmp_path / "cfg_test.rs"
    sample.write_text(
        '#[cfg(test)]\nmod tests {\n    fn helper() {\n        panic!("setup failure");\n    }\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE204") == []


def test_rust_panic_in_nested_function_inside_test_does_not_fire(tmp_path: Path) -> None:
    """``panic!()`` in a nested fn inside a ``#[test]`` function still counts as test context."""
    sample = tmp_path / "nested.rs"
    sample.write_text(
        '#[test]\nfn outer() {\n    fn inner() {\n        panic!("x");\n    }\n    inner();\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE204") == []


def test_rust_unreachable_does_not_fire_by_default(tmp_path: Path) -> None:
    """``unreachable!()`` is not in the default panic-macro set."""
    sample = tmp_path / "unreach.rs"
    sample.write_text(
        'fn run(x: Option<i32>) -> i32 {\n    match x {\n        Some(v) => v,\n        None => unreachable!("filtered earlier"),\n    }\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE204") == []


def test_rust_unreachable_fires_when_configured(tmp_path: Path) -> None:
    """Adding ``unreachable`` to ``panic_macros_rust`` makes it fire."""
    sample = tmp_path / "unreach_cfg.rs"
    sample.write_text(
        'fn run() {\n    unreachable!("x");\n}\n',
        encoding="utf-8",
    )
    overrides = {
        "rules": {
            "panic_macros_outside_tests": {
                "panic_macros_rust": ["panic", "todo", "unimplemented", "unreachable"],
            },
        },
    }
    result = _enabled_engine("panic_macros_outside_tests", overrides).check_file(str(sample))
    assert len(_violations(result, "SAFE204")) == 1


def test_rust_panic_with_inline_attribute_still_fires(tmp_path: Path) -> None:
    """``#[inline] fn run() { panic!(); }`` - non-test attribute doesn't clear SAFE204."""
    sample = tmp_path / "inline.rs"
    sample.write_text(
        '#[inline]\nfn run() {\n    panic!("x");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert len(_violations(result, "SAFE204")) == 1


def test_rust_panic_with_cfg_unix_attribute_still_fires(tmp_path: Path) -> None:
    """``#[cfg(unix)] fn run() { panic!(); }`` - cfg(non-test) doesn't clear SAFE204.

    Guards against a regression where the rule could match any
    ``#[cfg(...)]`` as test context. Only ``#[cfg(test)]`` and
    ``#[test]`` count.
    """
    sample = tmp_path / "cfg_unix.rs"
    sample.write_text(
        '#[cfg(unix)]\nfn run() {\n    panic!("x");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert len(_violations(result, "SAFE204")) == 1


def test_rust_scoped_panic_in_prod_fires(tmp_path: Path) -> None:
    """``std::panic!(...)`` (scoped macro path) also fires - trailing name is matched."""
    sample = tmp_path / "scoped.rs"
    sample.write_text(
        'fn run() {\n    std::panic!("x");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert len(_violations(result, "SAFE204")) == 1


# ---------------------------------------------------------------------------
# SAFE205 - lock_poisoning_ignored
# ---------------------------------------------------------------------------


def test_rust_mutex_lock_unwrap_fires_safe205(tmp_path: Path) -> None:
    """``mutex.lock().unwrap()`` fires SAFE205."""
    sample = tmp_path / "mutex.rs"
    sample.write_text(
        "use std::sync::Mutex;\nfn run(m: &Mutex<i32>) -> i32 {\n    *m.lock().unwrap()\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("lock_poisoning_ignored").check_file(str(sample))
    fired = _violations(result, "SAFE205")
    assert len(fired) == 1
    assert "lock" in fired[0].message
    assert "unwrap" in fired[0].message


def test_rust_rwlock_read_unwrap_fires_safe205(tmp_path: Path) -> None:
    """``rwlock.read().unwrap()`` fires."""
    sample = tmp_path / "rwread.rs"
    sample.write_text(
        "use std::sync::RwLock;\nfn run(r: &RwLock<i32>) -> i32 {\n    *r.read().unwrap()\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("lock_poisoning_ignored").check_file(str(sample))
    assert len(_violations(result, "SAFE205")) == 1


def test_rust_rwlock_write_expect_fires_safe205(tmp_path: Path) -> None:
    """``rwlock.write().expect("...")`` fires."""
    sample = tmp_path / "rwwrite.rs"
    sample.write_text(
        'use std::sync::RwLock;\nfn run(r: &RwLock<i32>) {\n    *r.write().expect("poisoned") = 1;\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("lock_poisoning_ignored").check_file(str(sample))
    assert len(_violations(result, "SAFE205")) == 1


def test_rust_match_on_lock_result_does_not_fire(tmp_path: Path) -> None:
    """``match m.lock() { Ok(g) => ..., Err(e) => ... }`` doesn't fire."""
    sample = tmp_path / "match.rs"
    sample.write_text(
        'use std::sync::Mutex;\nfn run(m: &Mutex<i32>) {\n    match m.lock() {\n        Ok(g) => println!("{}", *g),\n        Err(_) => eprintln!("poisoned"),\n    }\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("lock_poisoning_ignored").check_file(str(sample))
    assert _violations(result, "SAFE205") == []


def test_rust_try_lock_unwrap_fires(tmp_path: Path) -> None:
    """``try_lock().unwrap()`` also fires - it returns ``TryLockResult`` with a poison variant."""
    sample = tmp_path / "trylock.rs"
    sample.write_text(
        "use std::sync::Mutex;\nfn run(m: &Mutex<i32>) {\n    let _g = m.try_lock().unwrap();\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("lock_poisoning_ignored").check_file(str(sample))
    assert len(_violations(result, "SAFE205")) == 1


def test_rust_unrelated_unwrap_does_not_fire(tmp_path: Path) -> None:
    """``parse_number().unwrap()`` doesn't fire - ``parse_number`` isn't a lock method."""
    sample = tmp_path / "unrelated.rs"
    sample.write_text(
        'fn run() -> i32 {\n    "42".parse().unwrap()\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("lock_poisoning_ignored").check_file(str(sample))
    assert _violations(result, "SAFE205") == []


# ---------------------------------------------------------------------------
# SAFE306 - dangerous_mem_ops
# ---------------------------------------------------------------------------


def test_rust_mem_transmute_fires_safe306(tmp_path: Path) -> None:
    """``std::mem::transmute(...)`` fires SAFE306."""
    sample = tmp_path / "transmute.rs"
    sample.write_text(
        "fn run() -> i8 {\n    unsafe { std::mem::transmute::<u8, i8>(0u8) }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    fired = _violations(result, "SAFE306")
    assert len(fired) == 1
    assert "transmute" in fired[0].message


def test_rust_mem_forget_fires_safe306(tmp_path: Path) -> None:
    """``std::mem::forget(x)`` fires SAFE306."""
    sample = tmp_path / "forget.rs"
    sample.write_text(
        "fn run(v: Vec<i32>) {\n    std::mem::forget(v);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    assert len(_violations(result, "SAFE306")) == 1


def test_rust_mem_zeroed_fires_safe306(tmp_path: Path) -> None:
    """``std::mem::zeroed()`` fires SAFE306."""
    sample = tmp_path / "zeroed.rs"
    sample.write_text(
        "fn run() -> u32 {\n    unsafe { std::mem::zeroed() }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    assert len(_violations(result, "SAFE306")) == 1


def test_rust_bare_mem_transmute_via_use_path_fires(tmp_path: Path) -> None:
    """``mem::transmute(...)`` (after ``use std::mem``) also fires - the ``mem::`` prefix matches."""
    sample = tmp_path / "use_mem.rs"
    sample.write_text(
        "use std::mem;\nfn run() -> i8 {\n    unsafe { mem::transmute::<u8, i8>(0u8) }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    assert len(_violations(result, "SAFE306")) == 1


def test_rust_user_defined_transmute_does_not_fire(tmp_path: Path) -> None:
    """A user-defined ``my_helpers::transmute(x)`` doesn't fire - path doesn't contain ``mem``."""
    sample = tmp_path / "user_def.rs"
    sample.write_text(
        "fn run(x: u8) -> i8 {\n    my_helpers::transmute(x)\n}\nmod my_helpers {\n    pub fn transmute(x: u8) -> i8 { x as i8 }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    assert _violations(result, "SAFE306") == []


def test_rust_bare_transmute_call_does_not_fire(tmp_path: Path) -> None:
    """Bare ``transmute(x)`` (no scoped path) doesn't fire - indistinguishable from a local helper."""
    sample = tmp_path / "bare.rs"
    sample.write_text(
        "fn transmute(x: u8) -> i8 { x as i8 }\nfn run(x: u8) -> i8 { transmute(x) }\n",
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    assert _violations(result, "SAFE306") == []


def test_rust_clean_scoped_call_does_not_fire(tmp_path: Path) -> None:
    """Scoped call to non-dangerous fn (``std::fs::read``) doesn't fire SAFE306."""
    sample = tmp_path / "clean_scoped.rs"
    sample.write_text(
        'fn run() {\n    let _ = std::fs::read("/tmp/x");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    assert _violations(result, "SAFE306") == []


def test_rust_core_mem_transmute_also_fires(tmp_path: Path) -> None:
    """``core::mem::transmute`` (no_std variant) also fires - path contains ``mem``."""
    sample = tmp_path / "core_mem.rs"
    sample.write_text(
        "fn run() -> i8 {\n    unsafe { core::mem::transmute::<u8, i8>(0u8) }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("dangerous_mem_ops").check_file(str(sample))
    assert len(_violations(result, "SAFE306")) == 1


# ---------------------------------------------------------------------------
# SAFE602 - undocumented_unsafe
# ---------------------------------------------------------------------------


def test_rust_undocumented_unsafe_fires_safe602(tmp_path: Path) -> None:
    """``unsafe { }`` with no preceding SAFETY comment fires SAFE602."""
    sample = tmp_path / "undoc.rs"
    sample.write_text(
        "fn run() {\n    let x = 1;\n    unsafe {\n        do_stuff();\n    }\n}\nunsafe fn do_stuff() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    fired = _violations(result, "SAFE602")
    assert len(fired) == 1
    assert "SAFETY" in fired[0].message


def test_rust_documented_unsafe_does_not_fire(tmp_path: Path) -> None:
    """A ``// SAFETY:`` comment on the preceding line clears SAFE602."""
    sample = tmp_path / "doc.rs"
    sample.write_text(
        "fn run() {\n    // SAFETY: x is initialised by the caller\n    unsafe {\n        do_stuff();\n    }\n}\nunsafe fn do_stuff() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    assert _violations(result, "SAFE602") == []


def test_rust_safety_comment_case_insensitive(tmp_path: Path) -> None:
    """Both ``// SAFETY:`` and ``// Safety:`` are recognised."""
    sample = tmp_path / "case.rs"
    sample.write_text(
        "fn run() {\n    // Safety: invariants documented in fn docs\n    unsafe {\n        do_stuff();\n    }\n}\nunsafe fn do_stuff() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    assert _violations(result, "SAFE602") == []


def test_rust_block_safety_comment_works(tmp_path: Path) -> None:
    """Block comments ``/* SAFETY: ... */`` also count."""
    sample = tmp_path / "block_comment.rs"
    sample.write_text(
        "fn run() {\n    /* SAFETY: see fn-level docs */\n    unsafe {\n        do_stuff();\n    }\n}\nunsafe fn do_stuff() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    assert _violations(result, "SAFE602") == []


def test_rust_unrelated_preceding_comment_does_not_clear(tmp_path: Path) -> None:
    """A non-SAFETY comment doesn't satisfy the rule."""
    sample = tmp_path / "unrelated.rs"
    sample.write_text(
        "fn run() {\n    // TODO: refactor this\n    unsafe {\n        do_stuff();\n    }\n}\nunsafe fn do_stuff() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    assert len(_violations(result, "SAFE602")) == 1


def test_rust_multiple_unsafe_blocks_independent(tmp_path: Path) -> None:
    """Two unsafe blocks each need their own SAFETY comment.

    The first block has a SAFETY comment; the second does not. Only
    the second should fire.
    """
    sample = tmp_path / "two_blocks.rs"
    sample.write_text(
        "fn run() {\n    // SAFETY: documented\n    unsafe { do_stuff(); }\n    let _x = 1;\n    unsafe { do_stuff(); }\n}\nunsafe fn do_stuff() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    fired = _violations(result, "SAFE602")
    assert len(fired) == 1


def test_rust_safety_with_intervening_comment_still_clears(tmp_path: Path) -> None:
    """SAFETY comment followed by another comment, then unsafe - still clears.

    Walks back through line comments until hitting a non-comment node.
    A SAFETY line with a subsequent annotation comment between it and
    the unsafe block should still be recognised.
    """
    sample = tmp_path / "interleaved.rs"
    sample.write_text(
        "fn run() {\n    // SAFETY: caller upholds invariants\n    // (see RFC link)\n    unsafe {\n        do_stuff();\n    }\n}\nunsafe fn do_stuff() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    assert _violations(result, "SAFE602") == []


def test_rust_non_rust_file_skipped(tmp_path: Path) -> None:
    """Non-Rust files are skipped (engine-level language dispatch)."""
    sample = tmp_path / "x.py"
    sample.write_text("def foo():\n    pass\n", encoding="utf-8")
    result = _enabled_engine("undocumented_unsafe").check_file(str(sample))
    assert _violations(result, "SAFE602") == []
