# TypeScript

SafeLint analyses TypeScript source for the Holzmann "Power of Ten" safety rules — function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bug that style linters like ESLint don't catch. TypeScript support landed in v2.0.0rc1 and reuses the JavaScript rule implementations end-to-end (TS compiles to JS at runtime; the AST is a superset), with TypeScript-specific handling for the type-only constructs that the JS rules wouldn't otherwise recognise.

## File extensions

- **`.ts`** — TypeScript (no JSX). Parsed by `tree-sitter-typescript`'s `typescript` grammar.
- **`.tsx`** — TypeScript with JSX / React. Parsed by the separate `tsx` grammar (the two grammars differ because JSX changes the meaning of `<`, `>`, and a few other tokens). From the rule perspective TSX is just TypeScript with JSX nodes added — same logical language name (`"typescript"`), so a rule's `language` tuple needs one entry to cover both.
- **`.as`** — **AssemblyScript** is a TypeScript-syntax subset that compiles to WebAssembly. It parses cleanly with the standard TypeScript grammar; SafeLint treats `.as` files as TypeScript without special-casing. Rule output uses TypeScript's vocabulary.

## Quick start

!!! warning "v2.0.0rc2 (pre-release) — pin or pass `--pre`"

    Until v2.0.0 GA, an unpinned `pip install 'safelint[typescript]'` resolves to the latest 1.x release, which doesn't define this extra and won't install the TS grammar. For the RC, pin explicitly: `pip install 'safelint[typescript]==2.0.0rc2'` (or pass `--pre`).

```bash
pip install 'safelint[typescript]'     # the tool runs on Python; the [typescript] extra adds the TS grammar (and bundles JS too)
safelint check src/                    # lint a directory (git-modified files by default)
safelint check --all-files .           # lint everything
safelint check --format json src/      # machine-readable for editors / CI
```

If your project doesn't already have a Python toolchain, `pipx install 'safelint[typescript]'` isolates the install; or add `'safelint[typescript]'` as a dev dependency through any pip-compatible manager. v2.0.0+ ships every language grammar as an opt-in extra — plain `pip install safelint` installs only the engine and would skip every `.ts` / `.tsx` / `.as` file with an install hint on first run.

## Rules that fire on TypeScript

18 user-facing rules apply to TypeScript — the 17 cross-language rules plus 1 JavaScript-family rule (SAFE305 `wide_scope_declaration`, which also fires on TS because `var` is still legal there). The 2 Python-only rules (SAFE201, SAFE301) are skipped automatically by the engine's per-language dispatch.

The behaviour is identical to JavaScript for almost everything — see [JavaScript notes](javascript.md) for the canonical per-rule guidance. The differences below are TypeScript-specific.

| Code | Rule | TypeScript-specific notes |
|---|---|---|
| [SAFE101](../configuration/rules.md#safe101-function_length) | `function_length` | Same as JS. Type annotations don't inflate line counts — only body lines count. Long type signatures (e.g. `function f<T extends Record<string, unknown>>(...)`) occupy the same single signature line. |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | `nesting_depth` | Same as JS. TypeScript-only constructs (`interface`, `type` alias declarations) live at module scope and don't appear inside function bodies, so they don't contribute. |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | `max_arguments` | **Generic type parameters do NOT count.** `function f<T, U, V>(a, b)` counts as 2 arguments, not 5 — TS keeps type parameters in a separate `type_parameters` AST node. Default-value and rest parameters count exactly as in JS. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | `complexity` | Same as JS. Conditional types (`T extends string ? A : B`) are type-only and don't add cyclomatic complexity. |
| [SAFE202](../configuration/rules.md#safe202-empty_except) | `empty_except` | Same as JS — fires on empty `catch` blocks. |
| [SAFE203](../configuration/rules.md#safe203-logging_on_error) | `logging_on_error` | Same as JS — requires `console.*` / `logger.*` or rethrow in `catch`. |
| [SAFE302](../configuration/rules.md#safe302-global_mutation) | `global_mutation` | TS-specific pass-through unwrappers: `(globalThis as any).counter = 1` is recognised as a global write — the `as` cast and `!` non-null assertion don't break the receiver-chain walk. `declare global { ... }` (ambient declarations) doesn't fire because the block contains type declarations only, no runtime assignments. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | `side_effects_hidden` | Same as JS. Uses the same `io_functions_javascript` list by default (TypeScript inherits the JS config; see [config precedence](../configuration/toml.md#typescript-and-the-_javascript-config-keys)). |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | `side_effects` | Same as JS. |
| [SAFE305](../configuration/rules.md#safe305-wide_scope_declaration) | `wide_scope_declaration` | **JavaScript-family only**, but applies to TS too. `var` is legal in TS and still hazardous (function-scoped, hoisted); the rule fires identically on `.ts` / `.tsx` / `.as` files. Migration: replace with `let` (if reassigned) or `const` (if not). |
| [SAFE401](../configuration/rules.md#safe401-resource_lifecycle) | `resource_lifecycle` | Same as JS — tracked acquirer calls (`createReadStream`, `Worker`, …) must be inside `try { ... } finally { ... }`. Constructor invocations (`new Worker(...)`) are recognised. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | `unbounded_loops` | Same as JS. |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | `missing_assertions` | Same as JS. Uses `assertion_calls_javascript` by default — TS frameworks like Vitest / Jest typically configure the same call names, so no `_typescript` override is needed. Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | `test_existence` | **Pairs against TS test filenames:** `foo.ts` looks for `foo.test.ts` / `foo.spec.ts` / `foo.test.tsx` / `foo.spec.tsx` / `foo.test.as` / `foo.spec.as` under `test_dirs`. NOT `foo.test.js` — TS source pairs with TS tests (language-family consistency). Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | `test_coupling` | Same filename patterns as SAFE701 — if you change `src/foo.ts`, also change `foo.test.ts`. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | `tainted_sink` | **TS-only pass-through wrappers preserve taint:** `eval(userInput as string)`, `eval(userInput satisfies T)`, and `eval(userInput!)` all fire — the `as` / `satisfies` / `!` annotations are compile-time-only and don't change the runtime value. Default sinks / sources inherit from `_javascript` config. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | `return_value_ignored` | Same as JS. Discarded `Promise` from async TS functions still fires. |
| [SAFE803](../configuration/rules.md#safe803-null_dereference) | `null_dereference` | **Non-null assertion (`!`) does NOT bypass the rule.** `users.find(...)!.name` still fires — the `!` is a TS-only annotation, not a runtime guard. Optional chaining (`?.`) remains the only correctly-recognised safe form. |

The 2 rules **not registered for TypeScript** (same as for JS):

- [SAFE201 `bare_except`](../configuration/rules.md#safe201-bare_except) — TS `catch` always binds the caught error.
- [SAFE301 `global_state`](../configuration/rules.md#safe301-global_state) — TS has no `global` keyword.

## Configuration

SafeLint config is read from `[tool.safelint]` in `pyproject.toml` or from a standalone `safelint.toml`. TypeScript projects that don't already have a `pyproject.toml` typically prefer the standalone form.

### TypeScript inherits JavaScript config

The runtime is the same (TS compiles to JS), so the threat surface, I/O primitives, global namespaces, etc. are identical. By default, every `_javascript`-suffixed config key applies to BOTH `.js` AND `.ts` files. Setting `_typescript`-suffixed keys is opt-in — you do it only when you genuinely want different behaviour for `.ts` files. See [TypeScript and the `_javascript` config keys](../configuration/toml.md#typescript-and-the-_javascript-config-keys) for the full precedence rules.

```toml
# safelint.toml (typical TS-only project — no TS-specific config needed)
mode = "ci"
fail_on = "warning"

[javascript]
runtime = "node"             # node / browser / deno / cloudflare-workers / bun

[rules.tainted_sink]
enabled = true
# Both .js and .ts files use this list. No _typescript override needed.
sinks_javascript = ["eval", "Function", "myCustomDangerousFunction"]
```

```toml
# Rare: stricter TS sinks (legacy JS keeps the JS list)
[rules.tainted_sink]
sinks_javascript = ["eval", "Function"]                                # legacy JS
sinks_typescript = ["eval", "Function", "Object.assign", "innerHTML"]  # stricter for TS
```

### Runtime presets apply to TypeScript too

`[tool.safelint.javascript] runtime = "..."` selects which API surface the rule defaults assume — and TS inherits the chosen preset because the runtime is what determines `fs` vs `Deno.*` vs Cloudflare KV vs Bun-specific APIs. There is no separate `[tool.safelint.typescript]` table; TS and JS share the same runtime story. See [JavaScript runtime presets](../configuration/toml.md#javascript-runtime-presets) for the per-preset details.

## Installing the TypeScript extra

TypeScript grammar support ships as an optional extra so Python-only projects don't pay for it. The `[typescript]` extra also bundles `tree-sitter-javascript` because almost every TS project has a few `.js` files (vite/webpack configs, jest setup, etc.) — one install command covers both:

```bash
pip install 'safelint[typescript]'    # adds .ts, .tsx, .as (and .js too)
# or kitchen-sink:
pip install 'safelint[all]'
```

Without the extra, `safelint check` skips `.ts` / `.tsx` / `.as` files with a one-line install hint at lint time. If at least one other supported file (e.g. a Python file in a mixed repo) does get linted, the run continues normally. **If every candidate file gets skipped** — the typical case in a TS-only project — the [silent-failure guard](../configuration/cli.md#exit-code-2--silent-failure-triggers) fires and SafeLint exits with code 2 plus the install hint embedded in the error, so CI / pre-commit can't accidentally report green on an un-linted run.

## Pre-commit integration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/shelkesays/safelint
    rev: v2.0.0rc2       # pin to a release (replace with the GA tag once v2.0.0 ships)
    hooks:
      - id: safelint
        # TS users add the matching extra so pre-commit's isolated environment
        # installs ``tree-sitter-typescript`` (and the bundled JS grammar).
        additional_dependencies: ['safelint[typescript]']
        # The published hook's ``types_or`` already includes python,
        # javascript, ts, and tsx. Optional: scope to a directory.
        files: ^src/
```

**AssemblyScript (`.as`) users — additional override required.** Pre-commit's `identify` library has no `as` filetype tag, so the default `types_or: [python, javascript, ts, tsx]` won't match `.as` files. Override `types_or` with a permissive tag that `.as` files *actually* carry (`text` or `file`) and use `files` to scope the match. `types_or: []` does **not** work — pre-commit treats an empty tag list as "no tag matches" rather than "filter disabled", so the hook never fires.

```yaml
      - id: safelint
        additional_dependencies: ['safelint[typescript]']
        types_or: [text]                              # permissive tag .as files carry; files scopes the match
        files: ^src/.*\.(ts|tsx|as)$                  # explicit extension allow-list
```

## TypeScript-specific config keys

All JS config keys also work as `_typescript`-suffixed variants when you want TS-specific overrides:

- `[tool.safelint.rules.side_effects_hidden]` — `io_functions_typescript`
- `[tool.safelint.rules.side_effects]` — `io_functions_typescript`
- `[tool.safelint.rules.global_mutation]` — `global_namespaces_typescript`
- `[tool.safelint.rules.resource_lifecycle]` — `tracked_functions_typescript`
- `[tool.safelint.rules.missing_assertions]` — `assertion_calls_typescript`
- `[tool.safelint.rules.tainted_sink]` — `sinks_typescript`, `sanitizers_typescript`, `sources_typescript`
- `[tool.safelint.rules.return_value_ignored]` — `flagged_calls_typescript`
- `[tool.safelint.rules.null_dereference]` — `nullable_methods_typescript`

All accept a list of strings; bare-string typos (`sinks_typescript = "eval"` instead of `["eval"]`) raise a clear `TypeError` instead of silently coercing into a set of characters.

## Contributing

Want to refine a rule's TypeScript behaviour, add a TS-only handler, or extend AssemblyScript coverage? See [Adding a language](../contributing/adding-a-language.md) for the architecture overview, or open an issue / PR against the [main repo](https://github.com/shelkesays/safelint).
