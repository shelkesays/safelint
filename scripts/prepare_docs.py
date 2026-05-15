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
   ``build/snippets/_rules_at_a_glance.md`` - outside ``docs/`` on purpose,
   so MkDocs doesn't treat the snippet as a standalone page - and the
   ``rules.md`` page pulls it in via the snippets extension (configured
   with ``base_path: ["build/snippets", "docs"]`` in ``mkdocs.yml``).
   The output path is gitignored.

Run from the repo root:

    uv run python scripts/prepare_docs.py

Idempotent. All output paths are listed in ``.gitignore``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo-root files copied into docs/ are gitignored at the destination, so
# Material's auto-computed "Edit this page" link (``repo_url + edit_uri +
# dest_path``) would 404 against ``main``. We prepend YAML frontmatter
# with an absolute ``edit_url`` so Material points at the actual source
# file at the repo root instead.
_REPO_EDIT_URL_BASE = "https://github.com/shelkesays/safelint/edit/main/"

# Each entry: (source at repo root, destination under docs/, rewrite map).
#
# The rewrite map's keys are the *patterns* found in the source file's
# ``[label](URL)`` constructs; values are the docs-site-relative path that
# should appear in the destination. Values are computed relative to the
# *destination* directory - that's why the same source URL maps to different
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
            "docs/json-schema.md": "../json-schema.md",
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
            "docs/json-schema.md": "../json-schema.md",
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
            "docs/json-schema.md": "../json-schema.md",
        },
    ),
)


def _rewrite_links(text: str, mapping: dict[str, str]) -> str:
    """Replace every ``[label](old_url)`` whose old_url is a key of *mapping*."""
    if not mapping:
        return text
    # Sort keys longest-first so ``docs/json-schema.md`` is replaced before
    # the bare ``JSON_SCHEMA.md`` would be - defensive against future link forms.
    for old in sorted(mapping, key=len, reverse=True):
        # Plain string substitution - we anchor on the ``](`` prefix and the
        # closing ``)`` to avoid catching bare filename mentions in prose.
        # We do *not* parse Markdown structure, so a literal ``](OLD)`` token
        # inside a code span or fenced block would also be rewritten. None of
        # the source files (CHANGELOG / CONTRIBUTING / CODE_OF_CONDUCT /
        # SUPPORT) put literal Markdown link syntax inside code samples
        # today; if that changes, switch to a Markdown-aware rewrite.
        text = text.replace(f"]({old})", f"]({mapping[old]})")
    return text


_RULES_INDEX_DEST = "build/snippets/_rules_at_a_glance.md"


def _slugify_heading(code: str, name: str) -> str:
    """Return the heading slug Python-Markdown's ``toc`` extension produces for a rule.

    Rule headings on ``rules.md`` are written like::

        ### SAFE101 - `function_length`

    Python-Markdown's ``toc`` extension (enabled in ``mkdocs.yml`` as the
    plain ``toc:`` entry - *not* ``pymdownx.toc``) lowercases the text,
    drops non-alphanumeric runs, and joins the surviving tokens with
    single dashes. The em-dash and the inline-code backticks both fall
    out, leaving e.g. ``safe101-function_length``.
    """
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
        "<!-- Auto-generated by scripts/prepare_docs.py - do not edit by hand. -->",
        "",
        "| Code | Name | Default severity | Enabled by default |",
        "|---|---|---|---|",
    ]
    for rule_cls in ALL_RULES:
        code: str = rule_cls.code  # type: ignore[attr-defined]
        name: str = rule_cls.name  # type: ignore[attr-defined]
        defaults = rule_defaults.get(name, {})
        severity = defaults.get("severity", "-")
        enabled = "yes" if defaults.get("enabled", False) else "no"
        anchor = _slugify_heading(code, name)
        lines.append(
            f"| [`{code}`](#{anchor}) | `{name}` | {severity} | {enabled} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    # 1. Community-health files: copy + rewrite cross-refs + inject
    #    ``edit_url`` frontmatter so the rendered "Edit this page" link
    #    points at the repo-root source file (the gitignored docs/ copy
    #    isn't editable).
    for source_rel, dest_rel, mapping in _COPIES:
        source = repo_root / source_rel
        dest = repo_root / dest_rel
        text = source.read_text(encoding="utf-8")
        text = _rewrite_links(text, mapping)
        edit_url = f"{_REPO_EDIT_URL_BASE}{source_rel}"
        text = f"---\nedit_url: {edit_url}\n---\n\n{text}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"prepared {dest_rel} (from {source_rel}, {len(mapping)} link rewrites)")

    # 2. Rules-at-a-glance table from the live registry.
    rules_dest = repo_root / _RULES_INDEX_DEST
    rules_dest.parent.mkdir(parents=True, exist_ok=True)
    rules_dest.write_text(_generate_rules_index(repo_root), encoding="utf-8")
    print(f"prepared {_RULES_INDEX_DEST} (from safelint.rules.ALL_RULES)")


# MkDocs ``hooks:`` entry point - same logic, fires on every ``mkdocs build`` /
# ``mkdocs serve`` so local previews don't need a manual prep step.
def on_pre_build(config: object, **_: object) -> None:  # noqa: ARG001
    main()


def on_page_markdown(markdown: str, page: object, **_: object) -> str:
    """Honour ``edit_url`` in page frontmatter - MkDocs core ignores it.

    ``mkdocs.structure.pages.Page._set_edit_url`` derives every page's
    edit link purely from ``repo_url + edit_uri + src_path``; it does
    not consult ``page.meta``. For pages that exist only in the build
    tree (the gitignored copies of CHANGELOG / CONTRIBUTING /
    CODE_OF_CONDUCT / SUPPORT) the auto-derived link 404s, so this
    hook copies any frontmatter ``edit_url:`` value across to the
    runtime ``page.edit_url`` attribute that Material's template reads.
    """
    edit_url = getattr(page, "meta", {}).get("edit_url")
    if edit_url:
        page.edit_url = edit_url  # type: ignore[attr-defined]
    return markdown


if __name__ == "__main__":
    main()
