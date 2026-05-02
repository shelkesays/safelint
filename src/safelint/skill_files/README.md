# safelint Claude Code skill

A Claude Code skill that runs `safelint` against the current project and presents the violations in a reviewable format. Language-agnostic core with per-language addendums — mirrors safelint's `src/safelint/languages/` package layout.

Once installed, ask Claude Code things like:

- "run safelint"
- "lint my changes with safelint"
- "do a Power-of-Ten review on src/api/auth.py"
- "safelint check, all files"

…and the skill takes over: invokes `safelint check ... --format json`, parses the output, groups violations by file (and by language when more than one is involved), and offers to walk through fixes.

## Install

```bash
pip install safelint              # or: uv add safelint
safelint skill install            # copies the skill to ~/.claude/skills/safelint/
```

Restart Claude Code (or open a new session) to pick up the skill.

### Options

| Flag | Effect |
|---|---|
| (no flags) | Copy the bundled skill into `~/.claude/skills/safelint/`. Default. Stable across `pip upgrade safelint` runs — re-run `safelint skill install --force` to pick up newer skill content. |
| `--project` | Install into `<cwd>/.claude/skills/safelint/` instead of the user-global location. Activates the skill only inside this project — useful for team-shared overrides. |
| `--symlink` | Symlink to the bundled location instead of copying. `pip upgrade safelint` then immediately changes what Claude Code sees. Requires symlink support (POSIX, or Windows developer mode). |
| `--force` | Replace any existing `safelint/` skill at the target. Use this when re-installing after an upgrade. |

### Examples

```bash
# User-global (most common)
safelint skill install

# Project-local override (e.g. with project-specific guidance baked into SKILL.md)
safelint skill install --project

# Re-install after upgrading safelint itself
safelint skill install --force

# Skill development (changes to bundled files take effect immediately)
safelint skill install --symlink --force
```

### Where are the bundled files?

```bash
safelint skill path
```

Prints the on-disk location of the skill files inside your active safelint install. Useful for inspecting `SKILL.md` directly, or for debugging install issues.

## Layout

The skill ships *inside* the safelint Python package, under `safelint/skill_files/`:

```
src/safelint/skill_files/    # ↑ inside the wheel, located by `safelint skill path`
├── SKILL.md                 # Language-agnostic core (the entry point Claude reads)
├── README.md                # This file
└── languages/               # One addendum per supported language
    └── python.md            # Python-specific install / rationale / idiomatic fixes
```

The `languages/` subdirectory mirrors `src/safelint/languages/` in the safelint source tree. Each language safelint can lint has a corresponding addendum file here.

## Requirements

- `safelint` 1.6.0 or later on `PATH`. The `safelint skill install` subcommand and bundled skill files were added in v1.6.0.
- A project with at least one source file in a language safelint supports (currently Python).

## What the skill does

1. Verifies `safelint` is installed (`command -v safelint`).
2. Identifies the language(s) in the project against the registry in `SKILL.md` Step 2.
3. Picks a target based on what you said (modified files / all files / a specific path).
4. Runs `safelint check <target> --format json` and parses the result.
5. Optionally reads `languages/<lang>.md` for deeper language-specific guidance (idiomatic fixes, rule rationale tweaks).
6. Prints a one-line headline plus a per-file (and per-language, if multi-language) breakdown.
7. Offers a single concrete next step.

The skill never auto-fixes — every edit goes through a confirmation step.

## What the skill does NOT do

- It does not replace `ruff` / `ty` / `mypy` / `eslint` / `clippy` / etc. Those handle style and types in their respective languages; safelint enforces a different, narrower set of safety rules. Use both.
- It does not run `safelint --all-files` by default. Git-modified files only, unless you ask.
- It does not invent violations or guess at intent. Everything it reports comes from the JSON output.
- It does not assume Python idioms when fixing other-language code. For language-specific fix patterns it consults the matching `languages/<lang>.md`.

## Adding a new language

When safelint adds support for a new language, the skill needs a matching addendum. The workflow:

1. **In safelint itself** — follow [`ADDING_A_LANGUAGE.md`](../../ADDING_A_LANGUAGE.md). Register the language in `src/safelint/languages/__init__.py`, add the parser factory, expose node-type constants.
2. **In this skill** — create `languages/<lang>.md` modelled on `languages/python.md`. Cover at minimum:
   - Install nuance specific to that ecosystem (if any).
   - File extensions safelint will pick up.
   - Language-specific phrasing for the universal rule rationales (how `bare_except` translates to that language's catch-all idiom, what counts toward `nesting_depth`, etc.).
   - Idiomatic fix patterns for the rules most likely to fire in that language.
3. **In `SKILL.md`** — add a row to the **Step 2** language registry table pointing at your new addendum.

Keep the skill core (`SKILL.md`) language-neutral. Per-language detail belongs in the addendum. If you find yourself adding a language-specific paragraph to the core, that's a signal it should be in the addendum instead.

## Customising

The skill is just Markdown. Edit `SKILL.md` to tune wording, swap the suggested follow-up question, or add project-specific guidance (e.g. "for this repo, always pass `--mode ci`"). Claude Code re-reads the file on each invocation.

## See also

- The main safelint docs: [`README.md`](../../README.md), [`CONFIGURATION.md`](../../CONFIGURATION.md)
- JSON output schema: [`docs/JSON_SCHEMA.md`](../../docs/JSON_SCHEMA.md)
- Adding a new language to safelint: [`ADDING_A_LANGUAGE.md`](../../ADDING_A_LANGUAGE.md)
