"""Configuration defaults, constants, and config loader for safelint.

Config is searched in this priority order (highest first):

1. ``pyproject.toml`` - ``[tool.safelint]`` section  (preferred)
2. ``.safelint.yaml`` - legacy YAML config           (backward compat)
3. Built-in defaults

TOML support uses the stdlib ``tomllib`` module (Python 3.11+) or the
``tomli`` backport on Python 3.10.  YAML support requires ``PyYAML``, which
is now an optional dependency (``pip install safelint[yaml]``).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional parser availability flags
# ---------------------------------------------------------------------------

if sys.version_info >= (3, 11):
    import tomllib

    _TOML_AVAILABLE = True
else:  # pragma: no cover
    try:
        import tomllib  # type: ignore[no-redef]

        _TOML_AVAILABLE = True
    except ImportError:
        logging.debug("tomllib not available; trying tomli backport")
        try:
            import tomli as tomllib  # type: ignore[import-untyped,no-redef]

            _TOML_AVAILABLE = True
        except ImportError:
            logging.debug("tomli not available; TOML config support disabled")
            _TOML_AVAILABLE = False

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    logging.debug("PyYAML not available; YAML config support disabled")
    _YAML_AVAILABLE = False

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity / mode constants
# ---------------------------------------------------------------------------

SEVERITY_ORDER: dict[str, int] = {"warning": 0, "error": 1}

MODE_FAIL_ON: dict[str, str] = {"local": "error", "ci": "warning"}

YAML_CONFIG_FILENAME = ".safelint.yaml"
TOML_CONFIG_FILENAME = "pyproject.toml"
TOML_CONFIG_KEY = "safelint"

# Keep old name as alias so existing imports don't break.
CONFIG_FILENAME = YAML_CONFIG_FILENAME

# ---------------------------------------------------------------------------
# Built-in defaults - every key can be overridden via pyproject.toml or yaml
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
            "tainted_sink",
            "return_value_ignored",
            "null_dereference",
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
        # Dataflow hybrid rules - disabled by default; opt-in via config
        "tainted_sink": {
            "enabled": False,
            "severity": "error",
            "sinks": [
                "eval",
                "exec",
                "compile",
                "system",
                "popen",
                "Popen",
                "run",
                "call",
                "check_output",
                "execute",
            ],
            "sanitizers": ["escape", "sanitize", "clean", "validate", "quote", "encode", "bleach"],
            "sources": ["input", "readline", "recv", "recvfrom", "read"],
        },
        "return_value_ignored": {
            "enabled": False,
            "severity": "warning",
            "flagged_calls": [
                "run",
                "call",
                "check_output",
                "write",
                "send",
                "sendall",
                "sendfile",
                "seek",
                "truncate",
                "remove",
                "unlink",
                "rename",
                "replace",
                "makedirs",
                "mkdir",
                "rmdir",
            ],
        },
        "null_dereference": {
            "enabled": False,
            "severity": "error",
            "nullable_methods": [],
        },
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
# File parsers
# ---------------------------------------------------------------------------


def _read_toml_file(candidate: Path) -> dict[str, Any] | None:
    """Parse *candidate* as TOML and return the full document, or None on error."""
    try:
        with candidate.open("rb") as fp:
            return tomllib.load(fp)
    except Exception as exc:  # noqa: BLE001
        _log.error("Failed to parse %s: %s - using defaults", candidate, exc)
        return None


def _parse_yaml_file(candidate: Path) -> dict[str, Any] | None:
    """Parse *candidate* as YAML and return the mapping, or None on error."""
    try:
        return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        _log.error("Failed to parse %s: %s - using defaults", candidate, exc)
        return None


# ---------------------------------------------------------------------------
# Per-directory config finders
# ---------------------------------------------------------------------------


def _try_pyproject(directory: Path) -> dict[str, Any] | None:
    """Return ``[tool.safelint]`` from *directory*/pyproject.toml, or None."""
    if not _TOML_AVAILABLE:  # pragma: no cover
        return None
    candidate = directory / TOML_CONFIG_FILENAME
    if not candidate.exists():
        return None
    doc = _read_toml_file(candidate)
    if doc is None:
        return None
    return doc.get("tool", {}).get(TOML_CONFIG_KEY)


def _try_yaml(directory: Path) -> dict[str, Any] | None:
    """Return the parsed .safelint.yaml from *directory*, or None."""
    if not _YAML_AVAILABLE:  # pragma: no cover
        return None
    candidate = directory / YAML_CONFIG_FILENAME
    if not candidate.exists():
        return None
    return _parse_yaml_file(candidate)


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_config(search_from: Path | None = None) -> dict[str, Any]:
    """Locate and load safelint config, merging it with the built-in defaults.

    Searches upward from *search_from* (defaults to cwd).  At each directory
    the lookup order is:

    1. ``pyproject.toml`` → ``[tool.safelint]``
    2. ``.safelint.yaml``

    Returns ``DEFAULTS`` when no config file is found or when neither TOML
    nor YAML parsers are available.
    """
    root = search_from or Path.cwd()
    for parent in [root, *root.parents]:
        cfg = _try_pyproject(parent) or _try_yaml(parent)
        if cfg:
            return deep_merge(DEFAULTS, cfg)
    return DEFAULTS
