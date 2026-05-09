# GitHub Copilot

**Markers:** `.github/copilot-instructions.md`, `.github/copilot/`, or `.github/instructions/` in the project root for project-scope; `~/.github/copilot-instructions.md` for user-scope. Bare `.github/` alone is **not** a marker — it appears in nearly every repo for GitHub Actions.

**Install location:**

- User-scoped: `~/.github/copilot-instructions.md` — VS Code can be configured to read this via the `github.copilot.chat.codeGeneration.instructions` setting (it isn't auto-discovered like the project file is).
- Project-scoped: `<cwd>/.github/copilot-instructions.md` — Copilot's canonical instructions location, auto-loaded by VS Code's Copilot Chat. **Recommended for team-shared repos — commit the file.**

**How to invoke after install:**

Reload VS Code (or restart Copilot Chat). The instructions file is auto-loaded for the workspace. Then ask Copilot Chat *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**First-time bootstrap note:** Copilot's auto-detection signals (`.github/copilot-instructions.md`, `.github/copilot/`, `.github/instructions/`) only match an *existing* Copilot setup. For first-time installs on a fresh project, pass `--client copilot --project` explicitly.

**Manual install:**

```bash
safelint skill install --client copilot --project   # canonical, auto-loaded by VS Code
safelint skill install --client copilot             # user-global, requires settings tweak
```

See [Manual install](../manual-install.md) for the full flag reference.
