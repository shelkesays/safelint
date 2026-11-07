"""Lost-coverage reporting: the skipped-file count and per-language breakdown.

A parse failure removes a file from analysis entirely, and until now the run
said nothing about it: the file counted towards ``files_checked`` as though it
had been analysed, and the one ``SAFE000`` sat among however many thousand
other findings (#175). The per-language breakdown is the matching question for
a polyglot tree: "how many files of *my* language did you actually read?"
(#196).

The load-bearing case throughout is the **clean** run. "All checks passed."
printed over a tree where a quarter of the files were never parsed is the
failure both issues were filed about, and it is why the count is derived from
``LintResult.analysis_skipped`` rather than from counting ``SAFE000`` violations,
which read zero the moment someone sets ``ignore = ["SAFE000"]``.
"""

from __future__ import annotations

import json
import os
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from safelint.cli import _language_counts, _RunCounts, main
from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import LintResult, SafetyEngine
from safelint.formatters import RunCoverage


if TYPE_CHECKING:
    from pathlib import Path


_BROKEN_PY = "def broken(\n"
_CLEAN_PY = '"""Mod."""\n\n\ndef ok() -> int:\n    """Doc."""\n    return 1\n'


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    """Drive the real entry point and return its exit status.

    ``main`` reads ``sys.argv`` and exits, so argv is patched and SystemExit
    caught, the same way ``tests/test_main_routing.py`` does it.
    """
    monkeypatch.setattr("sys.argv", ["safelint", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    return int(exc.value.code or 0)


def _engine(**overrides: object) -> SafetyEngine:
    """Engine on stock defaults, optionally merged with *overrides*."""
    return SafetyEngine(deep_merge(DEFAULTS, dict(overrides)))


def test_a_parse_failure_marks_the_result_not_analysed(tmp_path: Path) -> None:
    """The flag is what tells a caller no rule ran against the file."""
    sample = tmp_path / "bad.py"
    sample.write_text(_BROKEN_PY, encoding="utf-8")

    result = _engine().check_file(str(sample))

    assert result.analysis_skipped is True
    assert [v.code for v in result.violations] == ["SAFE000"]


def test_a_parsed_file_is_not_counted_as_skipped(tmp_path: Path) -> None:
    """No false positives: a file that parsed is analysed, findings or not."""
    sample = tmp_path / "good.py"
    sample.write_text(_CLEAN_PY, encoding="utf-8")

    assert _engine().check_file(str(sample)).analysis_skipped is False


def test_the_flag_survives_a_globally_ignored_safe000(tmp_path: Path) -> None:
    """The reason the count is not derived from the violation list.

    ``ignore = ["SAFE000"]`` is documented as the way to silence parse noise,
    and it removes the only evidence a counting-based implementation would
    have. The coverage gap is unchanged, so the count must be too.
    """
    sample = tmp_path / "bad.py"
    sample.write_text(_BROKEN_PY, encoding="utf-8")

    result = _engine(ignore=["SAFE000"]).check_file(str(sample))

    assert result.violations == []  # nothing left to count
    assert result.analysis_skipped is True  # but the file still was not analysed


def test_an_unreadable_file_also_counts_as_not_analysed(tmp_path: Path) -> None:
    """A file safelint could not read ran no rules either.

    Read failures share the ``SAFE000`` constructor, so they share the flag.
    Pinned because "could not be parsed" in the summary wording covers this
    case too, and a reader should not have to wonder.
    """
    sample = tmp_path / "undecodable.py"
    sample.write_bytes(b"\xff\xfe\x00 invalid utf-8 \xff")

    result = _engine().check_file(str(sample))

    assert result.analysis_skipped is True


def test_an_excluded_or_unregistered_file_is_not_lost_coverage(tmp_path: Path) -> None:
    """Nothing was attempted for these, so they are not a coverage gap.

    This is why the field is ``analysis_skipped`` (default False) rather than a
    ``parsed`` flag defaulting True, which would have claimed a successful
    parse for files that were never opened.
    """
    unregistered = tmp_path / "notes.txt"
    unregistered.write_text("not a supported language\n", encoding="utf-8")

    result = _engine().check_file(str(unregistered))

    assert result.analysis_skipped is False
    assert result.violations == []


# ── the per-language breakdown (#196) ────────────────────────────────────────


def test_language_counts_are_sparse_and_use_the_language_flag_names() -> None:
    """Absent means none read; the keys are what ``--language`` accepts."""
    counts = _language_counts(["a.py", "b.py", "c.rs", "d.c"])

    assert counts == {"python": 2, "rust": 1, "c": 1}
    assert "go" not in counts  # sparse, not a zero-filled map over nine languages


def test_language_counts_ignore_an_unregistered_extension() -> None:
    """An unknown extension contributes nothing rather than a ``None`` bucket."""
    assert _language_counts(["README.txt", "Makefile", "a.py"]) == {"python": 1}


def test_language_counts_are_empty_for_no_files() -> None:
    """The degenerate case stays an empty map, not a crash."""
    assert _language_counts([]) == {}


# ── the three numbers are derived together (#175 + #196) ─────────────────────


def test_run_counts_derive_every_number_from_the_results() -> None:
    """One constructor, so checked / skipped / per-language cannot drift apart."""
    results = [
        LintResult(path="a.py"),
        LintResult(path="b.py", analysis_skipped=True),
        LintResult(path="c.rs"),
    ]

    counts = _RunCounts.from_results(results)

    assert counts.files_checked == 3
    assert counts.coverage.files_skipped == 1
    assert counts.coverage.by_language == {"python": 2, "rust": 1}


def test_run_counts_on_an_empty_run_are_all_zero() -> None:
    """A run that reached nothing reports nothing, not a division or a crash."""
    counts = _RunCounts.from_results([])

    assert counts.files_checked == 0
    assert counts.coverage.files_skipped == 0
    assert counts.coverage.by_language == {}


def test_run_coverage_owns_its_mapping() -> None:
    """``frozen=True`` alone would leave the mapping mutable through the caller.

    Two halves: the object copies what it was handed, so a later mutation of
    the caller's dict cannot change it, and what it exposes is a read-only
    proxy rather than a plain dict a consumer could write through.
    """
    source = {"python": 1}
    coverage = RunCoverage(files_skipped=0, by_language=source)

    source["python"] = 99  # mutating what we passed in must not reach the object

    assert coverage.by_language == {"python": 1}
    assert isinstance(coverage.by_language, MappingProxyType)


def test_run_counts_default_coverage_is_empty() -> None:
    """A bare ``_RunCounts`` carries a real, empty coverage object, not None."""
    counts = _RunCounts(files_checked=1)

    assert counts.coverage.files_skipped == 0
    assert counts.coverage.by_language == {}


# ── end to end: the whole pipeline, which is the actual contract ─────────────


def test_a_polyglot_run_reports_honest_coverage_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """One run, all three numbers, through the real CLI entry point.

    The unit tests above pin each piece; this is the one that would catch the
    pieces being wired up wrongly, which is the failure a user would actually
    meet.
    """
    (tmp_path / "good.py").write_text(_CLEAN_PY, encoding="utf-8")
    (tmp_path / "bad.py").write_text(_BROKEN_PY, encoding="utf-8")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")

    exit_code = _run_cli(monkeypatch, ["check", str(tmp_path), "--all-files", "--format", "json"])
    document = json.loads(capsys.readouterr().out)

    assert exit_code == 1  # the SAFE000 is an error
    summary = document["summary"]
    assert summary["files_checked"] == 3
    assert summary["files_skipped"] == 1
    assert summary["files_analysed"] == 2
    assert summary["files_checked_by_language"] == {"c": 1, "python": 2}


def test_lost_coverage_is_still_reported_when_safe000_is_ignored(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end on the dangerous configuration.

    With ``ignore = ["SAFE000"]`` the run is clean and exits 0, so the summary
    is the *only* place the gap can surface. If this regresses, safelint tells
    a user their code passed over a file it never read.
    """
    (tmp_path / "good.py").write_text(_CLEAN_PY, encoding="utf-8")
    (tmp_path / "bad.py").write_text(_BROKEN_PY, encoding="utf-8")
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "safelint.toml").write_text('ignore = ["SAFE000", "test_existence", "test_coupling"]\n', encoding="utf-8")

    exit_code = _run_cli(monkeypatch, ["check", str(tmp_path), "--all-files", "--config", str(config_dir), "--format", "json"])
    summary = json.loads(capsys.readouterr().out)["summary"]

    assert exit_code == 0  # nothing to report, the run "passed"
    assert summary["violations"] == 0  # no SAFE000 left to count
    assert summary["files_skipped"] == 1  # the gap is still visible
    assert summary["files_analysed"] == 1


def test_an_oversize_file_counts_as_lost_coverage(tmp_path: Path) -> None:
    """A file too large to read ran no rules, so it is not analysed (#274 review).

    It was previously counted as analysed, which let `files_analysed` claim
    full coverage and defeated the documented CI check: a project with one
    enormous generated file would report `files_skipped: 0` while that file was
    never examined. The pre-read refusals produce no violation at all - only a
    stderr warning - so the flag is the only place this can surface.
    """
    sample = tmp_path / "huge.py"
    sample.write_text("x = 1\n" * 200, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"max_file_size_bytes": 10}))

    result = engine.check_file(str(sample))

    assert result.analysis_skipped is True
    assert result.violations == []  # no violation, which is exactly why the flag matters


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo is POSIX-only; Windows has no FIFO to create")
def test_a_non_regular_file_counts_as_lost_coverage(tmp_path: Path) -> None:
    """A FIFO is refused before reading, and that is still lost coverage.

    Skipped on Windows, which has no ``os.mkfifo`` at all. The guard it tests
    is platform-independent and the oversize case above covers the same
    code path on every platform, so nothing is left unverified there.
    """
    fifo = tmp_path / "pipe.py"
    os.mkfifo(fifo)

    assert _engine().check_file(str(fifo)).analysis_skipped is True


def test_an_excluded_file_is_still_not_lost_coverage(tmp_path: Path) -> None:
    """The line the other side of the distinction, pinned so it cannot drift.

    An excluded file is out of scope by configuration, not lost. Counting it
    would make ``files_analysed`` meaningless on any project with an exclude
    list, which is every real project.
    """
    sample = tmp_path / "vendored.py"
    sample.write_text(_CLEAN_PY, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"extend_exclude_paths": [str(sample)]}))

    assert engine.check_file(str(sample)).analysis_skipped is False
