# SafeLint AI-client skill

A bundled skill / project-rule that lets AI clients (Claude Code, Cursor) run `safelint` against the current project and present the violations in a reviewable format. Language-agnostic core with per-language addendums — mirrors safelint's `src/safelint/languages/` package layout.

Two clients are supported today; both follow the *same* workflow because safelint's CLI surface is the same:

- **Claude Code** — installs as a directory skill at `~/.claude/skills/safelint/` containing `SKILL.md` + `languages/`.
- **Cursor** — installs as a single MDC project rule at `.cursor/rules/safelint.mdc` (or `~/.cursor/rules/safelint.mdc` for user-global).

Once installed, ask the agent things like:

- "run safelint"
- "lint my changes with safelint"
- "do a Power-of-Ten review on src/api/auth.py"
- "safelint check, all files"

…and the skill takes over: invokes `safelint check ... --format json`, parses the output, groups violations by file (and by language when more than one is involved), and offers to walk through fixes.

## Install

```bash
pip install safelint              # or: uv add safelint

# Claude Code (default)
safelint skill install            # ~/.claude/skills/safelint/ (user)
safelint skill install --project  # <cwd>/.claude/skills/safelint/

# Cursor
safelint skill install --client cursor             # ~/.cursor/rules/safelint.mdc (user)
safelint skill install --client cursor --project   # <cwd>/.cursor/rules/safelint.mdc
```

Restart the AI client (or reload its window) to pick up the new skill / rule.

### Options

| Flag | Effect |
|---|---|
| `--client` | Target AI client: `claude` (default — Claude Code skill directory) or `cursor` (single MDC project rule). |
| `--project` | Install into the current project (`<cwd>/.claude/skills/safelint` or `<cwd>/.cursor/rules/safelint.mdc`) instead of the user-global location. Useful for team-shared overrides committed to the repo. |
| `--symlink` | Symlink to the bundled location instead of copying. `pip upgrade safelint` then immediately changes what the AI client sees. Requires symlink support (POSIX, or Windows developer mode). |
| `--force` | Replace any existing safelint skill / rule at the target. Use this when re-installing after an upgrade. |

### Examples

```bash
# User-global Claude install (most common)
safelint skill install

# Cursor install committed into a team project (recommended for Cursor)
safelint skill install --client cursor --project

# Re-install after upgrading safelint itself
safelint skill install --force

# Skill development (changes to bundled files take effect immediately)
safelint skill install --symlink --force
```

### Where are the bundled files?

```bash
safelint skill path                  # Claude skill directory (default)
safelint skill path --client cursor  # Cursor MDC file path
```

Prints the on-disk location of the skill files inside your active safelint install. Useful for inspecting `SKILL.md` / `safelint.mdc` directly, or for debugging install issues.

## Layout

The skill ships *inside* the safelint Python package, under `safelint/skill_files/`:

```text
src/safelint/skill_files/    # ↑ inside the wheel, located by `safelint skill path`
├── SKILL.md                 # Language-agnostic core (the entry point Claude Code reads)
├── README.md                # This file
├── cursor/
│   └── safelint.mdc         # Cursor's native project-rule format (installed to .cursor/rules/)
└── languages/               # One addendum per supported language
    └── python.md            # Python-specific install / rationale / idiomatic fixes
```

The Claude install copies `SKILL.md` + `languages/` (the `cursor/` subdirectory is excluded — peer-client bundle). The Cursor install copies just `cursor/safelint.mdc`. Both clients can locate the language addendums via `safelint skill path` if they need them.

The `languages/` subdirectory mirrors `src/safelint/languages/` in the safelint source tree. Each language safelint can lint has a corresponding addendum file here.

## Requirements

- `safelint` 1.8.0 or later on `PATH`. The `safelint skill install` subcommand and bundled skill files arrived in v1.6.0; the `--client cursor` flag for installing into Cursor (and the `safelint skill path --client cursor` form) was added in v1.8.0, so this README's full instructions assume 1.8.0+.
- A project with at least one source file in a language safelint supports (currently Python).

## What the skill does

1. Verifies `safelint` is installed (cross-platform: `safelint --version`, falling back to a `shutil.which` Python check).
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
