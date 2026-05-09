# Windsurf

**Markers:** `.windsurfrules` or `.codeium/` in the project root for project-scope; `~/.codeium/` for user-scope.

**Install location:**

- User-scoped: `~/.windsurfrules` — Windsurf merges user-global rules with workspace rules when both exist.
- Project-scoped: `<cwd>/.windsurfrules` — Windsurf's canonical workspace rules file, auto-loaded. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Reload Windsurf (or restart the editor). The rules are auto-loaded from `.windsurfrules`. Then ask Windsurf *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client windsurf --project   # canonical, auto-loaded
safelint skill install --client windsurf             # user-global, merged with workspace rules
```

See [Manual install](../manual-install.md) for the full flag reference.
