"""End-to-end integration test of the Java + Spring Boot rule set.

Runs the full ``SafetyEngine`` against representative Spring Boot
fixtures under ``tests/fixtures/spring_boot/`` and asserts the
expected violation profile per rule. Acts as the v2.1.0 regression
baseline: any future change that shifts the rule firing pattern on
real Spring Boot code (false positive, false negative, message-format
drift) surfaces here.

The fixtures are inspired by patterns from canonical Spring Boot
reference apps (spring-petclinic, spring-boot-samples) but
deliberately scoped so that every positive case (rule should fire)
has a matching negative case (rule should NOT fire) in the same
file - both for the test's own clarity and as a contributor
reference for "what does idiomatic Spring code look like under
each rule?".
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from safelint.core.config import (
    DEFAULTS,
    _apply_java_framework_preset,
    deep_merge,
)
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from collections.abc import Iterable


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "spring_boot"


def _all_rules_enabled_config(framework: str = "spring-boot") -> dict:
    """Return a config dict with the spring-boot preset applied and every relevant rule enabled.

    Default rule state under ``DEFAULTS`` has the dataflow rules
    (SAFE801 / SAFE802 / SAFE803), the test-coverage rules
    (SAFE701 / SAFE702), the assertion rule (SAFE601), and the four
    Spring-specific rules (SAFE901-904) all opt-in. This helper
    flips every Java-applicable rule to ``enabled = True`` so the
    fixture-based assertions exercise the full rule surface.
    """
    cfg = copy.deepcopy(DEFAULTS)
    _apply_java_framework_preset(cfg, framework)
    # Flip every dataflow + opt-in Java-applicable rule to enabled
    # so the fixture assertions exercise the full rule surface.
    for rule in (
        "tainted_sink",
        "return_value_ignored",
        "null_dereference",
        "missing_assertions",
        "test_existence",
        "test_coupling",
    ):
        cfg["rules"].setdefault(rule, {})["enabled"] = True
    # The framework preset already flips spring_* rules under
    # spring-boot; under vanilla they stay disabled, which matches
    # the vanilla-vs-preset comparison test below.
    return cfg


def _run_engine(fixture: str, framework: str = "spring-boot", *, extra_config: dict | None = None) -> list:
    """Lint a single fixture file with the spring-boot preset and return all violations.

    Combines default config with the framework preset and any
    ``extra_config`` override (deep-merged on top). Returns the flat
    violation list - both blocking and advisory.
    """
    cfg = _all_rules_enabled_config(framework)
    if extra_config is not None:
        cfg = deep_merge(cfg, extra_config)
    engine = SafetyEngine(cfg)
    result = engine.check_file(str(FIXTURES_DIR / fixture))
    return result.violations + result.suppressed


def _codes_in(violations: Iterable) -> list[str]:
    """Return just the SAFE codes from a violation list, in order."""
    return [v.code for v in violations]


# ---------------------------------------------------------------------------
# Per-fixture assertions (spring-boot preset)
# ---------------------------------------------------------------------------


def test_user_controller_violations() -> None:
    """UserController.java exercises SAFE901 / SAFE903 / SAFE801 / SAFE803.

    The fixture is hand-crafted so each rule has exactly one
    intentional positive case (a violation should fire) and the
    rest of the code is the negative control (no false positives
    on the surrounding methods).
    """
    violations = _run_engine("UserController.java")
    codes = _codes_in(violations)
    # SAFE901: exactly one @Autowired field (the userService field;
    # the constructor-injected jdbc / cache fields are the negative
    # controls).
    assert codes.count("SAFE901") == 1, f"expected one SAFE901, got {codes.count('SAFE901')}: {codes}"
    # SAFE903: exactly one unvalidated @RequestBody (the create()
    # method; update() has @Valid and is the negative control;
    # findById() uses @PathVariable which is deliberately not
    # covered).
    assert codes.count("SAFE903") == 1
    # SAFE801: jdbc.query(sql_with_taint) under the spring-boot
    # preset (``query`` is a Spring-specific sink). Vanilla preset
    # would NOT fire this - tested separately below.
    assert codes.count("SAFE801") == 1
    # SAFE803: cache.get(id).toString() is the chained null-deref
    # pattern.
    assert codes.count("SAFE803") == 1


def test_user_service_violations() -> None:
    """UserService.java exercises SAFE902.

    Three positive / negative pairs:

    * ``registerUser`` (2 writes, no @Transactional) - SAFE902 fires.
    * ``registerUserSafe`` (2 writes, with @Transactional) - no SAFE902.
    * ``registerJustUser`` (1 write) - no SAFE902 (single-write exempt).
    * ``findById`` (no writes) - no SAFE902 (read-only).
    """
    violations = _run_engine("UserService.java")
    codes = _codes_in(violations)
    assert codes.count("SAFE902") == 1, f"expected exactly one SAFE902, got {codes}"


def test_background_job_violations() -> None:
    """BackgroundJob.java exercises SAFE904.

    Four method shapes, one positive:

    * ``runUnsafe`` (@Async + throws) - SAFE904 fires.
    * ``runSafe`` (@Async, no throws) - no SAFE904.
    * ``runFutureBased`` (@Async + CompletableFuture, no throws) - no SAFE904.
    * ``runSync`` (throws but NOT @Async) - no SAFE904.
    """
    violations = _run_engine("BackgroundJob.java")
    codes = _codes_in(violations)
    assert codes.count("SAFE904") == 1, f"expected exactly one SAFE904, got {codes}"


def test_resource_usage_violations() -> None:
    """ResourceUsage.java exercises SAFE401 across vanilla + spring-boot.

    Two positive cases (leakStream, leakInnerResource); two
    negatives (safeWithResources, safeManualClose). SAFE401 is a
    cross-language rule unaffected by the framework preset, so the
    count is identical under both.
    """
    violations = _run_engine("ResourceUsage.java")
    codes = _codes_in(violations)
    assert codes.count("SAFE401") == 2, f"expected exactly two SAFE401, got {codes}"


def test_complex_nesting_violations() -> None:
    """ComplexNesting.java exercises SAFE102 (nesting_depth) and SAFE104 (complexity).

    ``deepNested`` exceeds both defaults (depth 4 > 2; complexity
    well above 10). ``flatHelper`` + ``scoreSingle`` are the
    negative controls.
    """
    violations = _run_engine("ComplexNesting.java")
    codes = _codes_in(violations)
    assert codes.count("SAFE102") == 1, f"expected one SAFE102, got {codes}"
    assert codes.count("SAFE104") == 1, f"expected one SAFE104, got {codes}"


def test_long_method_violations() -> None:
    """LongMethod.java exercises SAFE101 (function_length).

    ``expandedSwitch`` runs over 60 lines (the default cap);
    ``compactSwitch`` is the negative control.
    """
    violations = _run_engine("LongMethod.java")
    codes = _codes_in(violations)
    assert codes.count("SAFE101") == 1, f"expected exactly one SAFE101, got {codes}"


def test_error_handling_violations() -> None:
    """ErrorHandling.java exercises SAFE202 (empty_except) and SAFE203 (logging_on_error).

    Three catch-block flavours that both rules consider broken
    (empty body, comment-only body, no logging) plus two safe
    controls (SLF4J logger.error, throw-e re-raise):

    * ``swallowExceptionEmpty`` (truly empty catch) - SAFE202 fires
      (empty body) and SAFE203 also fires (no log call AND not a
      re-raise).
    * ``swallowExceptionWithComment`` (comment-only catch) - same:
      SAFE202 (comment-only counts as empty under tree-sitter-java
      named-children semantics) + SAFE203.
    * ``catchWithoutLogging`` (catch with body but no logger call) -
      SAFE203 fires only (body is non-empty so SAFE202 stays
      silent).
    * ``catchWithLogging`` (SLF4J logger.error) - no rules fire.
    * ``catchAndRethrow`` (throw e re-raise) - no rules fire.

    So the expected counts are SAFE202 == 2, SAFE203 == 3.
    """
    violations = _run_engine("ErrorHandling.java")
    codes = _codes_in(violations)
    assert codes.count("SAFE202") == 2, f"expected exactly two SAFE202, got {codes}"
    assert codes.count("SAFE203") == 3, f"expected three SAFE203 (the two empty catches plus the one bare catch all miss logging), got {codes}"


# ---------------------------------------------------------------------------
# Preset comparison: vanilla vs spring-boot on the same fixture
# ---------------------------------------------------------------------------


def test_spring_specific_sinks_only_fire_under_spring_boot_preset() -> None:
    """``jdbc.query(sql)`` SAFE801 fires under spring-boot but NOT under vanilla.

    Confirms the framework preset's sink-list override is
    genuinely scoped to its ``[java]`` selector. Same fixture, two
    different presets, two different verdicts.
    """
    spring_codes = _codes_in(_run_engine("UserController.java", framework="spring-boot"))
    vanilla_codes = _codes_in(_run_engine("UserController.java", framework="vanilla"))
    # SAFE801 (Spring-specific sink ``query``) fires under spring-boot.
    assert "SAFE801" in spring_codes
    # Under vanilla, ``query`` is NOT a recognised sink and the rule
    # does NOT fire on this fixture.
    assert "SAFE801" not in vanilla_codes


def test_spring_rules_disabled_under_vanilla_preset() -> None:
    """SAFE901-904 are all default-disabled under vanilla; the preset toggle is the only enabler.

    The fixtures contain plenty of triggers for each Spring rule;
    running the engine under the vanilla preset should produce
    zero SAFE9xx violations across every fixture.
    """
    spring_codes = []
    for fixture in (
        "UserController.java",
        "UserService.java",
        "BackgroundJob.java",
    ):
        spring_codes.extend(_codes_in(_run_engine(fixture, framework="vanilla")))
    spring9xx = [c for c in spring_codes if c.startswith("SAFE9")]
    assert spring9xx == [], f"vanilla preset must not fire SAFE9xx, got {spring9xx}"


def test_spring_rules_all_fire_under_spring_boot_preset() -> None:
    """Sanity check: every SAFE9xx rule fires at least once across the fixture set.

    Confirms the wiring end-to-end: framework preset → rule
    enabled → engine dispatch → violation emitted. Catches the
    failure mode where a future change wires up the preset
    correctly but a typo / regression silently disables one of
    the four rules.
    """
    all_codes: list[str] = []
    for fixture in (
        "UserController.java",  # SAFE901, SAFE903
        "UserService.java",  # SAFE902
        "BackgroundJob.java",  # SAFE904
    ):
        all_codes.extend(_codes_in(_run_engine(fixture, framework="spring-boot")))
    for expected in ("SAFE901", "SAFE902", "SAFE903", "SAFE904"):
        assert expected in all_codes, f"{expected} did not fire across fixtures: {sorted(set(all_codes))}"


# ---------------------------------------------------------------------------
# Sanitiser end-to-end: SAFE801 with OWASP Encoder clears taint
# ---------------------------------------------------------------------------


def test_owasp_html_encoder_does_not_clear_sql_sink_taint(tmp_path: Path) -> None:
    """``Encode.forHtml(userInput)`` does NOT clear SAFE801 on a SQL ``jdbc.query`` sink.

    SAFE801 has a single shared ``sanitizers_java`` set that clears
    taint for every sink type. Context-specific output encoders -
    OWASP Java Encoder ``forHtml`` / ``forXml`` / ``forJavaScript``,
    Apache Commons ``escapeHtml*``, Spring ``htmlEscape`` - are
    deliberately NOT in the defaults because they do not make input
    safe for SQL / shell / reflection sinks. This test locks the
    behaviour in: an HTML encoder routed into a SQL sink must still
    fire SAFE801.

    The earlier ``test_owasp_encoder_sanitiser_clears_taint`` test
    (now removed) asserted the opposite and locked in a dangerous
    false negative. PR 56 review caught it.

    Projects that DO want HTML encoders treated as universal
    sanitisers can opt in by extending
    ``[tool.safelint.rules.tainted_sink] sanitizers_java``
    in their TOML; the strict default avoids the cross-context
    confusion by default.
    """
    # Build the controller source inline so the assertion is decoupled
    # from formatting choices in the shared fixture file. Previously this
    # test did a ``str.replace`` against the full UserController.java
    # snippet, which broke whenever the fixture was reformatted /
    # whitespace-shuffled even if SAFE801 behaviour was unchanged.
    sanitised_source = (
        "package com.example.petclinic;\n"
        "\n"
        "import org.springframework.jdbc.core.JdbcTemplate;\n"
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "import org.springframework.web.bind.annotation.RequestParam;\n"
        "import org.springframework.web.bind.annotation.RestController;\n"
        "\n"
        "@RestController\n"
        "public class HtmlEncodedSqlController {\n"
        "    private final JdbcTemplate jdbc;\n"
        "\n"
        "    public HtmlEncodedSqlController(JdbcTemplate jdbc) {\n"
        "        this.jdbc = jdbc;\n"
        "    }\n"
        "\n"
        '    @GetMapping("/search")\n'
        "    public java.util.List<?> search(@RequestParam String name) {\n"
        "        // HTML encoding does NOT make ``name`` safe for SQL\n"
        "        // concatenation; SAFE801 must still fire on jdbc.query.\n"
        "        String safe = org.owasp.encoder.Encode.forHtml(name);\n"
        '        String sql = "SELECT * FROM users WHERE name = \'" + safe + "\'";\n'
        "        return jdbc.query(sql, new Object[]{});\n"
        "    }\n"
        "}\n"
    )
    sanitised_file = tmp_path / "HtmlEncodedSqlController.java"
    sanitised_file.write_text(sanitised_source, encoding="utf-8")
    cfg = _all_rules_enabled_config("spring-boot")
    engine = SafetyEngine(cfg)
    result = engine.check_file(str(sanitised_file))
    codes = _codes_in(result.violations + result.suppressed)
    safe801_count = codes.count("SAFE801")
    assert safe801_count >= 1, f"expected SAFE801 to still fire on the SQL sink despite HTML encoding, got {safe801_count} hits: {codes}"


# ---------------------------------------------------------------------------
# Parametrised "all fixtures parse cleanly" sanity check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture",
    (
        "UserController.java",
        "UserService.java",
        "BackgroundJob.java",
        "ResourceUsage.java",
        "ComplexNesting.java",
        "LongMethod.java",
        "ErrorHandling.java",
    ),
)
def test_fixture_parses_without_safe000_error(fixture: str) -> None:
    """Every fixture must parse without a SAFE000 Tree-sitter parse-error.

    SAFE000 fires when ``tree.root_node.has_error`` is True -
    typically a malformed Java source or a grammar bug. If a
    fixture trips this, the rest of the rule assertions in the
    suite are meaningless because the parse-error short-circuit
    suppresses other rules. This test is the canary.
    """
    violations = _run_engine(fixture)
    codes = _codes_in(violations)
    assert "SAFE000" not in codes, f"{fixture} failed to parse cleanly: {codes}"
