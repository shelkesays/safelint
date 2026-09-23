"""Tests for the property-typed sanitiser config validators."""

from __future__ import annotations

import pytest

from safelint.core._validators import _validated_property_map, _validated_string_map
from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


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


# ---------------------------------------------------------------------------
# Adoption warnings: property declarations that cannot take effect
#
# The property tables fail *open* - a declaration that does not line up with the
# rest of the config simply never fires, which is indistinguishable from "the
# feature is broken". These assert each such case is surfaced on stderr (the
# project's typo-guard convention) and that a well-formed config stays silent.
# ---------------------------------------------------------------------------


def test_property_adoption_warnings(tmp_path, capsys) -> None:
    """Each inert-declaration shape produces exactly one targeted warning."""
    sample = tmp_path / "sample.py"
    sample.write_text("def g(u):\n    eval(u)\n", encoding="utf-8")

    cases = [
        # (overrides, substring expected in the warning)
        ({"sanitizers": ["escape"], "sanitizer_properties": {"escape": ["html"]}, "sink_properties": {"eval": "html"}}, "flat sanitizers list also contains escape"),
        ({"sanitizers": [], "sanitizer_properties": {"escape": []}, "sink_properties": {"eval": "html"}}, "empty property list for escape"),
        ({"sanitizers": [], "sanitizer_properties": {"escape": ["html"]}, "sink_properties": {"evl": "html"}}, "no configured sink named evl"),
        ({"sanitizers": [], "sanitizer_properties": {"escape": ["html"]}, "sink_properties": {}}, "no sink requires any of the declared properties"),
    ]
    for overrides, expected in cases:
        rule_cfg = {"enabled": True, "sinks": ["eval"], **overrides}
        engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
        engine.check_file(str(sample))
        err = capsys.readouterr().err
        assert expected in err, f"missing warning for {overrides}"
        assert err.count("safelint: warning:") == 1, f"expected one warning, got:\n{err}"


def test_well_formed_property_config_warns_nothing(tmp_path, capsys) -> None:
    """A contract whose declarations all line up produces no warning."""
    sample = tmp_path / "sample.py"
    sample.write_text("def g(u):\n    eval(u)\n", encoding="utf-8")
    rule_cfg = {
        "enabled": True,
        "sinks": ["eval"],
        "sanitizers": [],
        "sanitizer_properties": {"escape": ["html"]},
        "sink_properties": {"eval": "html"},
    }
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    engine.check_file(str(sample))
    assert "safelint: warning:" not in capsys.readouterr().err


def test_property_adoption_warning_emitted_once_per_run(tmp_path, capsys) -> None:
    """The warning is per-run, not per-file - the rule instance outlives the loop."""
    rule_cfg = {"enabled": True, "sinks": ["eval"], "sanitizers": [], "sanitizer_properties": {"escape": ["html"]}, "sink_properties": {}}
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    for name in ("a.py", "b.py", "c.py"):
        sample = tmp_path / name
        sample.write_text("def g(u):\n    eval(u)\n", encoding="utf-8")
        engine.check_file(str(sample))
    assert capsys.readouterr().err.count("safelint: warning:") == 1
