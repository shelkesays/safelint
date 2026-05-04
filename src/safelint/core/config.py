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
    # Skip files whose size exceeds this many bytes. Guards against
    # OOM on accidentally-huge inputs (binary blobs masquerading as
    # ``.py``, very large generated parsers, etc.). Default 5 MiB is
    # large enough that no realistic source file should hit it; raise
    # the bound explicitly if your project has legitimately huge
    # generated source. ``0`` is rejected as a likely typo and falls
    # back to this default with a warning.
    "max_file_size_bytes": 5 * 1024 * 1024,
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
            # Default tracked functions cover the most common resource-acquisition
            # primitives across Python's stdlib + popular libraries. Users can
            # extend (without re-listing) via ``extend_tracked_functions``.
            "tracked_functions": [
                "open",  # builtins.open — files
                "connect",  # sqlite3.connect, psycopg2.connect, mysql.connect, …
                "session",  # requests.session(), sqlalchemy session factories
                "Session",  # PEP-8-named session classes (requests.Session, sqlalchemy.Session)
                "Lock",  # threading.Lock, asyncio.Lock, multiprocessing.Lock
                "RLock",  # threading.RLock, asyncio.RLock
                "Semaphore",  # threading.Semaphore, asyncio.Semaphore
                "Pool",  # multiprocessing.Pool, concurrent.futures.*Pool
                "ThreadPoolExecutor",  # concurrent.futures
                "ProcessPoolExecutor",
                "socket",  # socket.socket
                "mmap",  # mmap.mmap
                "TemporaryFile",  # tempfile.TemporaryFile / NamedTemporaryFile
                "NamedTemporaryFile",
                "TemporaryDirectory",
                "ZipFile",  # zipfile.ZipFile
                "TarFile",  # tarfile.TarFile / tarfile.open
            ],
            "cleanup_patterns": ["close", "commit", "rollback", "release", "shutdown"],
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


def _peek_toml_file(candidate: Path) -> dict[str, Any] | None:
    """Parse *candidate* quietly: same as :func:`_read_toml_file` but no diagnostic.

    Used by probes (e.g. :func:`_directory_has_config`) that decide
    whether a directory contains an active config file *before*
    ``load_config`` runs. Without a quiet variant, a malformed
    ``safelint.toml`` would print the same parse-error diagnostic
    twice — once from the probe, once from the real load — confusing
    users who'd see the file flagged repeatedly. Real load remains
    the authoritative reporter.
    """
    try:
        # SAFE304 suppression below: this *is* an I/O probe by design.
        # Alternative names ("read", "load") would imply an authoritative
        # read, but this helper is deliberately a quiet peek.
        with candidate.open("rb") as fp:  # nosafe: SAFE304
            return tomllib.load(fp)
    # Fail-silent on purpose: the actual load path will surface the
    # error to the user. SAFE203's heuristic doesn't see the silence
    # as logging, so the suppression marker isn't needed.
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):  # nosafe: SAFE203
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


def _directory_has_config(directory: Path) -> bool:
    """Return True when *directory* contains an *active* safelint config file.

    "Active" mirrors :func:`load_config` exactly:

    * ``safelint.toml`` is parsed quietly; a malformed file is treated
      as *not* a config (so the upward walk continues, just like
      ``load_config`` falls through to the next candidate). Without
      this, a broken ``safelint.toml`` would still anchor the cache
      at a directory whose config never actually loads, and the user
      would silently get an unexpected ``.safelint_cache/`` placement.
    * ``pyproject.toml`` only counts when it actually has a
      ``[tool.safelint]`` section — an unrelated ``pyproject.toml``
      higher up the tree (e.g. a Python package whose author never
      configured safelint) shouldn't pin the cache there.

    Uses :func:`_peek_toml_file` (silent) rather than
    :func:`_read_toml_file` (verbose) so a malformed file's
    diagnostic is emitted exactly once — by the actual load path
    that follows. Otherwise the same broken file would print the
    same parse-error to stderr twice per run.
    """
    standalone = directory / STANDALONE_TOML_FILENAME
    if standalone.exists():
        return _peek_toml_file(standalone) is not None
    pyproject = directory / TOML_CONFIG_FILENAME
    if not pyproject.exists():
        return False
    doc = _peek_toml_file(pyproject)
    return doc is not None and doc.get("tool", {}).get(TOML_CONFIG_KEY) is not None


def find_config_root(search_from: Path | None = None) -> Path | None:
    """Return the directory holding the active safelint config, or None if defaults are used.

    Walks upward from *search_from* (defaults to cwd) using the same
    precedence as :func:`load_config`:

    1. ``safelint.toml``
    2. ``pyproject.toml`` containing a ``[tool.safelint]`` section

    Returns ``None`` when no config file is discoverable along the
    upward walk — the caller can then fall back to a sensible default
    (e.g. *search_from* itself) for any path that wants to live "next
    to the config".

    Used by the cache-dir resolver so ``.safelint_cache/`` ends up at
    the actual project root instead of an arbitrary subdirectory the
    user happened to pass to ``safelint check``.
    """
    root = search_from or Path.cwd()
    for parent in [root, *root.parents]:
        if _directory_has_config(parent):
            return parent
    return None


def _merge_extend_ignore(merged: dict[str, Any], extend_ignore: object) -> None:
    """Append ``extend_ignore`` entries onto ``merged["ignore"]`` (order-preserving dedupe).

    *extend_ignore* is typed ``object`` because the value flows directly
    from a TOML file — the type-narrowing happens via ``isinstance`` here.
    """
    if not isinstance(extend_ignore, (list, tuple)):
        msg = f"extend_ignore must be a list of strings, got {type(extend_ignore).__name__}"
        raise TypeError(msg)
    existing = merged.get("ignore", [])
    merged["ignore"] = list(dict.fromkeys([*existing, *extend_ignore]))


def _merge_extend_per_file_ignores(merged: dict[str, Any], extend_pfi: object) -> None:
    """Merge ``extend_per_file_ignores`` into ``merged["per_file_ignores"]`` per glob pattern."""
    if not isinstance(extend_pfi, dict):
        msg = f"extend_per_file_ignores must be a mapping, got {type(extend_pfi).__name__}"
        raise TypeError(msg)
    existing_pfi: dict[str, list[str]] = merged.get("per_file_ignores", {})
    # Iteration over a runtime-validated dict[Any, Any]; the type checker
    # can't infer per-key/value types so we annotate explicitly inside the
    # loop body for the call site to type-check.
    for raw_pattern, raw_entries in extend_pfi.items():
        pattern = str(raw_pattern)
        _merge_one_pfi_pattern(existing_pfi, pattern, raw_entries)
    merged["per_file_ignores"] = existing_pfi


def _merge_one_pfi_pattern(existing_pfi: dict[str, list[str]], pattern: str, entries: object) -> None:
    """Merge *entries* into *existing_pfi*[*pattern*] with order-preserving dedupe.

    *entries* is typed ``object`` because the value comes from a TOML
    file; the runtime ``isinstance`` check below narrows it before use.
    """
    if not isinstance(entries, (list, tuple)):
        msg = f"extend_per_file_ignores[{pattern!r}] must be a list of strings, got {type(entries).__name__}"
        raise TypeError(msg)
    # Cast the validated list elements to str — TOML strings come through
    # as str at runtime; non-strings would fail the engine's downstream
    # parse_per_file_ignores type-guard which has its own diagnostic.
    typed_entries: list[str] = [str(e) for e in entries]
    current = existing_pfi.get(pattern, [])
    existing_pfi[pattern] = list(dict.fromkeys([*current, *typed_entries]))


# Unique sentinel used by :func:`_apply_extend_keys` to distinguish
# *absent* from *explicitly-set-to-an-empty-or-falsy-value*. The dict
# ``.pop(key, None)`` idiom can't tell those apart — an explicit
# ``extend_ignore = 0`` would silently skip type validation otherwise.
_MISSING_KEY = object()


def _apply_extend_keys(merged: dict[str, Any]) -> dict[str, Any]:
    """Fold ``extend_ignore`` / ``extend_per_file_ignores`` into the resolved config.

    Modelled on ruff's ``extend-select`` / ``extend-ignore`` ergonomics: lets
    users *grow* a list-typed config value instead of replacing it. Without
    these keys, a project that wants to add ``"SAFE701"`` to the default
    ``ignore = []`` while keeping anything else added by their config would
    have to re-list every existing entry.

    Both keys are stripped from the returned dict so downstream consumers
    (engine, runner) only see the canonical ``ignore`` / ``per_file_ignores``.

    Sentinel-based detection means an explicitly-set falsy value
    (``extend_ignore = []`` or ``extend_ignore = 0``) is *not* skipped —
    empty lists pass through validation cleanly, and bad types like ``0``
    raise a clear :class:`TypeError` instead of being silently dropped.
    """
    extend_ignore = merged.pop("extend_ignore", _MISSING_KEY)
    if extend_ignore is not _MISSING_KEY:
        _merge_extend_ignore(merged, extend_ignore)
    extend_pfi = merged.pop("extend_per_file_ignores", _MISSING_KEY)
    if extend_pfi is not _MISSING_KEY:
        _merge_extend_per_file_ignores(merged, extend_pfi)
    return merged


def load_config(search_from: Path | None = None) -> dict[str, Any]:
    """Locate and load safelint config, merging it with the built-in defaults.

    Searches upward from *search_from* (defaults to cwd). At each directory
    the lookup order is:

    1. ``safelint.toml`` (standalone — keys at top level)
    2. ``pyproject.toml`` → ``[tool.safelint]``

    Always returns a fresh, deep-copied dict so callers can mutate the
    result (e.g. appending to ``ignore``) without corrupting the module
    ``DEFAULTS`` or sharing nested lists across loads.

    The user config may use ``extend_ignore`` / ``extend_per_file_ignores``
    to *grow* the corresponding default lists rather than replace them
    (mirrors ruff's ``extend-select`` / ``extend-ignore``). These keys
    are folded into ``ignore`` / ``per_file_ignores`` and stripped from
    the returned dict — downstream consumers only see the canonical keys.

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
            return _apply_extend_keys(deep_merge(copy.deepcopy(DEFAULTS), cfg))
    return copy.deepcopy(DEFAULTS)
