"""End-to-end smoke tests for C language registration.

Covers the language-registry plumbing: ``.c`` AND ``.h`` files are discovered
(C is the first two-extension language), the C parser handles them, parse
errors surface as ``SAFE000``, ``// nosafe`` suppression works, and Python-only
rules (no try/catch analogue) are correctly skipped on C files via the engine's
per-language dispatch.

Per-rule C behaviour lives in dedicated test files under
``tests/rules/test_*_c.py`` - this file stays focused on plumbing.
"""

from __future__ import annotations

from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import C, get_language_for_file, supported_extensions


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_c_extensions_in_supported_extensions() -> None:
    """Both ``.c`` and ``.h`` are registered (``.h`` lints as C)."""
    assert ".c" in supported_extensions()
    assert ".h" in supported_extensions()


def test_get_language_for_c_and_h_files_returns_c() -> None:
    """Both the ``.c`` and ``.h`` extensions route to the C LanguageDefinition."""
    assert get_language_for_file("foo.c") is C
    assert get_language_for_file("foo.h") is C


def test_c_language_definition_basics() -> None:
    """Sanity checks on the LanguageDefinition exposed by the C module."""
    assert C.name == "c"
    assert C.comment_node_type == "comment"
    assert C.comment_prefix == "//"
    tree = C.create_parser().parse(b"int main(void) { return 0; }\n")
    assert tree.root_node.type == "translation_unit"


def test_engine_parses_clean_c_file(tmp_path: Path) -> None:
    """A clean C file produces zero violations."""
    sample = tmp_path / "ok.c"
    sample.write_text("int add(int a, int b) {\n    return a + b;\n}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert result.violations == []
    assert result.suppressed == []


def test_engine_parses_clean_h_file(tmp_path: Path) -> None:
    """A ``.h`` header lints as C and a clean one produces zero violations."""
    sample = tmp_path / "ok.h"
    sample.write_text("int add(int a, int b) {\n    return a + b;\n}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert result.violations == []


def test_engine_emits_safe000_on_unparseable_c(tmp_path: Path) -> None:
    """Tree-sitter parse errors on broken C surface as SAFE000."""
    sample = tmp_path / "broken.c"
    sample.write_text("int broken( {\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE000" for v in result.violations), "Expected SAFE000 on broken C source"


def test_engine_skips_python_only_rules_on_c(tmp_path: Path) -> None:
    """Python-only rules (e.g. SAFE201 bare_except, SAFE301 global_state) never fire on C."""
    sample = tmp_path / "state.c"
    sample.write_text("int counter;\nint f(void) { return counter; }\n", encoding="utf-8")
    codes = {v.code for v in _engine().check_file(str(sample)).violations}
    assert "SAFE201" not in codes
    assert "SAFE301" not in codes


def test_c_nosafe_comment_suppresses_violation(tmp_path: Path) -> None:
    """A ``// nosafe`` directive on the offending line suppresses the violation."""
    sample = tmp_path / "supp.c"
    sample.write_text("int counter; // nosafe: SAFE302\nint f(void) { return counter; }\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE302" for v in result.violations)
    assert any(v.code == "SAFE302" for v in result.suppressed)


def test_engine_discovers_c_and_h_files_under_directory(tmp_path: Path) -> None:
    """``check_path`` on a directory picks up ``.c`` and ``.h`` files, not non-source files."""
    (tmp_path / "a.c").write_text("int f(void) { return 0; }\n", encoding="utf-8")
    (tmp_path / "b.h").write_text("int g(void);\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# notes\n", encoding="utf-8")
    file_names = {Path(result.path).name for result in _engine().check_path(str(tmp_path))}
    assert {"a.c", "b.h"}.issubset(file_names)
    assert "c.md" not in file_names
