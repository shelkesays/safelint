"""Tests for the property-typed sanitiser config validators."""

from __future__ import annotations

import sys

import pytest

from safelint.cli import main
from safelint.core._validators import ConfigValueError, _validated_property_map, _validated_string_list, _validated_string_map
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


# ---------------------------------------------------------------------------
# ConfigValueError: a mistyped config value is an error message, not a traceback
# ---------------------------------------------------------------------------


def test_config_value_error_is_a_type_error() -> None:
    """Subclassing TypeError keeps every existing caller and test working."""
    assert issubclass(ConfigValueError, TypeError)


def test_validators_raise_config_value_error() -> None:
    """All three validators raise the catchable subtype, not a bare TypeError."""
    with pytest.raises(ConfigValueError):
        _validated_string_list("eval", "sinks")
    with pytest.raises(ConfigValueError):
        _validated_property_map(["escape"], "sanitizer_properties")
    with pytest.raises(ConfigValueError):
        _validated_string_map(["eval"], "sink_properties")


def test_cli_renders_mistyped_config_as_one_line_error(tmp_path, monkeypatch, capsys) -> None:
    """``sinks = "eval"`` (missing brackets) prints one error line and exits 2.

    It used to escape the CLI as an uncaught TypeError, dumping a traceback
    that read like a crash in safelint and buried the message saying what to
    fix."""
    (tmp_path / "safelint.toml").write_text('[rules.tainted_sink]\nenabled = true\nsinks = "eval"\n', encoding="utf-8")
    sample = tmp_path / "sample.py"
    sample.write_text("def g(u):\n    eval(u)\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["safelint", "check", str(sample)])

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err.strip() == "safelint: error: sinks must be a list of strings, got str"
    assert "Traceback" not in err


def test_property_audit_runs_without_checking_any_file(tmp_path, capsys) -> None:
    """The audit happens at construction, so a cache hit cannot skip it.

    The engine returns cached results *before* rules run, so while the audit
    lived on the per-file path a warm cache silently dropped these warnings -
    a user re-running to re-read one would find it gone. Constructing the
    engine and checking nothing must still warn."""
    rule_cfg = {
        "enabled": True,
        "sinks": ["eval"],
        "sanitizers": [],
        "sanitizer_properties": {"escape": ["html"]},
        "sink_properties": {},
    }
    SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    assert "no sink requires any of the declared properties" in capsys.readouterr().err


def test_php_expression_sinks_are_not_reported_as_unknown(capsys) -> None:
    """`include` / `require` are valid `sink_properties_php` keys.

    PHP's expression sinks are recognised by node type (`include_expression`),
    never by a lookup in the flat `sinks_php` list, and
    `PhpTaintTracker._visit_include` consults their required property directly.
    Declaring one must not trip the unknown-sink typo guard."""
    rule_cfg = {
        "enabled": True,
        "sinks_php": ["eval"],
        "sanitizers_php": [],
        "sanitizer_properties_php": {"realpath": ["path_safe"]},
        "sink_properties_php": {"include": "path_safe", "require_once": "path_safe"},
    }
    SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    assert "safelint: warning:" not in capsys.readouterr().err


def test_unknown_sink_typo_still_warns_for_php(capsys) -> None:
    """The exemption is exact - a misspelt expression sink still warns."""
    rule_cfg = {
        "enabled": True,
        "sinks_php": ["eval"],
        "sanitizers_php": [],
        "sanitizer_properties_php": {"realpath": ["path_safe"]},
        "sink_properties_php": {"inclde": "path_safe"},
    }
    SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    assert "no configured sink named inclde" in capsys.readouterr().err


def test_typescript_javascript_shared_keys_warn_once(capsys) -> None:
    """One JS declaration warns once, not once per language that resolves it.

    TypeScript falls back to the `_javascript` keys when it declares none of
    its own, so auditing per language would emit the identical warning twice."""
    rule_cfg = {
        "enabled": True,
        "sanitizer_properties_javascript": {"encodeURI": ["url_safe"]},
        "sink_properties_javascript": {"eval": "url_safe"},
    }
    SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    assert capsys.readouterr().err.count("safelint: warning:") == 1


def test_typescript_own_keys_warn_separately(capsys) -> None:
    """A TypeScript-specific declaration is its own config and warns on its own."""
    rule_cfg = {
        "enabled": True,
        "sanitizer_properties_javascript": {"encodeURI": ["url_safe"]},
        "sink_properties_javascript": {"eval": "url_safe"},
        "sanitizer_properties_typescript": {"encodeURI": ["url_safe"]},
        "sink_properties_typescript": {"eval": "url_safe"},
    }
    SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    assert capsys.readouterr().err.count("safelint: warning:") == 2
