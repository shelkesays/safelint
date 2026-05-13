# SafeLint

> Holzmann "Power of Ten" safety lint rules for modern **Python, JavaScript, and TypeScript** — adapted from C/C++ aerospace conventions to bound function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bugs that a typical linter (ruff, pylint, mypy, ESLint) doesn't reach.

SafeLint complements your existing linters. Where ruff handles style and pylint catches general defects, SafeLint enforces a focused set of *safety* rules — the kind you'd want in code that has to be reviewable, testable, and predictably-terminating. It's a CLI, a pre-commit hook, a JSON / SARIF emitter for editor and CI consumers, and an [AI-client skill](ai-clients/index.md) that twelve agents (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed) speak.

## Currently supported languages

| Language | Extensions | Notes |
|----------|------------|-------|
| **Python** | `.py`, `.pyw` | — |
| **JavaScript** | `.js`, `.mjs`, `.cjs` | Runtime-agnostic source analysis covering Node.js, browser, Deno, Cloudflare Workers, Bun, and any WASM-hosted JS engine. Per-runtime *defaults* are switchable via [`[tool.safelint.javascript] runtime = "..."`](configuration/toml.md#javascript-runtime-presets). |
| **TypeScript** (including **AssemblyScript**) | `.ts`, `.tsx`, `.as` | Reuses the JS rule implementations end-to-end with TS-specific handling for type-only constructs (generics, `as` casts, non-null assertions, `declare global` blocks, etc.). Shares JS runtime presets since TS compiles to JS. |

**Rule coverage:** 17 rules apply to all three languages; 2 are Python-only (`bare_except`, `global_state` — the keywords don't exist in JS/TS) and 1 is JavaScript-family-only (`wide_scope_declaration` — `var`'s function-scoping hazard doesn't exist in Python, but applies to both `.js` and `.ts`).

**Planned future languages** (in working-priority order, no timelines committed): Go, Rust, Java, C, C++, PHP — see the [language-coverage roadmap](configuration/rules.md#planned).

## Quick start

!!! warning "v2.0.0rc2 (pre-release) — pin the version or pass `--pre`"

    Until v2.0.0 GA, an unpinned `pip install 'safelint[<lang>]'` resolves to the latest 1.x release, which **doesn't define these per-language extras** and so wouldn't install any grammar. For the RC, pin explicitly: `pip install 'safelint[python]==2.0.0rc2'` (or pass `--pre` to any command below).

```bash
pip install 'safelint[python]'         # adds .py, .pyw
pip install 'safelint[javascript]'     # adds .js, .mjs, .cjs
pip install 'safelint[typescript]'     # adds .ts, .tsx, .as (also bundles JS)
pip install 'safelint[all]'            # every supported language
pip install 'safelint[python,javascript]'   # multiple extras compose
# uv add 'safelint[typescript]' works the same way.

safelint check src/                    # lint a directory
safelint check --all-files .           # lint everything (default is git-modified only)
safelint check --format json src/      # machine-readable output for editors / CI
```

Pick the extras that match the languages you actually lint — every grammar ships as an opt-in extra so a Python-only project never pays for JavaScript / TypeScript grammars, a Go/JS-only project never pays for the Python grammar, and so on. `pip install safelint` alone installs only the engine; safelint emits a one-line install hint on first run telling you which extra to add for the files it found.

## Where to go from here

- **[Configuration](configuration/index.md)** — every CLI flag, every rule, every TOML option. Start here once you've installed.
- **[AI client integrations](ai-clients/index.md)** — install the skill into Claude Code / Cursor / 10 other agents with one command, then ask "run safelint" in the chat.
- **[JSON output schema](json-schema.md)** — for editor and plugin authors building on top of `safelint --format json`.
- **[Contributing](contributing/index.md)** — three contribution paths (rule, AI client, language), each with its own walkthrough.
- **[Changelog](project/changelog.md)** — what shipped when.

## What SafeLint won't do

SafeLint is a **review tool**, not a refactor tool. It surfaces violations and may emit advisory `Suggestions` in JSON output for editor integrations — but it never auto-fixes. There is no `--fix` flag and there never will be: every change to your code goes through your eyes.
