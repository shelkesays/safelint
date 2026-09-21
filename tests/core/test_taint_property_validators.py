"""Tests for the property-typed sanitiser config validators."""

from __future__ import annotations

import pytest

from safelint.core._validators import _validated_property_map, _validated_string_map


# ---------------------------------------------------------------------------
# _validated_property_map (sanitizer_properties: name -> [property, ...])
# ---------------------------------------------------------------------------


def test_property_map_valid_returns_frozensets() -> None:
    result = _validated_property_map({"escape": ["html_escaped"], "q": ["sql_escaped", "shell_quoted"]}, "sanitizer_properties")
    assert result == {"escape": frozenset({"html_escaped"}), "q": frozenset({"sql_escaped", "shell_quoted"})}


def test_property_map_empty_is_empty() -> None:
    assert _validated_property_map({}, "sanitizer_properties") == {}


def test_property_map_rejects_non_table() -> None:
    with pytest.raises(TypeError, match="must be a table"):
        _validated_property_map(["escape"], "sanitizer_properties")


def test_property_map_rejects_non_string_key() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        _validated_property_map({1: ["html_escaped"]}, "sanitizer_properties")


def test_property_map_rejects_non_list_value() -> None:
    with pytest.raises(TypeError, match="must be a list of strings"):
        _validated_property_map({"escape": "html_escaped"}, "sanitizer_properties")


def test_property_map_rejects_non_string_property() -> None:
    with pytest.raises(TypeError, match="only strings"):
        _validated_property_map({"escape": [1]}, "sanitizer_properties")


# ---------------------------------------------------------------------------
# _validated_string_map (sink_properties: name -> property)
# ---------------------------------------------------------------------------


def test_string_map_valid_returns_dict() -> None:
    assert _validated_string_map({"execute": "sql_escaped"}, "sink_properties") == {"execute": "sql_escaped"}


def test_string_map_empty_is_empty() -> None:
    assert _validated_string_map({}, "sink_properties") == {}


def test_string_map_rejects_non_table() -> None:
    with pytest.raises(TypeError, match="must be a table"):
        _validated_string_map(["execute"], "sink_properties")


def test_string_map_rejects_non_string_value() -> None:
    with pytest.raises(TypeError, match="string names to string properties"):
        _validated_string_map({"execute": ["sql_escaped"]}, "sink_properties")


def test_string_map_rejects_non_string_key() -> None:
    with pytest.raises(TypeError, match="string names to string properties"):
        _validated_string_map({2: "sql_escaped"}, "sink_properties")
