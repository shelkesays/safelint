"""End-to-end smoke tests for JavaScript (Node) language registration.

Covers the language-registry plumbing: ``.js`` / ``.mjs`` / ``.cjs``
files are discovered, the JavaScript parser handles them, parse errors
surface as ``SAFE000``, and Python-only rules are correctly skipped on
JS files (the engine's per-language dispatch is exercised here).

Per-rule JavaScript behaviour lives in dedicated test files under
``tests/rules/test_*_javascript.py`` — this file stays focused on the
cross-language plumbing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import JAVASCRIPT, get_language_for_file, supported_extensions


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


# ---------------------------------------------------------------------------
# Registry plumbing — JS is discoverable end-to-end.
# ---------------------------------------------------------------------------


def test_javascript_extensions_in_supported_extensions() -> None:
    """``.js`` / ``.mjs`` / ``.cjs`` are registered."""
    exts = supported_extensions()
    assert ".js" in exts
    assert ".mjs" in exts
    assert ".cjs" in exts


@pytest.mark.parametrize("ext", (".js", ".mjs", ".cjs"))
def test_get_language_for_js_file_returns_javascript(ext: str) -> None:
    """Each registered JS extension routes to the JAVASCRIPT LanguageDefinition."""
    lang = get_language_for_file(f"foo{ext}")
    assert lang is JAVASCRIPT


def test_javascript_language_definition_basics() -> None:
    """Sanity checks on the LanguageDefinition exposed by the JS module."""
    assert JAVASCRIPT.name == "javascript"
    assert JAVASCRIPT.comment_node_type == "comment"
    assert JAVASCRIPT.comment_prefix == "//"
    parser = JAVASCRIPT.create_parser()
    # Smoke test: parse a tiny program without raising.
    tree = parser.parse(b"const x = 1;")
    assert tree.root_node.type == "program"


# ---------------------------------------------------------------------------
# End-to-end: JS files flow through SafetyEngine.check_file.
# ---------------------------------------------------------------------------


def test_engine_parses_js_file_with_no_python_rules_firing(tmp_path: Path) -> None:
    """A clean JS file produces zero violations (Python-only rules are filtered out).

    Sample is small enough that no widened rule fires (function is
    short, has no nesting, no I/O, no taint flow). Verifies the
    engine parses the file and returns no violations rather than
    crashing on an empty rule list — the per-language dispatch
    correctly invokes only the rules whose ``language`` tuple
    includes ``"javascript"``.
    """
    sample = tmp_path / "ok.js"
    sample.write_text(
        "function add(a, b) { return a + b; }\nconst result = add(1, 2);\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert result.violations == []
    assert result.suppressed == []


def test_engine_parses_mjs_file(tmp_path: Path) -> None:
    """``.mjs`` (ES module) files are accepted by the JS parser."""
    sample = tmp_path / "module.mjs"
    sample.write_text(
        "export function add(a, b) { return a + b; }\nimport { other } from './other.mjs';\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert result.violations == []


def test_engine_parses_cjs_file(tmp_path: Path) -> None:
    """``.cjs`` (CommonJS module) files are accepted by the JS parser."""
    sample = tmp_path / "module.cjs"
    sample.write_text(
        "module.exports = function add(a, b) { return a + b; };\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert result.violations == []


def test_engine_emits_safe000_on_unparseable_js(tmp_path: Path) -> None:
    """Tree-sitter parse errors on broken JS surface as SAFE000."""
    sample = tmp_path / "broken.js"
    # Unterminated function body — Tree-sitter recovers but flags an error.
    sample.write_text("function broken( {\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    parse_violations = [v for v in result.violations if v.code == "SAFE000"]
    assert parse_violations, "Expected SAFE000 on broken JS source"


# ---------------------------------------------------------------------------
# File discovery — directory walks pick up JS files.
# ---------------------------------------------------------------------------


def test_engine_discovers_js_files_under_directory(tmp_path: Path) -> None:
    """``check_path`` on a directory picks up registered JS extensions alongside ``.py``."""
    (tmp_path / "a.js").write_text("const x = 1;\n", encoding="utf-8")
    (tmp_path / "b.mjs").write_text("export const y = 2;\n", encoding="utf-8")
    (tmp_path / "c.cjs").write_text("module.exports = 3;\n", encoding="utf-8")
    (tmp_path / "d.py").write_text("z = 4\n", encoding="utf-8")
    # Files that should *not* be picked up:
    (tmp_path / "e.json").write_text('{"k": 1}\n', encoding="utf-8")
    (tmp_path / "f.md").write_text("# notes\n", encoding="utf-8")

    results = _engine().check_path(str(tmp_path))
    file_names = {result.path.rsplit("/", 1)[-1] for result in results}
    assert {"a.js", "b.mjs", "c.cjs", "d.py"}.issubset(file_names)
    assert "e.json" not in file_names
    assert "f.md" not in file_names
