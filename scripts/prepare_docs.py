"""Copy repo-root community-health Markdown into docs/, rewriting cross-refs.

CHANGELOG.md / CONTRIBUTING.md / CODE_OF_CONDUCT.md / SUPPORT.md live at the
repo root because GitHub's community-health UI surfaces them there. The docs
site needs the same content but the cross-references inside (``[…](AI_CLIENTS.md)``
etc.) are repo-root-relative — they don't resolve when the file is placed
inside ``docs/contributing/`` or ``docs/project/``. This script does the copy
*and* rewrites the links to docs-site-relative form.

Run from the repo root:

    python scripts/prepare_docs.py

Idempotent. The output paths are listed in ``.gitignore`` — re-running just
overwrites; never commit the targets.
"""

from __future__ import annotations

import re
from pathlib import Path

# Each entry: (source at repo root, destination under docs/, rewrite map).
#
# The rewrite map's keys are the *patterns* found in the source file's
# ``[label](URL)`` constructs; values are the docs-site-relative path that
# should appear in the destination. Values are computed relative to the
# *destination* directory — that's why the same source URL maps to different
# destination URLs depending on where the file lands.
_COPIES: tuple[tuple[str, str, dict[str, str]], ...] = (
    (
        "CONTRIBUTING.md",
        "docs/contributing/index.md",
        {
            "AI_CLIENTS.md": "../ai-clients/index.md",
            "CONFIGURATION.md": "../configuration/index.md",
            "ADDING_AN_AI_CLIENT.md": "adding-an-ai-client.md",
            "ADDING_A_LANGUAGE.md": "adding-a-language.md",
            "CODE_OF_CONDUCT.md": "../project/code-of-conduct.md",
            "CITATION.cff": "https://github.com/shelkesays/safelint/blob/main/CITATION.cff",
            "SUPPORT.md": "../project/support.md",
            "CHANGELOG.md": "../project/changelog.md",
            "README.md": "../index.md",
            "docs/JSON_SCHEMA.md": "../json-schema.md",
        },
    ),
    (
        "CHANGELOG.md",
        "docs/project/changelog.md",
        {
            "AI_CLIENTS.md": "../ai-clients/index.md",
            "CONFIGURATION.md": "../configuration/index.md",
            "ADDING_AN_AI_CLIENT.md": "../contributing/adding-an-ai-client.md",
            "ADDING_A_LANGUAGE.md": "../contributing/adding-a-language.md",
            "CONTRIBUTING.md": "../contributing/index.md",
            "CODE_OF_CONDUCT.md": "code-of-conduct.md",
            "SUPPORT.md": "support.md",
            "README.md": "../index.md",
            "docs/JSON_SCHEMA.md": "../json-schema.md",
        },
    ),
    (
        "CODE_OF_CONDUCT.md",
        "docs/project/code-of-conduct.md",
        {},
    ),
    (
        "SUPPORT.md",
        "docs/project/support.md",
        {
            "AI_CLIENTS.md": "../ai-clients/index.md",
            "CONFIGURATION.md": "../configuration/index.md",
            "ADDING_AN_AI_CLIENT.md": "../contributing/adding-an-ai-client.md",
            "ADDING_A_LANGUAGE.md": "../contributing/adding-a-language.md",
            "CONTRIBUTING.md": "../contributing/index.md",
            "CODE_OF_CONDUCT.md": "code-of-conduct.md",
            "README.md": "../index.md",
            "docs/JSON_SCHEMA.md": "../json-schema.md",
        },
    ),
)


def _rewrite_links(text: str, mapping: dict[str, str]) -> str:
    """Replace every ``[label](old_url)`` whose old_url is a key of *mapping*."""
    if not mapping:
        return text
    # Sort keys longest-first so ``docs/JSON_SCHEMA.md`` is replaced before
    # the bare ``JSON_SCHEMA.md`` would be — defensive against future link forms.
    for old in sorted(mapping, key=len, reverse=True):
        # Match ``](OLD)`` exactly so we don't touch URL-like strings inside
        # code spans or prose where ``)`` doesn't close a link.
        text = text.replace(f"]({old})", f"]({mapping[old]})")
    return text


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    for source_rel, dest_rel, mapping in _COPIES:
        source = repo_root / source_rel
        dest = repo_root / dest_rel
        text = source.read_text(encoding="utf-8")
        text = _rewrite_links(text, mapping)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"prepared {dest_rel} (from {source_rel}, {len(mapping)} link rewrites)")


if __name__ == "__main__":
    main()
