# SafeLint AI client integrations

SafeLint ships skills / project rules for AI coding clients so you can ask the agent things like *"run safelint"*, *"lint my changes"*, or *"do a Power-of-Ten review on src/api/auth.py"* and have it invoke `safelint check` correctly, parse the JSON output, and present the violations in a reviewable format. This document covers:

- [Supported clients](#supported-clients)
- [Quick start](#quick-start)
- [How auto-detection works](#how-auto-detection-works)
- [Per-client guides](#per-client-guides)
- [Manual install (`--client`)](#manual-install---client)
- [Project vs user scope](#project-vs-user-scope)
- [Symlink mode (developer loop)](#symlink-mode-developer-loop)
- [Updating after a safelint upgrade](#updating-after-a-safelint-upgrade)
- [Troubleshooting](#troubleshooting)
- [Adding a new AI client (developer guide)](#adding-a-new-ai-client)
- [Roadmap](#roadmap)

## Supported clients

| Client | Native format | Install destination | Detection markers |
|---|---|---|---|
| **Claude Code** | Skill directory (`SKILL.md` + `languages/`) | `~/.claude/skills/safelint/` (user) or `<cwd>/.claude/skills/safelint/` (project) | `CLAUDE.md`, `.claude/`, or `.claude.json` in cwd; `~/.claude/` or `~/.claude.json` for user-scope |
| **Cursor** | Project Rule (`.mdc` file) | `~/.cursor/rules/safelint.mdc` (user) or `<cwd>/.cursor/rules/safelint.mdc` (project) | `.cursor/` or `.cursorrules` in cwd; `~/.cursor/` for user-scope |
| **GitHub Copilot** | Instructions Markdown | `~/.github/copilot-instructions.md` (user-global) or `<cwd>/.github/copilot-instructions.md` (project — canonical) | `.github/copilot-instructions.md`, `.github/copilot/`, or `.github/instructions/` in cwd; `~/.github/copilot-instructions.md` for user-scope |
| **Gemini** | Instructions Markdown (`GEMINI.md`) | `~/GEMINI.md` (user-global) or `<cwd>/GEMINI.md` (project — canonical, auto-discovered by Gemini CLI) | `GEMINI.md` or `.gemini/` in cwd; `~/.gemini/` for user-scope |

More are on the [roadmap](#roadmap). The registry in `src/safelint/_skill_install.py` is open-ended — adding a new client is a one-`ClientSpec` change (see [Adding a new AI client](#adding-a-new-ai-client)).

## Quick start

```bash
pip install safelint            # or: uv add safelint
safelint skill install          # auto-detects which AI client(s) you use
```

That single command:

1. Looks for AI-client markers in the current directory (`CLAUDE.md`, `.cursor/`, etc.).
2. If any are present, installs each detected client's skill **project-scoped** under the current directory.
3. If the current directory has no markers, looks in your home directory (`~/.claude/`, `~/.cursor/`).
4. If found there, installs each detected client's skill **user-scoped** under your home directory.
5. If nothing is found anywhere, prints an explicit error listing the `--client` commands you can run instead.

After install, restart the AI client (or reload its window) and ask things like *"run safelint"*.

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

If both clients are present, **both** are installed in the same run. The output prints the detected clients and a per-client success block:

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

## Per-client guides

### Claude Code

**Markers:** `CLAUDE.md`, `.claude/`, or `.claude.json` in the project root for project-scope; `~/.claude/` or `~/.claude.json` for user-scope. Any one marker is enough — detection picks the first one it finds.

**Install location:**

- User-scoped: `~/.claude/skills/safelint/` (a directory containing `SKILL.md`, `README.md`, `languages/python.md`)
- Project-scoped: `<cwd>/.claude/skills/safelint/` (same layout, just under the repo)

**How to invoke after install:**

Restart Claude Code (or open a new session). The skill registers automatically. Then in any conversation:

- *"run safelint"*
- *"lint my changes with safelint"*
- *"do a Power-of-Ten review on `src/api/auth.py`"*
- *"safelint check, all files"*

The skill takes over: invokes `safelint check ... --format json`, parses the output, groups violations by file (and by language when more than one is involved), and offers to walk through fixes.

### Cursor

**Markers:** `.cursor/` or `.cursorrules` in the project root for project-scope; `~/.cursor/` for user-scope.

**Install location:**

- User-scoped: `~/.cursor/rules/safelint.mdc` (a single MDC project rule)
- Project-scoped: `<cwd>/.cursor/rules/safelint.mdc` (recommended for team-shared repos — commit the file)

**How to invoke after install:**

Restart Cursor (or reload the window). The MDC rule is auto-loaded as a Project Rule. Then ask the Cursor agent the same prompts as for Claude Code (*"run safelint"*, *"lint my changes"*, etc.).

The MDC bundles the same step-by-step workflow as the Claude SKILL.md. Both clients run `safelint check ... --format json` and present the result the same way; only the file format differs.

### GitHub Copilot

**Markers:** `.github/copilot-instructions.md`, `.github/copilot/`, or `.github/instructions/` in the project root for project-scope; `~/.github/copilot-instructions.md` for user-scope. Bare `.github/` alone is **not** a marker — it appears in nearly every repo for GitHub Actions.

**Install location:**

- User-scoped: `~/.github/copilot-instructions.md` — VS Code can be configured to read this via the `github.copilot.chat.codeGeneration.instructions` setting (it isn't auto-discovered like the project file is).
- Project-scoped: `<cwd>/.github/copilot-instructions.md` — Copilot's canonical instructions location, auto-loaded by VS Code's Copilot Chat. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Reload VS Code (or restart Copilot Chat). The instructions file is auto-loaded for the workspace. Then ask Copilot Chat *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**First-time bootstrap note:** Copilot's auto-detection signals (`.github/copilot-instructions.md`, `.github/copilot/`, `.github/instructions/`) only match an *existing* Copilot setup. For first-time installs on a fresh project, pass `--client copilot --project` explicitly.

### Gemini

**Markers:** `GEMINI.md` or `.gemini/` in the project root for project-scope; `~/.gemini/` for user-scope.

**Install location:**

- User-scoped: `~/GEMINI.md` — Gemini CLI does not auto-discover this. Users wanting a global file configure Gemini CLI to read it explicitly (or symlink it where the CLI looks).
- Project-scoped: `<cwd>/GEMINI.md` — Gemini CLI's canonical instructions file, auto-discovered when invoked from the repo. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Restart Gemini CLI (or your IDE's Gemini integration). The `GEMINI.md` file is auto-discovered for the workspace. Then ask Gemini *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

## Manual install (`--client`)

Skip auto-detection by passing an explicit client name:

```bash
# Claude Code, user-scoped
safelint skill install --client claude

# Claude Code, project-scoped
safelint skill install --client claude --project

# Cursor, user-scoped
safelint skill install --client cursor

# Cursor, project-scoped (recommended for team-shared repos)
safelint skill install --client cursor --project

# GitHub Copilot, project-scoped (canonical — auto-loaded by VS Code)
safelint skill install --client copilot --project

# GitHub Copilot, user-global (requires VS Code settings to point at ~/.github/copilot-instructions.md)
safelint skill install --client copilot

# Gemini, project-scoped (canonical — auto-discovered by Gemini CLI)
safelint skill install --client gemini --project

# Gemini, user-global (requires Gemini CLI configuration to point at ~/GEMINI.md)
safelint skill install --client gemini
```

When `--client` is explicit, no detection runs and no detection notice is printed. The install proceeds at the requested scope (default: user; with `--project`: cwd).

## Project vs user scope

| | User scope (default) | Project scope (`--project`) |
|---|---|---|
| **Path** | `~/.<client>/...` | `<cwd>/.<client>/...` |
| **Activation** | Every session, every project | Only inside this project |
| **Best for** | Solo developer, one machine | Team-shared repos (commit the install) |
| **Auto-detect** | Triggered by markers under `~/` | Triggered by markers under `cwd` |

## Symlink mode (developer loop)

`--symlink` links to the bundled location instead of copying. After `pip upgrade safelint`, the skill / rule reflects the new content immediately — no `safelint skill install --force` needed.

```bash
safelint skill install --symlink
safelint skill install --client cursor --symlink
```

For Claude installs, the symlink is **per-entry**: the install creates a real directory at the target and symlinks each top-level entry (`SKILL.md`, `languages/`, etc.) into it. Peer-client subdirectories like `cursor/` are never symlinked into the Claude install — they're for Cursor's own install path.

Caveat: symlink mode requires symlink support — POSIX shells, or Windows with developer mode enabled. If you hit "operation not permitted", drop the `--symlink` flag and use the default copy mode.

## Updating after a safelint upgrade

Copy mode (default) is a snapshot — `pip upgrade safelint` doesn't touch the installed skill until you re-run the install. Two ways to refresh:

```bash
pip install --upgrade safelint
safelint skill update                     # idempotent — no-op if everything is fresh
# or, if you want to force-refresh customised installs back to bundled:
safelint skill update --force
```

`safelint skill update` runs a drift check first and only re-installs the installs that have actually drifted. With `--force`, it re-installs every detected install regardless. Inherits the same `--client` / `--project` / `--symlink` flags as `install`; the only behavioural difference is that **`--client auto` for update detects via install paths, not marker files** — "what's installed?" rather than "what client is the user using?".

Explicit `--client <name>` (e.g. `safelint skill update --client cursor`) is **cross-scope by default** — it refreshes matching installs in *both* the user scope (`~/.cursor/...`, `~/.claude/...`) and the project scope (`<cwd>/.cursor/...`, `<cwd>/.claude/...`). To restrict an explicit-client update to project scope only, pass `--project` as the orthogonal filter (`safelint skill update --client cursor --project`). This mirrors how `skill remove` resolves targets — `--client` selects *which* client, `--project` decides *where to look*.

**Shape preservation:** `update` (with or without `--force`) does **not** convert install modes silently. A symlink-mode install stays a symlink after refresh; a copy-mode install stays a copy. Pass `--symlink` explicitly if you want to *switch* a copy install to symlink mode mid-flight, but note that `--symlink` only takes effect for installs that `update` actually re-installs. If the install is already fresh, use `safelint skill update --force --symlink` to convert copy → symlink; symlink → copy must go through `remove` + `install` to be unambiguous.

For one-shot manual control, prefer the canonical, shape-preserving `skill update` form (this is what `skill update` was added for in v1.10 — the legacy `skill install --force` still works, but it ignores existing-install shape and silently overwrites it, which is rarely what you want for an in-place refresh):

```bash
safelint skill update --force                    # auto-detected clients (install-path detection)
safelint skill update --client cursor --force    # or specific client (cross-scope)
```

Symlink mode picks up changes automatically; no re-install needed unless you want to re-run detection (e.g. after adding a new client to the project).

### Removing an installed skill

```bash
safelint skill remove                     # auto-detect and remove every install
safelint skill remove --client cursor     # only Cursor installs (both shapes)
safelint skill remove --symlink           # only symlink-shape installs (keep copies)
safelint skill remove --project           # only project-scope installs (keep user-scope)
safelint skill remove --path /unusual/place/safelint.mdc   # one specific location
safelint skill remove --dry-run           # preview without deleting
```

`safelint skill remove` mirrors install's auto-detect *for install paths* (not marker files): it scans `~/.claude/skills/safelint/`, `<cwd>/.claude/skills/safelint/`, `~/.cursor/rules/safelint.mdc`, `<cwd>/.cursor/rules/safelint.mdc` and removes whatever exists.

#### What gets removed under each combination

The flags compose orthogonally — `--client` filters to one client, `--project` restricts to project scope, `--symlink` filters to symlink-shape installs. **The absence of a flag means "no filter"**, *not* "only the opposite":

| Invocation | What gets removed |
|---|---|
| `remove` (no flags) | Every detected install — copy + symlink, every client, both scopes |
| `remove --symlink` | Only symlink-shape installs (copy installs survive) |
| `remove --client cursor` | All detected Cursor installs (both shapes, both scopes) |
| `remove --client cursor --symlink` | Only symlink-shape Cursor installs |
| `remove --project` | All detected project-scope installs (user-scope survives) |
| `remove --client cursor --project --symlink` | Only project-scope, symlink-shape Cursor installs |
| `remove --path PATH` | Exactly one location, regardless of every other flag |

In particular, `safelint skill remove` **without `--symlink` removes both shapes** — it's not a "remove copies only" command. The `--symlink` flag is a filter you can opt into when you want to be selective; without it, cleanup is comprehensive.

#### Filesystem-level safety

`remove` only deletes from the install location. The bundled files inside `site-packages/` are never touched, regardless of install mode:

- **Copy install (single file)** — `target.unlink()` deletes the file.
- **Copy install (directory tree)** — `shutil.rmtree(target)` walks and deletes the materialised tree.
- **Symlink install (single file)** — `target.unlink()` deletes the **symlink**, not its bundled target.
- **Symlink install (per-entry directory layout, Claude `--symlink`)** — `shutil.rmtree(target)` removes the directory; inner symlinks are deleted but their targets in the bundled package stay intact.

So you can run `remove` freely without worrying about damaging the wheel — the worst case is "I have to re-run `install` to get the skill back".

#### Other flags

`--path PATH` is the escape hatch for unusual install locations — overrides every other flag, removes exactly that one path, errors on stderr if the path doesn't exist. `--dry-run` previews what would be removed without touching anything; useful for documentation / CI sanity checks before commit. Each line of `--dry-run` output includes the install shape (`copy` or `symlink`) so you know what `remove` would do at that location.

### Checking whether your installed skill is current

Two ways to verify:

```bash
# Dedicated subcommand — pipe-friendly, exits 1 if any install differs
safelint skill status

# Or, opt in to a single-shot check at the start of a normal lint run
safelint check --check-skill-freshness --all-files .
```

`safelint skill status` iterates every registered AI client and both scopes (user / project), reports each detected install location as **fresh** or **differs from bundled**, and exits 0 only when every detected install matches the current bundle. Useful in CI:

```bash
safelint skill status || safelint skill update
```

`safelint check --check-skill-freshness` is the same check folded into a normal lint run — it prints a stderr warning per stale install but **does not** fail the lint (informational only). The flag is opt-in so day-to-day `safelint check` invocations stay fast (no extra FS scan).

Note: customising your installed skill (the bundled `README.md` explicitly invites it) will surface as **differs from bundled** until you re-install. That's expected — the diagnostic message includes "or ignore if you've customised it".

## Troubleshooting

### "could not auto-detect an AI client"

Means neither cwd nor home had any of the registered markers. Either:

1. The AI client isn't installed on this machine — install it first, *then* run `safelint skill install`.
2. You want a specific client regardless of detection — use `--client <name>` explicitly. The error message lists the exact commands.

### "target already exists. Use --force to replace it."

A previous install is in the way. Pass `--force` to replace it. SafeLint refuses to silently overwrite by default to protect against losing a customised skill folder.

### Cursor doesn't seem to pick up the rule

Cursor reads `.cursor/rules/*.mdc` files at window load. After installing, you need to **reload the Cursor window** (Command Palette → "Developer: Reload Window") — the rule isn't hot-reloaded.

### Claude Code doesn't seem to pick up the skill

Same idea — Claude Code loads skills on session start. Open a new conversation or restart the app.

### "I want to inspect the bundled files without installing"

```bash
safelint skill path                  # Claude skill directory
safelint skill path --client cursor  # Cursor MDC file path
```

Useful for `cat $(safelint skill path)/SKILL.md` to see what the agent is reading.

## Adding a new AI client

The supported-clients list is a tuple of `ClientSpec` entries in `src/safelint/_skill_install.py`. Adding a client is a one-spec change plus a bundled artefact and tests — full step-by-step walkthrough (with a worked example, field reference, marker-choosing guidance, test checklist, and submission protocol) lives in **[`ADDING_AN_AI_CLIENT.md`](ADDING_AN_AI_CLIENT.md)**.

In short:

1. Bundle the artefact under `src/safelint/skill_files/<client>/`.
2. Append a `ClientSpec` to `_CLIENT_SPECS` (CLI choices auto-derive from the registry).
3. Update `_PEER_CLIENT_DIRS` if the bundle is a peer of the Claude tree.
4. Add tests mirroring the Cursor / Claude patterns.
5. Update [`AI_CLIENTS.md`](AI_CLIENTS.md) (this file) and [`CHANGELOG.md`](CHANGELOG.md).

## Roadmap

Candidates being tracked for future client support (each adds one `ClientSpec`):

- **GitHub Copilot** — `.github/copilot-instructions.md` style instructions
- **codex** — OpenAI's codex agent, file format TBD
- **windsurf** — `.windsurfrules` / `.codeium/` markers
- **antigravity** — TBD

If you'd find one of these useful, file a feature request with the marker convention you've seen in the wild. The `ClientSpec` design accommodates whatever conventions each tool settles on — we just need a stable description of how the agent finds its rules / skill.

## See also

- [`ADDING_AN_AI_CLIENT.md`](ADDING_AN_AI_CLIENT.md) — contributor guide for adding a new AI client to the registry
- [`README.md`](README.md) — overall safelint documentation
- [`CONFIGURATION.md`](CONFIGURATION.md) — `safelint check` flags and config-file format
- [`docs/JSON_SCHEMA.md`](docs/JSON_SCHEMA.md) — the JSON output schema both bundled skills tell the agent to parse
- [`src/safelint/skill_files/README.md`](src/safelint/skill_files/README.md) — the README that ships *inside* the wheel (shorter, install-focused reference)
- [`ADDING_A_LANGUAGE.md`](ADDING_A_LANGUAGE.md) — adding a new language to safelint itself (a different kind of extension)
