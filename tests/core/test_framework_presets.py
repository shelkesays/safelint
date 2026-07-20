"""Tests for the Python (django/flask/fastapi) + Pydantic + PHP (laravel) presets.

Mirrors :mod:`tests.core.test_java_framework_presets` - same resolver-warning
posture and drift guards - plus the Pydantic composable-axis behaviour (additive,
stacks on top of a framework preset).
"""

from __future__ import annotations

import copy

import pytest

from safelint.core.config import (
    _PHP_FRAMEWORK_PRESETS,
    _PHP_VALID_FRAMEWORKS,
    _PYTHON_FRAMEWORK_PRESETS,
    _PYTHON_VALID_FRAMEWORKS,
    DEFAULTS,
    _apply_php_framework_preset,
    _apply_python_framework_preset,
    _apply_python_pydantic_preset,
    _resolve_php_framework,
    _resolve_python_framework,
    _resolve_python_pydantic,
    load_config,
)


# ---------------------------------------------------------------------------
# Resolvers - default / valid / unknown / type errors (warn + fall back)
# ---------------------------------------------------------------------------


def test_python_framework_defaults_to_vanilla() -> None:
    """No ``[tool.safelint.python]`` table -> vanilla."""
    assert _resolve_python_framework({}) == "vanilla"


@pytest.mark.parametrize("framework", sorted(_PYTHON_VALID_FRAMEWORKS))
def test_every_python_framework_resolves(framework: str) -> None:
    """Each valid Python framework name resolves to itself."""
    assert _resolve_python_framework({"python": {"framework": framework}}) == framework


def test_unknown_python_framework_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown framework name warns on stderr and falls back to vanilla."""
    assert _resolve_python_framework({"python": {"framework": "djengo"}}) == "vanilla"
    err = capsys.readouterr().err
    assert "not recognised" in err
    assert "djengo" in err


def test_non_string_python_framework_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-string framework value warns and falls back."""
    assert _resolve_python_framework({"python": {"framework": 3}}) == "vanilla"
    assert "must be a string" in capsys.readouterr().err


def test_non_table_python_section_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-table ``[tool.safelint.python]`` warns and falls back."""
    assert _resolve_python_framework({"python": "nope"}) == "vanilla"
    assert "must be a table" in capsys.readouterr().err


def test_php_framework_defaults_to_vanilla() -> None:
    """No ``[tool.safelint.php]`` table -> vanilla."""
    assert _resolve_php_framework({}) == "vanilla"


@pytest.mark.parametrize("framework", sorted(_PHP_VALID_FRAMEWORKS))
def test_every_php_framework_resolves(framework: str) -> None:
    """Each valid PHP framework name resolves to itself."""
    assert _resolve_php_framework({"php": {"framework": framework}}) == framework


def test_unknown_php_framework_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown PHP framework name warns and falls back to vanilla."""
    assert _resolve_php_framework({"php": {"framework": "symphony"}}) == "vanilla"
    assert "not recognised" in capsys.readouterr().err


def test_pydantic_defaults_to_false() -> None:
    """``pydantic`` unset -> False."""
    assert _resolve_python_pydantic({}) is False
    assert _resolve_python_pydantic({"python": {}}) is False


def test_pydantic_true_resolves() -> None:
    """``pydantic = true`` -> True."""
    assert _resolve_python_pydantic({"python": {"pydantic": True}}) is True


def test_non_bool_pydantic_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-bool ``pydantic`` warns and falls back to False."""
    assert _resolve_python_pydantic({"python": {"pydantic": "yes"}}) is False
    assert "must be a boolean" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Drift guards - a framework's replace-lists must re-include every vanilla entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", sorted(_PYTHON_VALID_FRAMEWORKS - {"vanilla"}))
def test_python_preset_sinks_retain_all_vanilla(framework: str) -> None:
    """A Python framework's ``sinks`` list still contains every vanilla sink."""
    preset_sinks = _PYTHON_FRAMEWORK_PRESETS[framework]["rules"]["tainted_sink"]["sinks"]
    for vanilla in DEFAULTS["rules"]["tainted_sink"]["sinks"]:
        assert vanilla in preset_sinks


def test_laravel_preset_sinks_php_retain_all_vanilla() -> None:
    """Laravel's ``sinks_php`` still contains every vanilla PHP sink."""
    preset = _PHP_FRAMEWORK_PRESETS["laravel"]["rules"]["tainted_sink"]["sinks_php"]
    for vanilla in DEFAULTS["rules"]["tainted_sink"]["sinks_php"]:
        assert vanilla in preset


# ---------------------------------------------------------------------------
# Appliers - overrides land, baseline is a no-op, deep-copied
# ---------------------------------------------------------------------------


def test_django_preset_lands_sinks_and_enables_framework_rules() -> None:
    """Applying django adds its sinks and enables the SAFE905-907 framework rules."""
    d = copy.deepcopy(DEFAULTS)
    _apply_python_framework_preset(d, "django")
    sinks = d["rules"]["tainted_sink"]["sinks"]
    assert "RawSQL" in sinks
    assert "mark_safe" in sinks
    for rule in ("debug_mode_enabled", "mass_assignment", "unvalidated_request_input"):
        assert d["rules"][rule]["enabled"] is True


def test_preset_does_not_enable_shared_dataflow_rules() -> None:
    """A framework preset must NOT auto-enable the multi-language dataflow rules.

    Those rules apply to every language, so enabling them in the shared
    DEFAULTS would fire SAFE801/802/803 on Go / JS / Rust files when a
    user selects a *Python* (or PHP) framework. The preset only extends the
    sink lists; enabling stays the user's explicit, per-rule choice.
    """
    cases = (
        ("django", _apply_python_framework_preset),
        ("flask", _apply_python_framework_preset),
        ("fastapi", _apply_python_framework_preset),
        ("laravel", _apply_php_framework_preset),
    )
    for framework, applier in cases:
        d = copy.deepcopy(DEFAULTS)
        applier(d, framework)
        for rule in ("tainted_sink", "return_value_ignored", "null_dereference"):
            assert d["rules"][rule]["enabled"] is False, f"{framework} must not auto-enable {rule}"


def test_pydantic_preset_does_not_enable_tainted_sink() -> None:
    """``pydantic = true`` must not enable the shared ``tainted_sink`` rule either.

    Same polyglot-safety contract as the framework presets: the composable
    Pydantic toggle appends its constructors to the sink list and enables the
    Python/PHP-scoped ``mass_assignment`` rule, but leaves the multi-language
    ``tainted_sink`` opt-in so it never fires on Go / JS / Rust files.
    """
    d = copy.deepcopy(DEFAULTS)
    _apply_python_pydantic_preset(d, enabled=True)
    assert d["rules"]["tainted_sink"]["enabled"] is False
    assert "model_construct" in d["rules"]["tainted_sink"]["sinks"]
    assert d["rules"]["mass_assignment"]["enabled"] is True


def test_flask_preset_does_not_enable_mass_assignment() -> None:
    """Flask has no ORM, so SAFE906 stays disabled under the flask preset."""
    d = copy.deepcopy(DEFAULTS)
    _apply_python_framework_preset(d, "flask")
    assert "render_template_string" in d["rules"]["tainted_sink"]["sinks"]
    assert d["rules"].get("mass_assignment", {}).get("enabled") is not True


def test_laravel_preset_lands_php_sinks() -> None:
    """Applying laravel adds its PHP sinks and enables the rules."""
    d = copy.deepcopy(DEFAULTS)
    _apply_php_framework_preset(d, "laravel")
    assert "whereRaw" in d["rules"]["tainted_sink"]["sinks_php"]
    assert d["rules"]["debug_mode_enabled"]["enabled"] is True


def test_vanilla_preset_is_a_noop() -> None:
    """The vanilla baseline leaves DEFAULTS unchanged."""
    d = copy.deepcopy(DEFAULTS)
    before = copy.deepcopy(d)
    _apply_python_framework_preset(d, "vanilla")
    _apply_php_framework_preset(d, "vanilla")
    assert d == before


def test_preset_is_deep_copied_into_defaults() -> None:
    """Mutating the resolved config must not corrupt the module-level preset dict."""
    d = copy.deepcopy(DEFAULTS)
    _apply_python_framework_preset(d, "django")
    d["rules"]["tainted_sink"]["sinks"].append("__mutated__")
    fresh = copy.deepcopy(DEFAULTS)
    _apply_python_framework_preset(fresh, "django")
    assert "__mutated__" not in fresh["rules"]["tainted_sink"]["sinks"]


# ---------------------------------------------------------------------------
# Pydantic composable axis - additive, stacks on top of a framework
# ---------------------------------------------------------------------------


def test_pydantic_appends_without_clobbering_framework_sinks() -> None:
    """pydantic composes on top of django: django sinks survive, model_construct added."""
    d = copy.deepcopy(DEFAULTS)
    _apply_python_framework_preset(d, "django")
    _apply_python_pydantic_preset(d, enabled=True)
    sinks = d["rules"]["tainted_sink"]["sinks"]
    assert "RawSQL" in sinks  # framework sink survived
    assert "model_construct" in sinks  # pydantic addition present
    assert d["rules"]["mass_assignment"]["enabled"] is True


def test_pydantic_disabled_is_a_noop() -> None:
    """pydantic = false does not touch the sinks."""
    d = copy.deepcopy(DEFAULTS)
    before = copy.deepcopy(d)
    _apply_python_pydantic_preset(d, enabled=False)
    assert d == before


# ---------------------------------------------------------------------------
# Integration - explicit user TOML beats the preset (deep_merge runs last)
# ---------------------------------------------------------------------------


def test_user_sinks_override_the_django_preset(tmp_path, monkeypatch) -> None:
    """A user's explicit ``sinks`` wins over the django preset's list."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "safelint.toml").write_text(
        '[python]\nframework = "django"\n\n[rules.tainted_sink]\nsinks = ["only_this"]\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg["rules"]["tainted_sink"]["sinks"] == ["only_this"]
