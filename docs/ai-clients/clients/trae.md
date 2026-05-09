# Trae

**Markers:** `.trae/` in the project root for project-scope; `~/.trae/` for user-scope.

**Install location:**

- User-scoped: `~/.trae/rules/safelint.md`
- Project-scoped: `<cwd>/.trae/rules/safelint.md` — Trae auto-loads workspace rules. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Reload Trae (or restart the IDE). The rule is auto-loaded from `.trae/rules/`. Then ask Trae *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client trae --project   # recommended for team-shared repos
safelint skill install --client trae             # user-global
```

See [Manual install](../manual-install.md) for the full flag reference.
