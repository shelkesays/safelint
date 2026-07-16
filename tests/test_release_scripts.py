"""Tests for the release-automation helper scripts under ``scripts/``.

The scripts live outside the ``src`` package (they are release tooling, not part
of the shipped wheel), so they are loaded by path via ``importlib`` rather than
imported normally.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from types import ModuleType


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> ModuleType:
    """Load ``scripts/<name>.py`` as a module."""
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changelog_section = _load("changelog_section")
date_changelog = _load("date_changelog")


_SAMPLE = """\
# Changelog

## [Unreleased]

### Added

- A shiny new thing.

## [2.8.4] - 2026-07-15

### Security

- Closed a hole.

## [2.8.3] - 2026-07-13

### Changed

- Refactored internals.

[Unreleased]: https://github.com/shelkesays/safelint/compare/v2.8.2...HEAD
[2.8.4]: https://github.com/shelkesays/safelint/compare/v2.8.3...v2.8.4
"""


# ---------------------------------------------------------------------------
# changelog_section
# ---------------------------------------------------------------------------


def test_is_prerelease_classifies_rc_and_final() -> None:
    """rc / a / b / .dev suffixes are pre-releases; a bare X.Y.Z is not."""
    assert changelog_section.is_prerelease("2.9.0rc1")
    assert changelog_section.is_prerelease("2.9.0a2")
    assert changelog_section.is_prerelease("2.9.0.dev1")
    assert not changelog_section.is_prerelease("2.9.0")


def test_extract_section_prerelease_returns_unreleased() -> None:
    """A pre-release version pulls the [Unreleased] body."""
    out = changelog_section.extract_section(_SAMPLE, "2.9.0rc1")
    assert "A shiny new thing." in out
    assert "Closed a hole." not in out  # did not bleed into the next section


def test_extract_section_final_returns_versioned_block() -> None:
    """A final version pulls its own dated block, matching on the bracketed name."""
    out = changelog_section.extract_section(_SAMPLE, "2.8.4")
    assert "Closed a hole." in out
    assert "A shiny new thing." not in out
    assert "Refactored internals." not in out


def test_extract_section_missing_raises() -> None:
    """A final version with no matching section raises rather than returning empty."""
    with pytest.raises(ValueError, match=r"\[9\.9\.9\]"):
        changelog_section.extract_section(_SAMPLE, "9.9.9")


# ---------------------------------------------------------------------------
# date_changelog
# ---------------------------------------------------------------------------


def test_date_changelog_flips_heading_and_readds_unreleased() -> None:
    """[Unreleased] becomes the dated release heading with a fresh empty [Unreleased]."""
    out = date_changelog.date_changelog(_SAMPLE, "2.9.0", "2026-08-01")
    assert "## [2.9.0] - 2026-08-01" in out
    # A new empty Unreleased sits above the dated block.
    unreleased_idx = out.index("## [Unreleased]")
    dated_idx = out.index("## [2.9.0] - 2026-08-01")
    assert unreleased_idx < dated_idx
    # The moved content now lives under the dated heading, not Unreleased.
    assert out.index("A shiny new thing.") > dated_idx


def test_date_changelog_updates_footer_links() -> None:
    """Footers: [Unreleased] repointed to v2.9.0...HEAD and a new [2.9.0] link added."""
    out = date_changelog.date_changelog(_SAMPLE, "2.9.0", "2026-08-01")
    assert "[Unreleased]: https://github.com/shelkesays/safelint/compare/v2.9.0...HEAD" in out
    # prev = topmost dated heading (2.8.4), so the compare spans v2.8.4...v2.9.0.
    assert "[2.9.0]: https://github.com/shelkesays/safelint/compare/v2.8.4...v2.9.0" in out


def test_date_changelog_is_idempotent() -> None:
    """Re-running on an already-dated version is a no-op (guards the self-re-trigger)."""
    once = date_changelog.date_changelog(_SAMPLE, "2.9.0", "2026-08-01")
    twice = date_changelog.date_changelog(once, "2.9.0", "2026-08-09")
    assert once == twice  # second run does not re-date or shift the date


def test_date_changelog_preserves_trailing_newline() -> None:
    """The rewrite keeps the file's trailing newline (no spurious diff)."""
    out = date_changelog.date_changelog(_SAMPLE, "2.9.0", "2026-08-01")
    assert out.endswith("\n")
