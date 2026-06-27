"""Tests for the function-shape rules (SAFE101-105) on C files.

C-specific cases that exercise the dispatch added for C:

* ``function_definition`` is the only ``FUNCTION_TYPES`` member (no methods,
  closures, or lambdas).
* SAFE103 counts ``parameter_declaration`` nodes, found under the nested
  ``function_declarator.parameters`` (not directly on the function node).
* SAFE105 resolves the enclosing function name from
  ``declarator.declarator`` (C exposes no ``name`` field), so direct
  self-recursion is detected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_c_long_function_fires_safe101(tmp_path: Path) -> None:
    """A function over the default 60-line cap fires SAFE101."""
    sample = tmp_path / "long.c"
    body = "\n".join(f"    x += {i};" for i in range(70))
    sample.write_text(f"int longFn(void) {{\n    int x = 0;\n{body}\n    return x;\n}}\n", encoding="utf-8")
    safe101 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "longFn" in safe101[0].message


def test_c_short_function_is_clean(tmp_path: Path) -> None:
    """A short function fires nothing."""
    sample = tmp_path / "short.c"
    sample.write_text("int add(int a, int b) {\n    return a + b;\n}\n", encoding="utf-8")
    assert not _engine().check_file(str(sample)).violations


def test_c_deep_nesting_fires_safe102(tmp_path: Path) -> None:
    """Control flow nested beyond max_depth=2 fires SAFE102."""
    sample = tmp_path / "deep.c"
    sample.write_text(
        "int deep(int x) {\n    if (x) {\n        for (;;) {\n            while (x) {\n                return 1;\n            }\n        }\n    }\n    return 0;\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE102" for v in _engine().check_file(str(sample)).violations)


def test_c_shallow_nesting_is_clean(tmp_path: Path) -> None:
    """Nesting within the cap is clean."""
    sample = tmp_path / "shallow.c"
    sample.write_text("int f(int x) {\n    if (x) {\n        g();\n    }\n    return 0;\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE102" for v in _engine().check_file(str(sample)).violations)


def test_c_too_many_arguments_fires_safe103(tmp_path: Path) -> None:
    """Eight parameters over the default 7 fires SAFE103, naming the function."""
    sample = tmp_path / "args.c"
    sample.write_text("int many(int a, int b, int c, int d, int e, int f, int g, int h) {\n    return 0;\n}\n", encoding="utf-8")
    safe103 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message
    assert "many" in safe103[0].message


def test_c_void_parameter_is_not_counted_as_an_argument(tmp_path: Path) -> None:
    """``int f(void)`` is a zero-argument function; SAFE103 must not fire on it."""
    sample = tmp_path / "void.c"
    sample.write_text("int f(void) {\n    return 0;\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE103" for v in _engine().check_file(str(sample)).violations)


def test_c_high_complexity_fires_safe104(tmp_path: Path) -> None:
    """Cyclomatic complexity over the default 10 fires SAFE104; ``&&`` counts."""
    sample = tmp_path / "complex.c"
    conds = " ".join(f"if (x > {i} && x < {i + 1}) {{ }}" for i in range(8))
    sample.write_text(f"int c(int x) {{ {conds} return x; }}\n", encoding="utf-8")
    assert any(v.code == "SAFE104" for v in _engine().check_file(str(sample)).violations)


def test_c_direct_recursion_fires_safe105(tmp_path: Path) -> None:
    """A function calling itself directly fires SAFE105 (name from the declarator)."""
    sample = tmp_path / "rec.c"
    sample.write_text("int fact(int n) {\n    return n <= 1 ? 1 : n * fact(n - 1);\n}\n", encoding="utf-8")
    safe105 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE105"]
    assert len(safe105) == 1
    assert "fact" in safe105[0].message


def test_c_pointer_returning_recursion_fires_safe105(tmp_path: Path) -> None:
    """The name extractor unwraps the pointer declarator of ``char *walk(...)``."""
    sample = tmp_path / "ptr.c"
    sample.write_text("char *walk(char *p) {\n    return p ? walk(p + 1) : p;\n}\n", encoding="utf-8")
    assert any(v.code == "SAFE105" for v in _engine().check_file(str(sample)).violations)


def test_c_non_recursive_function_is_clean_for_safe105(tmp_path: Path) -> None:
    """Calling a *different* function is not recursion."""
    sample = tmp_path / "norec.c"
    sample.write_text("int caller(int n) {\n    return helper(n);\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE105" for v in _engine().check_file(str(sample)).violations)
