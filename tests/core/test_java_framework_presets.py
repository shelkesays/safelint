"""Tests for the [tool.safelint.java] framework preset mechanism.

Mirrors :mod:`tests.core.test_javascript_runtime_presets` - same test
shape against the Java preset registry. The Java preset is narrower
in scope (one non-vanilla framework today: ``spring-boot``) but the
plumbing and the resolver-warning posture are identical.
"""

from __future__ import annotations

import copy

import pytest

from safelint.core.config import (
    _JAVA_FRAMEWORK_PRESETS,
    _JAVA_VALID_FRAMEWORKS,
    DEFAULTS,
    _apply_java_framework_preset,
    _resolve_java_framework,
)


# ---------------------------------------------------------------------------
# _resolve_java_framework - extracts and validates the framework selector.
# ---------------------------------------------------------------------------


def test_default_framework_is_vanilla_when_unset() -> None:
    """A config with no ``[tool.safelint.java]`` table defaults to vanilla."""
    assert _resolve_java_framework({}) == "vanilla"


def test_explicit_framework_vanilla() -> None:
    """``framework = "vanilla"`` returns ``"vanilla"``."""
    assert _resolve_java_framework({"java": {"framework": "vanilla"}}) == "vanilla"


@pytest.mark.parametrize("framework", sorted(_JAVA_VALID_FRAMEWORKS))
def test_every_valid_framework_resolves(framework: str) -> None:
    """Every name in ``_JAVA_VALID_FRAMEWORKS`` is accepted."""
    assert _resolve_java_framework({"java": {"framework": framework}}) == framework


def test_unknown_framework_falls_back_to_vanilla(capsys: pytest.CaptureFixture[str]) -> None:
    """An unrecognised framework name warns on stderr and falls back to ``"vanilla"``."""
    result = _resolve_java_framework({"java": {"framework": "quarkus"}})
    assert result == "vanilla"
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "'quarkus' is not recognised" in err
    assert "spring-boot, vanilla" in err


def test_non_string_framework_falls_back_to_vanilla(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-string framework value warns and falls back."""
    result = _resolve_java_framework({"java": {"framework": 42}})
    assert result == "vanilla"
    err = capsys.readouterr().err
    assert "must be a string" in err


def test_non_table_java_section_falls_back_to_vanilla(capsys: pytest.CaptureFixture[str]) -> None:
    """A ``java`` key that isn't a table warns and falls back."""
    result = _resolve_java_framework({"java": "spring-boot"})
    assert result == "vanilla"
    err = capsys.readouterr().err
    assert "must be a table" in err


# ---------------------------------------------------------------------------
# _apply_java_framework_preset - planting overrides into a defaults dict.
# ---------------------------------------------------------------------------


def test_vanilla_preset_is_a_noop() -> None:
    """Applying ``vanilla`` doesn't change defaults (it IS the baseline)."""
    defaults = copy.deepcopy(DEFAULTS)
    before = copy.deepcopy(defaults)
    _apply_java_framework_preset(defaults, "vanilla")
    assert defaults == before


def test_unknown_preset_is_a_noop() -> None:
    """Applying an unknown framework name is a no-op (resolver already warned)."""
    defaults = copy.deepcopy(DEFAULTS)
    before = copy.deepcopy(defaults)
    _apply_java_framework_preset(defaults, "quarkus")
    assert defaults == before


def test_spring_boot_preset_overrides_sinks_java() -> None:
    """The ``spring-boot`` preset replaces ``sinks_java`` with the Spring-aware list.

    Specifically: the preset list MUST include both the vanilla entries
    (so the preset is a complete replacement, not a partial one) and
    the Spring-specific additions like ``query`` / ``queryForObject``.
    """
    defaults = copy.deepcopy(DEFAULTS)
    _apply_java_framework_preset(defaults, "spring-boot")
    sinks = defaults["rules"]["tainted_sink"]["sinks_java"]
    # Spring-specific JdbcTemplate / RestTemplate sinks present:
    assert "query" in sinks
    assert "queryForObject" in sinks
    assert "exchange" in sinks
    # Vanilla sinks still present (preset includes them so the user
    # doesn't lose stdlib coverage when switching to spring-boot):
    assert "exec" in sinks
    assert "executeQuery" in sinks
    assert "forName" in sinks


def test_spring_boot_preset_overrides_nullable_methods_java() -> None:
    """The ``spring-boot`` preset adds ``queryForObject`` to the nullable list.

    The zero-rows case actually raises ``EmptyResultDataAccessException``;
    the listing reflects the conservative treatment for RowMapper /
    nullable-column-value paths that CAN produce a null result.
    """
    defaults = copy.deepcopy(DEFAULTS)
    _apply_java_framework_preset(defaults, "spring-boot")
    nullable = defaults["rules"]["null_dereference"]["nullable_methods_java"]
    # Spring-specific addition:
    assert "queryForObject" in nullable
    # Vanilla nullable getters still present:
    assert "get" in nullable
    assert "getParameter" in nullable


def test_spring_boot_preset_does_not_touch_unrelated_rules() -> None:
    """The ``spring-boot`` preset leaves rules it doesn't override untouched.

    Confirms the preset's narrow scope: SAFE401 / SAFE304 / SAFE203 etc.
    are NOT overridden today. If a future preset version adds entries
    here, this test would surface the change and the user-facing doc
    should be updated alongside.
    """
    defaults = copy.deepcopy(DEFAULTS)
    before_resource_lifecycle = copy.deepcopy(defaults["rules"]["resource_lifecycle"])
    before_side_effects = copy.deepcopy(defaults["rules"]["side_effects"])
    before_logging_on_error = copy.deepcopy(defaults["rules"]["logging_on_error"])
    _apply_java_framework_preset(defaults, "spring-boot")
    assert defaults["rules"]["resource_lifecycle"] == before_resource_lifecycle
    assert defaults["rules"]["side_effects"] == before_side_effects
    assert defaults["rules"]["logging_on_error"] == before_logging_on_error


def test_preset_registry_covers_every_valid_framework() -> None:
    """Every name in ``_JAVA_VALID_FRAMEWORKS`` has a corresponding preset entry."""
    assert frozenset(_JAVA_FRAMEWORK_PRESETS.keys()) == _JAVA_VALID_FRAMEWORKS


def test_preset_is_deep_copied_into_defaults() -> None:
    """Mutating the returned defaults dict must NOT mutate the preset registry.

    Defensive contract: callers treat config as read-only, but if one
    ever did mutate (e.g. via a future rule-config builder), the
    preset registry must be unaffected.
    """
    defaults = copy.deepcopy(DEFAULTS)
    _apply_java_framework_preset(defaults, "spring-boot")
    # Capture pre-mutation snapshot of the preset registry.
    preset_snapshot = copy.deepcopy(_JAVA_FRAMEWORK_PRESETS["spring-boot"])
    # Mutate the defaults' resolved sinks list.
    defaults["rules"]["tainted_sink"]["sinks_java"].append("MUTATION_SENTINEL")
    # The registry must be unchanged.
    assert _JAVA_FRAMEWORK_PRESETS["spring-boot"] == preset_snapshot
