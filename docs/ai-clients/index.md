# AI client integrations

SafeLint ships skills / project rules for AI coding clients so you can ask the agent things like *"run safelint"*, *"lint my changes"*, or *"do a Power-of-Ten review on src/api/auth.py"* and have it invoke `safelint check` correctly, parse the JSON output, and present the violations in a reviewable format.

## Quick start

```bash
# Pick the extra matching your project's language(s) — v2.0.0+
# ships each grammar separately:
pip install 'safelint[python]'        # or: uv add 'safelint[python]'
# pip install 'safelint[javascript]'  # JS / Node
# pip install 'safelint[typescript]'  # TypeScript (bundles JS too)
# pip install 'safelint[all]'         # kitchen-sink

safelint skill install                # auto-detects AI clients AND language grammars
```

`safelint skill install` runs **two** auto-detections back-to-back:

1. **AI clients** — looks for markers (`CLAUDE.md`, `.cursor/`, `.github/copilot-instructions.md`, etc.) in the current directory or your home directory, then installs each detected client's skill at the matching scope.
2. **Language grammars** *(new in v2.0.0rc1)* — walks the project tree for source-file extensions, compares against the extras currently installed, and emits one composed install line if any grammars are missing. Example output for a Python + TypeScript monorepo with neither grammar installed:

   ```text
   safelint: warning: Detected source files for 2 languages (python, typescript) whose tree-sitter grammar isn't installed. Run: pip install 'safelint[python,typescript]'
   ```

   You run the single composed command and you're set up for every language in the repo. Silent when every needed grammar is already installed.

After install, restart the AI client (or reload its window) and ask things like *"run safelint"*.

## Supported clients

| Client | Native format | Install destination | Detection markers |
|---|---|---|---|
| **[Claude Code](clients/claude-code.md)** | Skill directory (`SKILL.md` + `languages/`) | `~/.claude/skills/safelint/` (user) or `<cwd>/.claude/skills/safelint/` (project) | `CLAUDE.md`, `.claude/`, or `.claude.json` in cwd; `~/.claude/` or `~/.claude.json` for user-scope |
| **[Cursor](clients/cursor.md)** | Project Rule (`.mdc` file) | `~/.cursor/rules/safelint.mdc` (user) or `<cwd>/.cursor/rules/safelint.mdc` (project) | `.cursor/` or `.cursorrules` in cwd; `~/.cursor/` for user-scope |
| **[GitHub Copilot](clients/github-copilot.md)** | Instructions Markdown | `~/.github/copilot-instructions.md` (user-global) or `<cwd>/.github/copilot-instructions.md` (project — canonical) | `.github/copilot-instructions.md`, `.github/copilot/`, or `.github/instructions/` in cwd; `~/.github/copilot-instructions.md` for user-scope |
| **[Gemini](clients/gemini.md)** | Instructions Markdown (`GEMINI.md`) | `~/GEMINI.md` (user-global) or `<cwd>/GEMINI.md` (project — canonical, auto-discovered by Gemini CLI) | `GEMINI.md` or `.gemini/` in cwd; `~/.gemini/` for user-scope |
| **[Windsurf](clients/windsurf.md)** | Project rules (`.windsurfrules`) | `~/.windsurfrules` (user-global) or `<cwd>/.windsurfrules` (project — canonical, auto-loaded by Windsurf) | `.windsurfrules` or `.codeium/` in cwd; `~/.codeium/` for user-scope |
| **[codex](clients/codex.md)** | Markdown instructions (`.codex/instructions.md`); also writes a delimited section into `AGENTS.md` when present | `~/.codex/instructions.md` (user) or `<cwd>/.codex/instructions.md` (project) — plus `<scope>/AGENTS.md` (section-only edit) when that file already exists | `.codex/` or `AGENTS.md` in cwd; `~/.codex/` for user-scope |
| **[Continue.dev](clients/continue-dev.md)** | Markdown rule (`.continue/rules/<name>.md`) | `~/.continue/rules/safelint.md` (user) or `<cwd>/.continue/rules/safelint.md` (project) | `.continue/`, `.continuerc`, or `.continuerc.json` in cwd; `~/.continue/` for user-scope |
| **[Cline](clients/cline.md)** | Markdown rule (`.clinerules/<name>.md`) | `~/.clinerules/safelint.md` (user) or `<cwd>/.clinerules/safelint.md` (project) | `.clinerules/` in cwd; `~/.clinerules/` for user-scope |
| **[aider](clients/aider.md)** | Markdown conventions (`CONVENTIONS.md`) — **not auto-loaded**; wire via `read:` in `.aider.conf.yml` | `~/CONVENTIONS.md` (user) or `<cwd>/CONVENTIONS.md` (project) | `.aider.conf.yml`, `.aider.conf.yaml`, or `CONVENTIONS.md` in cwd; `~/.aider.conf.{yml,yaml}` for user-scope |
| **[Trae](clients/trae.md)** | Markdown rule (`.trae/rules/<name>.md`) | `~/.trae/rules/safelint.md` (user) or `<cwd>/.trae/rules/safelint.md` (project) | `.trae/` in cwd; `~/.trae/` for user-scope |
| **[Antigravity](clients/antigravity.md)** | Markdown rule (`.antigravity/rules/<name>.md`) | `~/.antigravity/rules/safelint.md` (user) or `<cwd>/.antigravity/rules/safelint.md` (project) | `.antigravity/` in cwd; `~/.antigravity/` for user-scope |
| **[Zed](clients/zed.md)** | Workspace rules (`.rules`) | `~/.rules` (user) or `<cwd>/.rules` (project) | `.rules` or `.zed/` in cwd; `~/.rules` or `~/.zed/` for user-scope |

The registry in `_skill_install.py` is open-ended — adding a new client is a one-`ClientSpec` change. See [Adding a new AI client](../contributing/adding-an-ai-client.md) for the full walkthrough. If you'd like to see another client supported, file a feature request with the marker convention you've seen in the wild.

## How auto-detection works

`safelint skill install` (no `--client`) is `--client auto` under the hood. The detection is two-tier:

```text
[1] cwd has any client markers?
       │
       ├── yes ──→  install for each detected client, project-scoped
       │
       └── no
              │
              ▼
   [2] home has any client markers?
       │
       ├── yes ──→  install for each detected client, user-scoped
       │
       └── no  ──→  error: print explicit --client commands and exit 1
```

### Multi-detection

If multiple clients are present, **all** of them are installed in the same run. The output prints the detected clients and a per-client success block:

```text
safelint: detected Claude Code (CLAUDE.md) and Cursor (.cursor) in current directory
safelint: Claude Code skill copied to /repo/.claude/skills/safelint (project scope)
  → Restart Claude Code (or open a new session) to pick up the skill.
  → Then ask Claude Code "run safelint" or "lint with safelint".
safelint: Cursor rule copied to /repo/.cursor/rules/safelint.mdc (project scope)
  → Restart Cursor (or reload the window) to pick up the new rule.
  → Then ask Cursor "run safelint" or "lint with safelint".
```

### `--project` flag with auto

`--client auto --project` restricts detection to the current directory only — no home fallback. Useful when you want to commit the skill into your repo but don't want a surprise install at the home location if the cwd happens to have no markers yet.

## Lifecycle and scope

The dedicated topic pages cover everything past first-time install:

- **[Manual install (`--client`)](manual-install.md)** — every client × every scope, copy-pasteable.
- **[Project vs user scope + symlink mode](scope.md)** — when each scope makes sense; symlink mode for the developer loop.
- **[Updating, removing, freshness checks](lifecycle.md)** — `safelint skill update`, `remove`, `status` and the flag combinations.
- **[Troubleshooting](troubleshooting.md)** — auto-detect failures, "target already exists", clients not picking up the install.

## See also

- **[Adding a new AI client](../contributing/adding-an-ai-client.md)** — contributor guide for adding a new AI client to the registry.
- **[Configuration](../configuration/index.md)** — `safelint check` flags and config-file format.
- **[JSON output schema](../json-schema.md)** — the JSON output schema both bundled skills tell the agent to parse.
- **[`src/safelint/skill_files/README.md`](https://github.com/shelkesays/safelint/blob/main/src/safelint/skill_files/README.md)** — the README that ships *inside* the wheel (shorter, install-focused reference).
- **[Adding a new language](../contributing/adding-a-language.md)** — adding a new language to safelint itself (a different kind of extension).
