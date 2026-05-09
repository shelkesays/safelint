"""Tests for the [tool.safelint.javascript] runtime preset mechanism."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import pytest

from safelint.core.config import (
    _JS_RUNTIME_PRESETS,
    _JS_VALID_RUNTIMES,
    DEFAULTS,
    _apply_javascript_runtime_preset,
    _resolve_javascript_runtime,
    deep_merge,
    load_config,
)
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# _resolve_javascript_runtime — extracts and validates the runtime selector.
# ---------------------------------------------------------------------------


def test_default_runtime_is_node_when_unset() -> None:
    """A config with no ``[tool.safelint.javascript]`` table defaults to Node."""
    assert _resolve_javascript_runtime({}) == "node"


def test_explicit_runtime_node() -> None:
    """``runtime = "node"`` returns ``"node"``."""
    assert _resolve_javascript_runtime({"javascript": {"runtime": "node"}}) == "node"


@pytest.mark.parametrize("runtime", sorted(_JS_VALID_RUNTIMES))
def test_every_valid_runtime_resolves(runtime: str) -> None:
    """Every name in ``_JS_VALID_RUNTIMES`` is accepted."""
    assert _resolve_javascript_runtime({"javascript": {"runtime": runtime}}) == runtime


def test_unknown_runtime_falls_back_to_node(capsys: pytest.CaptureFixture[str]) -> None:
    """An unrecognised runtime name warns on stderr and falls back to ``"node"``."""
    result = _resolve_javascript_runtime({"javascript": {"runtime": "rhino"}})
    assert result == "node"
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "'rhino' is not recognised" in err
    assert "browser, bun, cloudflare-workers, deno, node" in err


def test_non_string_runtime_falls_back_to_node(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-string runtime value warns and falls back."""
    result = _resolve_javascript_runtime({"javascript": {"runtime": 42}})
    assert result == "node"
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "must be a string" in err


def test_non_table_javascript_section_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-table ``javascript`` value (e.g. a list) warns and falls back."""
    result = _resolve_javascript_runtime({"javascript": ["browser"]})
    assert result == "node"
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "must be a table" in err


# ---------------------------------------------------------------------------
# _apply_javascript_runtime_preset — modifies defaults in place.
# ---------------------------------------------------------------------------


def test_node_preset_is_a_noop() -> None:
    """Applying the ``"node"`` preset doesn't change DEFAULTS — it IS the baseline."""
    a = copy.deepcopy(DEFAULTS)
    b = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(a, "node")
    assert a == b


def test_browser_preset_overrides_node_defaults() -> None:
    """The ``browser`` preset replaces Node-style JS defaults with browser-style."""
    cfg = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, "browser")

    # Browser drops Node fs surface from ``side_effects.io_functions_javascript``.
    side_effects_io = cfg["rules"]["side_effects"]["io_functions_javascript"]
    assert "readFile" not in side_effects_io
    assert "writeFile" not in side_effects_io
    assert "fetch" in side_effects_io
    assert "setItem" in side_effects_io  # localStorage.setItem

    # Browser global namespaces drop ``global`` and ``process``, add ``document``.
    namespaces = cfg["rules"]["global_mutation"]["global_namespaces_javascript"]
    assert "document" in namespaces
    assert "window" in namespaces
    assert "process" not in namespaces
    assert "global" not in namespaces

    # Browser resource_lifecycle list is observers / streams / sockets, not Node fs.
    tracked = cfg["rules"]["resource_lifecycle"]["tracked_functions_javascript"]
    assert "Worker" in tracked
    assert "MutationObserver" in tracked
    assert "createReadStream" not in tracked


def test_deno_preset_uses_deno_apis() -> None:
    """The ``deno`` preset emphasises ``Deno.*`` APIs."""
    cfg = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, "deno")

    # Deno globals
    namespaces = cfg["rules"]["global_mutation"]["global_namespaces_javascript"]
    assert "Deno" in namespaces
    assert "process" not in namespaces

    # Deno resource lifecycle (call_name extracts the method, not Deno.):
    tracked = cfg["rules"]["resource_lifecycle"]["tracked_functions_javascript"]
    assert "open" in tracked  # Deno.open
    assert "listen" in tracked  # Deno.listen
    assert "createReadStream" not in tracked  # Node-only


def test_cloudflare_workers_preset_uses_kv_apis() -> None:
    """The ``cloudflare-workers`` preset reflects Workers' minimal surface."""
    cfg = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, "cloudflare-workers")

    # Workers KV / Durable Object methods:
    flagged = cfg["rules"]["return_value_ignored"]["flagged_calls_javascript"]
    assert "put" in flagged  # KV.put / R2.put
    assert "delete" in flagged

    # Workers has minimal global namespaces:
    namespaces = cfg["rules"]["global_mutation"]["global_namespaces_javascript"]
    assert "globalThis" in namespaces
    assert "self" in namespaces
    assert "window" not in namespaces  # no DOM in Workers
    assert "process" not in namespaces

    # Source list includes Request body methods:
    sources = cfg["rules"]["tainted_sink"]["sources_javascript"]
    assert "json" in sources
    assert "formData" in sources


def test_bun_preset_inherits_node_with_extras() -> None:
    """The ``bun`` preset extends Node defaults rather than replacing them."""
    cfg = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, "bun")

    # Bun adds ``serve`` to the resource_lifecycle tracked list:
    tracked = cfg["rules"]["resource_lifecycle"]["tracked_functions_javascript"]
    assert "serve" in tracked  # Bun.serve
    # And keeps the Node defaults:
    assert "createReadStream" in tracked


def test_unknown_runtime_preset_is_a_noop() -> None:
    """Applying an unknown preset name doesn't change defaults."""
    cfg = copy.deepcopy(DEFAULTS)
    expected = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, "rhino")
    assert cfg == expected


# ---------------------------------------------------------------------------
# Integration: load_config picks up the preset from a real TOML file.
# ---------------------------------------------------------------------------


def test_load_config_applies_browser_preset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``[tool.safelint.javascript] runtime = "browser"`` in TOML applies the browser preset."""
    (tmp_path / "safelint.toml").write_text(
        '[javascript]\nruntime = "browser"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    namespaces = cfg["rules"]["global_mutation"]["global_namespaces_javascript"]
    assert "document" in namespaces  # browser-only
    assert "process" not in namespaces  # Node-only


def test_load_config_user_explicit_overrides_preset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """User's explicit ``_javascript`` config still wins over the preset."""
    (tmp_path / "safelint.toml").write_text(
        '[javascript]\nruntime = "browser"\n\n[rules.global_mutation]\nglobal_namespaces_javascript = ["myCustomGlobal"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    namespaces = cfg["rules"]["global_mutation"]["global_namespaces_javascript"]
    assert namespaces == ["myCustomGlobal"]


def test_load_config_default_is_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No TOML at all → DEFAULTS (Node-style)."""
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    namespaces = cfg["rules"]["global_mutation"]["global_namespaces_javascript"]
    assert "process" in namespaces  # Node default


# ---------------------------------------------------------------------------
# Behavioural integration: a rule actually fires (or doesn't) per preset.
# ---------------------------------------------------------------------------


def test_browser_preset_fires_on_dom_lookup_chain(tmp_path: Path) -> None:
    """SAFE803 fires on ``document.getElementById(...).value`` under the browser preset."""
    sample = tmp_path / "dom.js"
    sample.write_text(
        "const v = document.getElementById('x').value;\n",
        encoding="utf-8",
    )
    # Construct a config equivalent to ``[tool.safelint.javascript] runtime = "browser"`` +
    # ``null_dereference.enabled = true``.
    cfg = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, "browser")
    cfg = deep_merge(cfg, {"rules": {"null_dereference": {"enabled": True}}})

    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE803" for v in result.violations)


def test_node_default_fires_on_node_resource_acquirer(tmp_path: Path) -> None:
    """SAFE401 fires on ``fs.createReadStream(...)`` under the default (Node) preset."""
    sample = tmp_path / "stream.js"
    sample.write_text(
        "function f(p) { return fs.createReadStream(p); }\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"resource_lifecycle": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_cloudflare_workers_preset_does_not_track_node_streams(tmp_path: Path) -> None:
    """Under the workers preset, ``fs.createReadStream`` is NOT in the tracked list — no fire."""
    sample = tmp_path / "stream.js"
    sample.write_text(
        "function f(p) { return fs.createReadStream(p); }\n",
        encoding="utf-8",
    )
    cfg = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, "cloudflare-workers")
    cfg = deep_merge(cfg, {"rules": {"resource_lifecycle": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    # Workers preset doesn't track createReadStream (no fs surface).
    assert not any(v.code == "SAFE401" for v in result.violations)


# ---------------------------------------------------------------------------
# Sanity: every preset is well-formed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", sorted(_JS_VALID_RUNTIMES))
def test_every_preset_can_be_applied_without_crashing(runtime: str) -> None:
    """Each declared preset applies cleanly to a fresh DEFAULTS copy."""
    cfg = copy.deepcopy(DEFAULTS)
    _apply_javascript_runtime_preset(cfg, runtime)
    # Sanity: every rule's _javascript-suffixed key (when present) is a list of strings.
    for rule_name, rule_cfg in cfg["rules"].items():
        if not isinstance(rule_cfg, dict):
            continue
        for key, value in rule_cfg.items():
            if not key.endswith("_javascript"):
                continue
            assert isinstance(value, list), f"{rule_name}.{key} should be a list"
            for item in value:
                assert isinstance(item, str), f"{rule_name}.{key} should contain strings, got {type(item).__name__}"


def test_valid_runtimes_match_preset_keys() -> None:
    """The validation set and the preset dict stay in sync."""
    assert frozenset(_JS_RUNTIME_PRESETS.keys()) == _JS_VALID_RUNTIMES
