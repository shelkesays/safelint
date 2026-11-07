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
from typing import NamedTuple


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


def _duplicate_versions(text: str) -> list[str]:
    """Return versions whose dated heading appears more than once.

    A repeated heading collapses in :func:`_dated_sections`'s dict and the LAST
    copy wins, so an edit to the first copy hides behind an untouched duplicate
    and the comparison passes (#280 review). A changelog has no legitimate
    duplicate release heading, so the caller refuses one outright rather than
    trying to compare both.

    Its own function rather than tracked inside the section walk, which
    safelint's own SAFE104 flagged at cyclomatic complexity 11 against a max
    of 10.
    """
    versions = [match.group("version") for line in text.split("\n") if (match := _DATED_HEADING.match(line)) is not None]
    return sorted({version for version in versions if versions.count(version) > 1})


def _footer_links(text: str) -> dict[str, str]:
    """Return ``{version: footer line}`` for each compare-link definition."""
    links: dict[str, str] = {}
    for line in text.split("\n"):
        match = _FOOTER_LINK.match(line)
        if match is not None:
            links[match.group("version")] = line.rstrip()
    return links


def _git(*args: str) -> str | None:
    """Run a read-only git command and return stdout, or None on any failure.

    ``text=True`` decodes, so an invalid blob raises ``UnicodeDecodeError``
    rather than returning - which escaped the caller and crashed instead of
    reporting the documented "cannot tell" status (#280 review). Decoded here
    with a replacement policy instead: a changelog that cannot be decoded
    cleanly is still worth comparing, and a crash tells nobody anything.
    """
    try:
        done = subprocess.run(["git", *args], capture_output=True, check=False)  # noqa: S603, S607 - argv list, no shell; git from PATH as elsewhere in scripts/
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


def _comparison_ref(base_ref: str) -> str | None:
    """Return the merge base of *base_ref* and HEAD, else None.

    Comparing against the base **tip** fails valid pull requests. When a
    release lands on the base while a branch is open, the base gains a dated
    section the branch has never seen, and the deleted-section check reports
    the branch as having *lost published notes* - which is both wrong and
    actively misleading, since the branch is merely out of date (#280 review).

    The merge base is the right reference: it is the newest state the branch
    actually diverged from, so a release landing afterwards is irrelevant,
    while any edit to a section that existed at the branch point is still
    caught.
    """
    merge_base = _git("merge-base", base_ref, "HEAD")
    return merge_base.strip() if merge_base is not None and merge_base.strip() else None


class _Verdict(NamedTuple):
    """What changed between the base and head changelogs."""

    shared: int
    missing: list[str]
    changed: list[str]
    changed_links: list[str]

    @property
    def has_findings(self) -> bool:
        """True when anything about a released version differs."""
        return bool(self.missing or self.changed or self.changed_links)


def _compare(base_text: str, head_text: str) -> _Verdict:
    """Compare every released section and footer that the two texts share.

    Split out of ``main`` to keep it under safelint's own complexity bar, which
    its self-lint caught at 11 against a max of 10.
    """
    base_sections, head_sections = _dated_sections(base_text), _dated_sections(head_text)
    # A version in the base but not the head means its heading was DELETED or
    # renamed, which loses the notes outright rather than editing them - worse
    # than what this check was written for, and it passed, because comparing
    # only the shared versions never looked at it (#279 review).
    base_versions, head_versions = set(base_sections), set(head_sections)
    missing = sorted(base_versions - head_versions)
    shared = sorted(base_versions & head_versions)
    changed = [v for v in shared if base_sections[v] != head_sections[v]]

    base_links, head_links = _footer_links(base_text), _footer_links(head_text)
    shared_links = sorted(set(base_links) & set(head_links) & base_versions)
    changed_links = [v for v in shared_links if base_links[v] != head_links[v]]
    return _Verdict(shared=len(shared), missing=missing, changed=changed, changed_links=changed_links)


def _read_head(path: Path) -> str | None:
    """Return *path*'s text, or None when it cannot be read.

    ``read_text`` raises on an unreadable or undecodable file, which would have
    crashed with a traceback instead of the documented "cannot tell" exit (#279
    review). A guard that dies noisily is nearly as bad as one that passes
    quietly: either way CI stops telling you about the thing it was added for.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


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

    head_text = _read_head(Path(args.changelog))
    if head_text is None:
        print(f"cannot tell: could not read {args.changelog} from the working tree", file=sys.stderr)
        return _EXIT_CANNOT_TELL
    ref = _comparison_ref(args.base_ref)
    if ref is None:
        print(f"cannot tell: no merge base between {args.base_ref} and HEAD", file=sys.stderr)
        return _EXIT_CANNOT_TELL
    base_text = _git("show", f"{ref}:{args.changelog}")
    if base_text is None:
        print(f"cannot tell: could not read {args.changelog} at {ref[:12]} (merge base with {args.base_ref})", file=sys.stderr)
        return _EXIT_CANNOT_TELL

    duplicated = _duplicate_versions(head_text)
    if duplicated:
        print(f"\nCHANGELOG has a duplicate release heading for: {', '.join(duplicated)}", file=sys.stderr)
        print("A duplicate hides an edit to the earlier copy from this comparison, so it is", file=sys.stderr)
        print("refused outright. Remove the repeated '## [X.Y.Z] - <date>' heading.", file=sys.stderr)
        return _EXIT_EDITED

    verdict = _compare(base_text, head_text)
    if not verdict.has_findings:
        print(f"CHANGELOG history intact: {verdict.shared} released section(s) unchanged against {args.base_ref}")
        return _EXIT_OK
    if verdict.missing:
        _report("whole section deleted or renamed", verdict.missing)
    if verdict.changed:
        _report("section body", verdict.changed)
    if verdict.changed_links:
        _report("compare-link footer", verdict.changed_links)
    return _EXIT_EDITED


if __name__ == "__main__":
    sys.exit(main())
