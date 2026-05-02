"""Tests for the per-file lint-result cache."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from safelint.core._cache import (
    CACHE_DIR_NAME,
    LintCache,
    compute_engine_fingerprint,
    compute_file_key,
)
from safelint.core.config import DEFAULTS
from safelint.core.engine import SafetyEngine
from safelint.rules.base import Violation


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Pure helper functions: compute_engine_fingerprint / compute_file_key
# ---------------------------------------------------------------------------


def test_engine_fingerprint_changes_with_safelint_version() -> None:
    """Bumping the safelint version invalidates every cache entry."""
    fp_v1 = compute_engine_fingerprint("1.4.0", [])
    fp_v2 = compute_engine_fingerprint("1.5.0", [])
    assert fp_v1 != fp_v2


def test_engine_fingerprint_changes_with_rule_config() -> None:
    """Per-rule config changes (e.g. raising max_lines) invalidate the cache."""
    rules_a = [("function_length", "SAFE101", "error", {"max_lines": 60})]
    rules_b = [("function_length", "SAFE101", "error", {"max_lines": 70})]
    assert compute_engine_fingerprint("1.5.0", rules_a) != compute_engine_fingerprint("1.5.0", rules_b)


def test_engine_fingerprint_independent_of_rule_order() -> None:
    """Engine fingerprint is order-stable so two equivalent rule sets hash the same."""
    rules_a = [
        ("function_length", "SAFE101", "error", {"max_lines": 60}),
        ("nesting_depth", "SAFE102", "error", {"max_depth": 2}),
    ]
    rules_b = list(reversed(rules_a))
    assert compute_engine_fingerprint("1.5.0", rules_a) == compute_engine_fingerprint("1.5.0", rules_b)


def test_file_key_changes_with_source() -> None:
    """Editing the source produces a different key, even with the same engine."""
    fp = compute_engine_fingerprint("1.5.0", [])
    assert compute_file_key(b"x = 1", fp) != compute_file_key(b"x = 2", fp)


def test_file_key_changes_with_engine() -> None:
    """Same source under different engine config hashes to different keys."""
    fp_a = compute_engine_fingerprint("1.5.0", [("a", "SAFE001", "error", {})])
    fp_b = compute_engine_fingerprint("1.5.0", [("b", "SAFE002", "error", {})])
    assert compute_file_key(b"x = 1", fp_a) != compute_file_key(b"x = 1", fp_b)


# ---------------------------------------------------------------------------
# LintCache: in-memory contract
# ---------------------------------------------------------------------------


def test_lint_cache_disabled_when_dir_is_none() -> None:
    """Passing ``None`` makes every operation a no-op (used by ``--no-cache``)."""
    cache = LintCache(None)
    assert cache.get("any-key") is None
    cache.put("any-key", [], [])  # must not raise


def test_lint_cache_round_trip_preserves_violations(tmp_path: Path) -> None:
    """``put`` then ``get`` returns equivalent Violation objects (frozen dataclass)."""
    cache = LintCache(tmp_path / "cache")
    v = Violation(rule="r", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error")
    cache.put("k1", [v], [])
    out = cache.get("k1")
    assert out is not None
    violations, suppressed = out
    assert len(violations) == 1
    assert violations[0] == v  # dataclass __eq__
    assert suppressed == []


def test_lint_cache_get_returns_none_for_missing_key(tmp_path: Path) -> None:
    """A key never written is a clean miss."""
    cache = LintCache(tmp_path / "cache")
    assert cache.get("never-stored") is None


def test_lint_cache_get_is_resilient_to_corrupt_payload(tmp_path: Path) -> None:
    """A truncated / non-JSON cache file is treated as a miss, not a crash."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "broken.json").write_text("{not-valid-json", encoding="utf-8")
    cache = LintCache(cache_dir)
    assert cache.get("broken") is None


def test_lint_cache_get_skips_schema_drift(tmp_path: Path) -> None:
    """A JSON file missing the expected keys (e.g. a future-format entry)
    is also a miss — schema drift never crashes the run."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "weird.json").write_text(json.dumps({"unexpected": []}), encoding="utf-8")
    cache = LintCache(cache_dir)
    assert cache.get("weird") is None


def test_lint_cache_directory_created_lazily(tmp_path: Path) -> None:
    """The cache directory is only created on the first put — ``--no-cache``
    runs that never write don't pollute the project tree with empty dirs."""
    cache_dir = tmp_path / "cache"
    cache = LintCache(cache_dir)
    assert not cache_dir.exists()
    cache.put("k", [], [])
    assert cache_dir.exists()


# ---------------------------------------------------------------------------
# Engine integration: caching round-trip
# ---------------------------------------------------------------------------


def test_engine_uses_cache_to_avoid_re_running_rules(tmp_path: Path) -> None:
    """Second lint of the same source under the same engine is served from cache."""
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    cache = LintCache(tmp_path / "cache")

    engine = SafetyEngine(DEFAULTS, cache=cache)

    # First run populates the cache.
    result1 = engine.check_file(str(sample))
    cache_files_after_first = list((tmp_path / "cache").glob("*.json"))
    assert cache_files_after_first, "first run must have written a cache entry"

    # Second run should produce equivalent results.
    result2 = engine.check_file(str(sample))
    assert [v.code for v in result1.violations] == [v.code for v in result2.violations]


def test_engine_without_cache_writes_nothing(tmp_path: Path) -> None:
    """``cache=None`` (default) leaves no on-disk artefacts."""
    sample = tmp_path / "ok.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    SafetyEngine(DEFAULTS, cache=None).check_file(str(sample))
    # No directory under tmp_path was created by the engine.
    assert not (tmp_path / CACHE_DIR_NAME).exists()


def test_engine_cache_invalidates_on_engine_config_change(tmp_path: Path) -> None:
    """Two engines with different rule configs must not share cache entries.

    Sets max_lines=4 on engine A so a 6-line function fires; then engine B
    with max_lines=999 is built on the SAME cache directory. If the cache
    were keyed only by file content, B would incorrectly serve A's stored
    violation.
    """
    sample = tmp_path / "func.py"
    sample.write_text("def f():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return d\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"

    cfg_strict = {**DEFAULTS, "rules": {**DEFAULTS["rules"], "function_length": {"enabled": True, "max_lines": 4, "severity": "error"}}}
    strict_engine = SafetyEngine(cfg_strict, cache=LintCache(cache_dir))
    strict_result = strict_engine.check_file(str(sample))
    assert any(v.rule == "function_length" for v in strict_result.violations)

    cfg_loose = {**DEFAULTS, "rules": {**DEFAULTS["rules"], "function_length": {"enabled": True, "max_lines": 999, "severity": "error"}}}
    loose_engine = SafetyEngine(cfg_loose, cache=LintCache(cache_dir))
    loose_result = loose_engine.check_file(str(sample))
    # A different engine config must not pull A's cached violation forward.
    assert not any(v.rule == "function_length" for v in loose_result.violations)


def test_engine_cache_invalidates_on_source_change(tmp_path: Path) -> None:
    """Editing the source produces a fresh lint, not the cached one."""
    sample = tmp_path / "f.py"
    sample.write_text("def f():\n    if True:\n        if True:\n            if True:\n                pass\n", encoding="utf-8")
    cache = LintCache(tmp_path / "cache")
    engine_a = SafetyEngine(DEFAULTS, cache=cache)
    deep_result = engine_a.check_file(str(sample))
    assert any(v.rule == "nesting_depth" for v in deep_result.violations)

    # Rewrite to a shallow function.
    sample.write_text("x = 1\n", encoding="utf-8")
    engine_b = SafetyEngine(DEFAULTS, cache=cache)
    shallow_result = engine_b.check_file(str(sample))
    assert not any(v.rule == "nesting_depth" for v in shallow_result.violations)
