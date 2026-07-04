"""Tests for the five C-only rules (the "Power of Ten homecoming").

SAFE106 nonlocal_jumps (enabled, warning), SAFE310 dynamic_allocation,
SAFE311 complex_macro, SAFE312 conditional_compilation, SAFE313
restricted_pointers (the last four opt-in).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules.c_rules import (
    ComplexMacroRule,
    ConditionalCompilationRule,
    DynamicAllocationRule,
    RestrictedPointersRule,
)


def _codes(src: str, tmp_path: Path, enable: list[str] | None = None) -> set[str]:
    sample = tmp_path / "sample.c"
    sample.write_text(src, encoding="utf-8")
    overrides = {"rules": {r: {"enabled": True} for r in (enable or [])}}
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
    return {v.code for v in engine.check_file(str(sample)).violations}


def _codes_with_config(src: str, tmp_path: Path, rule_config: dict) -> set[str]:
    """Like ``_codes``, but takes an explicit ``{rule_name: {..config..}}`` mapping so
    tests can exercise list knobs (e.g. ``nonlocal_jump_calls_c``), not just ``enabled``."""
    sample = tmp_path / "sample.c"
    sample.write_text(src, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": rule_config}))
    return {v.code for v in engine.check_file(str(sample)).violations}


def test_c_opt_in_rules_are_silent_by_default(tmp_path: Path) -> None:
    """SAFE310-313 are opt-in: source that would trip all four reports none with no overrides."""
    src = "#define CAT(a, b) a##b\n#ifdef DEBUG\nint d;\n#endif\nint **pp;\nvoid f(void) {\n    void *p = malloc(8);\n    free(p);\n}\n"
    codes = _codes(src, tmp_path)  # no overrides -> built-in defaults
    opt_in = {DynamicAllocationRule.code, ComplexMacroRule.code, ConditionalCompilationRule.code, RestrictedPointersRule.code}
    assert codes.isdisjoint(opt_in)


def test_safe106_defaults_enabled_at_warning_severity() -> None:
    """SAFE106 is the only default-on C-only rule and ships at warning severity - a contract lock.

    Visible-but-non-blocking at ``--fail-on=error`` is the maintainer decision (``goto err``
    cleanup is idiomatic); re-tiering it must be a conscious, test-breaking act.
    """
    cfg = DEFAULTS["rules"]["nonlocal_jumps"]
    assert cfg["enabled"] is True
    assert cfg["severity"] == "warning"


# --- SAFE106 nonlocal_jumps (enabled by default, severity=warning) -------------


def test_c_goto_fires_safe106(tmp_path: Path) -> None:
    """A ``goto`` is a non-local jump."""
    assert "SAFE106" in _codes("int f(void) {\n    goto done;\ndone:\n    return 1;\n}\n", tmp_path)


def test_c_longjmp_fires_safe106(tmp_path: Path) -> None:
    """A ``longjmp`` call is a non-local jump."""
    assert "SAFE106" in _codes("void f(void *buf) {\n    longjmp(buf, 1);\n}\n", tmp_path)


def test_c_goto_can_be_suppressed_with_nosafe(tmp_path: Path) -> None:
    """A sanctioned ``goto err`` cleanup can be annotated with ``// nosafe: SAFE106``."""
    src = "int f(void) {\n    goto err; // nosafe: SAFE106\nerr:\n    return -1;\n}\n"
    assert "SAFE106" not in _codes(src, tmp_path)


def test_c_no_goto_is_clean_for_safe106(tmp_path: Path) -> None:
    """Structured control flow does not fire SAFE106."""
    assert "SAFE106" not in _codes("int f(int x) {\n    return x > 0 ? 1 : 0;\n}\n", tmp_path)


def test_c_safe106_custom_jump_call_list_is_honoured(tmp_path: Path) -> None:
    """A custom ``nonlocal_jump_calls_c`` entry is matched (SAFE106 is default-on)."""
    cfg = {"nonlocal_jumps": {"nonlocal_jump_calls_c": ["my_longjmp_wrapper"]}}
    assert "SAFE106" in _codes_with_config("void f(void *b) {\n    my_longjmp_wrapper(b, 1);\n}\n", tmp_path, cfg)


def test_c_safe106_custom_list_replaces_defaults(tmp_path: Path) -> None:
    """The custom list replaces the defaults: a default entry (``setjmp``) no longer fires under an override."""
    cfg = {"nonlocal_jumps": {"nonlocal_jump_calls_c": ["my_longjmp_wrapper"]}}
    assert "SAFE106" not in _codes_with_config("void f(void *b) {\n    setjmp(b);\n}\n", tmp_path, cfg)


def test_c_safe106_goto_is_structural_not_list_driven(tmp_path: Path) -> None:
    """``goto`` fires structurally regardless of ``nonlocal_jump_calls_c`` - the knob scopes only the call names."""
    cfg = {"nonlocal_jumps": {"nonlocal_jump_calls_c": ["my_longjmp_wrapper"]}}
    assert "SAFE106" in _codes_with_config("void f(int x) {\n    if (x) goto out;\nout:\n    return;\n}\n", tmp_path, cfg)


# --- SAFE310 dynamic_allocation (opt-in) ---------------------------------------


def test_c_malloc_fires_safe310(tmp_path: Path) -> None:
    """``malloc`` is dynamic heap allocation."""
    assert "SAFE310" in _codes("void *f(void) {\n    return malloc(64);\n}\n", tmp_path, ["dynamic_allocation"])


def test_c_free_fires_safe310(tmp_path: Path) -> None:
    """``free`` is part of the dynamic-allocation lifecycle."""
    assert "SAFE310" in _codes("void f(void *p) {\n    free(p);\n}\n", tmp_path, ["dynamic_allocation"])


def test_c_no_allocation_is_clean_for_safe310(tmp_path: Path) -> None:
    """Stack-only code does not fire SAFE310."""
    assert "SAFE310" not in _codes("int f(void) {\n    int buf[16];\n    return buf[0];\n}\n", tmp_path, ["dynamic_allocation"])


def test_c_safe310_custom_allocation_call_list_is_honoured(tmp_path: Path) -> None:
    """A custom ``allocation_calls_c`` entry is matched (SAFE310 is opt-in, so enable it too)."""
    cfg = {"dynamic_allocation": {"enabled": True, "allocation_calls_c": ["my_pool_alloc"]}}
    assert "SAFE310" in _codes_with_config("void *f(int n) {\n    return my_pool_alloc(n);\n}\n", tmp_path, cfg)


def test_c_safe310_custom_list_replaces_defaults(tmp_path: Path) -> None:
    """The custom list replaces the defaults: ``malloc`` no longer fires under an override."""
    cfg = {"dynamic_allocation": {"enabled": True, "allocation_calls_c": ["my_pool_alloc"]}}
    assert "SAFE310" not in _codes_with_config("void *f(void) {\n    return malloc(8);\n}\n", tmp_path, cfg)


# --- SAFE311 complex_macro (opt-in) --------------------------------------------


def test_c_token_paste_macro_fires_safe311(tmp_path: Path) -> None:
    """A function-like macro using ``##`` token pasting fires SAFE311."""
    assert "SAFE311" in _codes("#define CAT(a, b) a##b\n", tmp_path, ["complex_macro"])


def test_c_variadic_macro_fires_safe311(tmp_path: Path) -> None:
    """A variadic ``__VA_ARGS__`` macro fires SAFE311."""
    assert "SAFE311" in _codes("#define LOG(...) printf(__VA_ARGS__)\n", tmp_path, ["complex_macro"])


def test_c_unbalanced_object_macro_fires_safe311(tmp_path: Path) -> None:
    """An object-like macro with unbalanced brackets is not a complete syntactic unit."""
    assert "SAFE311" in _codes("#define OPEN if (\n", tmp_path, ["complex_macro"])


def test_c_unbalanced_square_bracket_macro_fires_safe311(tmp_path: Path) -> None:
    """An object-like macro with an unbalanced ``[`` is not a complete syntactic unit."""
    assert "SAFE311" in _codes("#define BAD arr[\n", tmp_path, ["complex_macro"])


def test_c_simple_macro_is_clean_for_safe311(tmp_path: Path) -> None:
    """A simple, balanced macro is clean."""
    assert "SAFE311" not in _codes("#define MAX 10\n#define SQ(x) ((x) * (x))\n", tmp_path, ["complex_macro"])


def test_c_bracket_inside_string_literal_is_clean_for_safe311(tmp_path: Path) -> None:
    """A bracket inside a string literal (``#define OPEN "["``) is balanced - it does not count."""
    assert "SAFE311" not in _codes('#define OPEN "["\n#define PAREN "("\n', tmp_path, ["complex_macro"])


def test_c_escaped_quote_in_string_literal_is_clean_for_safe311(tmp_path: Path) -> None:
    """An escaped quote does not end the literal, so a trailing ``(`` inside it stays stripped."""
    assert "SAFE311" not in _codes('#define MSG "say \\"hi\\" ("\n', tmp_path, ["complex_macro"])


def test_c_misordered_brackets_fire_safe311(tmp_path: Path) -> None:
    """Equal open/close counts but wrong order (``)(``) is still not a complete syntactic unit."""
    assert "SAFE311" in _codes("#define BAD )(\n", tmp_path, ["complex_macro"])


def test_c_mismatched_nested_brackets_fire_safe311(tmp_path: Path) -> None:
    """Interleaved brackets (``([)]``) are balanced by count but not by nesting."""
    assert "SAFE311" in _codes("#define BAD ([)]\n", tmp_path, ["complex_macro"])


# --- SAFE312 conditional_compilation (opt-in) ----------------------------------


def test_c_ifdef_fires_safe312(tmp_path: Path) -> None:
    """A feature ``#ifdef`` is conditional compilation."""
    assert "SAFE312" in _codes("#ifdef DEBUG\nint d;\n#endif\n", tmp_path, ["conditional_compilation"])


def test_c_if_directive_fires_safe312(tmp_path: Path) -> None:
    """A ``#if`` version test is conditional compilation."""
    assert "SAFE312" in _codes("#if VERSION > 2\nint v;\n#endif\n", tmp_path, ["conditional_compilation"])


def test_c_include_guard_is_clean_for_safe312(tmp_path: Path) -> None:
    """An ``#ifndef X`` + ``#define X`` include guard is exempt."""
    assert "SAFE312" not in _codes("#ifndef HEADER_H\n#define HEADER_H\nint x;\n#endif\n", tmp_path, ["conditional_compilation"])


def test_c_ifndef_with_unrelated_define_first_fires_safe312(tmp_path: Path) -> None:
    """An ``#ifndef X`` whose first body statement is not ``#define X`` is a real conditional."""
    src = "#ifndef DEBUG\nint enabled;\n#define DEBUG 1\n#endif\n"
    assert "SAFE312" in _codes(src, tmp_path, ["conditional_compilation"])


# --- SAFE313 restricted_pointers (opt-in) --------------------------------------


def test_c_double_pointer_fires_safe313(tmp_path: Path) -> None:
    """A two-level pointer declarator exceeds the single-dereference limit."""
    assert "SAFE313" in _codes("int **pp;\n", tmp_path, ["restricted_pointers"])


def test_c_function_pointer_fires_safe313(tmp_path: Path) -> None:
    """A function-pointer declarator is restricted."""
    assert "SAFE313" in _codes("void (*fp)(int);\n", tmp_path, ["restricted_pointers"])


def test_c_single_pointer_is_clean_for_safe313(tmp_path: Path) -> None:
    """A single-level pointer is allowed."""
    assert "SAFE313" not in _codes("int f(int *p) {\n    return *p;\n}\n", tmp_path, ["restricted_pointers"])
