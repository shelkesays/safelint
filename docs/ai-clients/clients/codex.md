# codex

**Markers:** `.codex/`, `AGENTS.md`, or `.opencode/` in the project root for project-scope; `~/.codex/` for user-scope. `AGENTS.md` is intentionally a marker because it's the cross-agent shared file convention, its presence is a strong signal codex (or another `AGENTS.md`-reading agent) is in use. `.opencode/` covers [OpenCode (`sst/opencode`)](https://github.com/sst/opencode) projects, see the "OpenCode auto-detection" subsection below.

**Install location:**

- Primary (always written): `~/.codex/instructions.md` (user) or `<cwd>/.codex/instructions.md` (project, canonical, auto-discovered by codex).
- Secondary: `<scope>/AGENTS.md` gets a delimited HTML-comment section (`safelint:begin` / `safelint:end`) injected. **Other content in `AGENTS.md`, your hand-written notes, instructions for other agents, is preserved untouched.** The secondary install fires under two conditions:
    1. `AGENTS.md` already exists at the scope root, the section is appended without disturbing existing content.
    2. `.opencode/` is present at the project root and `AGENTS.md` doesn't exist yet, see the OpenCode subsection below for the one exception to the "we don't auto-create the shared file" rule.

**Lifecycle of the secondary section:**

- `install`, writes the section into `AGENTS.md` if the file exists.
- `update`, re-renders the section in place when content drifts (or unchanged when fresh).
- `status`, reports DIFFERS when the section content has drifted from bundled, even if the primary file is fresh.
- `remove`, strips just the section from `AGENTS.md`. Other content is preserved. If `AGENTS.md` ends up empty (only safelint content was ever there), the empty file is removed too.

**Symlink safety:** safelint refuses to follow a symlink at the `AGENTS.md` destination. If your `AGENTS.md` is a symlink (intentional or accidental), `install` / `update` / `remove` skip the secondary write entirely and print a `safelint: warning: refusing to install/remove safelint section through symlink at ...` line on stderr. The primary `.codex/instructions.md` install is unaffected. Replace the symlink with a real file if you want safelint to manage that location directly.

**How to invoke after install:**

Restart codex (or your codex-aware editor). The primary `.codex/instructions.md` is auto-discovered. Then ask codex *"run safelint"* / *"lint with safelint"*, same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client codex --project   # canonical .codex/instructions.md; also injects section into AGENTS.md if present
safelint skill install --client codex             # user-global
```

See [Manual install](../manual-install.md) for the full flag reference.

## OpenCode auto-detection

[OpenCode (`sst/opencode`)](https://github.com/sst/opencode) is a terminal-native open-source AI coding agent that reads `AGENTS.md` for project context, the same shared file codex's secondary install populates. Rather than carrying a separate client entry (whose install destination would also be `AGENTS.md`, creating a duplicate-write hazard), safelint piggybacks on the codex spec: `.opencode/` is one of codex's `cwd_markers`, so `safelint skill install --client=auto` notices these projects and runs the codex install path.

Two practical cases:

| Project state | What gets written | Why |
|---|---|---|
| `.opencode/` present, `AGENTS.md` does **not** exist | `.codex/instructions.md` (primary) + `AGENTS.md` (auto-created with the safelint section as the only content) | OpenCode's only safelint integration point is `AGENTS.md`; without seeding the file the secondary install would be a no-op and OpenCode would receive nothing. The auto-create is gated on `.opencode/` being present so users without OpenCode don't get a spurious file at the project root. |
| `.opencode/` present, `AGENTS.md` **already exists** | `.codex/instructions.md` (primary) + safelint section appended to existing `AGENTS.md` | Normal section-write path. Other agents' content in `AGENTS.md` is preserved. |

`.codex/instructions.md` is created in both cases. OpenCode itself doesn't read it; users on OpenCode-only projects can ignore or gitignore the `.codex/` directory if it bothers them. The actual integration is the safelint section in `AGENTS.md`.

OpenCode users can also invoke the install explicitly without relying on detection:

```bash
safelint skill install --client codex --project   # writes .codex/instructions.md + AGENTS.md section
```

### Note on OpenClaw

[OpenClaw (`openclaw.ai`)](https://openclaw.ai) was evaluated for a similar piggyback treatment but **deliberately not added** to the registry. OpenClaw is a chat-bridge agent (WhatsApp / Slack / Telegram / iMessage / Discord / Signal) whose configuration lives in a global `~/.openclaw/openclaw.json` file (channel allowlists and mention rules); it has no project-level rules / instructions file convention. Until that changes, there's no safelint integration shape that would produce a useful artefact for OpenClaw users.
