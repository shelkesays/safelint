"""Configuration defaults, constants, and config loader for safelint.

Config is searched in this priority order (highest first):

1. ``safelint.toml`` - standalone TOML, keys at the top level (no wrapper)
2. ``pyproject.toml`` - ``[tool.safelint]`` section
3. Built-in defaults

When both files exist in the same directory, ``safelint.toml`` wins (matching
ruff's ``ruff.toml`` precedence convention).

TOML support uses the stdlib ``tomllib`` module (Python 3.11+).
"""

from __future__ import annotations

import copy
from pathlib import Path
import tomllib
from typing import Any

from safelint.core import _diagnostics


# ---------------------------------------------------------------------------
# Severity / mode constants
# ---------------------------------------------------------------------------

SEVERITY_ORDER: dict[str, int] = {"warning": 0, "error": 1}

MODE_FAIL_ON: dict[str, str] = {"local": "error", "ci": "warning"}

TOML_CONFIG_FILENAME = "pyproject.toml"
TOML_CONFIG_KEY = "safelint"
STANDALONE_TOML_FILENAME = "safelint.toml"

# ---------------------------------------------------------------------------
# Built-in defaults - every key can be overridden via pyproject.toml
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "mode": "local",
    "fail_on": "error",
    "exclude_paths": [],
    "ignore": [],
    "per_file_ignores": {},
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
    # The error IS reported via _diagnostics.print_error; SAFE203's heuristic
    # only recognises stdlib logging method names so it can't see the call.
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:  # nosafe: SAFE203
        _diagnostics.print_error(f"failed to parse {candidate}: {exc} — skipping file")
        return None


# ---------------------------------------------------------------------------
# Per-directory config finders
# ---------------------------------------------------------------------------


def _try_standalone(directory: Path) -> dict[str, Any] | None:
    """Return the parsed safelint.toml from *directory*, or None."""
    candidate = directory / STANDALONE_TOML_FILENAME
    if not candidate.exists():
        return None
    return _read_toml_file(candidate)


def _try_pyproject(directory: Path) -> dict[str, Any] | None:
    """Return ``[tool.safelint]`` from *directory*/pyproject.toml, or None."""
    candidate = directory / TOML_CONFIG_FILENAME
    if not candidate.exists():
        return None
    doc = _read_toml_file(candidate)
    if doc is None:
        return None
    return doc.get("tool", {}).get(TOML_CONFIG_KEY)


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_config(search_from: Path | None = None) -> dict[str, Any]:
    """Locate and load safelint config, merging it with the built-in defaults.

    Searches upward from *search_from* (defaults to cwd). At each directory
    the lookup order is:

    1. ``safelint.toml`` (standalone — keys at top level)
    2. ``pyproject.toml`` → ``[tool.safelint]``

    Always returns a fresh, deep-copied dict so callers can mutate the
    result (e.g. appending to ``ignore``) without corrupting the module
    ``DEFAULTS`` or sharing nested lists across loads.

    Returns a copy of ``DEFAULTS`` when no config file is found.
    """
    root = search_from or Path.cwd()
    for parent in [root, *root.parents]:
        # ``or`` short-circuits on falsy, so an empty-but-present
        # standalone config (``{}``) would let us silently fall through
        # to pyproject.toml. Check presence (None vs anything) explicitly.
        cfg = _try_standalone(parent)
        if cfg is None:
            cfg = _try_pyproject(parent)
        if cfg is not None:
            return deep_merge(copy.deepcopy(DEFAULTS), cfg)
    return copy.deepcopy(DEFAULTS)
