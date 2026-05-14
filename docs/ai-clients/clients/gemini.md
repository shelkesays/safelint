# Gemini

**Markers:** `GEMINI.md` or `.gemini/` in the project root for project-scope; `~/.gemini/` for user-scope.

**Install location:**

- User-scoped: `~/GEMINI.md`, Gemini CLI does not auto-discover this. Users wanting a global file configure Gemini CLI to read it explicitly (or symlink it where the CLI looks).
- Project-scoped: `<cwd>/GEMINI.md`, Gemini CLI's canonical instructions file, auto-discovered when invoked from the repo. **Recommended for team-shared repos, commit the file.**

**How to invoke after install:**

Restart Gemini CLI (or your IDE's Gemini integration). The `GEMINI.md` file is auto-discovered for the workspace. Then ask Gemini *"run safelint"* / *"lint with safelint"*, same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client gemini --project   # canonical, auto-discovered by Gemini CLI
safelint skill install --client gemini             # user-global, requires CLI configuration
```

See [Manual install](../manual-install.md) for the full flag reference.
