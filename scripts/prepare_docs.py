"""Prepare docs/ build tree: copy community-health files + generate rule index.

Two responsibilities run from one place so both the GH Actions workflow and
``uv run mkdocs serve`` only need a single pre-build hook:

1. **Copy + rewrite community-health Markdown.** CHANGELOG.md / CONTRIBUTING.md
   / CODE_OF_CONDUCT.md / SUPPORT.md live at the repo root because GitHub's
   community-health UI surfaces them there. Their cross-references inside
   (``[…](AI_CLIENTS.md)`` etc.) are repo-root-relative and don't resolve
   when the file lands under ``docs/contributing/`` or ``docs/project/``,
   so we rewrite them as we copy.
2. **Generate the rules-at-a-glance table.** ``ALL_RULES`` and the per-rule
   defaults dict in ``safelint.core.config`` are the source of truth for
   rule code → name → severity → enabled. We snapshot them into
   ``docs/configuration/_rules_at_a_glance.md`` (gitignored) and the
   ``rules.md`` page pulls it in via the snippets extension.

Run from the repo root:

    uv run python scripts/prepare_docs.py

Idempotent. All output paths are listed in ``.gitignore``.
"""

from __future__ import annotations

import re
import sys
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


_RULES_INDEX_DEST = "build/snippets/_rules_at_a_glance.md"


def _slugify_heading(code: str, name: str) -> str:
    """Match the slug pymdownx.toc generates for rules.md ``### SAFE101 — `name``` headings."""
    return f"{code.lower()}-{name}"


def _generate_rules_index(repo_root: Path) -> str:
    """Render the rules-at-a-glance table from ALL_RULES + DEFAULTS."""
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from safelint.core.config import DEFAULTS  # noqa: PLC0415  (lazy: only when generating)
    from safelint.rules import ALL_RULES  # noqa: PLC0415

    rule_defaults: dict[str, dict[str, object]] = DEFAULTS["rules"]  # type: ignore[assignment]
    lines = [
        "<!-- Auto-generated by scripts/prepare_docs.py — do not edit by hand. -->",
        "",
        "| Code | Name | Default severity | Enabled by default |",
        "|---|---|---|---|",
    ]
    for rule_cls in ALL_RULES:
        code: str = rule_cls.code  # type: ignore[attr-defined]
        name: str = rule_cls.name  # type: ignore[attr-defined]
        defaults = rule_defaults.get(name, {})
        severity = defaults.get("severity", "—")
        enabled = "yes" if defaults.get("enabled", False) else "no"
        anchor = _slugify_heading(code, name)
        lines.append(
            f"| [`{code}`](#{anchor}) | `{name}` | {severity} | {enabled} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    # 1. Community-health files: copy + rewrite cross-refs.
    for source_rel, dest_rel, mapping in _COPIES:
        source = repo_root / source_rel
        dest = repo_root / dest_rel
        text = source.read_text(encoding="utf-8")
        text = _rewrite_links(text, mapping)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"prepared {dest_rel} (from {source_rel}, {len(mapping)} link rewrites)")

    # 2. Rules-at-a-glance table from the live registry.
    rules_dest = repo_root / _RULES_INDEX_DEST
    rules_dest.parent.mkdir(parents=True, exist_ok=True)
    rules_dest.write_text(_generate_rules_index(repo_root), encoding="utf-8")
    print(f"prepared {_RULES_INDEX_DEST} (from safelint.rules.ALL_RULES)")


# MkDocs ``hooks:`` entry point — same logic, fires on every ``mkdocs build`` /
# ``mkdocs serve`` so local previews don't need a manual prep step.
def on_pre_build(config: object, **_: object) -> None:  # noqa: ARG001
    main()


if __name__ == "__main__":
    main()
