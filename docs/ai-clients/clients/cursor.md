# Cursor

**Markers:** `.cursor/` or `.cursorrules` in the project root for project-scope; `~/.cursor/` for user-scope.

**Install location:**

- User-scoped: `~/.cursor/rules/safelint.mdc` (a single MDC project rule)
- Project-scoped: `<cwd>/.cursor/rules/safelint.mdc` (recommended for team-shared repos, commit the file)

**How to invoke after install:**

Restart Cursor (or reload the window). The MDC rule is auto-loaded as a Project Rule. Then ask the Cursor agent the same prompts as for Claude Code (*"run safelint"*, *"lint my changes"*, etc.).

The MDC bundles the same step-by-step workflow as the Claude `claude/SKILL.md` (and every other client's own file). All clients run `safelint check ... --format json` and present the result the same way; only the file format differs.

**Manual install:**

```bash
safelint skill install --client cursor            # user-scoped
safelint skill install --client cursor --project  # project-scoped
```

See [Manual install](../manual-install.md) for the full flag reference.
