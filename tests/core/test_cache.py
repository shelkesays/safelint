"""Tests for the per-file lint-result cache."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from safelint.core import _cache as cache_mod
from safelint.core._cache import (
    CACHE_DIR_NAME,
    LintCache,
    _atomic_write_json,
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


def test_engine_fingerprint_changes_with_per_file_ignores() -> None:
    """Adding/removing/editing a ``per_file_ignores`` entry shifts the fingerprint."""
    pfi_a: list[tuple[str, list[str], list[str]]] = []
    pfi_b: list[tuple[str, list[str], list[str]]] = [("**/tests/**", ["function_length"], ["SAFE101"])]
    pfi_c: list[tuple[str, list[str], list[str]]] = [("**/tests/**", ["function_length"], ["SAFE102"])]
    fp_empty = compute_engine_fingerprint("1.5.0", [], per_file_ignores=pfi_a)
    fp_b = compute_engine_fingerprint("1.5.0", [], per_file_ignores=pfi_b)
    fp_c = compute_engine_fingerprint("1.5.0", [], per_file_ignores=pfi_c)
    assert fp_empty != fp_b
    assert fp_b != fp_c


def test_engine_fingerprint_independent_of_per_file_ignores_order() -> None:
    """Two equivalent ``per_file_ignores`` lists hash the same regardless of order."""
    pfi_a: list[tuple[str, list[str], list[str]]] = [
        ("**/tests/**", ["function_length"], ["SAFE101"]),
        ("**/migrations/**", ["nesting_depth"], ["SAFE102"]),
    ]
    pfi_b = list(reversed(pfi_a))
    assert compute_engine_fingerprint("1.5.0", [], per_file_ignores=pfi_a) == compute_engine_fingerprint("1.5.0", [], per_file_ignores=pfi_b)


def test_engine_fingerprint_changes_with_engine_internal_ignored() -> None:
    """Toggling ``ignore = ["SAFE004"]`` (engine-internal) shifts the fingerprint.

    Engine-internal codes (SAFE000 parse, SAFE004 unused_suppression)
    aren't part of ``self.rules`` - they're emitted by the engine
    itself. Without folding the engine-internal-ignore set into the
    fingerprint, toggling them on/off would silently reuse stale
    cache entries that still carry (or lack) those engine-emitted
    violations.
    """
    fp_empty = compute_engine_fingerprint("1.5.0", [], engine_internal_ignored=())
    fp_safe004 = compute_engine_fingerprint("1.5.0", [], engine_internal_ignored=("SAFE004",))
    fp_unused = compute_engine_fingerprint("1.5.0", [], engine_internal_ignored=("unused_suppression",))
    fp_both = compute_engine_fingerprint("1.5.0", [], engine_internal_ignored=("SAFE004", "unused_suppression"))
    assert fp_empty != fp_safe004
    assert fp_safe004 != fp_unused
    assert fp_unused != fp_both
    # Stable across iteration order.
    fp_both_reordered = compute_engine_fingerprint("1.5.0", [], engine_internal_ignored=("unused_suppression", "SAFE004"))
    assert fp_both == fp_both_reordered


def test_file_key_changes_with_source() -> None:
    """Editing the source produces a different key, even with the same engine."""
    fp = compute_engine_fingerprint("1.5.0", [])
    assert compute_file_key(b"x = 1", fp, "f.py") != compute_file_key(b"x = 2", fp, "f.py")


def test_file_key_changes_with_engine() -> None:
    """Same source under different engine config hashes to different keys."""
    fp_a = compute_engine_fingerprint("1.5.0", [("a", "SAFE001", "error", {})])
    fp_b = compute_engine_fingerprint("1.5.0", [("b", "SAFE002", "error", {})])
    assert compute_file_key(b"x = 1", fp_a, "f.py") != compute_file_key(b"x = 1", fp_b, "f.py")


def test_file_key_changes_with_filepath() -> None:
    """Two files with identical contents under different paths must hash differently.

    Path-dependent rules (``test_existence``, ``test_coupling``,
    ``per_file_ignores`` patterns) and ``Violation.filepath`` itself would
    otherwise be wrong on a cross-file cache hit.
    """
    fp = compute_engine_fingerprint("1.5.0", [])
    assert compute_file_key(b"x = 1", fp, "src/a.py") != compute_file_key(b"x = 1", fp, "src/b.py")


def test_file_key_normalises_windows_separators() -> None:
    """Backslash- and forward-slash filepaths produce the same key.

    Lets a Windows-host editor and a POSIX CI runner share the same
    on-disk cache without spurious misses.
    """
    fp = compute_engine_fingerprint("1.5.0", [])
    assert compute_file_key(b"x = 1", fp, "src\\a.py") == compute_file_key(b"x = 1", fp, "src/a.py")


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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks need elevated permissions in CI")
def test_lint_cache_put_ignores_planted_deterministic_tmp_symlink(tmp_path: Path) -> None:
    """A symlink planted at the old predictable ``<key>.json.tmp`` name is not followed (H4).

    Before the ``mkstemp`` hardening the temp file had a deterministic
    ``<key>.json.tmp`` name; an attacker with write access to the cache dir
    could pre-plant a symlink there and have ``put`` write through it.
    ``mkstemp`` now creates the temp with an unguessable random name (and
    ``O_EXCL | O_NOFOLLOW``), so the planted symlink is simply ignored and
    its target is never touched.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("SECRET - DO NOT CLOBBER\n", encoding="utf-8")
    (cache_dir / "k1.json.tmp").symlink_to(victim)  # the pre-hardening predictable tmp path

    cache = LintCache(cache_dir)
    v = Violation(rule="r", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error")
    cache.put("k1", [v], [])

    # Victim untouched: the planted symlink was not the write target.
    assert victim.read_text(encoding="utf-8") == "SECRET - DO NOT CLOBBER\n"
    # The cache still wrote correctly through the random temp and round-trips.
    out = cache.get("k1")
    assert out is not None
    assert out[0][0] == v


class _InjectedOSError(OSError):
    """Sentinel ``OSError`` subclass for the cache fault-injection tests.

    A dedicated subclass lets ``pytest.raises`` target exactly the injected
    failure (satisfying ruff PT011) without a message string (TRY003), while
    still being caught by ``_atomic_write_json``'s ``except OSError`` cleanup.
    """


def test_atomic_write_json_closes_fd_and_cleans_up_when_fdopen_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If ``os.fdopen`` fails, the raw mkstemp fd is closed (no leak) and the temp is removed (H4 robustness).

    Directly exercises the fd-leak guard: ``os.fdopen`` raising before it
    takes ownership of the descriptor must not leak that descriptor.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    closed: list[int] = []
    real_close = cache_mod.os.close
    monkeypatch.setattr(cache_mod.os, "close", lambda fd: (closed.append(fd), real_close(fd))[1])
    # os.fdopen raises before taking ownership of the fd (the leak window).
    monkeypatch.setattr(cache_mod.os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(_InjectedOSError))

    with pytest.raises(_InjectedOSError):
        _atomic_write_json(cache_dir, cache_dir / "k.json", {"violations": [], "suppressed": []})

    assert closed, "the raw fd must be closed when fdopen fails, or it leaks"
    assert list(cache_dir.glob("*.json.tmp")) == [], "temp file must be cleaned up"
    assert not (cache_dir / "k.json").exists()


def test_atomic_write_json_cleans_up_when_rename_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the final atomic rename fails, the orphan temp is removed and the error propagates."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def boom_replace(self: Path, target: Path) -> None:
        raise _InjectedOSError

    monkeypatch.setattr(cache_mod.Path, "replace", boom_replace)

    with pytest.raises(_InjectedOSError):
        _atomic_write_json(cache_dir, cache_dir / "k.json", {"violations": [], "suppressed": []})

    assert list(cache_dir.glob("*.json.tmp")) == [], "temp file must be cleaned up after a failed rename"


def test_lint_cache_get_is_resilient_to_corrupt_payload(tmp_path: Path) -> None:
    """A truncated / non-JSON cache file is treated as a miss, not a crash."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "broken.json").write_text("{not-valid-json", encoding="utf-8")
    cache = LintCache(cache_dir)
    assert cache.get("broken") is None


def test_lint_cache_get_skips_schema_drift(tmp_path: Path) -> None:
    """A JSON file missing the expected keys (e.g. a future-format entry)
    is also a miss - schema drift never crashes the run."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "weird.json").write_text(json.dumps({"unexpected": []}), encoding="utf-8")
    cache = LintCache(cache_dir)
    assert cache.get("weird") is None


def test_lint_cache_directory_created_lazily(tmp_path: Path) -> None:
    """The cache directory is only created on the first put - ``--no-cache``
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


def test_engine_cache_invalidates_when_safe004_is_globally_ignored(tmp_path: Path) -> None:
    """Toggling ``ignore = ["SAFE004"]`` between runs invalidates cache entries.

    SAFE004 (``unused_suppression``) is engine-internal, not a
    ``BaseRule``, so it never appears in ``self.rules`` and toggling
    it in ``ignore`` doesn't change the rule set. Without folding
    the engine-internal-ignore set into the cache fingerprint, the
    second run would serve the first run's cached SAFE004 violation
    even though the user asked for it to be silenced.

    Concrete shape: file has ``# nosafe: SAFE304`` on a line with no
    side-effect violation, so SAFE004 fires. First engine has the
    default config (SAFE004 enabled); second engine adds it to
    ``ignore``. Both share the same on-disk cache directory.
    """
    sample = tmp_path / "unused_dir.py"
    sample.write_text("x = 1  # nosafe: SAFE304\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"

    cfg_default = DEFAULTS
    engine_default = SafetyEngine(cfg_default, cache=LintCache(cache_dir))
    result_default = engine_default.check_file(str(sample))
    assert any(v.code == "SAFE004" for v in result_default.violations), "first run must have emitted SAFE004"

    cfg_ignored = {**DEFAULTS, "ignore": ["SAFE004"]}
    engine_ignored = SafetyEngine(cfg_ignored, cache=LintCache(cache_dir))
    result_ignored = engine_ignored.check_file(str(sample))
    # The engine-internal-ignore toggle must have invalidated the cache;
    # SAFE004 must NOT come back from the prior cached entry.
    assert not any(v.code == "SAFE004" for v in result_ignored.violations)


def test_engine_cache_invalidates_when_safe004_is_ignored_by_rule_name(tmp_path: Path) -> None:
    """Same as above, but ``ignore = ["unused_suppression"]`` (rule name form)."""
    sample = tmp_path / "unused_dir_name.py"
    sample.write_text("x = 1  # nosafe: SAFE304\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"

    engine_default = SafetyEngine(DEFAULTS, cache=LintCache(cache_dir))
    assert any(v.code == "SAFE004" for v in engine_default.check_file(str(sample)).violations)

    cfg_ignored = {**DEFAULTS, "ignore": ["unused_suppression"]}
    result = SafetyEngine(cfg_ignored, cache=LintCache(cache_dir)).check_file(str(sample))
    assert not any(v.code == "SAFE004" for v in result.violations)


def test_globally_ignored_engine_internal_is_filtered_to_engine_codes() -> None:
    """``_globally_ignored_engine_internal`` only contains engine-internal entries.

    The field is what feeds the cache fingerprint via
    ``engine_internal_ignored``. Without filtering, adding an unrelated
    ``ignore = ["SAFE101"]`` would shift the engine-internal portion
    of the fingerprint too - burning the cache for no semantic reason
    (``active_rules`` already invalidates correctly). And typos like
    ``ignore = ["SAFETYP01"]`` (which surface as a stderr warning and
    otherwise do nothing) would invalidate the whole cache pointlessly.
    Lock the filtering invariant in.
    """
    cfg = {
        **DEFAULTS,
        "ignore": [
            "SAFE004",  # engine-internal - should be in the set (upper-case)
            "unused_suppression",  # engine-internal - should be in the set
            "SAFE101",  # normal rule - should NOT be in the set
            "function_length",  # normal rule by name - should NOT be in the set
            "SAFETYP01",  # typo - should NOT be in the set
        ],
    }
    engine = SafetyEngine(cfg)
    expected = frozenset({"SAFE004", "unused_suppression"})
    assert engine._globally_ignored_engine_internal == expected


def test_engine_cache_does_not_invalidate_on_unrelated_typo_ignore(tmp_path: Path) -> None:
    """Adding a typo entry like ``ignore = ["SAFETYP01"]`` must not invalidate the cache.

    Typo entries surface as a stderr warning and otherwise do nothing
    - they're not a valid rule, not engine-internal, change no rule
    behaviour. The cache fingerprint should be identical to the
    no-ignore baseline.
    """
    engine_baseline = SafetyEngine(DEFAULTS, cache=LintCache(tmp_path / "c1"))
    engine_typo = SafetyEngine({**DEFAULTS, "ignore": ["SAFETYP01"]}, cache=LintCache(tmp_path / "c2"))
    # Same fingerprint → cache entries written by one would be served
    # by the other. The typo doesn't change rule behaviour, so it
    # mustn't change the cache key.
    assert engine_baseline._get_engine_fingerprint() == engine_typo._get_engine_fingerprint()


def test_engine_cache_isolates_by_filepath(tmp_path: Path) -> None:
    """Two files with identical contents under different paths must not share cache entries.

    The cache key folds the filepath in, so each call gets its own entry
    and every emitted Violation carries the *current* call's filepath
    (not the path of whichever file populated the cache first).
    """
    sample_a = tmp_path / "a_long_name.py"
    sample_b = tmp_path / "b_long_name.py"
    long_body = "def f():\n" + "    a = 1\n" * 80 + "    return a\n"
    sample_a.write_text(long_body, encoding="utf-8")
    sample_b.write_text(long_body, encoding="utf-8")
    cache_dir = tmp_path / "cache"
    engine = SafetyEngine(DEFAULTS, cache=LintCache(cache_dir))

    result_a = engine.check_file(str(sample_a))
    result_b = engine.check_file(str(sample_b))

    cache_files = list(cache_dir.glob("*.json"))
    # Each path yielded its own cache entry - no cross-file aliasing.
    assert len(cache_files) >= 2
    # Every reported violation points at the file the caller asked about.
    assert all(v.filepath == str(sample_a) for v in result_a.violations)
    assert all(v.filepath == str(sample_b) for v in result_b.violations)
    # And both files were actually flagged (sanity check the rule fired).
    assert result_a.violations
    assert result_b.violations


def test_engine_cache_invalidates_when_per_file_ignores_added(tmp_path: Path) -> None:
    """Adding a ``per_file_ignores`` entry between runs invalidates the cache.

    Because ``per_file_ignores`` is folded into the engine fingerprint,
    the second engine has a different cache key - so the cached
    "no-suppression" entry from the first run isn't reused, and the
    fresh lint correctly moves SAFE101 into ``suppressed``.
    """
    sample = tmp_path / "func.py"
    sample.write_text("def f():\n" + "    a = 1\n" * 80 + "    return a\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"

    # Run 1: no per_file_ignores → SAFE101 is active, gets cached as such.
    cfg_a = {**DEFAULTS, "per_file_ignores": {}}
    engine_a = SafetyEngine(cfg_a, cache=LintCache(cache_dir))
    result_a = engine_a.check_file(str(sample))
    assert any(v.rule == "function_length" for v in result_a.violations)

    # Run 2: per_file_ignores adds a SAFE101 silence. Different fingerprint,
    # different cache key - fresh lint correctly suppresses SAFE101.
    cfg_b = {**DEFAULTS, "per_file_ignores": {"**/func.py": ["SAFE101"]}}
    engine_b = SafetyEngine(cfg_b, cache=LintCache(cache_dir))
    result_b = engine_b.check_file(str(sample))
    assert all(v.rule != "function_length" for v in result_b.violations)
    assert any(v.rule == "function_length" for v in result_b.suppressed)


def test_engine_cache_invalidates_when_per_file_ignores_removed(tmp_path: Path) -> None:
    """Removing a ``per_file_ignores`` entry between runs invalidates the cache.

    Regression for a real bug: an earlier implementation kept the cached
    suppressed list as-is on hit and only re-ran the per-file filter
    over the active list. That meant loosening ``per_file_ignores``
    would wrongly leave previously suppressed violations suppressed -
    the user removed the silence in config but kept seeing it applied.
    Folding the patterns into the fingerprint invalidates the entry,
    forcing a fresh lint that correctly returns SAFE101 to active.
    """
    sample = tmp_path / "func.py"
    sample.write_text("def f():\n" + "    a = 1\n" * 80 + "    return a\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"

    # Run 1: per_file_ignores silences SAFE101. Cached as suppressed.
    cfg_strict = {**DEFAULTS, "per_file_ignores": {"**/func.py": ["SAFE101"]}}
    engine_strict = SafetyEngine(cfg_strict, cache=LintCache(cache_dir))
    result_strict = engine_strict.check_file(str(sample))
    assert any(v.rule == "function_length" for v in result_strict.suppressed)
    assert all(v.rule != "function_length" for v in result_strict.violations)

    # Run 2: user removes the silence. The cache MUST invalidate so the
    # violation comes back as active - not stay suppressed from cache.
    cfg_open = {**DEFAULTS, "per_file_ignores": {}}
    engine_open = SafetyEngine(cfg_open, cache=LintCache(cache_dir))
    result_open = engine_open.check_file(str(sample))
    assert any(v.rule == "function_length" for v in result_open.violations)
    assert all(v.rule != "function_length" for v in result_open.suppressed)


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
