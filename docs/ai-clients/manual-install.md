# Manual install (`--client`)

Skip auto-detection by passing an explicit client name:

```bash
# Claude Code, user-scoped
safelint skill install --client claude

# Claude Code, project-scoped
safelint skill install --client claude --project

# Cursor, user-scoped
safelint skill install --client cursor

# Cursor, project-scoped (recommended for team-shared repos)
safelint skill install --client cursor --project

# GitHub Copilot, project-scoped (canonical — auto-loaded by VS Code)
safelint skill install --client copilot --project

# GitHub Copilot, user-global (requires VS Code settings to point at ~/.github/copilot-instructions.md)
safelint skill install --client copilot

# Gemini, project-scoped (canonical — auto-discovered by Gemini CLI)
safelint skill install --client gemini --project

# Gemini, user-global (requires Gemini CLI configuration to point at ~/GEMINI.md)
safelint skill install --client gemini

# Windsurf, project-scoped (canonical — auto-loaded by Windsurf)
safelint skill install --client windsurf --project

# Windsurf, user-global rules (merged with project rules at runtime)
safelint skill install --client windsurf

# codex, project-scoped (canonical .codex/instructions.md; also injects section into AGENTS.md if present)
safelint skill install --client codex --project

# codex, user-global
safelint skill install --client codex

# Continue.dev, project-scoped (recommended for team-shared repos)
safelint skill install --client continue --project

# Continue.dev, user-global (loaded across all workspaces)
safelint skill install --client continue

# Cline, project-scoped (recommended for team-shared repos)
safelint skill install --client cline --project

# Cline, user-global
safelint skill install --client cline

# aider, project-scoped (then wire `read: [CONVENTIONS.md]` into .aider.conf.yml)
safelint skill install --client aider --project

# aider, user-global
safelint skill install --client aider

# Trae, project-scoped (recommended for team-shared repos)
safelint skill install --client trae --project

# Trae, user-global
safelint skill install --client trae

# Antigravity, project-scoped (recommended for team-shared repos)
safelint skill install --client antigravity --project

# Antigravity, user-global
safelint skill install --client antigravity

# Zed, project-scoped (recommended for team-shared repos)
safelint skill install --client zed --project

# Zed, user-global
safelint skill install --client zed
```

When `--client` is explicit, no detection runs and no detection notice is printed. The install proceeds at the requested scope (default: user; with `--project`: cwd).

For the per-client install path, restart-step, and any client-specific gotchas, see the dedicated guide for each client (linked from the [AI clients overview](index.md)).
