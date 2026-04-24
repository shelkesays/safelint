"""Tests for safelint.core.config - load_config and deep_merge."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, _read_toml_file, _try_pyproject, deep_merge, load_config


def test_defaults_have_expected_keys() -> None:
    """DEFAULTS contains all required top-level keys."""
    assert "mode" in DEFAULTS
    assert "fail_on" in DEFAULTS
    assert "rules" in DEFAULTS
    assert "execution" in DEFAULTS


def test_load_config_returns_defaults_when_no_file(tmp_path: Path) -> None:
    """load_config() falls back to DEFAULTS when no .safelint.yaml is found."""
    config = load_config(tmp_path)

    assert config["mode"] == DEFAULTS["mode"]
    assert config["fail_on"] == DEFAULTS["fail_on"]
    assert "rules" in config


def test_load_config_merges_yaml_with_defaults(tmp_path: Path) -> None:
    """load_config() deep-merges a .safelint.yaml with built-in defaults."""
    (tmp_path / ".safelint.yaml").write_text(
        "mode: ci\nrules:\n  function_length:\n    max_lines: 20\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config["mode"] == "ci"
    assert config["rules"]["function_length"]["max_lines"] == 20
    # Keys not in the file should still come from defaults
    assert "nesting_depth" in config["rules"]


def test_load_config_walks_up_to_find_file(tmp_path: Path) -> None:
    """load_config() walks parent directories to find .safelint.yaml."""
    (tmp_path / ".safelint.yaml").write_text("mode: ci\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    config = load_config(nested)

    assert config["mode"] == "ci"


def test_deep_merge_overrides_scalar_values() -> None:
    """deep_merge() overrides scalar values from the override dict."""
    result = deep_merge({"a": 1, "b": 2}, {"b": 99, "c": 3})

    assert result == {"a": 1, "b": 99, "c": 3}


def test_deep_merge_recurses_into_nested_dicts() -> None:
    """deep_merge() recursively merges nested dicts without clobbering siblings."""
    base = {"rules": {"function_length": {"max_lines": 60, "enabled": True}}}
    override = {"rules": {"function_length": {"max_lines": 30}}}

    result = deep_merge(base, override)

    assert result["rules"]["function_length"]["max_lines"] == 30
    assert result["rules"]["function_length"]["enabled"] is True


def test_deep_merge_does_not_mutate_base() -> None:
    """deep_merge() returns a new dict without modifying the original."""
    base = {"a": {"x": 1}}
    deep_merge(base, {"a": {"x": 99}})

    assert base["a"]["x"] == 1


# ---------------------------------------------------------------------------
# TOML config loading
# ---------------------------------------------------------------------------


def test_load_config_reads_pyproject_toml(tmp_path: Path) -> None:
    """load_config() reads [tool.safelint] from pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.safelint]\nmode = 'ci'\n\n[tool.safelint.rules.function_length]\nmax_lines = 25\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config["mode"] == "ci"
    assert config["rules"]["function_length"]["max_lines"] == 25
    # Keys not in the file still come from defaults
    assert "nesting_depth" in config["rules"]


def test_load_config_pyproject_without_safelint_section_falls_back(tmp_path: Path) -> None:
    """pyproject.toml without [tool.safelint] does not block .safelint.yaml lookup."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n", encoding="utf-8")
    (tmp_path / ".safelint.yaml").write_text("mode: ci\n", encoding="utf-8")

    config = load_config(tmp_path)

    assert config["mode"] == "ci"


def test_load_config_pyproject_takes_priority_over_yaml(tmp_path: Path) -> None:
    """pyproject.toml [tool.safelint] takes priority over .safelint.yaml."""
    (tmp_path / "pyproject.toml").write_text("[tool.safelint]\nmode = 'ci'\n", encoding="utf-8")
    (tmp_path / ".safelint.yaml").write_text("mode: local\n", encoding="utf-8")

    config = load_config(tmp_path)

    assert config["mode"] == "ci"


def test_load_config_pyproject_walks_up(tmp_path: Path) -> None:
    """load_config() walks parent directories to find pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text("[tool.safelint]\nfail_on = 'warning'\n", encoding="utf-8")
    nested = tmp_path / "src" / "mypackage"
    nested.mkdir(parents=True)

    config = load_config(nested)

    assert config["fail_on"] == "warning"


# ---------------------------------------------------------------------------
# Invalid TOML handling
# ---------------------------------------------------------------------------


def test_read_toml_file_returns_none_on_invalid(tmp_path: Path) -> None:
    """_read_toml_file returns None and logs an error when TOML is malformed."""
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_bytes(b"\xff\xfe this is not valid toml \x00\x01")

    result = _read_toml_file(bad_toml)

    assert result is None


def test_try_pyproject_returns_none_for_invalid_toml(tmp_path: Path) -> None:
    """_try_pyproject returns None when pyproject.toml fails to parse."""
    (tmp_path / "pyproject.toml").write_bytes(b"\xff\xfe not toml \x00")

    result = _try_pyproject(tmp_path)

    assert result is None
