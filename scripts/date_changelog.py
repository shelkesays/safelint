#!/usr/bin/env python3
"""Date the CHANGELOG at release time: flip ``[Unreleased]`` to ``[X.Y.Z] - <date>``.

Usage:
    python scripts/date_changelog.py <version> <date> [changelog_path]

On a **final** release the release workflow runs this before tagging. It:

1. renames ``## [Unreleased]`` -> ``## [X.Y.Z] - <date>``,
2. re-inserts an empty ``## [Unreleased]`` above it, and
3. updates the reference-style compare footers: repoints
   ``[Unreleased]: .../compare/vX.Y.Z...HEAD`` and inserts
   ``[X.Y.Z]: .../compare/v<prev>...vX.Y.Z``.

**Idempotent**: if ``## [X.Y.Z]`` is already present (a re-run), the text is
returned unchanged, so the workflow's self-re-trigger cannot double-flip. The
date is passed in (from the workflow run) rather than read from the clock, which
keeps :func:`date_changelog` pure and unit-testable.
"""

from __future__ import annotations

import sys
from pathlib import Path


_COMPARE = "https://github.com/shelkesays/safelint/compare"
_TAG = "https://github.com/shelkesays/safelint/releases/tag"


def _heading_name(line: str) -> str | None:
    """Return the bracketed name of a ``## [name] ...`` heading, or None."""
    if not line.startswith("## ["):
        return None
    close = line.find("]")
    if close == -1:
        return None
    return line[line.index("[") + 1 : close]


def already_dated(changelog: str, version: str) -> bool:
    """Return True when a ``## [version]`` heading already exists."""
    return any(_heading_name(line) == version for line in changelog.splitlines())


def _previous_version(lines: list[str]) -> str | None:
    """Return the topmost dated release heading below ``[Unreleased]``."""
    for line in lines:
        name = _heading_name(line)
        if name is not None and name != "Unreleased":
            return name
    return None


def date_changelog(changelog: str, version: str, date: str) -> str:
    """Return *changelog* with ``[Unreleased]`` flipped to ``[version] - date``.

    A no-op (returns the input unchanged) when *version* is already dated.
    """
    if already_dated(changelog, version):
        return changelog
    trailing_newline = changelog.endswith("\n")
    lines = changelog.splitlines()
    prev = _previous_version(lines)
    body: list[str] = []
    for line in lines:
        if line.strip() == "## [Unreleased]":
            body.extend(["## [Unreleased]", "", f"## [{version}] - {date}"])
        elif line.startswith("[Unreleased]:"):
            body.append(f"[Unreleased]: {_COMPARE}/v{version}...HEAD")
            if prev is not None:
                body.append(f"[{version}]: {_COMPARE}/v{prev}...v{version}")
            else:
                body.append(f"[{version}]: {_TAG}/v{version}")
        else:
            body.append(line)
    text = "\n".join(body)
    return text + "\n" if trailing_newline else text


def main() -> int:
    """CLI: rewrite the changelog file in place, dating *version* as *date*."""
    if len(sys.argv) < 3:
        print("usage: date_changelog.py <version> <date> [changelog_path]", file=sys.stderr)
        return 2
    version, date = sys.argv[1], sys.argv[2]
    path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("CHANGELOG.md")
    original = path.read_text(encoding="utf-8")
    updated = date_changelog(original, version, date)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        print(f"dated CHANGELOG: [Unreleased] -> [{version}] - {date}")
    else:
        print(f"CHANGELOG already dates [{version}]; no change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
