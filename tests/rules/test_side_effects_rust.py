"""Tests for ``side_effects_hidden`` (SAFE303) and ``side_effects`` (SAFE304) on Rust files.

Rust-specific cases:

* The most common Rust I/O entry points are MACROS (``println!``,
  ``eprintln!``, ``write!``, ``dbg!``), not function calls.
  ``_first_io_call`` walks both ``call_expression`` and
  ``macro_invocation`` nodes; the configured ``io_functions_rust``
  list applies uniformly to both.
* The violation message renders Rust macros with the trailing ``!``
  so ``println!`` is clearly distinguished from a hypothetical
  ``println`` function.
* Scoped macros / calls (``std::println!``, ``std::fs::read``)
  resolve via the trailing-bareword extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional rule overrides; both rules ship enabled by default."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def _violations(result, code: str) -> list:
    """Return violations of *code* in *result*."""
    return [v for v in result.violations if v.code == code]


# ---------------------------------------------------------------------------
# SAFE303 - side_effects_hidden
# ---------------------------------------------------------------------------


def test_rust_pure_named_fn_with_println_macro_fires_safe303(tmp_path: Path) -> None:
    """``fn get_count() { println!(...); }`` - pure-named fn with println! fires SAFE303."""
    sample = tmp_path / "hidden.rs"
    sample.write_text(
        'fn get_count() -> i32 {\n    println!("debug");\n    42\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    fired = _violations(result, "SAFE303")
    assert len(fired) == 1
    assert "get_count" in fired[0].message
    assert "println!" in fired[0].message


def test_rust_pure_named_fn_with_fs_call_fires_safe303(tmp_path: Path) -> None:
    """``fn parse_config()`` calling ``std::fs::read`` fires SAFE303 (scoped call)."""
    sample = tmp_path / "fs.rs"
    sample.write_text(
        'fn parse_config() -> Vec<u8> {\n    std::fs::read("/etc/config").unwrap()\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    fired = _violations(result, "SAFE303")
    assert len(fired) == 1
    assert "parse_config" in fired[0].message
    assert "read" in fired[0].message


def test_rust_io_named_fn_with_println_does_not_fire_safe303(tmp_path: Path) -> None:
    """``fn write_log()`` with println! doesn't fire - name signals I/O."""
    sample = tmp_path / "io_named.rs"
    sample.write_text(
        'fn write_log(msg: &str) {\n    println!("{}", msg);\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _violations(result, "SAFE303") == []


def test_rust_pure_named_fn_with_no_io_does_not_fire(tmp_path: Path) -> None:
    """``fn compute_sum()`` with no I/O is clean."""
    sample = tmp_path / "clean.rs"
    sample.write_text(
        "fn compute_sum(a: i32, b: i32) -> i32 {\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _violations(result, "SAFE303") == []


# ---------------------------------------------------------------------------
# SAFE304 - side_effects
# ---------------------------------------------------------------------------


def test_rust_neutral_named_fn_with_io_fires_safe304(tmp_path: Path) -> None:
    """``fn process_data() { println!(...); }`` fires SAFE304 - name doesn't signal I/O."""
    sample = tmp_path / "process.rs"
    sample.write_text(
        'fn process_data() {\n    println!("step");\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    fired = _violations(result, "SAFE304")
    assert len(fired) == 1
    assert "process_data" in fired[0].message
    assert "println!" in fired[0].message


def test_rust_writer_named_fn_with_io_does_not_fire_safe304(tmp_path: Path) -> None:
    """``fn write_record()`` with println! doesn't fire - 'write' is in io_name_keywords."""
    sample = tmp_path / "writer.rs"
    sample.write_text(
        'fn write_record(r: &str) {\n    println!("{}", r);\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _violations(result, "SAFE304") == []


def test_rust_dbg_macro_fires_safe304(tmp_path: Path) -> None:
    """``dbg!()`` macro also counts as I/O - it prints to stderr."""
    sample = tmp_path / "dbg.rs"
    sample.write_text("fn process(x: i32) -> i32 {\n    dbg!(x)\n}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    fired = _violations(result, "SAFE304")
    assert len(fired) == 1
    assert "dbg!" in fired[0].message


def test_rust_format_macro_does_not_fire(tmp_path: Path) -> None:
    """``format!()`` is NOT I/O - returns String. Doesn't fire SAFE304."""
    sample = tmp_path / "format.rs"
    sample.write_text(
        'fn process(x: i32) -> String {\n    format!("{}", x)\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _violations(result, "SAFE304") == []


def test_rust_scoped_macro_fires_safe304(tmp_path: Path) -> None:
    """``std::println!`` (scoped macro path) fires - trailing name matches."""
    sample = tmp_path / "scoped_macro.rs"
    sample.write_text(
        'fn process() {\n    std::println!("x");\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert len(_violations(result, "SAFE304")) == 1


def test_rust_io_in_nested_closure_does_not_attribute_to_outer(tmp_path: Path) -> None:
    """I/O in a nested closure shouldn't attribute to the enclosing function.

    ``_first_io_call`` skips nested function / closure bodies via the
    ``skip_types=tuple(function_types)`` pattern.
    """
    sample = tmp_path / "closure.rs"
    sample.write_text(
        'fn process(items: Vec<i32>) -> Vec<i32> {\n    items.into_iter().map(|x| { eprintln!("{}", x); x * 2 }).collect()\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    # ``process`` itself doesn't fire (the I/O is in the closure body).
    # The closure body IS its own function; it doesn't have a name
    # field so it shows as ``<anonymous>`` and the keyword check
    # naturally skips it (no I/O keyword in ``<anonymous>``).
    # The closure has println-like I/O in a non-IO-named function,
    # so SAFE304 fires on the closure itself - exactly one violation.
    fired = _violations(result, "SAFE304")
    # Must emit at least one violation (otherwise the all-check below
    # passes vacuously and the test loses its regression value).
    assert len(fired) >= 1, "SAFE304 must fire on the closure body"
    # Outer ``process`` should NOT be in the fired list - the I/O isn't in its body.
    assert all("process" not in v.message or "anonymous" in v.message for v in fired)


# ---------------------------------------------------------------------------
# ``write!`` / ``writeln!`` perform I/O only if their TARGET does (#171).
# ---------------------------------------------------------------------------


def test_rust_write_to_a_formatter_in_fn_fmt_is_not_io(tmp_path: Path) -> None:
    """``write!(f, ..)`` where ``f`` is a ``Formatter`` performs no I/O.

    This is the only way to implement ``Display``, so reporting it made the rule
    fire on every formatting impl in the codebase. On ripgrep 16 of 34
    ``write!`` findings were inside ``fn fmt``.
    """
    sample = tmp_path / "disp.rs"
    sample.write_text(
        'impl fmt::Display for X {\n    fn fmt(&self, f: &mut fmt::Formatter<\'_>) -> fmt::Result {\n        write!(f, "hello")\n    }\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _violations(result, "SAFE304") == []
    assert _violations(result, "SAFE303") == []


def test_rust_write_to_a_local_string_buffer_is_not_io(tmp_path: Path) -> None:
    """``write!(&mut s, ..)`` into a ``String`` is string building, not I/O."""
    sample = tmp_path / "build.rs"
    sample.write_text(
        'fn build() -> String {\n    let mut s = String::new();\n    write!(&mut s, "x").unwrap();\n    s\n}\n',
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert _violations(result, "SAFE304") == []


def test_rust_write_to_a_string_parameter_is_not_io(tmp_path: Path) -> None:
    """A parameter typed ``&mut String`` is a buffer, so writing to it is not I/O."""
    sample = tmp_path / "param.rs"
    sample.write_text('fn into(buf: &mut String) {\n    write!(buf, "x").unwrap();\n}\n', encoding="utf-8")
    assert _violations(_engine().check_file(str(sample)), "SAFE304") == []


def test_rust_writeln_to_stdout_still_fires(tmp_path: Path) -> None:
    """The positive control: a path-expression target is not a known buffer, so it reports.

    Without this the fix could silence every ``write!`` and the tests above would
    still pass.
    """
    sample = tmp_path / "real.rs"
    sample.write_text('fn emit() {\n    writeln!(std::io::stdout(), "x").unwrap();\n}\n', encoding="utf-8")
    assert len(_violations(_engine().check_file(str(sample)), "SAFE304")) == 1


def test_rust_write_to_an_io_write_parameter_still_fires(tmp_path: Path) -> None:
    """A parameter typed ``&mut dyn std::io::Write`` is a stream, so it still reports."""
    sample = tmp_path / "stream.rs"
    sample.write_text('fn emit(w: &mut dyn std::io::Write) {\n    write!(w, "x").unwrap();\n}\n', encoding="utf-8")
    assert len(_violations(_engine().check_file(str(sample)), "SAFE304")) == 1


def test_rust_write_to_an_unknown_binding_still_fires(tmp_path: Path) -> None:
    """An unresolved target keeps reporting rather than being silently dropped."""
    sample = tmp_path / "unknown.rs"
    sample.write_text('fn q(w: Thing) {\n    write!(w, "x").unwrap();\n}\n', encoding="utf-8")
    assert len(_violations(_engine().check_file(str(sample)), "SAFE304")) == 1


def test_rust_println_is_unaffected_by_the_write_target_check(tmp_path: Path) -> None:
    """``println!`` has no target argument and must keep reporting."""
    sample = tmp_path / "p.rs"
    sample.write_text('fn p() {\n    println!("x");\n}\n', encoding="utf-8")
    assert len(_violations(_engine().check_file(str(sample)), "SAFE304")) == 1


# ---------------------------------------------------------------------------
# High-collision bare method names left SAFE304's Rust defaults (#178).
# ---------------------------------------------------------------------------


def test_rust_rwlock_read_no_longer_fires_safe304(tmp_path: Path) -> None:
    """``lock.read()`` is a lock acquisition, not filesystem I/O.

    ``call_name`` discards the receiver, so ``read`` / ``status`` / ``spawn`` /
    ``output`` / ``recv`` as bare names matched whatever they were called on.
    They stay in SAFE303's list, where the function name must also signal purity.
    """
    sample = tmp_path / "lock.rs"
    sample.write_text("fn lookup(lock: &RwLock<u32>) -> u32 {\n    *lock.read().unwrap()\n}\n", encoding="utf-8")
    assert _violations(_engine().check_file(str(sample)), "SAFE304") == []


def test_rust_specific_io_spellings_still_fire_safe304(tmp_path: Path) -> None:
    """``read_to_string`` and friends are unambiguous and keep reporting.

    The enclosing function is named ``contents`` rather than ``load`` on purpose:
    ``load`` is in ``io_name_keywords``, which exempts the function outright and
    would make this test pass without exercising the I/O list at all.
    """
    sample = tmp_path / "fs.rs"
    sample.write_text('fn contents() -> String {\n    std::fs::read_to_string("f").unwrap()\n}\n', encoding="utf-8")
    assert len(_violations(_engine().check_file(str(sample)), "SAFE304")) == 1


def test_rust_dropped_names_still_reachable_via_config(tmp_path: Path) -> None:
    """The names are defaults, not hard-coded: listing one restores the behaviour."""
    sample = tmp_path / "lock2.rs"
    sample.write_text("fn lookup(lock: &RwLock<u32>) -> u32 {\n    *lock.read().unwrap()\n}\n", encoding="utf-8")
    eng = _engine({"rules": {"side_effects": {"io_functions_rust": ["read"]}}})
    assert len(_violations(eng.check_file(str(sample)), "SAFE304")) == 1
