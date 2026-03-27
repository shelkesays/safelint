"""Configuration defaults, constants, and config loader for safelint."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity / mode constants
# ---------------------------------------------------------------------------

SEVERITY_ORDER: dict[str, int] = {"warning": 0, "error": 1}

MODE_FAIL_ON: dict[str, str] = {"local": "error", "ci": "warning"}

CONFIG_FILENAME = ".ai-safety.yaml"

# ---------------------------------------------------------------------------
# Built-in defaults — every key here can be overridden via .ai-safety.yaml
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "mode": "local",
    "fail_on": "error",
    "exclude_paths": [],
    "execution": {
        # Stop checking a file the moment the first violation is found.
        # Cheap structural rules run first so expensive checks are skipped
        # when basic problems already exist.
        "fail_fast": False,
        "order": [
            "function_length",
            "nesting_depth",
            "max_arguments",
            "bare_except",
            "empty_except",
            "global_state",
            "global_mutation",
            "unbounded_loops",
            "complexity",
            "side_effects_hidden",
            "side_effects",
            "logging_on_error",
            "resource_lifecycle",
            "test_coupling",
            "test_existence",
            "missing_assertions",
        ],
    },
    "rules": {
        "function_length": {"enabled": True, "max_lines": 60, "severity": "error"},
        "nesting_depth": {"enabled": True, "max_depth": 2, "severity": "error"},
        "max_arguments": {"enabled": True, "max_args": 7, "severity": "error"},
        "complexity": {"enabled": True, "max_complexity": 10, "severity": "error"},
        "bare_except": {"enabled": True, "severity": "error"},
        "empty_except": {"enabled": True, "severity": "error"},
        "logging_on_error": {"enabled": True, "severity": "warning"},
        "global_state": {"enabled": True, "severity": "warning"},
        "global_mutation": {"enabled": True, "severity": "error"},
        "side_effects_hidden": {
            "enabled": True,
            "severity": "error",
            "io_functions": ["open", "print", "input", "subprocess"],
            "pure_prefixes": [
                "calculate",
                "compute",
                "get",
                "check",
                "validate",
                "is",
                "has",
                "find",
                "parse",
                "transform",
                "convert",
                "format",
                "build",
                "resolve",
                "detect",
            ],
        },
        "side_effects": {
            "enabled": True,
            "severity": "warning",
            "io_functions": ["open", "print", "input"],
            "io_name_keywords": [
                "print",
                "log",
                "write",
                "read",
                "save",
                "load",
                "send",
                "fetch",
                "export",
                "import",
            ],
        },
        "resource_lifecycle": {
            "enabled": True,
            "severity": "error",
            "tracked_functions": ["open", "connect", "session"],
            "cleanup_patterns": ["close", "commit", "rollback"],
        },
        "unbounded_loops": {"enabled": True, "severity": "warning"},
        "missing_assertions": {"enabled": False, "severity": "warning"},
        "test_existence": {"enabled": False, "test_dirs": ["tests"], "severity": "warning"},
        "test_coupling": {"enabled": False, "test_dirs": ["tests"], "severity": "warning"},
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def _parse_yaml_file(candidate: Path) -> dict[str, Any] | None:
    """Parse *candidate* as YAML and return the mapping, or None on error."""
    try:
        return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        _log.error("Failed to parse %s: %s — using defaults", candidate, exc)
        return None


def load_config(search_from: Path | None = None) -> dict[str, Any]:
    """Locate and load .ai-safety.yaml, merging it with the built-in defaults.

    Walks up from *search_from* (defaults to cwd) until the config file is
    found or the filesystem root is reached. Falls back to built-in defaults
    when no file is found or PyYAML is not installed.
    """
    if not _YAML_AVAILABLE:
        _log.warning(
            "PyYAML not installed — using default config. Install with: pip install pyyaml"
        )
        return DEFAULTS

    root = search_from or Path.cwd()
    for parent in [root, *root.parents]:
        candidate = parent / CONFIG_FILENAME
        if not candidate.exists():
            continue
        raw = _parse_yaml_file(candidate)
        return deep_merge(DEFAULTS, raw) if raw is not None else DEFAULTS

    return DEFAULTS

    return DEFAULTS
