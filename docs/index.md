# SafeLint

> Holzmann "Power of Ten" safety lint rules for modern **Python, JavaScript, TypeScript, Java** (with **Spring Boot** framework preset), **Rust**, and **Go**, adapted from C/C++ aerospace conventions to bound function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bugs that a typical linter (ruff, pylint, mypy, ESLint, SpotBugs, Checkstyle, clippy, go vet) doesn't reach.

SafeLint complements your existing linters. Where ruff handles style and pylint catches general defects, SafeLint enforces a focused set of *safety* rules: the kind you'd want in code that has to be reviewable, testable, and predictably-terminating. See [The Power of Ten, adapted](power-of-ten.md) for how each of Holzmann's ten rules maps onto SafeLint's checks across the supported languages. It's a CLI, a [pre-commit hook](pre-commit.md), a JSON / SARIF emitter for editor and CI consumers, and an [AI-client skill](ai-clients/index.md) that fourteen agents (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed, Warp, Kiro) speak.

## Currently supported languages

| Language | Extensions | Notes |
|----------|------------|-------|
| **Python** | `.py`, `.pyw` | Default language; the rule set was originally designed for Python and ports unchanged. No per-runtime configuration. |
| **JavaScript** | `.js`, `.mjs`, `.cjs` | Runtime-agnostic source analysis covering Node.js, browser, Deno, Cloudflare Workers, Bun, and any WASM-hosted JS engine. Per-runtime *defaults* are switchable via [`[tool.safelint.javascript] runtime = "..."`](configuration/toml.md#javascript-runtime-presets). |
| **TypeScript** (including **AssemblyScript**) | `.ts`, `.tsx`, `.as` | Reuses the JS rule implementations end-to-end with TS-specific handling for type-only constructs (generics, `as` casts, non-null assertions, `declare global` blocks, etc.). Shares JS runtime presets since TS compiles to JS. |
| **Java** (with **Spring Boot** framework preset) | `.java` | 20 rules apply (the 15 cross-language core plus 5 shared with Python / JS / TS); 4 Spring-specific structural rules (`SAFE901-904`) target Spring annotation patterns. Per-framework *defaults* are switchable via [`[tool.safelint.java] framework = "..."`](languages/java.md#framework-presets). |
| **Rust** | `.rs` | 15 cross-language rules port cleanly (the all-five-languages set); 11 Rust-only rules cover panic placement, lock poisoning, `unsafe` block documentation, truncating `as` casts, silent `Err` arms, dangerous `mem::*` ops, needless `mut`, unchecked arithmetic on integer params, broad `.unwrap()` outside tests, interior-mutable `static`s, plus the empty-`Err` / unlogged-`Err` Rust analogues of `empty_except` / `logging_on_error`. Recognises both inline `#[cfg(test)] mod tests` and Cargo `tests/<stem>.rs` integration-test conventions. See [Rust](languages/rust.md). New in v2.2.0. |
| **Go** | `.go` | 16 cross-language rules apply (the 13 all-six core plus `global_mutation` / `dynamic_code_execution` / `resource_lifecycle`); 2 Go-only rules cover Go-idiom patterns: `empty_error_check` (the empty `if err != nil {}` swallow) and `panic_calls_outside_tests` (18 rules total for Go). Headline adaptations: the bare `for {}` infinite loop, the sibling `foo_test.go` convention, the `_ = f()` explicit-discard exemption, and the `defer x.Close()` resource form. See [Go](languages/go.md). New in v2.5.0. |

**Rule coverage:** 13 rules apply across all six languages (the cross-language core, including `no_recursion` and `blanket_suppression`); 2 more apply to Python / JS / TS / Java / Rust but not Go (`missing_assertions`, `null_dereference`); 3 apply to Python / JS / TS / Java / Go but not Rust (`global_mutation`, `dynamic_code_execution`, `resource_lifecycle`); 2 apply to Python / JavaScript / TypeScript / Java only (`empty_except`, `logging_on_error`); 1 is JavaScript-family-only (`wide_scope_declaration`); 2 are Python-only (`bare_except`, `global_state`); 4 are Java + Spring Boot only (`spring_*`); 11 are Rust-only (including `interior_mutable_static`); and 2 are Go-only (`empty_error_check`, `panic_calls_outside_tests`). Rules are skipped per language where the semantics don't translate (Go has no try/catch, `global` keyword, `var` hoisting, production assertion idiom, or chained-nullable idiom; Rust's `Result`/`Option`/`Drop` model covers its skips with Rust-specific replacements).

**Planned future languages** (in working-priority order, no timelines committed): PHP, C, C++. See the [language-coverage roadmap](configuration/rules.md#planned).

## Quick start

```bash
pip install 'safelint[python]'         # adds .py, .pyw
pip install 'safelint[javascript]'     # adds .js, .mjs, .cjs
pip install 'safelint[typescript]'     # adds .ts, .tsx, .as (also bundles JS)
pip install 'safelint[java]'           # adds .java (Spring Boot framework preset available)
pip install 'safelint[rust]'           # adds .rs
pip install 'safelint[go]'             # adds .go
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
