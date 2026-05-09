# Zed

**Markers:** `.rules` or `.zed/` in the project root for project-scope; `~/.rules` or `~/.zed/` for user-scope.

**Install location:**

- User-scoped: `~/.rules` — Zed loads user-global agent rules.
- Project-scoped: `<cwd>/.rules` — Zed's canonical workspace rules file. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Reload Zed (or restart the editor). The rules are auto-loaded from `.rules`. Then ask Zed's assistant *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client zed --project   # recommended for team-shared repos
safelint skill install --client zed             # user-global
```

See [Manual install](../manual-install.md) for the full flag reference.
