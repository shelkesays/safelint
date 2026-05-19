# JavaScript

SafeLint analyses JavaScript source for the Holzmann "Power of Ten" safety rules, function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bug that style linters like ESLint don't catch. JavaScript support landed in v1.13.0 alongside Python; the analysis is runtime-agnostic and runs identically across Node.js, browser, Deno, Cloudflare Workers, Bun, and WASM-hosted JS engines.

## File extensions

`.js`, `.mjs`, `.cjs`. JSX (`.jsx`) is not yet registered, see the [language roadmap](../configuration/rules.md#planned). TypeScript (`.ts` / `.tsx` / `.as`) lives on its own [language page](typescript.md) as of v2.0.0.

## Quick start

```bash
pip install 'safelint[javascript]'    # the tool itself runs on Python; the extra adds the JS grammar
safelint check src/                   # lint a directory (git-modified files by default)
safelint check --all-files .          # lint everything
safelint check --format json src/     # machine-readable for editors / CI
```

If your project doesn't already have a Python toolchain, the same install command works through `pipx install 'safelint[javascript]'` (isolates the install) or by adding `'safelint[javascript]'` as a dev dependency through any pip-compatible manager. v2.0.0 ships every language grammar as an opt-in extra; the `[javascript]` extra installs `tree-sitter-javascript` alongside the engine.

## Rules that fire on JavaScript

18 user-facing rules apply to JavaScript: the 16 cross-language rules (Python / JS / TS / Java) plus SAFE302 `global_mutation` (Python / JS / TS only, not ported to Java yet) plus the 1 JavaScript-family rule (SAFE305 `wide_scope_declaration`). The 2 Python-only rules (SAFE201, SAFE301) and the 4 Java + Spring Boot only rules (SAFE901-904) are skipped automatically by the engine's per-language dispatch.

| Code | Rule | Notes for JavaScript |
|---|---|---|
| [SAFE101](../configuration/rules.md#safe101-function_length) | `function_length` | Default cap 60 lines. Counts function declarations, function expressions, arrow functions, generators, and class methods uniformly. `count_mode = "statements"` is Python-only, JS files use `lines` (default) or `logical_lines`. |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | `nesting_depth` | Counts `if` / `for` / `for…in` / `while` / `do…while` / `switch` / `try` blocks. Default max 2. Optional chaining (`?.`) does not count toward depth. |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | `max_arguments` | Counts named, default-value (`b = 5`), rest (`...args`), and destructured (`{a, b}` / `[x, y]`) parameters. Default cap 7. No `self` / `cls` skip. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | `complexity` | Cyclomatic complexity, every `if` / `else if` / `for` / `while` / `case` / `catch` / ternary / `&&` / `||` / `??` adds one. Default cap 10. |
| [SAFE202](../configuration/rules.md#safe202-empty_except) | `empty_except` | Fires on `catch (e) {}`, `catch {}` (ES2019 optional binding), `catch (e) { ; }`, `catch (e) { 0; }`, `catch (e) { "TODO"; }`. |
| [SAFE203](../configuration/rules.md#safe203-logging_on_error) | `logging_on_error` | Requires `console.{log,info,warn,error,debug,trace}` (or generic `logger.*` / `pino.*` / `bunyan.*`) in every `catch`. `throw e;` (exact rethrow of the caught binding) is exempt. |
| [SAFE302](../configuration/rules.md#safe302-global_mutation) | `global_mutation` | Function-body writes to a configured global namespace. Default: `globalThis` / `window` / `global` / `self` / `process`. Bracket-notation (`window["x"] = 1`) and update-expressions (`process.exitCode++`) are also covered. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | `side_effects_hidden` | Functions named with a pure-prefix (`get`, `calculate`, `is`, …) that secretly call `console.log` / `fetch` / `fs.readFile`. Arrow functions bound via `const fetchUser = () => ...` are resolved via the enclosing `variable_declarator`. |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | `side_effects` | Any function calling an I/O primitive whose name doesn't signal I/O (no `log` / `write` / `read` / `fetch` / `send` / `load` substring, case-insensitive, so it matches `fetchUser`). |
| [SAFE305](../configuration/rules.md#safe305-wide_scope_declaration) | `wide_scope_declaration` | **JavaScript-only.** Fires on every `var` declaration, `var` is function-scoped (hoisted), `let` / `const` are block-scoped. |
| [SAFE401](../configuration/rules.md#safe401-resource_lifecycle) | `resource_lifecycle` | Tracked acquirer calls (`createReadStream`, `connect`, `Worker`, …) must be inside a `try { ... } finally { ... }`. Constructor invocations (`new Worker(...)`) are also recognised. The newer `using` syntax (Stage 3 / Node 22+) isn't yet treated as a safe form. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | `unbounded_loops` | `while (true)` with no `break`. Nested parens (`while ((true))`) are handled. The non-comparison-condition heuristic stays Python-only, JS idioms like `while (queue.length)` are commonly bounded. |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | `missing_assertions` | Functions with zero assertion calls. JS configures via `assertion_calls_javascript` (default: `assert`, `ok`, `equal`, `expect`, `should`, `console.assert`, …). Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | `test_existence` | Every source file should have a matching `<stem>.test.<ext>` (Jest) or `<stem>.spec.<ext>` (Mocha) under `test_dirs`. Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | `test_coupling` | Same pattern as SAFE701: if you change `src/foo.js`, you must also change `foo.test.js` in the same commit. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | `tainted_sink` | Function parameters / `prompt()` / `getItem()` flowing into `eval` / `Function` / `child_process`. `new Function(userInput)` is also recognised as a sink. Disabled by default. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | `return_value_ignored` | Bare calls to `fs.writeFile`, `stream.write`, `dispatchEvent`, etc., the returned Promise / boolean / handle carries information that's being discarded. Disabled by default. |
| [SAFE803](../configuration/rules.md#safe803-null_dereference) | `null_dereference` | `document.getElementById("id").textContent`, DOM lookups / array `find` / collection `get` can return `null` or `undefined`. Optional chaining (`?.`) is recognised as a safe form. Disabled by default. |

The 2 rules **not registered for JavaScript:**

- [SAFE201 `bare_except`](../configuration/rules.md#safe201-bare_except), JavaScript `catch` clauses always bind the caught error and don't have the `KeyboardInterrupt` / `SystemExit` hijack hazard, so there's no equivalent rule to fire.
- [SAFE301 `global_state`](../configuration/rules.md#safe301-global_state), JavaScript has no `global` read-only declaration form; on JS this would always be a strict subset of SAFE302 (`global_mutation`).

## Runtime presets

JavaScript source is the same regardless of where it runs, but the *APIs* it interacts with differ. The `[tool.safelint.javascript]` table selects which API surface the JavaScript rule defaults assume, sinks for taint analysis, tracked acquirers for resource-lifecycle, global namespaces for SAFE302, etc.

| Runtime | When to pick it | What changes |
|---|---|---|
| `node` (default) | Backend Node.js apps, CLIs, serverless functions running on Node-compatible runtimes | Node `fs` / `child_process` / `process` / streams. |
| `browser` | Browser-side JS, ES module bundles, anything running in a `<script>` or via a bundler targeting browsers | Web APIs only. DOM lookups (`getElementById`, `querySelector`) for SAFE803; observers / Workers / WebSocket / ReadableStream for SAFE401; `localStorage` / `addEventListener` / `postMessage` for SAFE802; `globalThis` / `window` / `self` / `document` global namespaces for SAFE302. Drops Node `fs` and `child_process` entirely. |
| `deno` | Deno scripts and Deno Deploy applications | `Deno.*` API surface. `Deno.open` / `Deno.connect` / `Deno.listen` for SAFE401; `Deno.run` / `Deno.Command` for SAFE801; `Deno` added to global namespaces; `process` and `window` dropped. |
| `cloudflare-workers` | Cloudflare Workers (V8 isolates); also a reasonable starting point for other Web-API-only edge runtimes | KV / R2 / Durable Object methods (`put` / `delete` / `get`), `Request` body methods (`json` / `formData` / `arrayBuffer` / `blob`) as taint sources, minimal global-namespace list. No `fs` surface. |
| `bun` | Bun runtime | Node defaults plus Bun-specific extras (`Bun.serve`, `Bun.spawn`). |

WASM-hosted JS engines (QuickJS-WASM, Boa, V8 in WASM, etc.) execute the same JS source, pick whichever preset matches the *API surface* the engine exposes (typically `browser` if the host provides Web APIs, or a minimal subset if it only exposes ECMAScript built-ins). Source-language analysis itself is identical across all runtimes, only the *defaults* change.

See [JavaScript runtime presets](../configuration/toml.md#javascript-runtime-presets) for the per-preset config details.

## Configuration

SafeLint reads its config from `[tool.safelint]` in `pyproject.toml`, or from a standalone `safelint.toml` at the project root. JavaScript projects that don't already have a `pyproject.toml` typically prefer the standalone form.

**`safelint.toml` (typical JS-only project):**

```toml
mode = "ci"                 # "local" (fail-on=error) or "ci" (fail-on=warning)
ignore = ["SAFE701"]        # rules suppressed project-wide

[javascript]
runtime = "browser"         # node / browser / deno / cloudflare-workers / bun

[per_file_ignores]
"*.test.js" = ["SAFE101", "SAFE601"]   # tests routinely have longer functions
"vendor/**" = ["*"]                     # ignore everything under vendor/

[rules.function_length]
max_lines = 80              # raise the default cap

[rules.tainted_sink]
enabled = true              # opt into the dataflow rules
sinks_javascript = ["eval", "Function", "myCustomDangerousFunction"]   # overrides the browser preset
```

**`pyproject.toml` (mixed Python + JS project):**

```toml
# Same content but add the [tool.safelint.*] prefix
[tool.safelint]
mode = "ci"
ignore = ["SAFE701"]

[tool.safelint.javascript]
runtime = "browser"

[tool.safelint.per_file_ignores]
"*.test.js" = ["SAFE101", "SAFE601"]

[tool.safelint.rules.tainted_sink]
enabled = true
sinks_javascript = ["eval", "Function", "myCustomDangerousFunction"]
```

User-explicit `_javascript`-suffixed config keys always win over the runtime preset, the preset only changes the *default* list.

## Installing the JavaScript extra

JavaScript grammar support ships as an optional extra so Python-only projects don't pay for it:

```bash
pip install 'safelint[javascript]'    # adds .js, .mjs, .cjs
# or, for TS projects that also have JS:
pip install 'safelint[typescript]'    # bundles tree-sitter-javascript too
# or kitchen-sink:
pip install 'safelint[all]'
```

Without the extra, `safelint check` skips `.js` / `.mjs` / `.cjs` files with a one-line install hint at lint time. **Heads-up for CI:** if the run discovers JS files but every one is skipped because the grammar isn't installed, safelint exits with code **2** (the silent-failure guard) so a CI pipeline can't accidentally report green when no linting actually happened. If your CI logic distinguishes "lint clean" from "lint setup is broken", branch on exit code 2, or just install the matching extra and the guard never fires.

## Pre-commit integration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/shelkesays/safelint
    rev: v2.1.0rc1      # pin to a release (use a recent tag; v2.1.0rc1 also unlocks the Java extra if you later add .java files)
    hooks:
      - id: safelint
        # JS / TS users add the matching extra so pre-commit's isolated
        # environment installs the right tree-sitter grammar.
        additional_dependencies: ['safelint[javascript]']
        # The published hook's `types_or` already includes python,
        # javascript, ts, and tsx. Optional: scope to a directory.
        files: ^src/
```

JavaScript projects don't need a Python interpreter on developer machines, `pre-commit` itself manages the safelint runtime in an isolated environment. CI integration is the same: drop `safelint check` into your existing GitHub Actions / GitLab CI / etc.

## JavaScript-specific config keys

Each rule that runs on JS has a `_javascript`-suffixed config key parallel to its Python counterpart. Setting these explicitly overrides the active runtime preset.

- **`[tool.safelint.rules.side_effects_hidden]`**, `io_functions_javascript` (e.g. `["log", "error", "fetch", "writeFile"]`)
- **`[tool.safelint.rules.side_effects]`**, `io_functions_javascript`
- **`[tool.safelint.rules.global_mutation]`**, `global_namespaces_javascript` (default depends on preset)
- **`[tool.safelint.rules.resource_lifecycle]`**, `tracked_functions_javascript`
- **`[tool.safelint.rules.missing_assertions]`**, `assertion_calls_javascript`
- **`[tool.safelint.rules.tainted_sink]`**, `sinks_javascript`, `sanitizers_javascript`, `sources_javascript`
- **`[tool.safelint.rules.return_value_ignored]`**, `flagged_calls_javascript`
- **`[tool.safelint.rules.null_dereference]`**, `nullable_methods_javascript`

All of these accept a list of strings; bare-string typos like `"log"` (instead of `["log"]`) raise a clear `TypeError` instead of silently coercing into a set of characters.

## Contributing

Want to refine a rule's JavaScript behaviour, add a runtime preset, or fix a parser edge case? See [Adding a language](../contributing/adding-a-language.md) for the architecture overview, or open an issue / PR against the [main repo](https://github.com/shelkesays/safelint). TypeScript (including TSX and AssemblyScript) reuses this infrastructure end-to-end, see the [TypeScript language page](typescript.md) for the per-language notes.
