# TypeScript / TSX / AssemblyScript addendum

This file is the TypeScript-specific addendum to safelint's bundled
AI-client skills. The agent reads it when the user's project contains
`.ts`, `.tsx`, or `.as` files. TypeScript inherits most of the
JavaScript rule behaviour; for the canonical per-rule notes, read
`languages/javascript.md`. The differences below are TypeScript-only.

## Install nuance

TypeScript support ships in the `[typescript]` extra in v2.0.0+. The
extra **bundles `tree-sitter-javascript` automatically** because almost
every TS project has `.js` files too (vite/webpack/eslint configs, jest
setup, generated declaration shims):

```bash
pip install 'safelint[typescript]'
# or, for uv-based projects:
uv add --dev 'safelint[typescript]'
```

No need to compose `[javascript,typescript]`, the TS extra already
includes the JS grammar.

For pre-commit integration, set `additional_dependencies` in
`.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.0.0rc3  # pin to a release (use the GA tag once v2.0.0 ships)
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[typescript]']
```

Without the extra, an all-TypeScript hook run skips every passed file
and exits with code 2 (pre-commit shows the hook as **Failed**),
printing a single error line:

```text
safelint: error: no files linted - every file pre-commit passed had a grammar that isn't installed - add 'safelint[typescript]' to additional_dependencies in your .pre-commit-config.yaml
```

(Hook mode suppresses the per-extension
`safelint: warning: skipping …` line when *every* file is skipped,
the error already carries the install hint; a mixed run that still
lints some files keeps the warning as context.)

## Scope

- **`.ts`**, TypeScript (no JSX). Parsed by tree-sitter-typescript's
  `typescript` grammar.
- **`.tsx`**, TypeScript with JSX (React, etc.). Parsed by the separate
  `tsx` grammar inside tree-sitter-typescript. From safelint's
  perspective both grammars share one logical language name
  (`"typescript"`), so the same 18 rules apply uniformly.
- **`.as`**, AssemblyScript (TS-syntax compiled to WebAssembly). Parses
  with the standard TypeScript grammar; safelint treats `.as` as
  TypeScript without special-casing.

## Rule count

18 rules fire on TypeScript: the 17 cross-language rules plus SAFE305
`wide_scope_declaration` (JS-family-only, flags `var`, which is
still legal but discouraged in TypeScript). The 2 Python-only rules
(SAFE201, SAFE301) are skipped automatically.

## TypeScript-specific rule behaviour

The differences from JavaScript:

| Code | Rule | TypeScript-specific behaviour |
|---|---|---|
| SAFE103 | `max_arguments` | **Generic type parameters do NOT count.** `function f<T, U>(a)` counts 1 argument, not 3. TS keeps type parameters in a separate `type_parameters` AST node, outside `formal_parameters`. |
| SAFE302 | `global_mutation` | **`as` cast, `satisfies`, `!` non-null assertion** in the LHS chain are unwrapped before the receiver walk. `(globalThis as any).counter = 1` correctly resolves to `globalThis` and fires. **`declare global { ... }` ambient blocks** don't fire, they contain type declarations only, no runtime assignments. |
| SAFE305 | `wide_scope_declaration` | Fires on `var` in TS too, `var` is still function-scoped / hoisted regardless of the surrounding type system. Replace with `let` (if reassigned) or `const` (if not). |
| SAFE701 / SAFE702 | `test_existence` / `test_coupling` | **TS sources pair with TS test files,** not JS test files. `foo.ts` looks for `foo.test.ts` / `foo.spec.ts` / `foo.test.tsx` / `foo.spec.tsx` / `foo.test.as` / `foo.spec.as` under `test_dirs`. |
| SAFE801 | `tainted_sink` | **TS pass-through wrappers preserve taint.** `eval(userInput as string)`, `eval(userInput satisfies T)`, and `eval(userInput!)` all fire, the `as` / `satisfies` / `!` annotations are compile-time-only and don't affect the runtime value, so taint flows through. |
| SAFE803 | `null_dereference` | **Non-null assertion (`!`) does NOT bypass the rule.** `users.find(...)!.name` still fires, the `!` is a TS-only annotation, not a runtime guard. The underlying call CAN return undefined; the `!` just silences the TS compiler. Optional chaining (`?.`) remains the only correctly-recognised safe form. |

Everything else (function length, nesting depth, complexity, error
handling, side effects, resource lifecycle, unbounded loops, missing
assertions, return-value-ignored) is identical to JavaScript behaviour.
Read `languages/javascript.md` for the canonical guidance on those rules.

## Config sharing

TypeScript inherits the `_javascript`-suffixed config keys by default:

- `sinks_javascript`, `sanitizers_javascript`, `sources_javascript`
  (SAFE801)
- `tracked_functions_javascript` (SAFE401)
- `global_namespaces_javascript` (SAFE302)
- `io_functions_javascript` (SAFE303 / SAFE304)
- `assertion_calls_javascript` (SAFE601)
- `nullable_methods_javascript` (SAFE803)
- `flagged_calls_javascript` (SAFE802)

A `.ts` file reading any of these gets the JS list automatically.
Users can set `_typescript`-suffixed variants to override per-language
when they have a concrete reason (different sinks for new TS code vs
legacy JS, etc.). The override door is open but most projects don't
need to use it.

## JavaScript runtime presets

The `[tool.safelint.javascript] runtime = "..."` setting applies to TS
files too. TS compiles to JS at runtime; the runtime (Node, browser,
Deno, Cloudflare Workers, Bun) determines the relevant API surface for
the rule defaults. There is no separate `[tool.safelint.typescript]`
table.

## What this addendum does NOT cover

- Idiomatic fix patterns for each rule. Those are in
  `languages/javascript.md`; the patterns work identically on
  TypeScript source.
- TypeScript-specific type-system advice. SafeLint is a runtime-safety
  linter, not a TS type checker, use `tsc` for type errors. The rules
  here all operate on the AST as if types had been erased.
