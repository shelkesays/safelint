"""Tests for safelint.core.config - load_config and deep_merge."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import (
    DEFAULTS,
    _read_toml_file,
    _try_pyproject,
    _try_standalone,
    deep_merge,
    find_config_root,
    load_config,
)


def test_defaults_have_expected_keys() -> None:
    """DEFAULTS contains all required top-level keys."""
    assert "mode" in DEFAULTS
    assert "fail_on" in DEFAULTS
    assert "rules" in DEFAULTS
    assert "execution" in DEFAULTS


def test_load_config_returns_defaults_when_no_file(tmp_path: Path) -> None:
    """load_config() falls back to DEFAULTS when no config file is found."""
    config = load_config(tmp_path)

    assert config["mode"] == DEFAULTS["mode"]
    assert config["fail_on"] == DEFAULTS["fail_on"]
    assert "rules" in config


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
    """pyproject.toml without [tool.safelint] falls back to defaults."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n", encoding="utf-8")

    config = load_config(tmp_path)

    assert config["mode"] == DEFAULTS["mode"]


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


# ---------------------------------------------------------------------------
# Standalone safelint.toml
# ---------------------------------------------------------------------------


def test_load_config_reads_standalone_safelint_toml(tmp_path: Path) -> None:
    """load_config() reads top-level keys from safelint.toml (no wrapper)."""
    (tmp_path / "safelint.toml").write_text(
        "mode = 'ci'\n\n[rules.function_length]\nmax_lines = 25\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config["mode"] == "ci"
    assert config["rules"]["function_length"]["max_lines"] == 25
    assert "nesting_depth" in config["rules"]


def test_load_config_standalone_takes_priority_over_pyproject(tmp_path: Path) -> None:
    """safelint.toml wins when both it and pyproject.toml [tool.safelint] exist."""
    (tmp_path / "pyproject.toml").write_text("[tool.safelint]\nmode = 'local'\n", encoding="utf-8")
    (tmp_path / "safelint.toml").write_text("mode = 'ci'\n", encoding="utf-8")

    config = load_config(tmp_path)

    assert config["mode"] == "ci"


def test_load_config_standalone_walks_up(tmp_path: Path) -> None:
    """load_config() walks parent directories to find safelint.toml."""
    (tmp_path / "safelint.toml").write_text("fail_on = 'warning'\n", encoding="utf-8")
    nested = tmp_path / "src" / "mypackage"
    nested.mkdir(parents=True)

    config = load_config(nested)

    assert config["fail_on"] == "warning"


def test_try_standalone_returns_none_when_missing(tmp_path: Path) -> None:
    """_try_standalone returns None when safelint.toml is absent."""
    assert _try_standalone(tmp_path) is None


def test_try_standalone_returns_none_for_invalid_toml(tmp_path: Path) -> None:
    """_try_standalone returns None when safelint.toml fails to parse."""
    (tmp_path / "safelint.toml").write_bytes(b"\xff\xfe not toml \x00")

    assert _try_standalone(tmp_path) is None


def test_find_config_root_returns_dir_with_standalone(tmp_path: Path) -> None:
    """``find_config_root`` returns the directory containing ``safelint.toml``."""
    (tmp_path / "safelint.toml").write_text("ignore = []\n", encoding="utf-8")
    assert find_config_root(tmp_path) == tmp_path


def test_find_config_root_skips_malformed_standalone_and_walks_up(tmp_path: Path) -> None:
    """A malformed ``safelint.toml`` is treated as not-a-config so the walk continues.

    Mirrors :func:`load_config` semantics — a broken file would otherwise
    anchor the cache at a directory whose config never actually loads.
    """
    inner = tmp_path / "subdir"
    inner.mkdir()
    # Malformed standalone in subdir: must NOT anchor here.
    (inner / "safelint.toml").write_bytes(b"\xff\xfe not toml \x00")
    # Valid standalone in tmp_path: that's where the walk should land.
    (tmp_path / "safelint.toml").write_text("ignore = []\n", encoding="utf-8")
    assert find_config_root(inner) == tmp_path


def test_find_config_root_does_not_double_print_parse_diagnostic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Probing a malformed config must not emit the parse-error diagnostic.

    The ``load_config`` path is the authoritative reporter; the probe
    used by ``find_config_root`` (and downstream by the cache anchor)
    is silent so a single broken file isn't surfaced to stderr twice
    per run.
    """
    (tmp_path / "safelint.toml").write_bytes(b"\xff\xfe not toml \x00")
    find_config_root(tmp_path)
    captured = capsys.readouterr()
    assert "failed to parse" not in captured.err


def test_find_config_root_returns_dir_with_tool_safelint_pyproject(tmp_path: Path) -> None:
    """``find_config_root`` returns the dir of a pyproject with ``[tool.safelint]``."""
    (tmp_path / "pyproject.toml").write_text('[tool.safelint]\nfail_on = "error"\n', encoding="utf-8")
    assert find_config_root(tmp_path) == tmp_path


def test_find_config_root_skips_pyproject_without_safelint(tmp_path: Path) -> None:
    """A ``pyproject.toml`` without ``[tool.safelint]`` does not anchor."""
    (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n', encoding="utf-8")
    assert find_config_root(tmp_path) is None


def test_find_config_root_returns_none_when_no_config_anywhere(tmp_path: Path) -> None:
    """``find_config_root`` returns ``None`` when nothing matches up the tree."""
    nested = tmp_path / "deep" / "deeper"
    nested.mkdir(parents=True)
    assert find_config_root(nested) is None


# ---------------------------------------------------------------------------
# extend_ignore / extend_per_file_ignores (1.8.0)
# ---------------------------------------------------------------------------


def test_extend_ignore_appends_to_existing_ignore_list(tmp_path: Path) -> None:
    """``extend_ignore`` grows the ``ignore`` list instead of replacing it."""
    (tmp_path / "safelint.toml").write_text(
        'ignore = ["SAFE701"]\nextend_ignore = ["SAFE702", "SAFE801"]\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert "SAFE701" in config["ignore"]
    assert "SAFE702" in config["ignore"]
    assert "SAFE801" in config["ignore"]
    # extend_ignore is consumed; downstream consumers only see ``ignore``.
    assert "extend_ignore" not in config


def test_extend_ignore_dedupes_when_overlapping(tmp_path: Path) -> None:
    """Duplicate codes between ``ignore`` and ``extend_ignore`` collapse to one."""
    (tmp_path / "safelint.toml").write_text(
        'ignore = ["SAFE701"]\nextend_ignore = ["SAFE701", "SAFE702"]\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config["ignore"].count("SAFE701") == 1
    assert "SAFE702" in config["ignore"]


def test_extend_per_file_ignores_merges_lists(tmp_path: Path) -> None:
    """``extend_per_file_ignores`` concatenates entries for an existing pattern."""
    (tmp_path / "safelint.toml").write_text(
        '[per_file_ignores]\n"tests/**" = ["SAFE101"]\n[extend_per_file_ignores]\n"tests/**" = ["SAFE102"]\n"docs/**" = ["SAFE601"]\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert sorted(config["per_file_ignores"]["tests/**"]) == ["SAFE101", "SAFE102"]
    assert config["per_file_ignores"]["docs/**"] == ["SAFE601"]
    assert "extend_per_file_ignores" not in config


def test_extend_ignore_validates_input_type(tmp_path: Path) -> None:
    """A non-list ``extend_ignore`` raises TypeError up front.

    Bare strings are explicitly rejected: ``extend_ignore = "SAFE701"``
    (missing brackets) would otherwise expand char-by-char during the
    iterable-unpacking merge, silently corrupting the ignore list.
    """
    (tmp_path / "safelint.toml").write_text(
        'extend_ignore = "SAFE701"\n',
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="extend_ignore"):
        load_config(tmp_path)


def test_extend_ignore_rejects_non_string_entries(tmp_path: Path) -> None:
    """Non-string entries in ``extend_ignore`` (e.g. ``[123]``) raise TypeError.

    Old behaviour silently coerced via ``str(...)`` which masked typos
    like ``[101]`` (intent: ``["SAFE101"]``). The validator now requires
    every entry to already be a str.
    """
    (tmp_path / "safelint.toml").write_text(
        "extend_ignore = [101]\n",
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="extend_ignore"):
        load_config(tmp_path)


def test_extend_ignore_rejects_corrupted_base_ignore(tmp_path: Path) -> None:
    """A misconfigured ``ignore = "SAFE701"`` (string) is caught when extend_ignore is also set.

    Without validating the base, ``[*existing, *extend_ignore]`` would
    expand the string char-by-char and slip past the engine's later
    type-guard (which only sees the resulting ``list[str]``).
    """
    (tmp_path / "safelint.toml").write_text(
        'ignore = "SAFE701"\nextend_ignore = ["SAFE702"]\n',
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="ignore"):
        load_config(tmp_path)


def test_extend_per_file_ignores_validates_input_type(tmp_path: Path) -> None:
    """A non-mapping ``extend_per_file_ignores`` raises TypeError."""
    (tmp_path / "safelint.toml").write_text(
        'extend_per_file_ignores = ["nope"]\n',
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="extend_per_file_ignores"):
        load_config(tmp_path)
