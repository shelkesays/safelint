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


def test_rust_panic_in_rstest_function_does_not_fire(tmp_path: Path) -> None:
    """``#[rstest]`` (bare) and ``#[rstest::rstest]`` (scoped) clear SAFE204.

    rstest is the most popular parametric-test framework for Rust;
    its attribute doesn't end in ``test`` so trailing-name matching
    alone wouldn't catch it. Both forms are recognised via
    ``_RUST_TEST_ATTRIBUTE_NAMES``.
    """
    sample = tmp_path / "rstest_test.rs"
    sample.write_text(
        '#[rstest]\nfn it_works() {\n    panic!("in an rstest");\n}\n#[rstest::rstest]\nfn it_scoped() {\n    panic!("in scoped rstest");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("panic_macros_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE204") == []


def test_rust_panic_in_tokio_test_function_does_not_fire(tmp_path: Path) -> None:
    """``#[tokio::test]`` (scoped path attribute) is recognised as test context.

    Same shape applies to ``#[actix_web::test]``, ``#[async_std::test]``,
    ``#[smol_potat::test]``, and any other async-test framework that
    suffixes its attribute macro with ``test``. The detection extracts
    the trailing identifier of the ``scoped_identifier`` and matches
    against ``"test"``.
    """
    sample = tmp_path / "tokio_test.rs"
    sample.write_text(
        '#[tokio::test]\nasync fn test_it() {\n    panic!("in a tokio test");\n}\n',
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
# SAFE206 - silent_result_discard
# ---------------------------------------------------------------------------


def test_rust_empty_err_arm_fires_safe206(tmp_path: Path) -> None:
    """``Err(_) => { 0 }`` (single-literal body) fires SAFE206."""
    sample = tmp_path / "empty_err.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) -> i32 {\n    match r {\n        Ok(v) => v,\n        Err(_) => 0,\n    }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("silent_result_discard").check_file(str(sample))
    safe206 = _violations(result, "SAFE206")
    assert len(safe206) == 1
    assert "Err" in safe206[0].message


def test_rust_empty_err_arm_with_binding_fires(tmp_path: Path) -> None:
    """``Err(e) => {}`` also fires - the noop body is the silent part."""
    sample = tmp_path / "empty_err_bind.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(e) => {}\n    }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("silent_result_discard").check_file(str(sample))
    # The Ok(_) arm has Ok pattern, not Err - it doesn't fire.
    # Only Err(e) => {} fires.
    safe206 = _violations(result, "SAFE206")
    assert len(safe206) == 1


def test_rust_handled_err_arm_does_not_fire_safe206(tmp_path: Path) -> None:
    """``Err(e) => cleanup()`` doesn't fire (body is non-empty)."""
    sample = tmp_path / "handled.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(e) => { cleanup(); }\n    }\n}\nfn cleanup() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("silent_result_discard").check_file(str(sample))
    assert _violations(result, "SAFE206") == []


def test_rust_empty_if_let_err_body_fires_safe206(tmp_path: Path) -> None:
    """``if let Err(_) = r {}`` fires SAFE206."""
    sample = tmp_path / "if_let_empty.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    if let Err(_) = r {}\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("silent_result_discard").check_file(str(sample))
    assert len(_violations(result, "SAFE206")) == 1


def test_rust_if_let_ok_with_no_else_does_not_fire(tmp_path: Path) -> None:
    """``if let Ok(v) = r { ... }`` doesn't fire - SAFE206 only flags Err patterns.

    Guards the rule from over-firing on the common ``if let Ok(...)
    = ... { handle }`` idiom where the Err case is intentionally
    skipped (often handled elsewhere or not relevant).
    """
    sample = tmp_path / "if_let_ok.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    if let Ok(v) = r { process(v); }\n}\nfn process(_v: i32) {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("silent_result_discard").check_file(str(sample))
    assert _violations(result, "SAFE206") == []


def test_rust_non_err_patterns_and_plain_if_do_not_fire(tmp_path: Path) -> None:
    """Match arms with non-Err patterns and plain ``if cond`` aren't flagged.

    Guards SAFE206 / SAFE207 against firing on:
    * Literal-pattern arms (``0 => ...``)
    * Wildcard arms (``_ => ...``)
    * Plain ``if cond { ... }`` (no ``let``)
    * Match arms whose pattern is bare ``Ok(_)`` rather than ``Err(_)``

    Exercises the early-return branches in ``_is_err_pattern`` (non
    tuple_struct_pattern) and ``_if_let_err_pattern_and_body`` (no
    let_condition).
    """
    sample = tmp_path / "non_err.rs"
    sample.write_text(
        "fn run(x: i32, r: Result<i32, String>) {\n"
        "    match x {\n"
        "        0 => {},\n"
        "        _ => {},\n"
        "    }\n"
        "    if x > 0 {\n"
        "        process();\n"
        "    }\n"
        "    match r {\n"
        "        Ok(_) => {},\n"
        "        Err(e) => { cleanup(e); }\n"
        "    }\n"
        "}\n"
        "fn process() {}\n"
        "fn cleanup(_e: String) {}\n",
        encoding="utf-8",
    )
    # Both rules are checked - the only firing case is SAFE207 on
    # the Err(e) arm with cleanup() (no log, no return, no panic).
    safe206_result = _enabled_engine("silent_result_discard").check_file(str(sample))
    safe207_result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert _violations(safe206_result, "SAFE206") == []
    assert len(_violations(safe207_result, "SAFE207")) == 1


def test_rust_block_with_single_literal_noop_fires(tmp_path: Path) -> None:
    """``Err(_) => { 0 }`` (block containing a single literal) counts as noop and fires SAFE206.

    Exercises ``_block_is_noop`` paths that the tail-form
    literal test doesn't reach.
    """
    sample = tmp_path / "block_literal.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) -> i32 {\n    match r {\n        Ok(v) => v,\n        Err(_) => { 0 }\n    }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("silent_result_discard").check_file(str(sample))
    assert len(_violations(result, "SAFE206")) == 1


def test_rust_let_underscore_assign_does_not_fire(tmp_path: Path) -> None:
    """``let _ = r;`` doesn't fire - explicit auditable discard, not silent.

    The idiomatic Rust way to explicitly disclaim caring about a
    Result is ``let _ = ...``. SAFE206 deliberately doesn't fire on
    this because it's MORE auditable than the empty Err arm
    pattern - the ``_`` is visible at the use site.
    """
    sample = tmp_path / "let_discard.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    let _ = r;\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("silent_result_discard").check_file(str(sample))
    assert _violations(result, "SAFE206") == []


# ---------------------------------------------------------------------------
# SAFE207 - unlogged_error_branch
# ---------------------------------------------------------------------------


def test_rust_err_arm_without_log_fires_safe207(tmp_path: Path) -> None:
    """``Err(e) => { cleanup(); }`` (no log call) fires SAFE207."""
    sample = tmp_path / "unlogged.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(e) => { cleanup(); }\n    }\n}\nfn cleanup() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    safe207 = _violations(result, "SAFE207")
    assert len(safe207) == 1
    assert "log" in safe207[0].message.lower() or "log::error" in safe207[0].message


def test_rust_err_arm_with_log_does_not_fire(tmp_path: Path) -> None:
    """``Err(e) => { log::error!(...) }`` doesn't fire."""
    sample = tmp_path / "logged.rs"
    sample.write_text(
        'fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(e) => { log::error!("{}", e); }\n    }\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert _violations(result, "SAFE207") == []


def test_rust_err_arm_with_eprintln_does_not_fire(tmp_path: Path) -> None:
    """``Err(e) => { eprintln!(...) }`` doesn't fire - eprintln is in log set."""
    sample = tmp_path / "eprintln.rs"
    sample.write_text(
        'fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(e) => { eprintln!("oops: {}", e); }\n    }\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert _violations(result, "SAFE207") == []


def test_rust_err_arm_with_return_does_not_fire(tmp_path: Path) -> None:
    """``Err(e) => { return; }`` doesn't fire - early return is an explicit response."""
    sample = tmp_path / "return.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(_e) => { return; }\n    }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert _violations(result, "SAFE207") == []


def test_rust_err_arm_with_panic_does_not_fire(tmp_path: Path) -> None:
    """``Err(e) => panic!(...)`` doesn't fire - panic makes the failure loud."""
    sample = tmp_path / "panic.rs"
    sample.write_text(
        'fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(e) => panic!("fatal: {}", e),\n    }\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert _violations(result, "SAFE207") == []


def test_rust_err_arm_with_err_tail_does_not_fire(tmp_path: Path) -> None:
    """``Err(e) => Err(e)`` (re-raise pattern) doesn't fire - error is propagated."""
    sample = tmp_path / "rethrow.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) -> Result<i32, String> {\n    match r {\n        Ok(v) => Ok(v + 1),\n        Err(e) => Err(e),\n    }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert _violations(result, "SAFE207") == []


def test_rust_if_let_err_without_log_fires_safe207(tmp_path: Path) -> None:
    """``if let Err(e) = r { cleanup(); }`` fires SAFE207."""
    sample = tmp_path / "if_let_unlogged.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    if let Err(_e) = r {\n        cleanup();\n    }\n}\nfn cleanup() {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert len(_violations(result, "SAFE207")) == 1


def test_rust_empty_err_body_does_not_fire_safe207(tmp_path: Path) -> None:
    """Empty Err bodies are SAFE206 territory; SAFE207 stays quiet on them."""
    sample = tmp_path / "empty_err_body.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(_) => {}\n    }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert _violations(result, "SAFE207") == []


def test_rust_log_call_inside_nested_closure_does_not_satisfy(tmp_path: Path) -> None:
    """A log call inside a closure inside the Err branch doesn't satisfy SAFE207.

    The closure may never run synchronously (or at all). The
    ``_body_has_log_call`` helper skips nested function / closure
    bodies for this reason.
    """
    sample = tmp_path / "nested_closure.rs"
    sample.write_text(
        'fn run(r: Result<i32, String>) {\n    match r {\n        Ok(_) => {},\n        Err(e) => { let _f = || log::error!("{}", e); cleanup(); }\n    }\n}\nfn cleanup() {}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("unlogged_error_branch").check_file(str(sample))
    assert len(_violations(result, "SAFE207")) == 1


# ---------------------------------------------------------------------------
# SAFE208 - result_unwrap_outside_tests
# ---------------------------------------------------------------------------


def test_rust_bare_unwrap_outside_tests_fires_safe208(tmp_path: Path) -> None:
    """``r.unwrap()`` outside tests fires SAFE208."""
    sample = tmp_path / "unwrap208.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) -> i32 {\n    r.unwrap()\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("result_unwrap_outside_tests").check_file(str(sample))
    fired = _violations(result, "SAFE208")
    assert len(fired) == 1
    assert "unwrap" in fired[0].message


def test_rust_expect_outside_tests_fires_safe208(tmp_path: Path) -> None:
    """``.expect(...)`` also fires."""
    sample = tmp_path / "expect208.rs"
    sample.write_text(
        'fn run(r: Result<i32, String>) -> i32 {\n    r.expect("must not fail")\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("result_unwrap_outside_tests").check_file(str(sample))
    assert len(_violations(result, "SAFE208")) == 1


def test_rust_unwrap_in_test_function_does_not_fire_safe208(tmp_path: Path) -> None:
    """``#[test] fn foo() { r.unwrap() }`` doesn't fire - tests get panic behaviour."""
    sample = tmp_path / "test_unwrap208.rs"
    sample.write_text(
        "#[test]\nfn test_it() {\n    let r: Result<i32, ()> = Ok(1);\n    let _v = r.unwrap();\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("result_unwrap_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE208") == []


def test_rust_unwrap_in_cfg_test_mod_does_not_fire_safe208(tmp_path: Path) -> None:
    """``#[cfg(test)] mod tests`` exempts ``.unwrap()`` inside."""
    sample = tmp_path / "cfg_test_unwrap.rs"
    sample.write_text(
        "#[cfg(test)]\nmod tests {\n    fn helper(r: Result<i32, ()>) -> i32 {\n        r.unwrap()\n    }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("result_unwrap_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE208") == []


def test_rust_unwrap_or_does_not_fire_safe208(tmp_path: Path) -> None:
    """``.unwrap_or(default)`` is explicit-default-on-Err and doesn't fire."""
    sample = tmp_path / "unwrap_or.rs"
    sample.write_text(
        "fn run(r: Result<i32, String>) -> i32 {\n    r.unwrap_or(0)\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("result_unwrap_outside_tests").check_file(str(sample))
    assert _violations(result, "SAFE208") == []


# ---------------------------------------------------------------------------
# SAFE110 - needless_mut
# ---------------------------------------------------------------------------


def test_rust_let_mut_never_reassigned_fires_safe110(tmp_path: Path) -> None:
    """``let mut x = 5; println!("{}", x);`` fires - x never reassigned."""
    sample = tmp_path / "needless.rs"
    sample.write_text(
        'fn run() {\n    let mut x = 5;\n    println!("{}", x);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("needless_mut").check_file(str(sample))
    fired = _violations(result, "SAFE110")
    assert len(fired) == 1
    assert "mut x" in fired[0].message


def test_rust_let_mut_reassigned_does_not_fire(tmp_path: Path) -> None:
    """``let mut x = 5; x = 10;`` doesn't fire - x IS reassigned."""
    sample = tmp_path / "reassigned.rs"
    sample.write_text(
        "fn run() {\n    let mut x = 5;\n    x = 10;\n    let _y = x;\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("needless_mut").check_file(str(sample))
    assert _violations(result, "SAFE110") == []


def test_rust_let_mut_compound_assignment_does_not_fire(tmp_path: Path) -> None:
    """``let mut x = 5; x += 1;`` doesn't fire - compound assignment counts."""
    sample = tmp_path / "compound.rs"
    sample.write_text(
        "fn run() {\n    let mut x = 5;\n    x += 1;\n    let _y = x;\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("needless_mut").check_file(str(sample))
    assert _violations(result, "SAFE110") == []


def test_rust_let_mut_method_call_does_not_fire(tmp_path: Path) -> None:
    """``let mut v = Vec::new(); v.push(1);`` doesn't fire - method may take &mut self."""
    sample = tmp_path / "method110.rs"
    sample.write_text(
        "fn run() {\n    let mut v = Vec::new();\n    v.push(1);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("needless_mut").check_file(str(sample))
    assert _violations(result, "SAFE110") == []


def test_rust_let_mut_mut_reference_does_not_fire(tmp_path: Path) -> None:
    """``let mut x = 5; consume(&mut x);`` doesn't fire - &mut x needs mut."""
    sample = tmp_path / "mut_ref.rs"
    sample.write_text(
        "fn run() {\n    let mut x = 5;\n    consume(&mut x);\n}\nfn consume(_x: &mut i32) {}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("needless_mut").check_file(str(sample))
    assert _violations(result, "SAFE110") == []


def test_rust_let_without_mut_does_not_fire_safe110(tmp_path: Path) -> None:
    """``let x = 5;`` (no mut) doesn't fire - the rule only flags mut bindings."""
    sample = tmp_path / "immut.rs"
    sample.write_text(
        'fn run() {\n    let x = 5;\n    println!("{}", x);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("needless_mut").check_file(str(sample))
    assert _violations(result, "SAFE110") == []


# ---------------------------------------------------------------------------
# SAFE112 - unchecked_arithmetic_on_input
# ---------------------------------------------------------------------------


def test_rust_arithmetic_on_int_param_fires_safe112(tmp_path: Path) -> None:
    """``fn run(a: u32, b: u32) -> u32 { a + b }`` fires SAFE112."""
    sample = tmp_path / "arith.rs"
    sample.write_text(
        "fn run(a: u32, b: u32) -> u32 {\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    fired = _violations(result, "SAFE112")
    assert len(fired) >= 1
    assert "+" in fired[0].message
    assert "checked_add" in fired[0].message


def test_rust_subtraction_on_int_param_fires(tmp_path: Path) -> None:
    """``fn run(a: i64, b: i64) -> i64 { a - b }`` fires."""
    sample = tmp_path / "sub.rs"
    sample.write_text(
        "fn run(a: i64, b: i64) -> i64 {\n    a - b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    assert len(_violations(result, "SAFE112")) >= 1


def test_rust_division_on_int_param_does_not_fire(tmp_path: Path) -> None:
    """``/`` is deliberately excluded - division-by-zero is a separate hazard."""
    sample = tmp_path / "div.rs"
    sample.write_text(
        "fn run(a: u32, b: u32) -> u32 {\n    a / b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    assert _violations(result, "SAFE112") == []


def test_rust_arithmetic_on_string_param_does_not_fire(tmp_path: Path) -> None:
    """``fn run(s: String) -> usize { s.len() + 1 }`` doesn't fire on s (not integer)."""
    sample = tmp_path / "non_int.rs"
    sample.write_text(
        "fn run(s: String) -> usize {\n    s.len() + 1\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    # ``s.len() + 1`` - neither operand is the int param ``s`` (left is method call).
    # So no fire even though there's a ``+``.
    assert _violations(result, "SAFE112") == []


def test_rust_arithmetic_on_local_does_not_fire_safe112(tmp_path: Path) -> None:
    """Arithmetic on locals (not params) doesn't fire."""
    sample = tmp_path / "local.rs"
    sample.write_text(
        "fn run() -> u32 {\n    let a: u32 = 5;\n    let b: u32 = 10;\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    assert _violations(result, "SAFE112") == []


def test_rust_float_param_arithmetic_does_not_fire(tmp_path: Path) -> None:
    """Float parameters aren't flagged - SAFE112 only targets integer overflow.

    ``f32`` / ``f64`` are primitive_type but not in the integer set;
    ``_integer_param_names`` skips them. Float arithmetic has its
    own hazards (NaN, infinity, precision) but they're a different
    category than silent integer overflow.
    """
    sample = tmp_path / "float.rs"
    sample.write_text(
        "fn run(a: f64, b: f64) -> f64 {\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    assert _violations(result, "SAFE112") == []


def test_rust_tuple_destructure_param_not_checked(tmp_path: Path) -> None:
    """Tuple-destructured params aren't analysed - their pattern isn't a plain identifier.

    ``fn f((a, b): (u32, u32))`` parses with pattern = tuple_pattern,
    not identifier, so SAFE112's name lookup skips it. Documented
    heuristic limitation rather than a bug.
    """
    sample = tmp_path / "tuple_param.rs"
    sample.write_text(
        "fn run((a, b): (u32, u32)) -> u32 {\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    assert _violations(result, "SAFE112") == []


def test_rust_param_with_literal_arithmetic_fires(tmp_path: Path) -> None:
    """``fn run(a: u32) -> u32 { a + 1 }`` fires - param-and-literal still flagged."""
    sample = tmp_path / "param_lit.rs"
    sample.write_text(
        "fn run(a: u32) -> u32 {\n    a + 1\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("unchecked_arithmetic_on_input").check_file(str(sample))
    assert len(_violations(result, "SAFE112")) == 1


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
# SAFE308 - truncating_as_cast
# ---------------------------------------------------------------------------


def test_rust_as_u8_cast_fires_safe308(tmp_path: Path) -> None:
    """``big as u8`` fires SAFE308 - silent truncation hazard."""
    sample = tmp_path / "trunc.rs"
    sample.write_text(
        "fn run(big: u64) -> u8 {\n    big as u8\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("truncating_as_cast").check_file(str(sample))
    fired = _violations(result, "SAFE308")
    assert len(fired) == 1
    assert "as u8" in fired[0].message
    assert "try_from" in fired[0].message


def test_rust_as_i32_cast_fires_safe308(tmp_path: Path) -> None:
    """``f as i32`` fires - float-to-int is truncating."""
    sample = tmp_path / "f_to_i.rs"
    sample.write_text(
        "fn run(f: f64) -> i32 {\n    f as i32\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("truncating_as_cast").check_file(str(sample))
    assert len(_violations(result, "SAFE308")) == 1


def test_rust_as_usize_does_not_fire_safe308(tmp_path: Path) -> None:
    """``as usize`` doesn't fire - usize isn't in the truncating-target set (widest type on 64-bit)."""
    sample = tmp_path / "usize.rs"
    sample.write_text(
        "fn run(x: u32) -> usize {\n    x as usize\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("truncating_as_cast").check_file(str(sample))
    assert _violations(result, "SAFE308") == []


def test_rust_as_i128_does_not_fire_safe308(tmp_path: Path) -> None:
    """``as i128`` doesn't fire - widest signed type, casts to it don't truncate."""
    sample = tmp_path / "i128.rs"
    sample.write_text(
        "fn run(x: i64) -> i128 {\n    x as i128\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("truncating_as_cast").check_file(str(sample))
    assert _violations(result, "SAFE308") == []


def test_rust_cast_to_reference_type_does_not_fire(tmp_path: Path) -> None:
    """``ptr as &T`` (reference cast) doesn't fire - target isn't a primitive_type."""
    sample = tmp_path / "ref_cast.rs"
    sample.write_text(
        "fn run(p: *const u8) -> *const i8 {\n    p as *const i8\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("truncating_as_cast").check_file(str(sample))
    # ``*const i8`` is a pointer_type, not primitive_type, so no fire.
    assert _violations(result, "SAFE308") == []


def test_rust_truncating_cast_targets_configurable(tmp_path: Path) -> None:
    """Custom ``truncating_cast_targets_rust`` overrides the default set."""
    sample = tmp_path / "configurable.rs"
    sample.write_text(
        "fn run(x: u64) -> u8 {\n    x as u8\n}\nfn run2(x: u32) -> i32 {\n    x as i32\n}\n",
        encoding="utf-8",
    )
    overrides = {
        "rules": {
            "truncating_as_cast": {
                # Only flag casts to i32; tolerate u8.
                "truncating_cast_targets_rust": ["i32"],
            },
        },
    }
    result = _enabled_engine("truncating_as_cast", overrides).check_file(str(sample))
    fired = _violations(result, "SAFE308")
    # Only the ``as i32`` cast fires; ``as u8`` is now excluded.
    assert len(fired) == 1
    assert "as i32" in fired[0].message


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
