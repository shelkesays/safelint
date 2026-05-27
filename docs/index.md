# SafeLint

> Holzmann "Power of Ten" safety lint rules for modern **Python, JavaScript, TypeScript, Java** (with **Spring Boot** framework preset), and **Rust**, adapted from C/C++ aerospace conventions to bound function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bugs that a typical linter (ruff, pylint, mypy, ESLint, SpotBugs, Checkstyle, clippy) doesn't reach.

SafeLint complements your existing linters. Where ruff handles style and pylint catches general defects, SafeLint enforces a focused set of *safety* rules: the kind you'd want in code that has to be reviewable, testable, and predictably-terminating. It's a CLI, a [pre-commit hook](pre-commit.md), a JSON / SARIF emitter for editor and CI consumers, and an [AI-client skill](ai-clients/index.md) that twelve agents (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed) speak.

## Currently supported languages

| Language | Extensions | Notes |
|----------|------------|-------|
| **Python** | `.py`, `.pyw` | Default language; the rule set was originally designed for Python and ports unchanged. No per-runtime configuration. |
| **JavaScript** | `.js`, `.mjs`, `.cjs` | Runtime-agnostic source analysis covering Node.js, browser, Deno, Cloudflare Workers, Bun, and any WASM-hosted JS engine. Per-runtime *defaults* are switchable via [`[tool.safelint.javascript] runtime = "..."`](configuration/toml.md#javascript-runtime-presets). |
| **TypeScript** (including **AssemblyScript**) | `.ts`, `.tsx`, `.as` | Reuses the JS rule implementations end-to-end with TS-specific handling for type-only constructs (generics, `as` casts, non-null assertions, `declare global` blocks, etc.). Shares JS runtime presets since TS compiles to JS. |
| **Java** (with **Spring Boot** framework preset) | `.java` | 16 cross-language rules port cleanly; 4 Spring-specific structural rules (`SAFE901-904`) target Spring annotation patterns. Per-framework *defaults* are switchable via [`[tool.safelint.java] framework = "..."`](languages/java.md#framework-presets). |
| **Rust** | `.rs` | 17 cross-language rules port cleanly; 10 Rust-only rules cover panic placement, lock poisoning, `unsafe` block documentation, truncating `as` casts, silent `Err` arms, dangerous `mem::*` ops, needless `mut`, unchecked arithmetic on integer params, broad `.unwrap()` outside tests, plus the empty-`Err` / unlogged-`Err` Rust analogues of `empty_except` / `logging_on_error`. Recognises both inline `#[cfg(test)] mod tests` and Cargo `tests/<stem>.rs` integration-test conventions. See [Rust](languages/rust.md). New in v2.2.0. |

**Rule coverage:** 17 cross-language rules apply across all five languages; 2 are Python-only (`bare_except`, `global_state`); 1 applies to Python / JS / TS but not Java / Rust (`global_mutation`; Java has no clean analogue, deferred; Rust's `static mut` is unsafe-gated and covered by `undocumented_unsafe`); 1 is JavaScript-family-only (`wide_scope_declaration`); 4 are Java + Spring Boot only (`spring_*`); and 10 are Rust-only. 6 cross-language rules (`bare_except`, `empty_except`, `logging_on_error`, `global_state`, `global_mutation`, `resource_lifecycle`) are deliberately skipped for Rust because Rust's `Result`/`Option`/`Drop` model doesn't have direct analogues; their spirit is covered by Rust-specific replacements where relevant.

**Planned future languages** (in working-priority order, no timelines committed): Go, C, C++, PHP. See the [language-coverage roadmap](configuration/rules.md#planned).

## Quick start

```bash
pip install 'safelint[python]'         # adds .py, .pyw
pip install 'safelint[javascript]'     # adds .js, .mjs, .cjs
pip install 'safelint[typescript]'     # adds .ts, .tsx, .as (also bundles JS)
pip install 'safelint[java]'           # adds .java (Spring Boot framework preset available)
pip install 'safelint[rust]'           # adds .rs
pip install 'safelint[all]'            # every supported language
pip install 'safelint[python,rust]'    # multiple extras compose (e.g. PyO3 / maturin)
# uv add 'safelint[typescript]' works the same way.

safelint check src/                    # lint a directory
safelint check --all-files .           # lint everything (default is git-modified only)
safelint check --format json src/      # machine-readable output for editors / CI
```

Pick the extras that match the languages you actually lint. Every grammar ships as an opt-in extra so a Python-only project never pays for JavaScript / TypeScript grammars, a Go/JS-only project never pays for the Python grammar, and so on. `pip install safelint` alone installs only the engine; safelint emits a one-line install hint on first run telling you which extra to add for the files it found.

## Where to go from here

- **[Configuration](configuration/index.md)**: every CLI flag, every rule, every TOML option. Start here once you've installed.
- **[Pre-commit](pre-commit.md)**: drop a 10-line block into `.pre-commit-config.yaml` and SafeLint runs on every `git commit`.
- **[AI client integrations](ai-clients/index.md)**: install the skill into Claude Code / Cursor / 10 other agents with one command, then ask "run safelint" in the chat.
- **[JSON output schema](json-schema.md)**: for editor and plugin authors building on top of `safelint --format json`.
- **[Contributing](contributing/index.md)**: three contribution paths (rule, AI client, language), each with its own walkthrough.
- **[Changelog](project/changelog.md)**: what shipped when.

## What SafeLint won't do

SafeLint is a **review tool**, not a refactor tool. It surfaces violations and may emit advisory `Suggestions` in JSON output for editor integrations, but it never auto-fixes. There is no `--fix` flag and there never will be: every change to your code goes through your eyes.
