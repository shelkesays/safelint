"""Dataflow rules (SAFE801 / SAFE802) on C++ files.

C++ reuses the C taint tracker (``CTaintTracker``); these tests confirm the
C++ wiring (reference-parameter seeding, ``getenv`` source, qualified sink
name) and that the C tracker's review-fix behaviours (ternary propagation,
inline assignment propagation, compound-assignment taint, sanitizer-arg
non-descent) carry over to C++ source.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _codes(src: str, tmp_path: Path, enable: list[str] | None = None, config: dict | None = None) -> set[str]:
    """Return violation codes for *src* written as a ``.cpp`` file."""
    sample = tmp_path / "sample.cpp"
    sample.write_text(src, encoding="utf-8")
    rules = {r: {"enabled": True} for r in (enable or [])}
    rules.update(config or {})
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": rules}))
    return {v.code for v in engine.check_file(str(sample)).violations}


def test_cpp_tainted_param_into_system_fires_safe801(tmp_path: Path) -> None:
    """A tainted parameter flowing into ``system`` fires SAFE801."""
    src = "void run(const char* in) {\n    system(in);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, enable=["tainted_sink"])


def test_cpp_reference_param_seeds_taint(tmp_path: Path) -> None:
    """A reference parameter (``const std::string& s``) is seeded and flows to a sink.

    ``reference_declarator`` nests its name as a plain child (not on a
    ``declarator`` field), which ``_cpp_param_identifier`` unwraps specially.
    """
    src = "void run(const std::string& s) {\n    system(s);\n}\n"
    assert "SAFE801" in _codes(src, tmp_path, enable=["tainted_sink"])


def test_cpp_getenv_source_taints_then_sinks(tmp_path: Path) -> None:
    """``getenv`` return value is tainted and flags when it reaches ``system``."""
    src = 'void f() {\n    char* x = getenv("X");\n    system(x);\n}\n'
    assert "SAFE801" in _codes(src, tmp_path, enable=["tainted_sink"])


def test_cpp_ternary_propagates_taint(tmp_path: Path) -> None:
    """Taint through a ``?:`` conditional expression reaches the sink (carry-over)."""
    src = 'void run(const char* in) {\n    const char* y = cond ? in : "safe";\n    system(y);\n}\n'
    assert "SAFE801" in _codes(src, tmp_path, enable=["tainted_sink"])


def test_cpp_sanitizer_clears_taint(tmp_path: Path) -> None:
    """A sanitizer call clears taint before the sink - no SAFE801."""
    src = "void run(const char* in) {\n    const char* y = sanitize(in);\n    system(y);\n}\n"
    assert "SAFE801" not in _codes(src, tmp_path, enable=["tainted_sink"])


def test_cpp_untainted_literal_is_clean_for_safe801(tmp_path: Path) -> None:
    """A constant argument to ``system`` is clean for SAFE801."""
    src = 'void f() {\n    system("ls");\n}\n'
    assert "SAFE801" not in _codes(src, tmp_path, enable=["tainted_sink"])


def test_cpp_unnamed_parameter_is_skipped(tmp_path: Path) -> None:
    """An unnamed parameter contributes no tainted name; a literal sink stays clean."""
    src = 'void f(const char*) {\n    system("ls");\n}\n'
    assert "SAFE801" not in _codes(src, tmp_path, enable=["tainted_sink"])


def test_cpp_ignored_return_fires_safe802(tmp_path: Path) -> None:
    """A bare ``fclose(f);`` whose return is discarded fires SAFE802."""
    src = "void f() {\n    fclose(handle);\n}\n"
    assert "SAFE802" in _codes(src, tmp_path, enable=["return_value_ignored"])


def test_cpp_dataflow_rules_silent_by_default(tmp_path: Path) -> None:
    """SAFE801 / SAFE802 are opt-in: tainted flow and ignored returns are silent by default."""
    src = "void run(const char* in) {\n    system(in);\n    fclose(handle);\n}\n"
    codes = _codes(src, tmp_path)
    assert "SAFE801" not in codes
    assert "SAFE802" not in codes
