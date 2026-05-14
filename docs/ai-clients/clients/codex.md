# codex

**Markers:** `.codex/` or `AGENTS.md` in the project root for project-scope; `~/.codex/` for user-scope. `AGENTS.md` is intentionally a marker because it's the cross-agent shared file convention, its presence is a strong signal codex is in use.

**Install location:**

- Primary (always written): `~/.codex/instructions.md` (user) or `<cwd>/.codex/instructions.md` (project, canonical, auto-discovered by codex).
- Secondary (only when `AGENTS.md` already exists at the scope root): `<scope>/AGENTS.md` gets a delimited HTML-comment section (`safelint:begin` / `safelint:end`) injected. **Other content in `AGENTS.md`, your hand-written notes, instructions for other agents, is preserved untouched.** safelint never auto-creates `AGENTS.md`; the secondary install is opt-in via "the user already has the file".

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
