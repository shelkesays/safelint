# Cline

**Markers:** `.clinerules/` in the project root for project-scope; `~/.clinerules/` for user-scope.

**Install location:**

- User-scoped: `~/.clinerules/safelint.md` — Cline auto-loads user-global rules across workspaces.
- Project-scoped: `<cwd>/.clinerules/safelint.md` — Cline auto-loads any `.md` under `.clinerules/`. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Reload your IDE (or restart Cline). The rule is auto-loaded. Then ask Cline *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client cline --project   # recommended for team-shared repos
safelint skill install --client cline             # user-global
```

See [Manual install](../manual-install.md) for the full flag reference.
