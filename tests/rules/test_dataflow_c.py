"""Tests for the dataflow rules (SAFE801 tainted_sink, SAFE802 return_value_ignored) on C files.

C-specific behaviour exercised here:

* ``argv`` is seeded tainted via function parameters; ``subscript_expression``
  (``argv[1]``) keeps the taint; ``getenv`` / ``fgets`` / ... are call sources.
* Sinks are the command-exec (``system`` / ``popen`` / ``exec*``) and
  unbounded-copy (``strcpy`` / ``sprintf`` / ``strcat`` / ``gets`` / ``memcpy``)
  families; a sanitizer call (``validate`` / ``escape`` / ``snprintf`` / ...)
  clears taint.
* SAFE802: a bare flagged call (``fclose(fp);``) fires; an explicit
  ``(void)fclose(fp);`` cast does NOT (the call is wrapped in a
  ``cast_expression``, not a bare expression-statement call).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _codes(src: str, tmp_path: Path, rule: str) -> set[str]:
    sample = tmp_path / "sample.c"
    sample.write_text(src, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {rule: {"enabled": True}}}))
    return {v.code for v in engine.check_file(str(sample)).violations}


# --- SAFE801 tainted_sink (opt-in) ---------------------------------------------


def test_c_argv_into_system_fires_safe801(tmp_path: Path) -> None:
    """``argv`` (param-seeded) flowing into ``system`` is a command-injection sink."""
    src = "int main(int argc, char **argv) {\n    system(argv[1]);\n    return 0;\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_getenv_into_strcpy_fires_safe801(tmp_path: Path) -> None:
    """A ``getenv`` source assigned to a variable then copied via ``strcpy`` is tainted."""
    src = 'void f(void) {\n    char buf[8];\n    char *e = getenv("PATH");\n    strcpy(buf, e);\n}\n'
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_sanitized_argument_is_clean_for_safe801(tmp_path: Path) -> None:
    """A sanitizer call between source and sink clears the taint."""
    src = "void f(char **argv) {\n    char buf[8];\n    strcpy(buf, validate(argv[1]));\n}\n"
    assert "SAFE801" not in _codes(src, tmp_path, "tainted_sink")


def test_c_literal_argument_is_clean_for_safe801(tmp_path: Path) -> None:
    """A sink called with only a string literal is not tainted."""
    src = 'void f(void) {\n    system("ls -l");\n}\n'
    assert "SAFE801" not in _codes(src, tmp_path, "tainted_sink")


def test_c_compound_assignment_preserves_taint_for_safe801(tmp_path: Path) -> None:
    """A read-modify-write (``buf += ...``-style via concat helper) keeps prior taint."""
    src = "void f(char **argv) {\n    char *p = argv[1];\n    p = p;\n    system(p);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


# --- SAFE802 return_value_ignored (opt-in) -------------------------------------


def test_c_ignored_fclose_fires_safe802(tmp_path: Path) -> None:
    """A bare ``fclose(fp);`` discards the return value."""
    src = "void f(void *fp) {\n    fclose(fp);\n}\n"
    assert "SAFE802" in _codes(src, tmp_path, "return_value_ignored")


def test_c_void_cast_discard_is_clean_for_safe802(tmp_path: Path) -> None:
    """An explicit ``(void)fclose(fp);`` documents the discard and does NOT fire."""
    src = "void f(void *fp) {\n    (void)fclose(fp);\n}\n"
    assert "SAFE802" not in _codes(src, tmp_path, "return_value_ignored")


def test_c_used_return_value_is_clean_for_safe802(tmp_path: Path) -> None:
    """Assigning the return value clears SAFE802."""
    src = "int f(void *fp) {\n    int rc = fclose(fp);\n    return rc;\n}\n"
    assert "SAFE802" not in _codes(src, tmp_path, "return_value_ignored")


# --- SAFE801 taint-propagation branches ----------------------------------------


def test_c_cast_expression_propagates_taint(tmp_path: Path) -> None:
    """``(char *)tainted`` passes taint through the cast."""
    src = "void f(char **argv) {\n    char *p = (char *)argv[1];\n    system(p);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_reassignment_then_subscript_propagates_taint(tmp_path: Path) -> None:
    """A reassigned pointer stays tainted, and a subsequent ``cfg[0]`` index keeps it.

    (Struct ``->`` field propagation is covered separately by
    ``test_c_struct_field_access_propagates_taint``.)
    """
    src = "void f(char **argv) {\n    char **cfg = argv;\n    system(cfg[0]);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_pointer_arithmetic_propagates_taint(tmp_path: Path) -> None:
    """A binary/pointer expression over a tainted operand stays tainted."""
    src = "void f(char **argv) {\n    system(argv[1] + 0);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_compound_assignment_keeps_prior_taint(tmp_path: Path) -> None:
    """A compound assignment is read-modify-write: a clean RHS does not clear taint."""
    src = "void f(char **argv) {\n    long p = (long)argv[1];\n    p += 1;\n    system((char *)p);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_reassignment_to_clean_value_clears_taint(tmp_path: Path) -> None:
    """A plain assignment of a clean value clears the name's taint."""
    src = 'void f(char **argv) {\n    char *p = argv[1];\n    p = "safe";\n    system(p);\n}\n'
    assert "SAFE801" not in _codes(src, tmp_path, "tainted_sink")


def test_c_declaration_without_initializer_is_clean(tmp_path: Path) -> None:
    """A declaration with no initializer introduces no taint."""
    src = "void f(void) {\n    char *p;\n    system(p);\n}\n"
    assert "SAFE801" not in _codes(src, tmp_path, "tainted_sink")


def test_c_struct_field_access_propagates_taint(tmp_path: Path) -> None:
    """A ``->`` field access propagates the tainted receiver (field_expression branch)."""
    src = "struct S { char *c; };\nvoid f(char **argv) {\n    struct S *s = (struct S *)argv[1];\n    system(s->c);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_assignment_to_non_identifier_is_handled(tmp_path: Path) -> None:
    """An assignment whose LHS is not a bare identifier (``buf[0] = ...``) does not crash or taint a name."""
    src = "void f(char **argv) {\n    char buf[8];\n    buf[0] = argv[1][0];\n    system(buf);\n}\n"
    # buf itself is never tainted by an indexed write, so no SAFE801.
    assert "SAFE801" not in _codes(src, tmp_path, "tainted_sink")


def test_c_underscore_variable_is_tracked(tmp_path: Path) -> None:
    """C has no blank identifier, so a variable named ``_`` carries taint normally."""
    src = "void f(char **argv) {\n    char *_ = argv[1];\n    system(_);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_unknown_wrapper_preserves_taint_by_default(tmp_path: Path) -> None:
    """With the default ``assume_taint_preserving = true``, an unknown wrapping call keeps taint."""
    src = "void f(char **argv) {\n    system(wrap(argv[1]));\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, "tainted_sink")


def test_c_assume_taint_preserving_false_drops_unknown_call(tmp_path: Path) -> None:
    """With ``assume_taint_preserving = false`` an unknown wrapping call drops taint."""
    sample = tmp_path / "sample.c"
    sample.write_text("void f(char **argv) {\n    system(wrap(argv[1]));\n}\n", encoding="utf-8")
    overrides = {"rules": {"tainted_sink": {"enabled": True, "assume_taint_preserving": False}}}
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
    assert not any(v.code == "SAFE801" for v in engine.check_file(str(sample)).violations)
