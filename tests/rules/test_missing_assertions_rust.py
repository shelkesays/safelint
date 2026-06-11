"""Tests for ``missing_assertions`` (SAFE601) on Rust files.

Rust-specific cases:

* Rust expresses assertions exclusively through macros
  (``assert!``, ``assert_eq!``, ``assert_ne!``, ``debug_assert!``,
  etc.); tree-sitter-rust parses these as ``macro_invocation`` with
  a ``macro`` field carrying the bareword (or scoped) name.
* The bareword extraction strips ``std::`` / ``core::`` qualifiers so
  ``std::assert!(x)`` and ``assert!(x)`` are both recognised.
* ``panic!`` / ``todo!`` / ``unreachable!`` / ``unimplemented!`` are
  NOT in the default ``assertion_calls_rust`` set - they're failure-
  exit markers, not invariant assertions. Tests confirm they don't
  satisfy the rule unless explicitly configured.
* Nested function / closure bodies are skipped so an assertion in a
  closure body doesn't credit the enclosing function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

    from safelint.core.engine import LintResult
    from safelint.rules.base import Violation

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _enabled_engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with ``missing_assertions`` enabled (it's off by default)."""
    base = {"rules": {"missing_assertions": {"enabled": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config)


def _safe601(result: LintResult) -> list[Violation]:
    """Return the list of SAFE601 violations on *result*."""
    return [v for v in result.violations if v.code == "SAFE601"]


def test_rust_function_without_assertions_fires(tmp_path: Path) -> None:
    """A Rust function with no assertion macros fires SAFE601."""
    sample = tmp_path / "no_assert.rs"
    sample.write_text("fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n", encoding="utf-8")
    result = _enabled_engine().check_file(str(sample))
    fired = _safe601(result)
    assert len(fired) == 1
    assert "add" in fired[0].message


def test_rust_function_with_assert_macro_does_not_fire(tmp_path: Path) -> None:
    """``assert!(cond)`` satisfies the rule."""
    sample = tmp_path / "assert.rs"
    sample.write_text(
        "fn add(a: i32, b: i32) -> i32 {\n    assert!(a >= 0);\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert _safe601(result) == []


def test_rust_function_with_assert_eq_macro_does_not_fire(tmp_path: Path) -> None:
    """``assert_eq!(a, b)`` satisfies the rule."""
    sample = tmp_path / "assert_eq.rs"
    sample.write_text(
        "fn add(a: i32, b: i32) -> i32 {\n    let r = a + b;\n    assert_eq!(r, a + b);\n    r\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert _safe601(result) == []


def test_rust_function_with_debug_assert_does_not_fire(tmp_path: Path) -> None:
    """``debug_assert!(cond)`` satisfies the rule (in defaults)."""
    sample = tmp_path / "debug_assert.rs"
    sample.write_text(
        "fn add(a: i32, b: i32) -> i32 {\n    debug_assert!(a >= 0);\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert _safe601(result) == []


def test_rust_function_with_scoped_assert_does_not_fire(tmp_path: Path) -> None:
    """``std::assert!(cond)`` - scoped form's trailing name is matched."""
    sample = tmp_path / "scoped_assert.rs"
    sample.write_text(
        "fn add(a: i32, b: i32) -> i32 {\n    std::assert!(a >= 0);\n    a + b\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert _safe601(result) == []


def test_rust_function_with_panic_macro_still_fires(tmp_path: Path) -> None:
    """``panic!()`` is NOT in the default assertion set; SAFE601 still fires.

    Guards against accidentally widening the defaults to include
    failure-exit macros. ``panic!`` exits, it doesn't verify an
    invariant - so the rule must not consider it equivalent to
    ``assert!``.
    """
    sample = tmp_path / "panic.rs"
    sample.write_text(
        'fn run(x: i32) -> i32 {\n    if x < 0 { panic!("negative"); }\n    x + 1\n}\n',
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert len(_safe601(result)) == 1


def test_rust_function_with_panic_configured_does_not_fire(tmp_path: Path) -> None:
    """``panic!`` becomes accepted when listed in ``assertion_calls_rust``."""
    sample = tmp_path / "panic_configured.rs"
    sample.write_text(
        'fn run(x: i32) -> i32 {\n    if x < 0 { panic!("negative"); }\n    x + 1\n}\n',
        encoding="utf-8",
    )
    overrides = {
        "rules": {
            "missing_assertions": {
                "assertion_calls_rust": [
                    "assert",
                    "assert_eq",
                    "assert_ne",
                    "debug_assert",
                    "debug_assert_eq",
                    "debug_assert_ne",
                    "panic",
                ],
            },
        },
    }
    result = _enabled_engine(overrides).check_file(str(sample))
    assert _safe601(result) == []


def test_rust_assert_inside_closure_does_not_credit_outer(tmp_path: Path) -> None:
    """An assert inside a nested closure must not satisfy the enclosing fn.

    The outer ``run`` has no assert macros directly in its body; the
    only ``assert!`` is inside a closure assigned to ``check``. The
    rule's walk skips closure bodies, so the outer function should
    still fire.
    """
    sample = tmp_path / "nested_closure.rs"
    sample.write_text(
        "fn run(x: i32) -> i32 {\n    let check = |v: i32| { assert!(v >= 0); };\n    check(x);\n    x + 1\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    fired = _safe601(result)
    # Outer ``run`` fires (no direct assert). The closure body counts
    # as a separate function and itself contains an assertion, so it
    # does NOT fire. Expect exactly one violation, on ``run``.
    assert len(fired) == 1
    assert "run" in fired[0].message


def test_rust_prop_assert_does_not_fire(tmp_path: Path) -> None:
    """``prop_assert!`` (proptest crate) satisfies the rule by default."""
    sample = tmp_path / "prop_assert.rs"
    sample.write_text(
        "fn check(x: i32) -> i32 {\n    prop_assert!(x >= 0);\n    x\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine().check_file(str(sample))
    assert _safe601(result) == []


def test_rust_min_assertions_two_single_assert_fires(tmp_path: Path) -> None:
    """With ``min_assertions = 2``, a single ``assert!`` is below threshold."""
    sample = tmp_path / "one.rs"
    sample.write_text("fn f(x: i32) -> i32 {\n    assert!(x > 0);\n    x\n}\n", encoding="utf-8")
    config = deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True, "min_assertions": 2}}})
    result = SafetyEngine(config).check_file(str(sample))
    hits = [v for v in result.violations if v.code == "SAFE601"]
    assert len(hits) == 1


def test_rust_min_assertions_two_clean_with_two(tmp_path: Path) -> None:
    """Two assertion macros satisfy ``min_assertions = 2``."""
    sample = tmp_path / "two.rs"
    sample.write_text("fn f(x: i32) -> i32 {\n    assert!(x > 0);\n    assert!(x < 100);\n    x\n}\n", encoding="utf-8")
    config = deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True, "min_assertions": 2}}})
    result = SafetyEngine(config).check_file(str(sample))
    assert [v for v in result.violations if v.code == "SAFE601"] == []
