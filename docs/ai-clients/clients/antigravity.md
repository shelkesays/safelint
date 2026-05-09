# Antigravity

**Markers:** `.antigravity/` in the project root for project-scope; `~/.antigravity/` for user-scope.

**Install location:**

- User-scoped: `~/.antigravity/rules/safelint.md`
- Project-scoped: `<cwd>/.antigravity/rules/safelint.md` — Antigravity loads workspace rules. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Reload Antigravity (or restart the IDE). The rule is auto-loaded from `.antigravity/rules/`. Then ask Antigravity *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client antigravity --project   # recommended for team-shared repos
safelint skill install --client antigravity             # user-global
```

See [Manual install](../manual-install.md) for the full flag reference.
