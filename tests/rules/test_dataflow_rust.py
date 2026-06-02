"""Tests for ``tainted_sink`` (SAFE801), ``return_value_ignored`` (SAFE802),
and ``null_dereference`` (SAFE803) on Rust files.

Rust-specific cases worth calling out:

* ``let x = value`` is the binding form (``let_declaration``), not
  ``const`` / ``let`` like JavaScript; the Rust tracker propagates
  taint through it the same way.
* Method calls (``cmd.arg(tainted)``) and qualified path calls
  (``Command::new("echo").arg(tainted)``) both resolve via ``call_name``'s
  ``field_expression`` and ``scoped_identifier`` branches.
* The default sink list focuses on stdlib: ``Command``, ``arg``,
  ``args``, the ``query`` family for raw-SQL crates, ``open`` for
  filesystem paths, ``Library`` for FFI loading.
* Sources are trimmed to call names whose RETURN value carries
  user data: ``var`` (``env::var``) and ``read_to_string``
  (``std::fs::read_to_string``). Out-parameter / count-returning
  calls (``read_line``, ``recv``, ``recv_from``, ``lock``) and
  bareword-colliding builders (``args`` vs ``Command::args``)
  are intentionally NOT in defaults.
* Macros (``println!`` / ``sqlx::query!``) are NOT modelled - a
  known limitation documented in CONFIGURATION.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _enabled_engine(rule: str, overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with the given dataflow rule enabled (off by default)."""
    base = {"rules": {rule: {"enabled": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config)


# ---------------------------------------------------------------------------
# SAFE801 - tainted_sink
# ---------------------------------------------------------------------------


def test_rust_direct_param_to_command_arg_fires(tmp_path: Path) -> None:
    """``Command::new("echo").arg(tainted)`` fires SAFE801.

    Direct ``Command::new(tainted)`` detection is deliberately NOT in
    the default ``sinks_rust`` set because ``call_name()`` reduces all
    ``Type::new(...)`` to the bareword ``"new"`` (would also fire on
    ``String::new`` / ``Vec::new`` / etc.). The practical detection
    path is ``.arg(tainted)`` - which is also the idiomatic call shape
    since the program name in ``Command::new`` is almost always a
    literal.
    """
    sample = tmp_path / "cmd.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    Command::new("echo").arg(user_input);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    safe801 = [v for v in result.violations if v.code == "SAFE801"]
    assert len(safe801) >= 1
    assert "user_input" in safe801[0].message
    assert "arg" in safe801[0].message


def test_rust_taint_through_let_binding_fires(tmp_path: Path) -> None:
    """``let y = tainted; Command::new("echo").arg(y);`` propagates taint."""
    sample = tmp_path / "let.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let y = user_input;\n    Command::new("echo").arg(y);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_taint_through_assignment_fires(tmp_path: Path) -> None:
    """``y = tainted`` (assignment_expression) propagates taint."""
    sample = tmp_path / "assign.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let mut y = String::new();\n    y = user_input;\n    Command::new("echo").arg(y);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_method_call_sink_fires(tmp_path: Path) -> None:
    """``cmd.arg(tainted)`` fires SAFE801 - method call resolves via field_expression."""
    sample = tmp_path / "arg.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let mut cmd = Command::new("echo");\n    cmd.arg(user_input);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    safe801 = [v for v in result.violations if v.code == "SAFE801"]
    assert len(safe801) >= 1
    assert "arg" in safe801[0].message


def test_rust_sanitised_value_does_not_fire(tmp_path: Path) -> None:
    """``validate(tainted)`` clears taint and downstream sink doesn't fire."""
    sample = tmp_path / "san.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let y = validate(user_input);\n    Command::new("echo").arg(y);\n}\nfn validate(s: String) -> String { s }\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_rust_clean_param_does_not_fire(tmp_path: Path) -> None:
    """A parameter not flowing to a sink doesn't fire."""
    sample = tmp_path / "clean.rs"
    sample.write_text(
        "fn add(a: i32, b: i32) -> i32 { a + b }\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_rust_source_call_to_sink_fires(tmp_path: Path) -> None:
    """``std::env::var("KEY").unwrap()`` flowing into ``Command::new`` fires.

    Tests the source-call code path end-to-end with a real-world source
    shape:

    * ``std::env::var(...)`` is a scoped path; ``call_name`` extracts
      the trailing bareword ``"var"``, which matches the default
      ``sources_rust`` entry and marks the call's return as tainted.
    * The chained ``.unwrap()`` is a method call whose receiver is the
      tainted ``std::env::var(...)`` call. The receiver-aware taint
      check in ``_call_tainted`` propagates taint through, so the
      ``unwrap()`` result is tainted too.
    * ``Command::new("echo").arg(tainted)`` is the downstream sink.

    Earlier versions of this test used a local ``fn var() -> String``
    stub because the tracker didn't yet propagate taint through method
    chains. That limitation was lifted by the receiver-taint fix, so
    the test now exercises the production source shape directly.
    """
    sample = tmp_path / "source.rs"
    sample.write_text(
        'use std::process::Command;\nfn run() {\n    let user_input = std::env::var("USER_INPUT").unwrap();\n    Command::new("echo").arg(user_input);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_tuple_destructure_param_taints(tmp_path: Path) -> None:
    """``fn f((a, b): (String, String)) - both ``a`` and ``b`` are tainted entry points."""
    sample = tmp_path / "tuple_param.rs"
    sample.write_text(
        'use std::process::Command;\nfn run((user_input, _other): (String, i32)) {\n    Command::new("echo").arg(user_input);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_destructuring_assignment_propagates_taint(tmp_path: Path) -> None:
    """Rust 1.59+ destructuring assignment ``(a, b) = (tainted, _);`` propagates taint.

    The LHS of an ``assignment_expression`` here is a ``tuple_expression``
    (not a ``tuple_pattern`` like in ``let (a, b) = ...``), so
    ``_iter_pattern_identifiers`` must walk the same way through both
    shapes. Without ``tuple_expression`` in the recurse set, ``a`` would
    never be marked tainted and the downstream sink would silently pass.
    """
    sample = tmp_path / "destructure_assign.rs"
    sample.write_text(
        "use std::process::Command;\n"
        "fn run(user_input: String) {\n"
        "    let mut a = String::new();\n"
        "    let mut b = String::new();\n"
        '    (a, b) = (user_input, String::from("clean"));\n'
        '    Command::new("echo").arg(a);\n'
        "}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations), "Destructuring assignment LHS (tuple_expression) must rebind taint on its identifiers"


def test_rust_taint_through_reference_propagates(tmp_path: Path) -> None:
    """``&tainted`` keeps the value tainted - reference is a pass-through."""
    sample = tmp_path / "ref.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let y = &user_input;\n    Command::new("echo").arg(y);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_taint_through_try_expression_propagates(tmp_path: Path) -> None:
    """``tainted?`` carries taint (the ``?`` operator returns the Ok value)."""
    sample = tmp_path / "try.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: Result<String, std::io::Error>) -> Result<(), std::io::Error> {\n    let y = user_input?;\n    Command::new("echo").arg(y);\n    Ok(())\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


# ---------------------------------------------------------------------------
# SAFE802 - return_value_ignored
# ---------------------------------------------------------------------------


def test_rust_bare_write_call_fires_safe802(tmp_path: Path) -> None:
    """``file.write(buf);`` (bare expression statement) fires SAFE802.

    Rust's ``io::Write::write`` returns ``Result<usize>`` carrying
    failure information; ignoring it silently swallows I/O errors.
    """
    sample = tmp_path / "write.rs"
    sample.write_text(
        "use std::io::Write;\nfn run(mut f: std::fs::File, buf: &[u8]) {\n    f.write(buf);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    safe802 = [v for v in result.violations if v.code == "SAFE802"]
    assert len(safe802) == 1


def test_rust_bare_spawn_call_fires_safe802(tmp_path: Path) -> None:
    """``cmd.spawn();`` discards the Child / Result and fires SAFE802."""
    sample = tmp_path / "spawn.rs"
    sample.write_text(
        'use std::process::Command;\nfn run() {\n    Command::new("echo").spawn();\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    assert any(v.code == "SAFE802" for v in result.violations)


def test_rust_assigned_write_does_not_fire(tmp_path: Path) -> None:
    """``let n = f.write(buf);`` doesn't fire - the result is bound, not discarded."""
    sample = tmp_path / "assigned.rs"
    sample.write_text(
        "use std::io::Write;\nfn run(mut f: std::fs::File, buf: &[u8]) {\n    let _ = f.write(buf);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    assert not any(v.code == "SAFE802" for v in result.violations)


def test_rust_unflagged_call_does_not_fire(tmp_path: Path) -> None:
    """A bare call to a non-flagged function doesn't fire."""
    sample = tmp_path / "unflagged.rs"
    sample.write_text("fn run() { println(); }\nfn println() {}\n", encoding="utf-8")
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    assert not any(v.code == "SAFE802" for v in result.violations)


def test_rust_compound_assignment_propagates_taint(tmp_path: Path) -> None:
    """``buf += tainted`` propagates taint to ``buf`` via compound_assignment_expr."""
    sample = tmp_path / "compound.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let mut buf = String::new();\n    buf += &user_input;\n    Command::new("echo").arg(buf);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_struct_destructure_param_taints(tmp_path: Path) -> None:
    """``fn f(Point { x, y }: Point)`` - struct-destructured params taint both fields."""
    sample = tmp_path / "struct_param.rs"
    sample.write_text(
        'use std::process::Command;\nstruct Cfg { cmd: String, other: i32 }\nfn run(Cfg { cmd, other: _ }: Cfg) {\n    Command::new("echo").arg(cmd);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_let_without_init_clears_shadowed_taint(tmp_path: Path) -> None:
    """``let x;`` re-binds untainted; downstream sink with that ``x`` doesn't fire."""
    sample = tmp_path / "let_no_init.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let user_input: String;\n    user_input = "echo".to_string();\n    Command::new("echo").arg(user_input);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_rust_field_expression_preserves_taint(tmp_path: Path) -> None:
    """``tainted.field`` keeps taint; ``Command::new("echo").arg(t.field)`` fires."""
    sample = tmp_path / "field.rs"
    sample.write_text(
        'use std::process::Command;\nstruct Req { path: String }\nfn run(t: Req) {\n    Command::new("echo").arg(t.path);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_method_call_on_tainted_receiver_preserves_taint(tmp_path: Path) -> None:
    """``tainted.trim()`` keeps taint; the receiver flows through the call result.

    Pins the receiver-taint path in ``RustTaintTracker._call_tainted``:
    method calls with zero positional arguments (``.trim()``, ``.clone()``,
    ``.to_string()``) historically read as "no taint to check" because the
    inspection only looked at positional args. The fix inspects the
    receiver too; this test ensures the SAFE801 sink fires.
    """
    sample = tmp_path / "receiver_method.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    Command::new("echo").arg(user_input.trim());\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_method_call_chain_on_tainted_receiver_preserves_taint(tmp_path: Path) -> None:
    """``tainted.trim().to_string()`` keeps taint across a method chain.

    Recursive ``_is_tainted`` on the inner ``call_expression`` keeps the
    receiver-taint check working at every link in a method chain.
    """
    sample = tmp_path / "receiver_chain.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let cleaned = user_input.trim().to_string();\n    Command::new("echo").arg(cleaned);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_method_call_on_clean_receiver_stays_clean(tmp_path: Path) -> None:
    """A literal receiver (``"foo".to_string()``) doesn't taint the sink.

    Guards against the receiver-taint fix over-firing: only *tainted*
    receivers propagate; clean ones (string literals, locally-constructed
    values) must not trip SAFE801.
    """
    sample = tmp_path / "receiver_clean.rs"
    sample.write_text(
        'use std::process::Command;\nfn run() {\n    Command::new("echo").arg("hello".to_string().trim());\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_rust_method_call_on_tainted_receiver_assume_false_drops_taint(tmp_path: Path) -> None:
    """With ``assume_taint_preserving = false``, receiver method calls drop taint.

    The receiver-inspection only fires inside the
    ``assume_taint_preserving=True`` branch, so disabling that knob must
    still produce the documented "unknown calls return clean" behaviour.
    """
    sample = tmp_path / "receiver_assume_false.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    Command::new("echo").arg(user_input.trim());\n}\n',
        encoding="utf-8",
    )
    overrides = {"rules": {"tainted_sink": {"assume_taint_preserving": False}}}
    result = _enabled_engine("tainted_sink", overrides).check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_rust_array_literal_with_tainted_element_propagates(tmp_path: Path) -> None:
    """``[tainted, clean]`` propagates taint to the array."""
    sample = tmp_path / "array.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let args = [user_input, "clean".to_string()];\n    Command::new("echo").arg(&args[0]);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_assume_taint_preserving_false_drops_taint(tmp_path: Path) -> None:
    """With ``assume_taint_preserving = false``, unknown calls return clean."""
    sample = tmp_path / "assume.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let y = wrap(user_input);\n    Command::new("echo").arg(y);\n}\nfn wrap(s: String) -> String { s }\n',
        encoding="utf-8",
    )
    overrides = {
        "rules": {
            "tainted_sink": {"assume_taint_preserving": False},
        },
    }
    result = _enabled_engine("tainted_sink", overrides).check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_rust_sink_with_non_identifier_arg_records_expr(tmp_path: Path) -> None:
    """Tainted non-identifier expression (``Command::new("echo").arg(tainted + "x")``) records ``<expr>``."""
    sample = tmp_path / "expr_arg.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    Command::new("echo").arg(user_input + "x");\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    safe801 = [v for v in result.violations if v.code == "SAFE801"]
    assert any("<expr>" in v.message for v in safe801)


def test_rust_nested_closure_isolated(tmp_path: Path) -> None:
    """Closure body is analysed separately; the closure's param doesn't taint the enclosing fn."""
    sample = tmp_path / "closure.rs"
    sample.write_text(
        'use std::process::Command;\nfn run() {\n    let h = |user_input: String| {\n        Command::new("echo").arg(user_input);\n    };\n    h("echo".to_string());\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    # The closure body fires (its parameter is tainted and flows to a sink).
    safe801 = [v for v in result.violations if v.code == "SAFE801"]
    assert len(safe801) >= 1


def test_rust_closure_captures_enclosing_tainted_local(tmp_path: Path) -> None:
    """A closure body referencing an enclosing-scope tainted local fires SAFE801.

    Pins the closure-seeding contract in ``_rust_check``: the closure
    parameter list doesn't carry ``user_input``, but it's captured from
    the outer ``fn run(user_input: String)``. Pass 1 caches ``run``'s
    tainted set; pass 2 seeds the closure with that set + its own params.
    Without the seeding step, the closure's reference to ``user_input``
    looks like a free variable and SAFE801 never fires.
    """
    sample = tmp_path / "closure_capture.rs"
    sample.write_text(
        "use std::process::Command;\n"
        "fn run(user_input: String) {\n"
        "    let items = vec![1, 2, 3];\n"
        "    items.iter().for_each(|_| {\n"
        '        Command::new("echo").arg(user_input.clone());\n'
        "    });\n"
        "}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations), "Closure must inherit ``user_input`` taint from the enclosing function's parameter list"


def test_rust_nested_closure_inherits_outer_closure_taint(tmp_path: Path) -> None:
    """Inner closures inherit taint transitively through outer closures.

    Pass 2 caches each closure's final tainted set when it's analysed,
    so an inner closure reached later in the same walk picks up the
    outer closure's tainted set via ``_rust_closure_enclosing_tainted``.
    Verifies the cache-propagation contract.
    """
    sample = tmp_path / "closure_nested_capture.rs"
    sample.write_text(
        "use std::process::Command;\n"
        "fn run(user_input: String) {\n"
        "    let outer = |_x: i32| {\n"
        "        let inner = |_y: i32| {\n"
        '            Command::new("echo").arg(user_input.clone());\n'
        "        };\n"
        "        inner(1);\n"
        "    };\n"
        "    outer(0);\n"
        "}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_closure_in_clean_function_stays_clean(tmp_path: Path) -> None:
    """A closure inside a function with no tainted params doesn't fire on a literal sink arg.

    Guards against the closure-seeding fix over-firing: when the
    enclosing scope has nothing tainted, the closure's seed must be
    its own params only - a closure passing a string literal to
    ``Command::new("...").arg(...)`` should stay clean.
    """
    sample = tmp_path / "closure_clean.rs"
    sample.write_text(
        'use std::process::Command;\nfn run() {\n    let items = vec![1, 2, 3];\n    items.iter().for_each(|_| {\n        Command::new("echo").arg("constant");\n    });\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


# ---------------------------------------------------------------------------
# SAFE803 - null_dereference (Rust: ``.unwrap()`` / ``.expect()``)
# ---------------------------------------------------------------------------


def test_rust_unwrap_on_map_get_fires_safe803(tmp_path: Path) -> None:
    """``map.get(&k).unwrap()`` fires - ``HashMap::get`` returns ``Option<&V>``.

    Headline case: unwrapping a missing-key lookup panics at runtime.
    Safer alternatives surfaced in the message: ``if let Some(v) =``
    or ``match``.
    """
    sample = tmp_path / "map_unwrap.rs"
    sample.write_text(
        "use std::collections::HashMap;\nfn run(map: &HashMap<String, i32>, k: &str) -> i32 {\n    *map.get(k).unwrap()\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    safe803 = [v for v in result.violations if v.code == "SAFE803"]
    assert len(safe803) == 1
    assert "get" in safe803[0].message


def test_rust_expect_on_parse_fires_safe803(tmp_path: Path) -> None:
    """``"42".parse::<i32>().expect("...")`` fires - parse returns Result."""
    sample = tmp_path / "parse_expect.rs"
    sample.write_text(
        'fn run(s: &str) -> i32 {\n    s.parse().expect("not an int")\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    safe803 = [v for v in result.violations if v.code == "SAFE803"]
    assert len(safe803) == 1
    assert "parse" in safe803[0].message


def test_rust_if_let_guard_does_not_fire(tmp_path: Path) -> None:
    """``if let Some(v) = map.get(&k) { ... }`` is the safe form - no fire."""
    sample = tmp_path / "if_let.rs"
    sample.write_text(
        "use std::collections::HashMap;\nfn run(map: &HashMap<String, i32>, k: &str) -> i32 {\n    if let Some(v) = map.get(k) { *v } else { 0 }\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert not any(v.code == "SAFE803" for v in result.violations)


def test_rust_unwrap_on_unflagged_call_does_not_fire(tmp_path: Path) -> None:
    """``some_clean_call().unwrap()`` doesn't fire when the inner call isn't in the nullable set."""
    sample = tmp_path / "clean_unwrap.rs"
    sample.write_text(
        "fn run() -> i32 {\n    pure_helper().unwrap()\n}\nfn pure_helper() -> Result<i32, ()> { Ok(1) }\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert not any(v.code == "SAFE803" for v in result.violations)


def test_rust_unwrap_with_reference_peel_fires(tmp_path: Path) -> None:
    """``(&map.get(&k)).unwrap()`` still fires - reference is a pass-through wrapper."""
    sample = tmp_path / "ref_unwrap.rs"
    sample.write_text(
        "use std::collections::HashMap;\nfn run(map: &HashMap<String, i32>, k: &str) -> i32 {\n    *(&map.get(k)).unwrap().clone()\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert any(v.code == "SAFE803" for v in result.violations)


def test_rust_unwrap_on_iterator_next_fires(tmp_path: Path) -> None:
    """``iter.next().unwrap()`` fires - ``Iterator::next`` returns ``Option<T>``."""
    sample = tmp_path / "next.rs"
    sample.write_text(
        "fn first(v: Vec<i32>) -> i32 {\n    v.into_iter().next().unwrap()\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert any(v.code == "SAFE803" for v in result.violations)


def test_rust_let_tuple_destructure_propagates_taint(tmp_path: Path) -> None:
    """``let (a, b) = produce_tainted();`` taints both ``a`` and ``b``."""
    sample = tmp_path / "let_tuple.rs"
    sample.write_text(
        'use std::process::Command;\nfn run(user_input: String) {\n    let (a, _b) = (user_input, 0);\n    Command::new("echo").arg(a);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_let_struct_destructure_propagates_taint(tmp_path: Path) -> None:
    """``let Cfg { cmd, .. } = tainted_cfg;`` taints ``cmd``.

    Exercises ``_iter_pattern_identifiers``'s ``struct_pattern`` /
    ``field_pattern`` recursion (the let-destructure path; the param-
    destructure path goes through ``_rust_collect_pattern_names``
    instead).
    """
    sample = tmp_path / "let_struct.rs"
    sample.write_text(
        'use std::process::Command;\nstruct Cfg { cmd: String, other: i32 }\nfn run(user_input: Cfg) {\n    let Cfg { cmd, other: _ } = user_input;\n    Command::new("echo").arg(cmd);\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_untyped_closure_param_taints(tmp_path: Path) -> None:
    """Untyped closure param ``|x|`` seeds the tainted set with ``x``.

    Exercises the ``identifier`` branch of ``_rust_param_names`` -
    typed closure params parse as ``parameter`` nodes (the same shape
    as function params), but untyped ``|x, y|`` closure params expose
    the bound name as a bare ``identifier`` child directly under
    ``closure_parameters``.
    """
    sample = tmp_path / "closure_untyped.rs"
    sample.write_text(
        'use std::process::Command;\nfn run() {\n    let h = |x| { Command::new("echo").arg(x); };\n    h("echo".to_string());\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_rust_self_parameter_not_seeded_as_tainted(tmp_path: Path) -> None:
    """``&self`` is excluded from the tainted set even when method is called on tainted data.

    A method on ``&self`` could pass ``self`` directly to a sink and
    the rule would otherwise fire on every method - too noisy. The
    spirit of SAFE801 is to flag user-controlled INPUTS (parameters);
    ``self`` is the receiver, not an input.
    """
    sample = tmp_path / "self.rs"
    sample.write_text(
        'use std::process::Command;\nstruct Runner { cmd: String }\nimpl Runner {\n    fn run(&self) {\n        Command::new("echo").arg(&self.cmd);\n    }\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_rust_unwrap_message_recommends_if_let(tmp_path: Path) -> None:
    """The Rust SAFE803 message recommends ``if let Some(x) = ...`` / ``match`` / ``?``."""
    sample = tmp_path / "msg.rs"
    sample.write_text(
        "use std::collections::HashMap;\nfn run(map: &HashMap<String, i32>, k: &str) -> i32 {\n    *map.get(k).unwrap()\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    safe803 = [v for v in result.violations if v.code == "SAFE803"]
    assert len(safe803) == 1
    msg = safe803[0].message
    assert "if let Some" in msg
    assert "match" in msg
    assert "?" in msg
