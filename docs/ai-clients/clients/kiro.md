# Kiro

**Markers:** `.kiro/` in the project root for project-scope; `~/.kiro/` for user-scope.

**Install location:**

- User-scoped: `~/.kiro/steering/safelint.md`, Kiro loads user-global steering files across all projects.
- Project-scoped: `<cwd>/.kiro/steering/safelint.md`, Kiro loads workspace steering files for the active project. **Recommended for team-shared repos, commit the file.**

Kiro auto-discovers every Markdown file under `.kiro/steering/` and loads it for each interaction (default `inclusion: always`); no YAML front matter is needed for the always-on behaviour safelint relies on.

**How to invoke after install:**

Reload Kiro (or restart the IDE). The steering file is auto-loaded from `.kiro/steering/`. Then ask Kiro *"run safelint"* / *"lint with safelint"*, same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client kiro --project   # recommended for team-shared repos
safelint skill install --client kiro             # user-global, loaded across all projects
```

**Note on `AGENTS.md`:** Kiro also honours the `AGENTS.md` standard as a fallback, the same file the [codex](codex.md) client owns. safelint installs to Kiro's first-class `.kiro/steering/safelint.md` rather than coupling on the shared `AGENTS.md`; if your project already drives codex/OpenCode through `AGENTS.md`, Kiro will pick that up too, but the steering file is the canonical, self-contained integration point.

See [Manual install](../manual-install.md) for the full flag reference.
