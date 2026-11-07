"""The guard that stops a rebase rewriting published release notes (#278).

The failure it exists to catch is silent: a branch's entries sit under
``## [Unreleased]`` -> ``### Fixed``, the release workflow renames that heading
to ``## [X.Y.Z] - <date>``, and a later rebase merges the entries into the
**dated** section without conflicting, because the subsection headings match
either side. It happened four times in one day and was caught only by hand.

These tests stand up a real throwaway git repository rather than mocking
``git show``, because the thing under test is precisely the comparison against
another ref: a mock would assert that the script calls git, not that it reaches
the right verdict.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from types import ModuleType


_RELEASED = """# Changelog

## [Unreleased]

## [2.18.0] - 2026-11-07

### Fixed

- **A real fix that shipped.** Body text.

## [2.17.2] - 2026-11-07

### Fixed

- **An older fix.** Body text.

[2.18.0]: https://example.invalid/compare/v2.17.2...v2.18.0
[2.17.2]: https://example.invalid/compare/v2.17.1...v2.17.2
"""


def _load_script() -> ModuleType:
    """Import ``scripts/check_changelog_history.py`` as a module."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_changelog_history.py"
    spec = importlib.util.spec_from_file_location("check_changelog_history", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    """Run a git command in *repo*, failing loudly."""
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A git repo whose committed CHANGELOG has two released sections."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "CHANGELOG.md").write_text(_RELEASED, encoding="utf-8")
    _git(tmp_path, "add", "CHANGELOG.md")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _run(script: ModuleType, repo: Path, base: str = "HEAD") -> int:
    """Run the checker inside *repo* and return its exit status."""
    cwd = Path.cwd()
    try:
        os.chdir(repo)
        return int(script.main(["--base-ref", base]))
    finally:
        os.chdir(cwd)


def test_an_unchanged_changelog_passes(repo: Path) -> None:
    """The overwhelmingly common case must be silent and green."""
    assert _run(_load_script(), repo) == 0


def test_adding_to_unreleased_is_allowed(repo: Path) -> None:
    """The only part of the file a branch may freely rewrite."""
    path = repo / "CHANGELOG.md"
    path.write_text(_RELEASED.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- **My new entry.**\n"), encoding="utf-8")

    assert _run(_load_script(), repo) == 0


def test_the_real_failure_is_caught(repo: Path) -> None:
    """The #278 shape: an entry lands inside a dated section.

    This is what a rebase across a release actually produces - the new bullet
    prepended to the released section's ``### Fixed``, with no conflict.
    """
    path = repo / "CHANGELOG.md"
    path.write_text(
        _RELEASED.replace(
            "### Fixed\n\n- **A real fix that shipped.**",
            "### Fixed\n\n- **My new entry that was never in 2.18.0.** Body.\n\n- **A real fix that shipped.**",
            1,
        ),
        encoding="utf-8",
    )

    assert _run(_load_script(), repo) == 1


def test_the_failure_message_names_the_version_and_the_cause(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A guard nobody can act on is barely better than silence."""
    path = repo / "CHANGELOG.md"
    path.write_text(_RELEASED.replace("- **An older fix.** Body text.", "- **Edited after release.** Body text."), encoding="utf-8")

    status = _run(_load_script(), repo)
    err = capsys.readouterr().err

    assert status == 1
    assert "2.17.2" in err  # which version
    assert "rebase across a release" in err  # why it probably happened
    assert "#278" in err  # where to read more


def test_a_new_dated_section_is_allowed(repo: Path) -> None:
    """The release workflow itself adds one, so this must not be refused."""
    path = repo / "CHANGELOG.md"
    path.write_text(_RELEASED.replace("## [2.18.0] - 2026-11-07", "## [2.19.0] - 2026-12-01\n\n### Added\n\n- **New.**\n\n## [2.18.0] - 2026-11-07"), encoding="utf-8")

    assert _run(_load_script(), repo) == 0


def test_a_rewritten_compare_footer_is_caught(repo: Path) -> None:
    """The footers were corrupted by the same mechanism once, so they count too."""
    path = repo / "CHANGELOG.md"
    path.write_text(_RELEASED.replace("[2.17.2]: https://example.invalid/compare/v2.17.1...v2.17.2", "[2.17.2]: https://example.invalid/compare/WRONG...v2.17.2"), encoding="utf-8")

    assert _run(_load_script(), repo) == 1


def test_an_unreadable_base_ref_is_distinguishable_from_a_violation(repo: Path) -> None:
    """Exit 2 means "could not tell", which must not read as "this is fine".

    Collapsing it into 0 would make a misconfigured CI job silently stop
    guarding, which is the failure mode this whole check exists to remove.
    """
    assert _run(_load_script(), repo, base="refs/heads/does-not-exist") == 2
