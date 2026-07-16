#!/usr/bin/env python3
"""Extract one CHANGELOG.md section as GitHub-release-note text.

Usage:
    python scripts/changelog_section.py <version> [changelog_path]

For a **pre-release** version (``X.Y.ZrcN`` / ``a`` / ``b`` / ``.dev``) the
current ``## [Unreleased]`` section is returned - rc changelogs stay under
Unreleased until the production tag. For a **final** version the
``## [X.Y.Z]`` section is returned (its heading may carry a `` - <date>``
suffix). Exits non-zero if the expected section is absent, so a release never
ships empty / wrong notes silently.

The core is the pure :func:`extract_section` (text in, text out) so it is
unit-tested without touching the filesystem; ``main`` is the thin CLI the
release workflow calls.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


_PRERELEASE = re.compile(r"(rc|a|b|\.dev)\d*$")


def is_prerelease(version: str) -> bool:
    """Return True for a PEP 440 pre-release version (rc / a / b / .dev)."""
    return bool(_PRERELEASE.search(version))


def _heading_name(line: str) -> str | None:
    """Return the bracketed name of a ``## [name] ...`` heading, or None."""
    if not line.startswith("## ["):
        return None
    close = line.find("]")
    if close == -1:
        return None
    return line[line.index("[") + 1 : close]


def extract_section(changelog: str, version: str) -> str:
    """Return the release-note body for *version* from *changelog* text.

    Raises:
        ValueError: if the expected ``## [Unreleased]`` (pre-release) or
            ``## [X.Y.Z]`` (final) heading is not present.
    """
    wanted = "Unreleased" if is_prerelease(version) else version
    lines = changelog.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _heading_name(line) == wanted:
            start = i + 1
            break
    if start is None:
        msg = f"no '## [{wanted}]' section found in CHANGELOG"
        raise ValueError(msg)
    end = start
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    return "\n".join(lines[start:end]).strip()


def main() -> int:
    """CLI: print the section body for the given version to stdout."""
    if len(sys.argv) < 2:
        print("usage: changelog_section.py <version> [changelog_path]", file=sys.stderr)
        return 2
    version = sys.argv[1]
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("CHANGELOG.md")
    try:
        section = extract_section(path.read_text(encoding="utf-8"), version)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
