"""Additional tests to reach the 80 % coverage threshold."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from safelint.core.config import SafeLintConfig
from safelint.core.engine import SafeLintEngine
from safelint.core.runner import run


# ---------------------------------------------------------------------------
# runner.run()
# ---------------------------------------------------------------------------


def test_run_without_config(tmp_path: Path) -> None:
    """run() with no config path uses defaults and returns lint results."""
    sample = tmp_path / "clean.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    results = run(sample)

    assert len(results) == 1
    assert results[0].path == sample


def test_run_with_config_path(tmp_path: Path) -> None:
    """run() loads the config from the supplied path."""
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text("max_function_lines: 5\n", encoding="utf-8")
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    results = run(sample, config_path=config_file)

    assert len(results) == 1


# ---------------------------------------------------------------------------
# SafeLintConfig — JSON loading and error paths
# ---------------------------------------------------------------------------


def test_config_loads_json_file(tmp_path: Path) -> None:
    """from_file() parses a JSON config correctly."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"max_function_lines": 20}), encoding="utf-8")

    config = SafeLintConfig.from_file(cfg)

    assert config.max_function_lines == 20


def test_config_missing_file_raises(tmp_path: Path) -> None:
    """from_file() raises FileNotFoundError for a non-existent path."""
    with pytest.raises(FileNotFoundError):
        SafeLintConfig.from_file(tmp_path / "missing.yaml")


def test_config_unsupported_extension_raises(tmp_path: Path) -> None:
    """from_file() raises ValueError for an unsupported file extension."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("[tool]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported config format"):
        SafeLintConfig.from_file(cfg)


def test_config_non_mapping_payload_raises(tmp_path: Path) -> None:
    """from_file() raises ValueError when the YAML root is not a mapping."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        SafeLintConfig.from_file(cfg)


# ---------------------------------------------------------------------------
# SafeLintEngine.lint_path() — directory traversal
# ---------------------------------------------------------------------------


def test_engine_lint_path_traverses_directory(tmp_path: Path) -> None:
    """lint_path() with a directory visits every .py file inside it."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("z = 3\n", encoding="utf-8")

    config = SafeLintConfig(
        enabled_rules=["function-length"],
        exclude=[],  # don't exclude anything so all .py files are visited
    )
    engine = SafeLintEngine(config=config)
    results = engine.lint_path(tmp_path)

    paths = {r.path for r in results}
    assert tmp_path / "a.py" in paths
    assert tmp_path / "b.py" in paths
    assert sub / "c.py" in paths


def test_engine_lint_path_single_file(tmp_path: Path) -> None:
    """lint_path() with a file path delegates to lint_file."""
    sample = tmp_path / "sample.py"
    sample.write_text("x = 1\n", encoding="utf-8")

    engine = SafeLintEngine()
    results = engine.lint_path(sample)

    assert len(results) == 1
    assert results[0].path == sample


# ---------------------------------------------------------------------------
# SideEffectsRule — branch coverage
# ---------------------------------------------------------------------------


def _make_side_effects_engine(*, allow: bool = False) -> SafeLintEngine:
    config = SafeLintConfig(
        enabled_rules=["side-effects"],
        allow_top_level_side_effects=allow,
    )
    return SafeLintEngine(config=config)


def test_side_effects_allow_flag_short_circuits(tmp_path: Path) -> None:
    """When allow_top_level_side_effects=True the rule returns empty."""
    sample = tmp_path / "se.py"
    sample.write_text("print('boom')\n", encoding="utf-8")

    engine = _make_side_effects_engine(allow=True)
    result = engine.lint_file(sample)

    assert result.violations == []


def test_side_effects_assignment_with_literal_is_allowed(tmp_path: Path) -> None:
    """Module-level assignments to literals do not count as side effects."""
    sample = tmp_path / "se.py"
    sample.write_text("VERSION = '1.0.0'\n", encoding="utf-8")

    engine = _make_side_effects_engine()
    result = engine.lint_file(sample)

    assert result.violations == []


def test_side_effects_annotated_assignment_is_allowed(tmp_path: Path) -> None:
    """Module-level annotated assignments with constant values are allowed."""
    sample = tmp_path / "se.py"
    sample.write_text("x: int = 0\n", encoding="utf-8")

    engine = _make_side_effects_engine()
    result = engine.lint_file(sample)

    assert result.violations == []


def test_side_effects_module_docstring_is_allowed(tmp_path: Path) -> None:
    """A module-level string expression (docstring) is not flagged."""
    sample = tmp_path / "se.py"
    sample.write_text('"""Module docstring."""\n', encoding="utf-8")

    engine = _make_side_effects_engine()
    result = engine.lint_file(sample)

    assert result.violations == []


def test_side_effects_all_append_is_allowed(tmp_path: Path) -> None:
    """``__all__.append(...)`` is explicitly whitelisted."""
    sample = tmp_path / "se.py"
    sample.write_text("__all__.append('foo')\n", encoding="utf-8")

    engine = _make_side_effects_engine()
    result = engine.lint_file(sample)

    assert result.violations == []


def test_side_effects_if_not_main_guard_is_flagged(tmp_path: Path) -> None:
    """An if-statement that is not the __main__ guard is flagged."""
    source = textwrap.dedent("""\
        if some_condition:
            do_something()
    """)
    sample = tmp_path / "se.py"
    sample.write_text(source, encoding="utf-8")

    engine = _make_side_effects_engine()
    result = engine.lint_file(sample)

    codes = [v.code for v in result.violations]
    assert "SAFE301" in codes


# ---------------------------------------------------------------------------
# ResourceLifecycleRule — with open() usage (covers visit_With body)
# ---------------------------------------------------------------------------


def test_resource_lifecycle_with_open_is_safe(tmp_path: Path) -> None:
    """open() inside a with statement does not trigger SAFE401."""
    source = textwrap.dedent("""\
        with open('file.txt') as f:
            data = f.read()
    """)
    sample = tmp_path / "res.py"
    sample.write_text(source, encoding="utf-8")

    config = SafeLintConfig(enabled_rules=["resource-lifecycle"])
    engine = SafeLintEngine(config=config)
    result = engine.lint_file(sample)

    assert result.violations == []


def test_resource_lifecycle_async_with_open_is_safe(tmp_path: Path) -> None:
    """open() inside an async with statement does not trigger SAFE401."""
    source = textwrap.dedent("""\
        async def read():
            async with open('file.txt') as f:
                data = f.read()
    """)
    sample = tmp_path / "res_async.py"
    sample.write_text(source, encoding="utf-8")

    config = SafeLintConfig(enabled_rules=["resource-lifecycle"])
    engine = SafeLintEngine(config=config)
    result = engine.lint_file(sample)

    assert result.violations == []
