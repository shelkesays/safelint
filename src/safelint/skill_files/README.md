# SafeLint AI-client skill

A bundled skill / project-rule that lets fourteen AI clients (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed, Warp, Kiro) run `safelint` against the current project and present the violations in a reviewable format. The instructions are language-agnostic; per-language addendums sit alongside under `languages/`, currently Python, JavaScript, TypeScript, Java, Rust, Go, PHP, C, and C++ (mirroring safelint's `src/safelint/languages/` package layout).

> **For the comprehensive user guide** (auto-detection logic, per-client setup, troubleshooting, adding a new client) see the [AI client integrations](https://shelkesays.github.io/safelint/ai-clients/) docs. The README you're reading is the in-wheel reference; it covers the install command surface and the layout of the bundled files. The full guide lives on the docs site.

Fourteen clients ship today; all follow the *same* workflow because safelint's CLI surface is the same:

- **Claude Code**: installs as a single skill manifest at `~/.claude/skills/safelint/SKILL.md` (or `<cwd>/.claude/skills/safelint/SKILL.md` for project scope). Language-specific addendums are looked up on demand via `safelint skill path`, same as the other clients.
- **Cursor**: installs as a single MDC project rule at `.cursor/rules/safelint.mdc` (or `~/.cursor/rules/safelint.mdc` for user-global).
- **GitHub Copilot**: installs as a Markdown instructions file at `.github/copilot-instructions.md` (or `~/.github/copilot-instructions.md` for user-global).
- **Gemini**: installs as a Markdown instructions file at `<cwd>/GEMINI.md` (canonical, auto-discovered by Gemini CLI) or `~/GEMINI.md` (user-global; requires Gemini CLI config).
- **Windsurf**: installs as a project rules file at `<cwd>/.windsurfrules` (canonical, auto-loaded by Windsurf) or `~/.windsurfrules` (user-global; merged with project rules at runtime).
- **codex**: installs the primary instructions at `.codex/instructions.md` and *also* writes a delimited HTML-comment section into `AGENTS.md` when that cross-agent shared file already exists at the scope root. Other content in `AGENTS.md` is preserved. **OpenCode (`sst/opencode`)** projects auto-detect into this same spec because OpenCode reads `AGENTS.md` for project context; `.opencode/` is in the codex spec's marker set, so an OpenCode-only project transparently gets the safelint section without naming codex explicitly.
- **Continue.dev**: installs as a Markdown rule at `<cwd>/.continue/rules/safelint.md` (canonical, auto-loaded) or `~/.continue/rules/safelint.md` (user-global; loaded across workspaces).
- **Cline**: installs as a Markdown rule at `<cwd>/.clinerules/safelint.md` (canonical, auto-loaded) or `~/.clinerules/safelint.md` (user-global).
- **aider**: installs as `<cwd>/CONVENTIONS.md` or `~/CONVENTIONS.md`. **Not auto-loaded** ;  wire it in by adding `read: [CONVENTIONS.md]` to your `.aider.conf.yml`.
- **Trae**: installs as a Markdown rule at `<cwd>/.trae/rules/safelint.md` (canonical, auto-loaded) or `~/.trae/rules/safelint.md` (user-global).
- **Antigravity**: installs as a Markdown rule at `<cwd>/.antigravity/rules/safelint.md` (canonical, auto-loaded) or `~/.antigravity/rules/safelint.md` (user-global).
- **Zed**: installs as workspace rules at `<cwd>/.rules` (canonical, auto-loaded) or `~/.rules` (user-global).
- **Warp**: project-scope only. Installs as a Markdown instructions file at `<cwd>/WARP.md` (auto-discovered by Warp's AI). Warp does **not** read any user-scope filesystem file; cross-project rules are managed through the Warp Drive UI (Personal > Rules) instead, so `safelint skill install --client warp` requires `--project`.
- **Kiro**: installs as a steering file at `<cwd>/.kiro/steering/safelint.md` (canonical, auto-loaded for every interaction) or `~/.kiro/steering/safelint.md` (user-global, across all projects). Kiro also honours the `AGENTS.md` standard as a fallback, but safelint installs to its first-class steering file rather than coupling on the shared `AGENTS.md` (owned by the codex client).

Once installed, ask the agent things like:

- "run safelint"
- "lint my changes with safelint"
- "do a Power-of-Ten review on src/api/auth.py"
- "safelint check, all files"

…and the skill takes over: invokes `safelint check ... --format json`, parses the output, groups violations by file (and by language when more than one is involved), and offers to walk through fixes.

## Install

```bash
# Pick the extra matching your project's language(s): v2.0.0+ ships
# each grammar separately. See the project README for the full table.
pip install 'safelint[python]'            # or: uv add 'safelint[python]'
# pip install 'safelint[javascript]'      # JS / Node
# pip install 'safelint[typescript]'      # TypeScript (bundles JS too)
# pip install 'safelint[all]'             # kitchen-sink
safelint skill install                    # auto-detects which AI client(s) you use
```

`safelint skill install` does **two** auto-detections in one shot:

1. **Which AI client(s) you use**, looks for marker files (`CLAUDE.md`, `.cursor/`, `.github/copilot-instructions.md`, etc.) and installs the skill files into each detected client's config dir.
2. **Which language grammar(s) your project needs**, walks the project for source-file extensions, compares against installed extras, and if any grammars are missing it emits one composed install line:
   ```text
   safelint: warning: Detected source files for 2 languages (python, typescript) whose tree-sitter grammar isn't installed. Run: pip install 'safelint[python,typescript]'
   ```
   You run the single composed `pip install` command and you're set up for every language in your repo.

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
safelint skill install --client claude --project    # <cwd>/.claude/skills/safelint/SKILL.md

# Cursor
safelint skill install --client cursor              # ~/.cursor/rules/safelint.mdc (user)
safelint skill install --client cursor --project    # <cwd>/.cursor/rules/safelint.mdc

# GitHub Copilot
safelint skill install --client copilot             # ~/.github/copilot-instructions.md (user-global; requires VS Code config to be auto-read)
safelint skill install --client copilot --project   # <cwd>/.github/copilot-instructions.md (canonical Copilot location)

# Gemini
safelint skill install --client gemini --project    # <cwd>/GEMINI.md (canonical, auto-discovered by Gemini CLI)
safelint skill install --client gemini              # ~/GEMINI.md (user-global; requires Gemini CLI config)

# Windsurf
safelint skill install --client windsurf --project  # <cwd>/.windsurfrules (canonical, auto-loaded)
safelint skill install --client windsurf            # ~/.windsurfrules (user-global; merged with project rules)

# codex (also injects section into AGENTS.md when present)
safelint skill install --client codex --project     # <cwd>/.codex/instructions.md + AGENTS.md section if AGENTS.md exists
safelint skill install --client codex               # ~/.codex/instructions.md

# Continue.dev
safelint skill install --client continue --project  # <cwd>/.continue/rules/safelint.md (auto-loaded)
safelint skill install --client continue            # ~/.continue/rules/safelint.md (user-global)

# Cline
safelint skill install --client cline --project     # <cwd>/.clinerules/safelint.md (auto-loaded)
safelint skill install --client cline               # ~/.clinerules/safelint.md (user-global)

# aider (then wire `read: [CONVENTIONS.md]` into .aider.conf.yml)
safelint skill install --client aider --project     # <cwd>/CONVENTIONS.md
safelint skill install --client aider               # ~/CONVENTIONS.md

# Trae
safelint skill install --client trae --project      # <cwd>/.trae/rules/safelint.md (auto-loaded)
safelint skill install --client trae                # ~/.trae/rules/safelint.md (user-global)

# Antigravity
safelint skill install --client antigravity --project  # <cwd>/.antigravity/rules/safelint.md (auto-loaded)
safelint skill install --client antigravity            # ~/.antigravity/rules/safelint.md (user-global)

# Zed
safelint skill install --client zed --project       # <cwd>/.rules (auto-loaded)
safelint skill install --client zed                 # ~/.rules (user-global)

# Warp (project-scope only; --project is required - Warp has no user-scope file)
safelint skill install --client warp --project      # <cwd>/WARP.md (auto-discovered)

# Kiro
safelint skill install --client kiro --project      # <cwd>/.kiro/steering/safelint.md (auto-loaded)
safelint skill install --client kiro                # ~/.kiro/steering/safelint.md (user-global)
```

### Options

| Flag | Effect |
|---|---|
| `--client` | Target AI client: `auto` (default, detect from cwd, then home), or one of: `claude`, `cursor`, `copilot`, `gemini`, `windsurf`, `codex`, `continue`, `cline`, `aider`, `trae`, `antigravity`, `zed`, `warp`, `kiro`. New clients added to the registry extend this list automatically. |
| `--project` | Force project scope: install under the current working directory instead of your home directory. The exact path is per-client, often `<cwd>/.<client>/...`, but several clients install a file at the project root (e.g. `GEMINI.md`, `.windsurfrules`, `.rules`, `WARP.md`, `CONVENTIONS.md`). With `--client auto`, restricts detection to cwd and refuses to fall back to home. |
| `--symlink` | Symlink to the bundled location instead of copying. `pip upgrade safelint` then immediately changes what the AI client sees. Requires symlink support (POSIX, or Windows developer mode). |
| `--force` | Replace any existing safelint skill / rule at the target. Use this when re-installing after an upgrade. |

### Examples

```bash
# Auto-detect: install for every AI client this project / user uses
safelint skill install

# Auto-detect, but only inside this project (no home fallback)
safelint skill install --project

# Cursor install committed into a team project
safelint skill install --client cursor --project

# Re-install after upgrading safelint itself
safelint skill install --force

# Skill development (changes to bundled files take effect immediately)
safelint skill install --symlink --force

# Refresh installed skills after pip upgrade (idempotent: no-op when fresh)
safelint skill update

# Force-refresh every install regardless of drift (revert customisations)
safelint skill update --force

# Remove every detected install
safelint skill remove

# Remove only symlink-shape installs, keep copy installs intact
safelint skill remove --symlink

# Preview removal without deleting
safelint skill remove --dry-run

# Remove an unusual install location auto-detect won't see (path tail must match a registered install shape)
safelint skill remove --path /unusual/place/.cursor/rules/safelint.mdc
```

> **Security note:** ``--path PATH`` validates that *PATH*'s tail matches a registered install relpath (e.g. `.cursor/rules/safelint.mdc`, `.codex/instructions.md`) before deleting, so a typo like `--path ~/.config` (intending `--path ~/.cursor/...`) won't ``shutil.rmtree`` the wrong directory. The codex secondary install at `AGENTS.md` also refuses to follow symlinks during install / update / remove, so a symlinked `AGENTS.md` won't be read or written through.

### Where are the bundled files?

```bash
safelint skill path                  # bundle root directory
safelint skill path --client claude  # <bundle>/claude/SKILL.md (file)
safelint skill path --client cursor  # <bundle>/cursor/safelint.mdc (file)
```

Without `--client`, prints the bundle root directory: every client looks up the shared addendums at `<that path>/languages/<lang>.md`. With `--client <name>`, prints that specific client's bundled artefact file path instead - useful for inspecting the source of a particular install or as a `cat` target.

### Is my installed skill up to date?

After `pip install --upgrade safelint`, the bundled files inside the wheel update but your installed skill stays at whatever version was last installed. Two ways to check:

```bash
# Dedicated subcommand: exits 1 if any install differs from the bundled version
safelint skill status

# Or, fold the check into a normal lint run (informational stderr warning, doesn't fail the run)
safelint check --check-skill-freshness --all-files .
```

Pipe-friendly idiom for CI / upgrade scripts:

```bash
safelint skill status || safelint skill update
```

`safelint skill status` exits 0 on a clean run and still prints output: one `safelint: <client> <artefact> at <path> (<scope> scope), fresh` line per detected install plus a final `all detected installs match the bundled version` summary. When something drifts it prints `differs from bundled` for the affected install and a per-install scope-aware refresh command (e.g. `safelint skill update --client cursor --project`); the per-installation hint matters so each diagnostic points at the *exact* install that drifted, even though bare `safelint skill update` will refresh every auto-detected install (project- and user-scope alike) on its own. If you've customised your skill on purpose, ignore the diff, the diagnostic explicitly mentions that case.

## Layout

The skill ships *inside* the safelint Python package, under `safelint/skill_files/`:

```text
src/safelint/skill_files/    # ↑ inside the wheel, located by `safelint skill path`
├── README.md                # This file
├── claude/
│   └── SKILL.md             # Claude Code's skill manifest (installed to .claude/skills/safelint/SKILL.md)
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
├── continue/
│   └── safelint.md          # Continue.dev's rule (installed to .continue/rules/safelint.md)
├── cline/
│   └── safelint.md          # Cline's rule (installed to .clinerules/safelint.md)
├── aider/
│   └── CONVENTIONS.md       # aider's conventions (installed to CONVENTIONS.md; wire via read: in .aider.conf.yml)
├── trae/
│   └── safelint.md          # Trae's rule (installed to .trae/rules/safelint.md)
├── antigravity/
│   └── safelint.md          # Antigravity's rule (installed to .antigravity/rules/safelint.md)
├── zed/
│   └── safelint.md          # Zed's workspace rules (installed to .rules at scope root)
├── warp/
│   └── WARP.md              # Warp's instructions (installed to WARP.md at scope root; project-scope only)
├── kiro/
│   └── safelint.md          # Kiro's steering file (installed to .kiro/steering/safelint.md)
└── languages/               # One addendum per supported language
    ├── python.md            # Python-specific install / rationale / idiomatic fixes
    ├── javascript.md        # JavaScript (Node), runtime presets, JS-rule notes
    ├── typescript.md        # TypeScript / TSX / AssemblyScript, TS-specific rule handling
    ├── java.md              # Java + Spring Boot framework preset, Java-rule notes, SAFE901-904
    ├── rust.md              # Rust-specific rules and Holzmann-inspired additions
    ├── go.md                # Go-specific rules (SAFE209 / SAFE211) and idiomatic adaptations
    ├── php.md               # PHP-specific rules (global keyword, superglobal taint, @ suppression) and idiomatic adaptations
    ├── c.md                 # C-specific rules (SAFE106 / SAFE310-313 - the Power-of-Ten homecoming) and idiomatic adaptations
    └── cpp.md               # C++-specific rules (SAFE315 / SAFE316 + the C family widened) and idiomatic adaptations
```

**What ends up where after install:**

- Every client copies exactly one bundled file to the install destination, e.g. Claude Code copies `claude/SKILL.md` to `.claude/skills/safelint/SKILL.md`; Cursor copies `cursor/safelint.mdc` to `.cursor/rules/safelint.mdc`; Windsurf copies `windsurf/safelint-rules.md` to `.windsurfrules` (renamed at the destination); Zed copies `zed/safelint.md` to `.rules` (renamed); the rest follow the same one-file-in, one-file-out pattern.
- codex is the one client that touches *two* destinations: the primary `.codex/instructions.md` and a delimited section inside `AGENTS.md` when that file already exists at the scope root.

All clients can locate the bundled language addendums via `safelint skill path` if they need them at runtime.

The `languages/` subdirectory mirrors `src/safelint/languages/` in the safelint source tree. Each language safelint can lint has a corresponding addendum file here.

## Requirements

- `safelint` 2.0.0 or later on `PATH`. Notable history:
  - `safelint skill install` and the bundled skill files were added in **v1.6.0**.
  - `--client cursor` (Cursor support) and the auto-detection default for `--client` arrived in **v1.8.0**.
  - `safelint skill status` and `safelint check --check-skill-freshness` (drift detection between bundled and installed skills) arrived in **v1.9.0**.
  - JavaScript (Node) support and runtime presets landed in **v1.13.0**.
  - **v2.0.0rc1** ships language grammars as opt-in extras (`[python]` / `[javascript]` / `[typescript]` / `[all]`), adds TypeScript / TSX / AssemblyScript, adds the silent-failure exit-code-2 guard, and teaches `safelint skill install` to auto-detect project languages. The bundled skill files in this directory document the v2.0.0+ install story, so a 1.x-era `safelint` on `PATH` won't behave the way the skills describe, bump first.
- A project with at least one source file in a language safelint supports (Python, JavaScript, TypeScript, Java, Rust, Go, PHP, C, or C++ today).

## What the skill does

1. Verifies `safelint` is installed (cross-platform: `safelint --version`, falling back to a `shutil.which` Python check).
2. Identifies the language(s) in the project against the registry in `claude/SKILL.md` Step 2 (or the equivalent step in the peer client's own file).
3. Picks a target based on what you said (modified files / all files / a specific path).
4. Runs `safelint check <target>... --format json` (one or more paths) and parses the result.
5. Optionally reads `languages/<lang>.md` for deeper language-specific guidance (idiomatic fixes, rule rationale tweaks).
6. Prints a one-line headline plus a per-file (and per-language, if multi-language) breakdown.
7. Offers a single concrete next step.

The skill never auto-fixes, every edit goes through a confirmation step.

## What the skill does NOT do

- It does not replace `ruff` / `ty` / `mypy` / `eslint` / `clippy` / etc. Those handle style and types in their respective languages; safelint enforces a different, narrower set of safety rules. Use both.
- It does not run `safelint --all-files` by default. Git-modified files only, unless you ask.
- It does not invent violations or guess at intent. Everything it reports comes from the JSON output.
- It does not assume Python idioms when fixing other-language code. For language-specific fix patterns it consults the matching `languages/<lang>.md`.

## Adding a new language

When safelint adds support for a new language, the skill needs a matching addendum. The workflow:

1. **In safelint itself**, follow the [Adding a new language](https://shelkesays.github.io/safelint/contributing/adding-a-language/) guide. Register the language in `src/safelint/languages/__init__.py`, add the parser factory, expose node-type constants.
2. **In this skill**, create `languages/<lang>.md` modelled on `languages/python.md`. Cover at minimum:
   - Install nuance specific to that ecosystem (if any).
   - File extensions safelint will pick up.
   - Language-specific phrasing for the universal rule rationales (how `bare_except` translates to that language's catch-all idiom, what counts toward `nesting_depth`, etc.).
   - Idiomatic fix patterns for the rules most likely to fire in that language.
3. **In every per-client core file** (`claude/SKILL.md` plus each peer-client file under `<client>/`), add a row to the **Step 2** language registry table pointing at your new addendum.

Keep the skill core language-neutral. Per-language detail belongs in the addendum. If you find yourself adding a language-specific paragraph to the core, that's a signal it should be in the addendum instead.

## Customising

The skill is just Markdown. Edit `claude/SKILL.md` (or the peer client's own file under `<client>/`) at the install destination to tune wording, swap the suggested follow-up question, or add project-specific guidance (e.g. "for this repo, always pass `--mode ci`"). The agent re-reads the file on each invocation.

## See also

- **AI client integrations guide:** [AI client integrations](https://shelkesays.github.io/safelint/ai-clients/), the comprehensive user doc (auto-detection, per-client setup, troubleshooting)
- **Adding a new AI client:** [Adding a new AI client](https://shelkesays.github.io/safelint/contributing/adding-an-ai-client/), contributor walkthrough for shipping a new client integration
- The main safelint docs: [README](https://github.com/shelkesays/safelint/blob/main/README.md), [Configuration reference](https://shelkesays.github.io/safelint/configuration/)
- JSON output schema: [JSON output schema](https://shelkesays.github.io/safelint/json-schema/)
- Adding a new language to safelint: [Adding a new language](https://shelkesays.github.io/safelint/contributing/adding-a-language/)
