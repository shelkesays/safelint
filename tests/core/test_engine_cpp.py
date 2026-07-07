"""End-to-end smoke tests for C++ language registration.

Covers the language-registry plumbing: the six C++ extensions
(``.cpp`` / ``.cxx`` / ``.cc`` / ``.hpp`` / ``.hxx`` / ``.hh``) are discovered
and route to the C++ LanguageDefinition, plain ``.h`` stays with C, the C++
parser handles them, parse errors surface as ``SAFE000``, ``// nosafe``
suppression works, and Python-only rules are skipped on C++ files.

Per-rule C++ behaviour lives in dedicated test files under
``tests/rules/test_*_cpp.py`` - this file stays focused on plumbing.
"""

from __future__ import annotations

from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import CPP, C, get_language_for_file, supported_extensions


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_cpp_extensions_in_supported_extensions() -> None:
    """All six C++ source / header extensions are registered."""
    for ext in (".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"):
        assert ext in supported_extensions()


def test_cpp_extensions_route_to_cpp_language() -> None:
    """The six C++ extensions route to the C++ LanguageDefinition."""
    for ext in (".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"):
        assert get_language_for_file(f"foo{ext}") is CPP


def test_plain_h_still_routes_to_c_not_cpp() -> None:
    """A plain ``.h`` header stays with C (documented) - only C++-specific headers are C++."""
    assert get_language_for_file("foo.h") is C


def test_cpp_language_definition_basics() -> None:
    """Sanity checks on the LanguageDefinition exposed by the C++ module."""
    assert CPP.name == "cpp"
    assert CPP.comment_node_type == "comment"
    assert CPP.comment_prefix == "//"
    tree = CPP.create_parser().parse(b"int main() { return 0; }\n")
    assert tree.root_node.type == "translation_unit"


def test_engine_parses_clean_cpp_file(tmp_path: Path) -> None:
    """A clean C++ file produces zero violations."""
    sample = tmp_path / "ok.cpp"
    sample.write_text("int add(int a, int b) { return a + b; }\n", encoding="utf-8")
    assert _engine().check_file(str(sample)).violations == []


def test_engine_emits_safe000_on_unparseable_cpp(tmp_path: Path) -> None:
    """A syntactically broken C++ file surfaces a SAFE000 parse error, not a crash."""
    sample = tmp_path / "broken.cpp"
    sample.write_text("int f( { return\n", encoding="utf-8")
    codes = {v.code for v in _engine().check_file(str(sample)).violations}
    assert "SAFE000" in codes


def test_cpp_nosafe_comment_suppresses_violation(tmp_path: Path) -> None:
    """An inline ``// nosafe`` comment suppresses the violation on its line."""
    sample = tmp_path / "supp.cpp"
    body = "\n".join(f"    x += {i};" for i in range(70))
    sample.write_text(f"int longFn() {{  // nosafe: SAFE101\n    int x = 0;\n{body}\n    return x;\n}}\n", encoding="utf-8")
    codes = {v.code for v in _engine().check_file(str(sample)).violations}
    assert "SAFE101" not in codes


def test_engine_skips_python_only_rules_on_cpp(tmp_path: Path) -> None:
    """Python-only rules (e.g. SAFE301 global_state) never fire on C++ files."""
    sample = tmp_path / "state.cpp"
    sample.write_text("int g = 0;\nvoid f() { g = 1; }\n", encoding="utf-8")
    codes = {v.code for v in _engine().check_file(str(sample)).violations}
    assert "SAFE301" not in codes


def test_engine_discovers_cpp_files_under_directory(tmp_path: Path) -> None:
    """``check_path`` on a directory picks up C++ source / header files, not non-source files."""
    (tmp_path / "a.cpp").write_text("int f() { return 0; }\n", encoding="utf-8")
    (tmp_path / "b.hpp").write_text("int g();\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# notes\n", encoding="utf-8")
    file_names = {Path(result.path).name for result in _engine().check_path(str(tmp_path))}
    assert {"a.cpp", "b.hpp"}.issubset(file_names)
    assert "c.md" not in file_names
