"""Content-addressed lint-result cache.

Editor integrations (VSCode, the upcoming Claude Code skill) and pre-commit
hooks both re-run safelint many times against mostly-unchanged inputs. The
parse-and-walk pipeline isn't free; caching the rule output keyed on file
content makes re-lints essentially instant when nothing has changed.

Design:

* **Per-file key** = ``sha256(source_bytes + engine_fingerprint)``. The
  engine fingerprint folds in the safelint version, an internal cache
  schema version, and the active rule set + per-rule config — so any
  semantically meaningful change to *what* would be reported invalidates
  the cache automatically. Editing source contents also invalidates,
  by construction.
* **Storage** = one JSON file per key under ``<cache_dir>/<key>.json``.
  The file holds two flat lists of violations + suppressed entries
  serialised via ``dataclasses.asdict``. JSON (not pickle) is deliberate:
  cache files are user-readable, never deserialise arbitrary code, and
  survive Python upgrades.
* **Invalidation** is implicit — old keys simply become unreachable when
  the inputs hashing into them change. There is no LRU or TTL; users who
  want to clear the cache delete the directory. ``rm -rf .safelint_cache/``
  is always safe.
* **Fail-open** — any I/O or deserialisation error is treated as a cache
  miss. The cache is a performance optimisation, never a correctness
  requirement, so corrupted entries fall through to a fresh lint
  rather than failing the run.
"""

from __future__ import annotations

import contextlib
from dataclasses import asdict
import hashlib
import json
from typing import TYPE_CHECKING, Any

from safelint.rules.base import Violation


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


CACHE_DIR_NAME = ".safelint_cache"
# Bump when the cache file schema changes in a way old entries can't
# satisfy. Folded into the key, so old entries become unreachable
# automatically — no migration code needed.
_CACHE_SCHEMA_VERSION = "1"


def compute_engine_fingerprint(
    safelint_version: str,
    active_rules: Iterable[tuple[str, str, str, dict[str, Any]]],
) -> str:
    """Return a hex digest summarising the engine state that affects rule output.

    *active_rules* is an iterable of ``(name, code, severity, config)``
    tuples — one per rule that's enabled for this run. Folding the per-rule
    config in means a user changing e.g. ``max_lines = 60`` to ``70``
    invalidates the cache for every file even though the source is
    unchanged.
    """
    payload: dict[str, Any] = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "safelint_version": safelint_version,
        "rules": sorted(
            [{"name": name, "code": code, "severity": severity, "config": config} for name, code, severity, config in active_rules],
            key=lambda r: r["code"],
        ),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def compute_file_key(source: bytes, engine_fingerprint: str) -> str:
    """Return a hex digest for caching the lint of *source* under this engine."""
    digest = hashlib.sha256()
    digest.update(source)
    digest.update(b"\x00")
    digest.update(engine_fingerprint.encode("utf-8"))
    return digest.hexdigest()


class LintCache:
    """JSON-on-disk cache for ``(violations, suppressed)`` keyed by file hash.

    A ``LintCache(None)`` is a no-op (every ``get`` is a miss, every
    ``put`` is a no-op) — used for ``--no-cache`` and tests.
    """

    def __init__(self, cache_dir: Path | None) -> None:
        """Initialise the cache; creates *cache_dir* lazily on first put."""
        self.cache_dir = cache_dir
        self._created = False

    def get(self, key: str) -> tuple[list[Violation], list[Violation]] | None:
        """Return cached ``(violations, suppressed)`` for *key*, or None on miss."""
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{key}.json"
        # Any read / parse failure is a miss — cache must be fail-open.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # nosafe: SAFE203
            return None
        try:
            violations = [Violation(**v) for v in data["violations"]]
            suppressed = [Violation(**v) for v in data["suppressed"]]
        except (KeyError, TypeError):  # nosafe: SAFE203
            return None
        return violations, suppressed

    def put(self, key: str, violations: list[Violation], suppressed: list[Violation]) -> None:
        """Store ``(violations, suppressed)`` under *key*. Best-effort; errors silently swallowed."""
        if self.cache_dir is None:
            return
        if not self._created:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._created = True
            # Disk full / permission denied / read-only filesystem: best-effort
            # only; never fail the lint run because the cache couldn't be
            # written. Practically untestable without complex filesystem
            # mocking that adds no real assurance.
            except OSError:  # nosafe: SAFE203
                return
        path = self.cache_dir / f"{key}.json"
        payload = {
            "violations": [asdict(v) for v in violations],
            "suppressed": [asdict(v) for v in suppressed],
        }
        # Atomic-ish write: write to a temp file in the same directory,
        # then rename. Avoids partial-write garbage that future reads
        # would then need to skip.
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        # Same fail-open posture: if the rename fails we just don't have
        # a cache entry for this run. Untestable without filesystem fault
        # injection.
        except OSError:  # nosafe: SAFE203
            # Clean up the temp file if rename failed; double-fail is fine.
            with contextlib.suppress(OSError):
                tmp.unlink()
