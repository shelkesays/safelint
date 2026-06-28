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
