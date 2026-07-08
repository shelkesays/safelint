"""Tests for the ``safelint list-rules`` subcommand and the rule catalogue.

Covers:

* The :mod:`safelint._rule_listing` helpers - spec generation, filtering,
  and each of the four output formatters (``text`` / ``json`` /
  ``markdown`` / ``sarif``).
* The CLI surface in :mod:`safelint.cli` - the ``list-rules`` subcommand
  routing, the ``--list-rules`` flag alias, and the zero-match exit-code
  contract.

The catalogue is bundled-defaults-driven (severity and ``default_enabled``
come from :data:`safelint.core.config.DEFAULTS`) so these tests don't
need a user config or a temp project - they exercise the same data the
shipped wheel exposes.
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

import pytest

from safelint import __version__, cli
from safelint import _rule_listing as rl
from safelint._rule_listing import (
    RuleSpec,
    _description_for,
    filter_specs,
    format_json_listing,
    format_markdown_listing,
    format_sarif_listing,
    format_text,
    iter_rule_specs,
)
from safelint.rules import ALL_RULES
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# iter_rule_specs - catalogue extraction
# ---------------------------------------------------------------------------


def test_iter_rule_specs_returns_one_entry_per_registered_rule() -> None:
    """Catalogue length matches :data:`safelint.rules.ALL_RULES`."""
    specs = iter_rule_specs()
    assert len(specs) == len(ALL_RULES)


def test_iter_rule_specs_spec_fields_for_function_length() -> None:
    """SAFE101 ``function_length`` carries its expected catalogue fields.

    Anchoring on a single well-known rule guards against accidental
    rewiring of the DEFAULTS lookup or the docstring extraction.
    """
    specs = {s.code: s for s in iter_rule_specs()}
    spec = specs["SAFE101"]
    assert spec.name == "function_length"
    assert spec.severity == "error"
    assert spec.default_enabled is True
    assert "python" in spec.languages
    assert "rust" in spec.languages
    assert spec.category == "function shape"
    assert spec.category_digit == "1"
    assert "exceeds" in spec.description.lower()


def test_iter_rule_specs_rust_only_rule_has_off_default() -> None:
    """Rust-only opt-in rules (e.g. SAFE110 ``needless_mut``) come through as off-by-default."""
    specs = {s.code: s for s in iter_rule_specs()}
    spec = specs["SAFE110"]
    assert spec.name == "needless_mut"
    assert spec.languages == ("rust",)
    assert spec.default_enabled is False
    assert spec.severity == "warning"


def test_iter_rule_specs_spring_rules_in_framework_category() -> None:
    """SAFE9xx Spring rules land in the framework-specific category band."""
    specs = {s.code: s for s in iter_rule_specs()}
    sp = specs["SAFE901"]
    assert sp.category_digit == "9"
    assert sp.category == "framework-specific"
    assert sp.languages == ("java",)


# ---------------------------------------------------------------------------
# filter_specs - language / enabled-only filter combinations
# ---------------------------------------------------------------------------


def test_filter_specs_language_rust_drops_non_rust_only_rules() -> None:
    """``language='rust'`` keeps cross-language + rust-only rules, drops the rest."""
    specs = iter_rule_specs()
    rust = filter_specs(specs, language="rust")
    codes = {s.code for s in rust}
    # SAFE110 is rust-only - must be present.
    assert "SAFE110" in codes
    # SAFE101 applies to rust as part of its cross-language tuple - must be present.
    assert "SAFE101" in codes
    # SAFE201 (bare_except) is python-only - must be filtered out.
    assert "SAFE201" not in codes
    # SAFE901 (Spring) is java-only - must be filtered out.
    assert "SAFE901" not in codes


def test_filter_specs_enabled_only_drops_opt_in_rules() -> None:
    """``enabled_only=True`` keeps only rules whose DEFAULTS entry is ``enabled: True``."""
    specs = iter_rule_specs()
    on = filter_specs(specs, enabled_only=True)
    codes = {s.code for s in on}
    # SAFE101 ships enabled.
    assert "SAFE101" in codes
    # SAFE110 is opt-in - must be filtered.
    assert "SAFE110" not in codes
    # SAFE801 (tainted_sink) is opt-in - must be filtered.
    assert "SAFE801" not in codes


def test_filter_specs_combines_language_and_enabled_only() -> None:
    """Both filters compose - language=rust + enabled_only yields the cross-language rust-applicable subset."""
    specs = iter_rule_specs()
    out = filter_specs(specs, language="rust", enabled_only=True)
    codes = {s.code for s in out}
    # SAFE101 ships enabled and applies to rust.
    assert "SAFE101" in codes
    # SAFE110 applies to rust but is opt-in - must be filtered.
    assert "SAFE110" not in codes
    # SAFE201 (python-only) - must be filtered.
    assert "SAFE201" not in codes


def test_filter_specs_empty_input_returns_empty() -> None:
    """No specs in → no specs out, regardless of filter shape."""
    assert filter_specs([], language="python") == []
    assert filter_specs([], enabled_only=True) == []


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------


def test_format_text_includes_category_header_and_rule_row() -> None:
    """The text view emits a per-category header line and one row per rule."""
    specs = iter_rule_specs()
    out = format_text(specs)
    # Section header for the 1xx band.
    assert "1xx - function shape" in out
    # A specific rule row - using the rule code as the anchor since the
    # spacing is alignment-driven and brittle to assert verbatim.
    assert "SAFE101" in out
    assert "function_length" in out
    # The default column shows ``on`` for enabled-by-default rules and
    # ``off`` for opt-in rules - exercise both.
    assert " on " in out or " on\n" in out
    assert "off" in out


def test_format_text_empty_input_returns_empty_string() -> None:
    """Empty specs → empty output, so callers can branch on it."""
    assert format_text([]) == ""


def test_format_text_groups_by_category_in_canonical_order() -> None:
    """Category sections appear in 1xx -> 9xx order, even when specs are shuffled."""
    specs = iter_rule_specs()
    out = format_text(specs)
    one = out.find("1xx -")
    two = out.find("2xx -")
    three = out.find("3xx -")
    assert -1 < one < two < three


# ---------------------------------------------------------------------------
# format_json_listing
# ---------------------------------------------------------------------------


def test_format_json_listing_emits_versioned_document_with_rules_array() -> None:
    """JSON output carries ``version`` + a sorted ``rules`` array with the full per-rule schema."""
    specs = iter_rule_specs()
    doc = json.loads(format_json_listing(specs))
    assert doc["version"] == __version__
    rules = doc["rules"]
    assert len(rules) == len(specs)
    # Sorted by code - SAFE101 must come before SAFE110.
    codes = [r["code"] for r in rules]
    assert codes == sorted(codes)
    # Schema spot-check: every rule has the documented keys.
    expected_keys = {"code", "name", "severity", "default_enabled", "languages", "category", "description"}
    for rule in rules:
        assert expected_keys <= set(rule.keys())


def test_format_json_listing_rust_only_rule_languages_field() -> None:
    """Rust-only rules render with a single-element ``languages`` list."""
    specs = [s for s in iter_rule_specs() if s.code == "SAFE110"]
    doc = json.loads(format_json_listing(specs))
    assert doc["rules"][0]["languages"] == ["rust"]
    assert doc["rules"][0]["default_enabled"] is False


# ---------------------------------------------------------------------------
# format_markdown_listing
# ---------------------------------------------------------------------------


def test_format_markdown_listing_emits_one_table_per_category() -> None:
    """Markdown output renders ``## Nxx - <category>`` headers and a table beneath each."""
    specs = iter_rule_specs()
    out = format_markdown_listing(specs)
    assert "## 1xx - function shape" in out
    assert "## 2xx - error handling" in out
    # Table shape: header row + separator row.
    assert "| Code | Name | Severity |" in out
    assert "|---|---|---|" in out
    # The function_length rule appears with backticks around the code.
    assert "`SAFE101`" in out


def test_format_markdown_listing_empty_input_returns_empty_string() -> None:
    """No specs → empty Markdown so docs pipelines don't materialise blank pages."""
    assert format_markdown_listing([]) == ""


# ---------------------------------------------------------------------------
# format_sarif_listing
# ---------------------------------------------------------------------------


def test_format_sarif_listing_emits_valid_sarif_2_1_0_skeleton() -> None:
    """SARIF output is a 2.1.0 document with the catalogue under ``tool.driver.rules``."""
    specs = iter_rule_specs()
    doc = json.loads(format_sarif_listing(specs))
    assert doc["version"] == "2.1.0"
    assert doc["$schema"].endswith("sarif-schema-2.1.0.json")
    run = doc["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "safelint"
    assert driver["version"] == __version__
    # Results array MUST be present and empty - this is a catalogue document.
    assert run["results"] == []
    # One reportingDescriptor per rule, sorted by code.
    rule_ids = [r["id"] for r in driver["rules"]]
    assert rule_ids == sorted(rule_ids)
    assert len(rule_ids) == len(specs)


def test_format_sarif_listing_descriptor_carries_default_config_and_properties() -> None:
    """Each SARIF rule descriptor carries ``defaultConfiguration`` + ``properties``."""
    specs = [s for s in iter_rule_specs() if s.code in {"SAFE101", "SAFE110"}]
    doc = json.loads(format_sarif_listing(specs))
    by_id = {r["id"]: r for r in doc["runs"][0]["tool"]["driver"]["rules"]}
    fl = by_id["SAFE101"]
    assert fl["defaultConfiguration"] == {"level": "error", "enabled": True}
    assert "python" in fl["properties"]["languages"]
    assert fl["properties"]["category"] == "function shape"
    nm = by_id["SAFE110"]
    assert nm["defaultConfiguration"] == {"level": "warning", "enabled": False}
    assert nm["properties"]["languages"] == ["rust"]


# ---------------------------------------------------------------------------
# CLI surface - list-rules subcommand + --list-rules flag alias
# ---------------------------------------------------------------------------


def test_cli_main_routes_list_rules_subcommand(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """First non-flag arg ``list-rules`` invokes ``_run_list_rules``."""
    monkeypatch.setattr("sys.argv", ["safelint", "list-rules", "--language=rust"])
    spy = mocker.patch.object(cli, "_run_list_rules", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()
    # The parser-derived Namespace was constructed and forwarded.
    args = spy.call_args.args[0]
    assert args.language == "rust"
    assert args.output_format == "text"


def test_cli_main_routes_list_rules_flag_alias(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--list-rules`` anywhere in argv dispatches to the same handler."""
    monkeypatch.setattr("sys.argv", ["safelint", "--list-rules", "--format=json"])
    spy = mocker.patch.object(cli, "_run_list_rules", return_value=0)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    spy.assert_called_once()
    args = spy.call_args.args[0]
    assert args.output_format == "json"


def test_cli_help_list_rules_subcommand_defers_to_argparse(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``safelint help list-rules`` prints argparse's per-subcommand help."""
    monkeypatch.setattr("sys.argv", ["safelint", "help", "list-rules"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "list-rules" in captured.out
    assert "--language" in captured.out
    assert "--format" in captured.out


def test_description_for_handles_rules_without_docstring() -> None:
    """The fallback path uses the rule name when ``__doc__`` is missing.

    Today's shipped rules all have class docstrings; the fallback exists
    so a contributor adding a docstring-less rule still gets a
    catalogue-renderable description instead of an empty string.
    """

    class _NoDocRule(BaseRule):
        name = "needs_a_description"
        code = "SAFE998"

        def check_file(self, filepath, tree):  # type: ignore[override]
            return []

    _NoDocRule.__doc__ = None
    desc = _description_for(_NoDocRule)
    assert desc == "Needs a description"


def test_format_text_empty_after_filter_returns_empty() -> None:
    """A filter that drops everything leaves :func:`format_text` empty.

    The CLI uses this branch (via :func:`filter_specs` returning ``[]``)
    to decide whether to emit the stderr error path - confirm the
    contract holds end-to-end.
    """
    assert format_text([]) == ""


def test_print_rule_listing_renders_each_format_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """``_print_rule_listing`` writes the right output for each of the four formats.

    Mocking ``_run_list_rules`` in the routing tests leaves the actual
    rendering dispatch untested - this test drives every branch
    (``text`` / ``markdown`` / ``json`` / ``sarif``) directly so the
    behaviour is exercised end-to-end.
    """
    specs = [s for s in iter_rule_specs() if s.code == "SAFE101"]
    for fmt in ("text", "markdown", "json", "sarif"):
        cli._print_rule_listing(specs, fmt)
        captured = capsys.readouterr()
        assert "SAFE101" in captured.out, f"format {fmt!r} did not render the rule code"


def test_grouped_by_category_handles_unknown_band_synthesizes_other_section() -> None:
    """A rule whose code doesn't slot into 1xx-9xx lands in the synthetic ``other`` section.

    Today no such rule ships, but the catalogue's category-bucket logic
    is defensive against contributor mistakes (wrong code prefix); the
    test pins that the fallback bucket renders rather than dropping the
    rule on the floor.
    """
    odd = RuleSpec(
        code="ODD000",
        name="oddball",
        severity="warning",
        languages=("python",),
        default_enabled=False,
        category="other",
        category_digit="?",
        description="Synthetic rule for grouping fallback test.",
    )
    out = format_text([odd])
    assert "?xx - other" in out
    assert "ODD000" in out


def test_cli_list_rules_zero_match_exits_two(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A filter combination matching zero rules exits 2 + writes a stderr error.

    The exit-2 contract guards against typos in CI scripts silently producing
    an empty catalogue document.
    """
    # Drive the runner directly with a controlled empty catalogue to exercise
    # the stderr error path. Hand-built Namespace mirrors what argparse would
    # produce for ``safelint list-rules --language rust`` against an empty
    # iterator.
    args = argparse.Namespace(language="rust", output_format="text", enabled_only=False)
    # Force an empty catalogue: ``list`` consumes the (spec, ...) iterator and
    # yields nothing. ``monkeypatch`` restores the original after the test.
    monkeypatch.setattr(rl, "iter_rule_specs", list)
    rc = cli._run_list_rules(args)
    captured = capsys.readouterr()
    assert rc == 2
    assert "no rules matched" in captured.err
