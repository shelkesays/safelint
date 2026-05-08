# SafeLint AI-client skill

A bundled skill / project-rule that lets AI clients (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex; more on the way) run `safelint` against the current project and present the violations in a reviewable format. Language-agnostic core with per-language addendums — mirrors safelint's `src/safelint/languages/` package layout.

> **For the comprehensive user guide** — auto-detection logic, per-client setup, troubleshooting, adding a new client — see [`AI_CLIENTS.md`](../../AI_CLIENTS.md). The README you're reading is the in-wheel reference; it covers the install command surface and the layout of the bundled files. The full guide lives at the repo root.

Six clients ship today; all follow the *same* workflow because safelint's CLI surface is the same:

- **Claude Code** — installs as a directory skill at `~/.claude/skills/safelint/` containing `SKILL.md` + `languages/`.
- **Cursor** — installs as a single MDC project rule at `.cursor/rules/safelint.mdc` (or `~/.cursor/rules/safelint.mdc` for user-global).
- **GitHub Copilot** — installs as a Markdown instructions file at `.github/copilot-instructions.md` (or `~/.github/copilot-instructions.md` for user-global).
- **Gemini** — installs as a Markdown instructions file at `<cwd>/GEMINI.md` (canonical, auto-discovered by Gemini CLI) or `~/GEMINI.md` (user-global; requires Gemini CLI config).
- **Windsurf** — installs as a project rules file at `<cwd>/.windsurfrules` (canonical, auto-loaded by Windsurf) or `~/.windsurfrules` (user-global; merged with project rules at runtime).
- **codex** — installs the primary instructions at `.codex/instructions.md` and *also* writes a delimited HTML-comment section into `AGENTS.md` when that cross-agent shared file already exists at the scope root. Other content in `AGENTS.md` is preserved.

Once installed, ask the agent things like:

- "run safelint"
- "lint my changes with safelint"
- "do a Power-of-Ten review on src/api/auth.py"
- "safelint check, all files"

…and the skill takes over: invokes `safelint check ... --format json`, parses the output, groups violations by file (and by language when more than one is involved), and offers to walk through fixes.

## Install

```bash
pip install safelint            # or: uv add safelint
safelint skill install          # auto-detects which AI client(s) you use
```

By default, `safelint skill install` runs in `--client auto` mode:

1. If your current directory has client markers (e.g. `CLAUDE.md`, `.cursor/`, `.github/copilot-instructions.md`), it installs each detected client's skill **project-scoped**.
2. Otherwise it looks in your home directory and, if found, installs each detected client's skill **user-scoped**.
3. If nothing is found anywhere, it errors out with the exact `--client` commands you can run instead.

Restart the AI client (or reload its window) to pick up the new skill / rule.

### Manual install

Skip auto-detection:

```bash
# Claude Code, user-scoped
safelint skill install --client claude
safelint skill install --client claude --project    # <cwd>/.claude/skills/safelint/

# Cursor
safelint skill install --client cursor              # ~/.cursor/rules/safelint.mdc (user)
safelint skill install --client cursor --project    # <cwd>/.cursor/rules/safelint.mdc

# GitHub Copilot
safelint skill install --client copilot             # ~/.github/copilot-instructions.md (user-global; requires VS Code config to be auto-read)
safelint skill install --client copilot --project   # <cwd>/.github/copilot-instructions.md (canonical Copilot location)

# Gemini
safelint skill install --client gemini --project    # <cwd>/GEMINI.md (canonical — auto-discovered by Gemini CLI)
safelint skill install --client gemini              # ~/GEMINI.md (user-global; requires Gemini CLI config)

# Windsurf
safelint skill install --client windsurf --project  # <cwd>/.windsurfrules (canonical — auto-loaded)
safelint skill install --client windsurf            # ~/.windsurfrules (user-global; merged with project rules)

# codex (also injects section into AGENTS.md when present)
safelint skill install --client codex --project     # <cwd>/.codex/instructions.md + AGENTS.md section if AGENTS.md exists
safelint skill install --client codex               # ~/.codex/instructions.md
```

### Options

| Flag | Effect |
|---|---|
| `--client` | Target AI client: `auto` (default — detect from cwd, then home), `claude`, or `cursor`. New clients added to the registry extend this list automatically. |
| `--project` | Force project scope (`<cwd>/.<client>/...`). With `--client auto`, restricts detection to cwd and refuses to fall back to home. |
| `--symlink` | Symlink to the bundled location instead of copying. `pip upgrade safelint` then immediately changes what the AI client sees. Requires symlink support (POSIX, or Windows developer mode). |
| `--force` | Replace any existing safelint skill / rule at the target. Use this when re-installing after an upgrade. |

### Examples

```bash
# Auto-detect — install for every AI client this project / user uses
safelint skill install

# Auto-detect, but only inside this project (no home fallback)
safelint skill install --project

# Cursor install committed into a team project
safelint skill install --client cursor --project

# Re-install after upgrading safelint itself
safelint skill install --force

# Skill development (changes to bundled files take effect immediately)
safelint skill install --symlink --force

# Refresh installed skills after pip upgrade (idempotent — no-op when fresh)
safelint skill update

# Force-refresh every install regardless of drift (revert customisations)
safelint skill update --force

# Remove every detected install
safelint skill remove

# Remove only symlink-shape installs, keep copy installs intact
safelint skill remove --symlink

# Preview removal without deleting
safelint skill remove --dry-run

# Remove an unusual install location auto-detect won't see
safelint skill remove --path /unusual/place/safelint.mdc
```

### Where are the bundled files?

```bash
safelint skill path                  # Claude skill directory (default)
safelint skill path --client cursor  # Cursor MDC file path
```

Prints the on-disk location of the skill files inside your active safelint install. Useful for inspecting `SKILL.md` / `safelint.mdc` directly, or for debugging install issues.

### Is my installed skill up to date?

After `pip install --upgrade safelint`, the bundled files inside the wheel update but your installed skill stays at whatever version was last installed. Two ways to check:

```bash
# Dedicated subcommand — exits 1 if any install differs from the bundled version
safelint skill status

# Or, fold the check into a normal lint run (informational stderr warning, doesn't fail the run)
safelint check --check-skill-freshness --all-files .
```

Pipe-friendly idiom for CI / upgrade scripts:

```bash
safelint skill status || safelint skill update
```

`safelint skill status` exits 0 on a clean run and still prints output: one `safelint: <client> <artefact> at <path> (<scope> scope) — fresh` line per detected install plus a final `all detected installs match the bundled version` summary. When something drifts it prints `differs from bundled` for the affected install and a per-install scope-aware refresh command (e.g. `safelint skill update --client cursor --project`); the per-installation hint matters so each diagnostic points at the *exact* install that drifted, even though bare `safelint skill update` will refresh every auto-detected install (project- and user-scope alike) on its own. If you've customised your skill on purpose, ignore the diff — the diagnostic explicitly mentions that case.

## Layout

The skill ships *inside* the safelint Python package, under `safelint/skill_files/`:

```text
src/safelint/skill_files/    # ↑ inside the wheel, located by `safelint skill path`
├── SKILL.md                 # Language-agnostic core (the entry point Claude Code reads)
├── README.md                # This file
├── cursor/
│   └── safelint.mdc         # Cursor's native project-rule format (installed to .cursor/rules/)
├── copilot/
│   └── copilot-instructions.md  # GitHub Copilot's instructions file (installed to .github/)
├── gemini/
│   └── GEMINI.md            # Gemini CLI's instructions file (installed to repo root)
├── windsurf/
│   └── safelint-rules.md    # Windsurf's project rules (installed to .windsurfrules at scope root)
├── codex/
│   └── instructions.md      # codex's instructions (installed to .codex/instructions.md; also AGENTS.md when present)
└── languages/               # One addendum per supported language
    └── python.md            # Python-specific install / rationale / idiomatic fixes
```

The Claude install copies `SKILL.md` + `languages/` (the `cursor/`, `copilot/`, `gemini/`, `windsurf/`, and `codex/` subdirectories are excluded — peer-client bundles). The Cursor install copies just `cursor/safelint.mdc`. The Copilot install copies just `copilot/copilot-instructions.md`. The Gemini install copies just `gemini/GEMINI.md`. The Windsurf install copies just `windsurf/safelint-rules.md` (renamed to `.windsurfrules` at the destination). The codex install copies `codex/instructions.md` to `.codex/instructions.md` and additionally writes a delimited section into `AGENTS.md` when that file already exists. All clients can locate the language addendums via `safelint skill path` if they need them.

The `languages/` subdirectory mirrors `src/safelint/languages/` in the safelint source tree. Each language safelint can lint has a corresponding addendum file here.

## Requirements

- `safelint` 1.9.0 or later on `PATH`. Notable history:
  - `safelint skill install` and the bundled skill files were added in **v1.6.0**.
  - `--client cursor` (Cursor support) and the auto-detection default for `--client` arrived in **v1.8.0**.
  - `safelint skill status` and `safelint check --check-skill-freshness` (drift detection between bundled and installed skills) arrived in **v1.9.0**.
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

- **AI client integrations guide:** [`AI_CLIENTS.md`](../../AI_CLIENTS.md) — the comprehensive user doc (auto-detection, per-client setup, troubleshooting)
- **Adding a new AI client:** [`ADDING_AN_AI_CLIENT.md`](../../ADDING_AN_AI_CLIENT.md) — contributor walkthrough for shipping a new client integration
- The main safelint docs: [`README.md`](../../README.md), [`CONFIGURATION.md`](../../CONFIGURATION.md)
- JSON output schema: [`docs/JSON_SCHEMA.md`](../../docs/JSON_SCHEMA.md)
- Adding a new language to safelint: [`ADDING_A_LANGUAGE.md`](../../ADDING_A_LANGUAGE.md)
