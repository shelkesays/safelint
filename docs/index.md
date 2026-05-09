# SafeLint

> Holzmann "Power of Ten" safety lint rules for modern Python — adapted from C/C++ aerospace conventions to bound function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bugs that a typical linter (ruff, pylint, mypy) doesn't reach.

SafeLint complements your existing linters. Where ruff handles style and pylint catches general defects, safelint enforces a focused set of *safety* rules — the kind you'd want in code that has to be reviewable, testable, and predictably-terminating. It's a CLI, a pre-commit hook, a JSON / SARIF emitter for editor and CI consumers, and an [AI-client skill](ai-clients/index.md) that twelve agents (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed) speak.

## Quick start

```bash
pip install safelint                  # or: uv add safelint
safelint check src/                   # lint a directory
safelint check --all-files .          # lint everything (default is git-modified only)
safelint check --format json src/     # machine-readable output for editors / CI
```

## Where to go from here

- **[Configuration](configuration/index.md)** — every CLI flag, every rule, every TOML option. Start here once you've installed.
- **[AI client integrations](ai-clients/index.md)** — install the skill into Claude Code / Cursor / 10 other agents with one command, then ask "run safelint" in the chat.
- **[JSON output schema](json-schema.md)** — for editor and plugin authors building on top of `safelint --format json`.
- **[Contributing](contributing/index.md)** — three contribution paths (rule, AI client, language), each with its own walkthrough.
- **[Changelog](project/changelog.md)** — what shipped when.

## What safelint won't do

SafeLint is a **review tool**, not a refactor tool. It surfaces violations and may emit advisory `Suggestions` in JSON output for editor integrations — but it never auto-fixes. There is no `--fix` flag and there never will be: every change to your code goes through your eyes.
