"""End-to-end smoke tests for Go language registration.

Covers the language-registry plumbing: ``.go`` files are discovered, the
Go parser handles them, parse errors surface as ``SAFE000``, ``// nosafe``
suppression works, and Python-only rules (no try/catch analogue) are
correctly skipped on Go files via the engine's per-language dispatch.

Per-rule Go behaviour lives in dedicated test files under
``tests/rules/test_*_go.py`` - this file stays focused on plumbing.
"""

from __future__ import annotations

from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import GO, get_language_for_file, supported_extensions


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_go_extension_in_supported_extensions() -> None:
    """``.go`` is registered."""
    assert ".go" in supported_extensions()


def test_get_language_for_go_file_returns_go() -> None:
    """The ``.go`` extension routes to the GO LanguageDefinition."""
    assert get_language_for_file("foo.go") is GO


def test_go_language_definition_basics() -> None:
    """Sanity checks on the LanguageDefinition exposed by the Go module."""
    assert GO.name == "go"
    assert GO.comment_node_type == "comment"
    assert GO.comment_prefix == "//"
    tree = GO.create_parser().parse(b"package main\nfunc main() {}\n")
    assert tree.root_node.type == "source_file"


def test_engine_parses_clean_go_file(tmp_path: Path) -> None:
    """A clean Go file produces zero violations."""
    sample = tmp_path / "ok.go"
    sample.write_text("package main\nfunc add(a, b int) int {\n\treturn a + b\n}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert result.violations == []
    assert result.suppressed == []


def test_engine_emits_safe000_on_unparseable_go(tmp_path: Path) -> None:
    """Tree-sitter parse errors on broken Go surface as SAFE000."""
    sample = tmp_path / "broken.go"
    sample.write_text("package main\nfunc broken( {\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE000" for v in result.violations), "Expected SAFE000 on broken Go source"


def test_engine_skips_python_only_rules_on_go(tmp_path: Path) -> None:
    """Python-only rules (e.g. SAFE201 bare_except, SAFE301 global_state) never fire on Go."""
    sample = tmp_path / "state.go"
    sample.write_text("package main\nvar counter int\n", encoding="utf-8")
    codes = {v.code for v in _engine().check_file(str(sample)).violations}
    assert "SAFE201" not in codes
    assert "SAFE301" not in codes


def test_go_nosafe_comment_suppresses_violation(tmp_path: Path) -> None:
    """A ``// nosafe`` directive on the offending line suppresses the violation."""
    sample = tmp_path / "supp.go"
    sample.write_text("package main\nvar counter int // nosafe: SAFE302\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE302" for v in result.violations)
    assert any(v.code == "SAFE302" for v in result.suppressed)


def test_engine_discovers_go_files_under_directory(tmp_path: Path) -> None:
    """``check_path`` on a directory picks up ``.go`` files alongside ``.py``."""
    (tmp_path / "a.go").write_text("package main\nfunc f() {}\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("z = 4\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# notes\n", encoding="utf-8")
    file_names = {Path(result.path).name for result in _engine().check_path(str(tmp_path))}
    assert {"a.go", "b.py"}.issubset(file_names)
    assert "c.md" not in file_names
