"""Path handling that differs between Windows and POSIX (#265).

safelint compares paths in two different ways, and they disagreed. The
changed-set membership test uses ``Path.__eq__``, which **case-folds on
Windows**; test-dir membership compares ``Path.parts`` tuples, which did not.
On a case-insensitive filesystem that meant a ``test_dirs`` entry of
``packages/core/src/test`` matched nothing when the directory on disk was
spelled ``packages/Core/src/Test``, silently mis-scoping SAFE601 / SAFE701 /
SAFE702 across the whole tree.

The other half of #265 is a silent false negative: SAFE702 answers "did this
file change?" by canonical-path equality, so a caller supplying paths in a
different spelling (an MSYS / Git Bash ``/c/project/...`` path has no drive
letter, and Windows resolves it under the current drive) gets "nothing
changed" for every file and a clean run. That is indistinguishable from
success, which is why it now warns.

These tests are written to assert correctly on **both** platforms rather than
being skipped on one: the case expectation is derived from
``os.path.normcase``, which is the same function the implementation uses.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from safelint.core import engine
from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules._test_files import _path_components_contain


if TYPE_CHECKING:
    import pytest


#: True where the filesystem (and therefore ``normcase``) ignores case: Windows.
_CASE_INSENSITIVE = os.path.normcase("A") == os.path.normcase("a")


def test_components_match_is_exact_when_the_case_agrees() -> None:
    """The ordinary case has to keep working on every platform."""
    assert _path_components_contain(("repo", "packages", "core", "src", "test", "x.ts"), ("packages", "core", "src", "test"))


def test_components_match_follows_the_platform_case_rules() -> None:
    """Case handling must match the filesystem, not a hardcoded guess.

    On Windows these are one directory and must match; on POSIX they are two
    and must not. Deriving the expectation from ``os.path.normcase`` keeps this
    a real assertion on both platforms instead of a skip on one, and it fails
    if the implementation and the platform ever disagree again.
    """
    matched = _path_components_contain(("repo", "packages", "Core", "src", "Test", "x.ts"), ("packages", "core", "src", "test"))

    assert matched is _CASE_INSENSITIVE


def test_a_non_matching_component_run_is_still_rejected() -> None:
    """Case folding must not widen the match to unrelated directories."""
    assert not _path_components_contain(("repo", "packages", "core", "lib", "x.ts"), ("packages", "core", "src", "test"))


def test_an_empty_needle_never_matches() -> None:
    """Guard against a ``test_dirs`` entry that parses to no components."""
    assert not _path_components_contain(("a", "b"), ())


# ── the silent false negative (#265) ─────────────────────────────────────────


def _coupling_engine(changed: list[str]) -> SafetyEngine:
    """Engine with SAFE702 enabled and *changed* injected as the changed set."""
    config = deep_merge(DEFAULTS, {"rules": {"test_coupling": {"enabled": True, "test_dirs": ["tests"]}}})
    return SafetyEngine(config, changed_files=changed)


def _write_project(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create ``src/app.ts`` with a paired ``tests/app.test.ts``; return its relative path.

    ``chdir`` into *root* because a **relative** ``test_dirs`` entry is anchored
    at the process working directory (see ``_find_test_file``), so without this
    the rule would look for ``tests/`` in safelint's own checkout and skip every
    file for "no paired test exists" - masking what these tests are about.
    """
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "app.ts").write_text("export const a = 1;\n", encoding="utf-8")
    (root / "tests" / "app.test.ts").write_text("export const t = 1;\n", encoding="utf-8")
    monkeypatch.chdir(root)
    return Path("src") / "app.ts"


def test_unmatchable_changed_paths_warn_instead_of_silently_skipping(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The #265 failure mode: SAFE702 finds nothing and the run looks clean.

    A drive-less rooted path is what Git Bash hands a wrapper on Windows. It
    canonicalises to somewhere that does not exist, so no linted file is ever
    seen as changed. Without the warning this is indistinguishable from "your
    code is fine".
    """
    source = _write_project(tmp_path, monkeypatch)

    result = _coupling_engine(["/c/nonexistent-drive-prefix/src/app.ts"]).check_file(str(source))

    assert [v.code for v in result.violations] == []  # the silent part, unchanged
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "could be located on disk" in err
    assert "SAFE702" in err


def test_no_warning_when_at_least_one_changed_path_exists(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A deleted file in the changed set must not produce noise.

    This is why the trigger is "none of them exist" rather than "any is
    missing": a commit that removes a file legitimately carries a path that is
    gone, and warning about it every run would train users to ignore the line.
    """
    source = _write_project(tmp_path, monkeypatch)

    _coupling_engine([str(source), "src/deleted.ts"]).check_file(str(source))

    assert "could be located on disk" not in capsys.readouterr().err


def test_an_empty_changed_set_does_not_warn(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty set is a legitimate state (nothing changed), not a mis-spelling."""
    source = _write_project(tmp_path, monkeypatch)

    _coupling_engine([]).check_file(str(source))

    assert "could be located on disk" not in capsys.readouterr().err


def test_coupling_still_fires_for_a_matched_source(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The rule itself is unchanged: a matched source with an untouched test fires."""
    source = _write_project(tmp_path, monkeypatch)

    result = _coupling_engine([str(source)]).check_file(str(source))

    assert [v.code for v in result.violations] == ["SAFE702"]
    assert "could be located on disk" not in capsys.readouterr().err


def test_coupling_stays_quiet_when_the_paired_test_also_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """And the clean direction still reads clean."""
    source = _write_project(tmp_path, monkeypatch)
    paired = Path("tests") / "app.test.ts"

    result = _coupling_engine([str(source), str(paired)]).check_file(str(source))

    assert result.violations == []


# ── exclude patterns with Windows separators (found by the new Windows CI job) ──


def test_exclude_pattern_separators_are_folded_on_windows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both platform branches asserted from one host.

    Exclusion matches an ``as_posix()`` path against the raw pattern, so a
    pattern carrying backslashes - what ``str(Path(...))`` produces, and what a
    Windows user naturally writes - could never match and the exclusion
    silently did nothing. Folding is Windows-only because a backslash is a
    legitimate escape character in a POSIX glob.
    """
    pattern = r"C:\vendor\**"

    monkeypatch.setattr(engine, "_IS_WINDOWS", False)
    assert engine._normalise_exclude_pattern(pattern) == pattern  # POSIX: untouched

    monkeypatch.setattr(engine, "_IS_WINDOWS", True)
    assert engine._normalise_exclude_pattern(pattern) == "C:/vendor/**"


def test_a_posix_pattern_is_unchanged_by_folding(monkeypatch: pytest.MonkeyPatch) -> None:
    """A forward-slash pattern must survive the Windows branch untouched."""
    monkeypatch.setattr(engine, "_IS_WINDOWS", True)

    assert engine._normalise_exclude_pattern("vendor/**") == "vendor/**"


def test_an_absolute_exclude_path_actually_excludes_the_file(tmp_path: Path) -> None:
    """End to end, on whichever platform is running.

    ``extend_exclude_paths=[str(path)]`` is the documented form, and on Windows
    ``str`` yields backslashes. Before the fix this file was linted and reported
    violations despite being excluded; the Windows CI job is what surfaced it.
    """
    sample = tmp_path / "skip_me.py"
    sample.write_text("def f():\n    if True:\n        if True:\n            if True:\n                pass\n", encoding="utf-8")
    config = deep_merge(DEFAULTS, {"extend_exclude_paths": [str(sample)]})

    result = SafetyEngine(config).check_file(str(sample))

    assert result.violations == []
    assert result.suppressed == []
