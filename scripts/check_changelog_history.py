#!/usr/bin/env python3
"""Refuse a change that edits the notes of an already-released version.

Rebasing a feature branch across a release silently rewrites published release
notes, and it never conflicts, so nothing asks (#278). A branch adds entries
under ``## [Unreleased]`` -> ``### Fixed``; the release workflow renames that
heading to ``## [X.Y.Z] - <date>`` and inserts a fresh empty ``[Unreleased]``.
On rebase git sees ``### Fixed`` either side with identical surrounding
context and merges cleanly - into the **dated** section.

That happened four times in one day (on the branches for #266, #270, #275 and
#276), and every one was caught only by diffing the dated sections by hand
afterwards. A conflict would have been safe, because it would have prompted; a
clean rebase is the dangerous case.

The rule enforced here: **a dated section present in both the base branch and
the head must be byte-identical.** A pull request has no business editing the
notes of a shipped version. Adding a *new* dated section is allowed, because
that is what the release workflow itself does, and so is any edit to
``[Unreleased]``.

Usage::

    check_changelog_history.py --base-ref origin/main [--changelog CHANGELOG.md]

Exits 0 when the history is intact, 1 when a released section was edited, and
2 when the comparison could not be made (a missing ref, say) - the three states
kept distinct so CI can tell "this is wrong" from "I could not tell".
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


#: A dated release heading: ``## [2.18.0] - 2026-11-07``. The date is required,
#: which is what distinguishes a shipped section from ``## [Unreleased]``.
_DATED_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\] - \d{4}-\d{2}-\d{2}\s*$")

#: A compare-link footer: ``[2.18.0]: https://github.com/...``. These were
#: corrupted once by the same mechanism, so they are compared too.
_FOOTER_LINK = re.compile(r"^\[(?P<version>[^\]]+)\]:\s")

_EXIT_OK = 0
_EXIT_EDITED = 1
_EXIT_CANNOT_TELL = 2


def _dated_sections(text: str) -> dict[str, str]:
    """Return ``{version: section text}`` for every dated release heading.

    A section runs from its heading to the next ``## `` heading, so it carries
    its own subsections and bullets. ``[Unreleased]`` has no date and is
    therefore absent by construction, which is the point: it is the only part
    of the file a pull request may freely rewrite.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in text.split("\n"):
        match = _DATED_HEADING.match(line)
        if match is None and not (line.startswith("## ") and current is not None):
            body.append(line)
            continue
        if current is not None:
            sections[current] = "\n".join(body).rstrip()
        current = match.group("version") if match is not None else None
        body = [line] if match is not None else []
    if current is not None:
        sections[current] = "\n".join(body).rstrip()
    return sections


def _footer_links(text: str) -> dict[str, str]:
    """Return ``{version: footer line}`` for each compare-link definition."""
    links: dict[str, str] = {}
    for line in text.split("\n"):
        match = _FOOTER_LINK.match(line)
        if match is not None:
            links[match.group("version")] = line.rstrip()
    return links


def _git_show(ref: str, path: str) -> str | None:
    """Return *path* as of *ref*, or None when it cannot be read."""
    try:
        done = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=False)  # noqa: S603, S607 - argv list, no shell; git from PATH as elsewhere in scripts/
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def _report(kind: str, differing: list[str]) -> None:
    """Print one explanatory block for the versions that changed."""
    print(f"\nCHANGELOG history changed: {kind} edited for already-released version(s): {', '.join(differing)}", file=sys.stderr)
    print("\nA pull request must not edit the notes of a version that has shipped.", file=sys.stderr)
    print("The usual cause is a rebase across a release: the branch's entries were", file=sys.stderr)
    print("written under '## [Unreleased]', the release workflow renamed that heading", file=sys.stderr)
    print("to '## [X.Y.Z] - <date>', and the rebase merged them into the dated section", file=sys.stderr)
    print("without conflicting (see issue #278).", file=sys.stderr)
    print("\nTo fix: move those entries back under '## [Unreleased]' and restore the", file=sys.stderr)
    print("dated section from the base branch verbatim:", file=sys.stderr)
    print("    git show <base>:CHANGELOG.md", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Compare the dated sections of CHANGELOG.md against *base-ref*."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-ref", required=True, help="the ref to compare against, e.g. origin/main")
    parser.add_argument("--changelog", default="CHANGELOG.md", help="path to the changelog (default: CHANGELOG.md)")
    args = parser.parse_args(argv)

    head_text = Path(args.changelog).read_text(encoding="utf-8") if Path(args.changelog).is_file() else None
    if head_text is None:
        print(f"cannot tell: {args.changelog} is not a file in the working tree", file=sys.stderr)
        return _EXIT_CANNOT_TELL
    base_text = _git_show(args.base_ref, args.changelog)
    if base_text is None:
        print(f"cannot tell: could not read {args.changelog} at {args.base_ref}", file=sys.stderr)
        return _EXIT_CANNOT_TELL

    base_sections, head_sections = _dated_sections(base_text), _dated_sections(head_text)
    shared = sorted(set(base_sections) & set(head_sections))
    changed = [v for v in shared if base_sections[v] != head_sections[v]]

    base_links, head_links = _footer_links(base_text), _footer_links(head_text)
    shared_links = sorted(set(base_links) & set(head_links) & set(base_sections))
    changed_links = [v for v in shared_links if base_links[v] != head_links[v]]

    if not changed and not changed_links:
        print(f"CHANGELOG history intact: {len(shared)} released section(s) unchanged against {args.base_ref}")
        return _EXIT_OK
    if changed:
        _report("section body", changed)
    if changed_links:
        _report("compare-link footer", changed_links)
    return _EXIT_EDITED


if __name__ == "__main__":
    sys.exit(main())
