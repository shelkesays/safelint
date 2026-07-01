"""Tests for the state / side-effect rules on C files.

Covers the C dispatch for:

* SAFE302 ``global_mutation`` - file-scope mutable ``declaration`` (``static``
  counts; ``const`` and prototypes / ``typedef`` / ``extern`` are exempt).
* SAFE303 / SAFE304 ``side_effects`` - libc/POSIX I/O primitives
  (``io_functions_c``) inside a pure-looking / non-I/O-named function.
* SAFE309 ``dynamic_code_execution`` - the ``dlopen`` / ``dlsym`` loader pair.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _codes(src: str, tmp_path: Path, overrides: dict | None = None) -> set[str]:
    sample = tmp_path / "sample.c"
    sample.write_text(src, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides or {}))
    return {v.code for v in engine.check_file(str(sample)).violations}


# --- SAFE302 global_mutation (enabled by default) ------------------------------


def test_c_file_scope_mutable_global_fires_safe302(tmp_path: Path) -> None:
    """A plain file-scope variable is shared mutable state."""
    codes = _codes("int counter = 0;\nint f(void) { return counter; }\n", tmp_path)
    assert "SAFE302" in codes


def test_c_static_file_scope_variable_fires_safe302(tmp_path: Path) -> None:
    """A ``static`` file-scope variable is shared within the translation unit."""
    assert "SAFE302" in _codes("static int cache = 0;\nint g(void) { return cache; }\n", tmp_path)


def test_c_underscore_global_is_not_skipped_for_safe302(tmp_path: Path) -> None:
    """C has no blank identifier, so a file-scope ``int _;`` is real mutable state."""
    assert "SAFE302" in _codes("int _ = 0;\nint f(void) { return _; }\n", tmp_path)


def test_c_const_global_is_clean_for_safe302(tmp_path: Path) -> None:
    """A ``const`` file-scope variable is immutable and never fires."""
    assert "SAFE302" not in _codes("const int LIMIT = 10;\nint h(void) { return LIMIT; }\n", tmp_path)


def test_c_typedef_is_clean_for_safe302(tmp_path: Path) -> None:
    """A ``typedef`` is a type alias, not a variable definition - exempt."""
    assert "SAFE302" not in _codes("typedef int myint;\nint h(myint x) { return x; }\n", tmp_path)


def test_c_const_pointer_to_const_global_is_clean_for_safe302(tmp_path: Path) -> None:
    """``const int *const p`` is a const pointer to const - genuinely immutable."""
    assert "SAFE302" not in _codes("const int *const P = 0;\nint h(void) { return P ? 1 : 0; }\n", tmp_path)


def test_c_pointer_to_const_global_fires_safe302(tmp_path: Path) -> None:
    """``const int *p`` has a const pointee but a MUTABLE pointer - shared mutable state."""
    assert "SAFE302" in _codes("const int *p;\nint h(void) { return p ? 1 : 0; }\n", tmp_path)


def test_c_function_prototype_is_clean_for_safe302(tmp_path: Path) -> None:
    """A function prototype is not a variable definition."""
    assert "SAFE302" not in _codes("int helper(int x);\nint h(void) { return helper(1); }\n", tmp_path)


def test_c_pointer_returning_prototype_is_clean_for_safe302(tmp_path: Path) -> None:
    """A pointer-returning prototype (``char *foo(void);``) wraps its declarator but is still a prototype."""
    assert "SAFE302" not in _codes("char *foo(void);\nchar *g(void) { return foo(); }\n", tmp_path)


def test_c_function_pointer_global_fires_safe302(tmp_path: Path) -> None:
    """A file-scope function-pointer *variable* is mutable state (distinct from a prototype)."""
    assert "SAFE302" in _codes("int (*fp)(int);\nint f(void) { return fp ? 1 : 0; }\n", tmp_path)


def test_c_extern_forward_reference_is_clean_for_safe302(tmp_path: Path) -> None:
    """``extern int g;`` (no initialiser) is a forward reference, not a definition - exempt."""
    assert "SAFE302" not in _codes("extern int g;\nint h(void) { return g; }\n", tmp_path)


def test_c_extern_with_initializer_fires_safe302(tmp_path: Path) -> None:
    """``extern int g = 1;`` is a definition of file-scope mutable state, so it still fires."""
    assert "SAFE302" in _codes("extern int g = 1;\nint h(void) { return g; }\n", tmp_path)


def test_c_mixed_extern_declaration_flags_only_the_initialised_declarator(tmp_path: Path) -> None:
    """In ``extern int a, b = 1;`` only ``b`` (initialised = a definition) fires; ``a`` stays a forward reference."""
    sample = tmp_path / "sample.c"
    sample.write_text("extern int a, b = 1;\nint h(void) { return a + b; }\n", encoding="utf-8")
    msgs = [v.message for v in SafetyEngine(DEFAULTS).check_file(str(sample)).violations if v.code == "SAFE302"]
    assert len(msgs) == 1
    assert '"b"' in msgs[0]


def test_c_local_variable_is_clean_for_safe302(tmp_path: Path) -> None:
    """A block-scoped local is not file-scope state."""
    assert "SAFE302" not in _codes("int f(void) {\n    int local = 0;\n    return local;\n}\n", tmp_path)


# --- SAFE303 side_effects_hidden (enabled by default) --------------------------


def test_c_pure_named_function_with_io_fires_safe303(tmp_path: Path) -> None:
    """A pure-sounding name (``compute_``) that calls an I/O primitive fires SAFE303."""
    assert "SAFE303" in _codes('int compute_total(int x) {\n    printf("%d", x);\n    return x;\n}\n', tmp_path)


def test_c_pure_named_function_without_io_is_clean_for_safe303(tmp_path: Path) -> None:
    """A pure-named function that does no I/O is clean."""
    assert "SAFE303" not in _codes("int compute_total(int a, int b) {\n    return a + b;\n}\n", tmp_path)


# --- SAFE304 side_effects (enabled by default) ---------------------------------


def test_c_io_call_in_non_io_named_function_fires_safe304(tmp_path: Path) -> None:
    """``printf`` inside a function whose name doesn't signal I/O fires SAFE304."""
    assert "SAFE304" in _codes('int calc(int x) {\n    printf("%d", x);\n    return x;\n}\n', tmp_path)


def test_c_io_call_in_io_named_function_is_clean_for_safe304(tmp_path: Path) -> None:
    """An I/O-signalling name (contains ``write``) exempts the function."""
    assert "SAFE304" not in _codes('int write_line(int x) {\n    printf("%d", x);\n    return x;\n}\n', tmp_path)


def test_c_pure_function_is_clean_for_safe304(tmp_path: Path) -> None:
    """A function with no I/O calls is clean."""
    assert "SAFE304" not in _codes("int add(int a, int b) {\n    return a + b;\n}\n", tmp_path)


# --- SAFE309 dynamic_code_execution (opt-in) -----------------------------------


def test_c_dlopen_fires_safe309_when_enabled(tmp_path: Path) -> None:
    """``dlopen`` is C's dynamic code-loading surface."""
    overrides = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert "SAFE309" in _codes('void load(void) {\n    void *handle = dlopen("lib.so", 1);\n}\n', tmp_path, overrides)


def test_c_dlsym_fires_safe309_when_enabled(tmp_path: Path) -> None:
    """``dlsym`` resolves a symbol from a dynamically loaded object."""
    overrides = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert "SAFE309" in _codes('void *resolve(void *h) {\n    return dlsym(h, "sym");\n}\n', tmp_path, overrides)


def test_c_ordinary_call_is_clean_for_safe309(tmp_path: Path) -> None:
    """A non-loader call does not fire SAFE309."""
    overrides = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert "SAFE309" not in _codes("int f(void) {\n    return compute(1);\n}\n", tmp_path, overrides)
