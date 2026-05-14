# Continue.dev

**Markers:** `.continue/`, `.continuerc`, or `.continuerc.json` in the project root for project-scope; `~/.continue/` for user-scope.

**Install location:**

- User-scoped: `~/.continue/rules/safelint.md`, Continue.dev auto-loads user-global rules across workspaces.
- Project-scoped: `<cwd>/.continue/rules/safelint.md`, Continue.dev auto-loads workspace rules. **Recommended for team-shared repos, commit the file.**

**How to invoke after install:**

Reload your IDE (or restart Continue.dev). The rule is auto-loaded from `.continue/rules/`. Then ask Continue *"run safelint"* / *"lint with safelint"*, same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client continue --project   # recommended for team-shared repos
safelint skill install --client continue             # user-global, loaded across all workspaces
```

See [Manual install](../manual-install.md) for the full flag reference.
