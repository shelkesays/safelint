"""End-to-end smoke tests for PHP language registration.

Covers the language-registry plumbing: ``.php`` files are discovered, the
PHP parser handles them, parse errors surface as ``SAFE000``, ``// nosafe``
suppression works, file-level ``// safelint: ignore`` directives work, and
Python-only rules are correctly skipped on PHP files via the engine's
per-language dispatch.

Per-rule PHP behaviour lives in dedicated test files under
``tests/rules/test_*_php.py`` - this file stays focused on plumbing.
"""

from __future__ import annotations

from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import PHP, get_language_for_file, supported_extensions


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def _long_function(name: str, lines: int = 70, *, decl_suffix: str = "") -> str:
    """A PHP function body long enough to trip SAFE101 (function_length default 60)."""
    body = "\n".join(f"    $a{i} = {i};" for i in range(lines))
    return f"<?php\nfunction {name}() {{{decl_suffix}\n{body}\n}}\n"


def test_php_extension_in_supported_extensions() -> None:
    """``.php`` is registered."""
    assert ".php" in supported_extensions()


def test_get_language_for_php_file_returns_php() -> None:
    """The ``.php`` extension routes to the PHP LanguageDefinition."""
    assert get_language_for_file("foo.php") is PHP


def test_php_language_definition_basics() -> None:
    """Sanity checks on the LanguageDefinition exposed by the PHP module."""
    assert PHP.name == "php"
    assert PHP.comment_node_type == "comment"
    assert PHP.comment_prefix == "//"
    tree = PHP.create_parser().parse(b"<?php\nfunction main() {}\n")
    assert tree.root_node.type == "program"


def test_engine_parses_clean_php_file(tmp_path: Path) -> None:
    """A clean PHP file produces zero violations."""
    sample = tmp_path / "ok.php"
    sample.write_text("<?php\nfunction add($a, $b) {\n    return $a + $b;\n}\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert result.violations == []
    assert result.suppressed == []


def test_engine_emits_safe000_on_unparseable_php(tmp_path: Path) -> None:
    """Tree-sitter parse errors on broken PHP surface as SAFE000."""
    sample = tmp_path / "broken.php"
    sample.write_text("<?php\nfunction broken( {\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE000" for v in result.violations), "Expected SAFE000 on broken PHP source"


def test_engine_skips_python_only_rules_on_php(tmp_path: Path) -> None:
    """Python-only rules (e.g. SAFE201 bare_except, SAFE301 global_state) never fire on PHP."""
    sample = tmp_path / "state.php"
    sample.write_text("<?php\n$counter = 0;\n", encoding="utf-8")
    codes = {v.code for v in _engine().check_file(str(sample)).violations}
    assert "SAFE201" not in codes
    assert "SAFE301" not in codes


def test_php_known_bad_file_fires_safe101(tmp_path: Path) -> None:
    """A function longer than the SAFE101 limit fires the expected rule."""
    sample = tmp_path / "big.php"
    sample.write_text(_long_function("big"), encoding="utf-8")
    assert any(v.code == "SAFE101" for v in _engine().check_file(str(sample)).violations)


def test_php_nosafe_comment_suppresses_violation(tmp_path: Path) -> None:
    """A ``// nosafe`` directive on the offending line suppresses the violation."""
    sample = tmp_path / "supp.php"
    sample.write_text(_long_function("big", decl_suffix=" // nosafe: SAFE101"), encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE101" for v in result.violations)
    assert any(v.code == "SAFE101" for v in result.suppressed)


def test_php_file_level_ignore_directive_suppresses_violation(tmp_path: Path) -> None:
    """A standalone ``// safelint: ignore: SAFE101`` directive suppresses the rule file-wide."""
    sample = tmp_path / "fileignore.php"
    body = "\n".join(f"    $a{i} = {i};" for i in range(70))
    sample.write_text(
        f"<?php\n// safelint: ignore: SAFE101\nfunction big() {{\n{body}\n}}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE101" for v in result.violations)
    assert any(v.code == "SAFE101" for v in result.suppressed)


def test_engine_discovers_php_files_under_directory(tmp_path: Path) -> None:
    """``check_path`` on a directory picks up ``.php`` files and reports their violations."""
    (tmp_path / "a.php").write_text(_long_function("big"), encoding="utf-8")
    (tmp_path / "b.py").write_text("z = 4\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# notes\n", encoding="utf-8")
    results = list(_engine().check_path(str(tmp_path)))
    file_names = {Path(result.path).name for result in results}
    assert {"a.php", "b.py"}.issubset(file_names)
    assert "c.md" not in file_names
    php_result = next(result for result in results if Path(result.path).name == "a.php")
    assert any(v.code == "SAFE101" for v in php_result.violations)
