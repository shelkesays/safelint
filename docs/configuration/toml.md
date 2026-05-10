# Configuration file

SafeLint is configured via `[tool.safelint]` in your `pyproject.toml`, or a standalone `safelint.toml` in your project root (TOML keys at the top level — no `[tool.safelint]` wrapper). When both files are present, `safelint.toml` wins.

All keys are optional — anything you leave out falls back to the built-in defaults.

For per-rule TOML options (`[tool.safelint.rules.<name>]`) see the [Rules reference](rules.md). For in-source suppression (`# nosafe`, `# safelint: ignore`) see [Suppression mechanisms](suppression.md).

## Top-level options

| Key | Default | What it does |
|---|---|---|
| `mode` | `"local"` | Sets the default failure threshold. `"local"` = only errors block. `"ci"` = warnings block too. |
| `fail_on` | `"error"` | Minimum severity that blocks the run. `"error"` or `"warning"`. Overrides `mode`. |
| `exclude_paths` | `[]` | Glob patterns for files to skip entirely, e.g. `["tests/**", "migrations/**"]`. |
| `ignore` | `[]` | List of rule codes or names to suppress globally across the entire project. |
| `per_file_ignores` | `{}` | Map of glob pattern → list of codes/names to suppress only for matching files. |
| `max_file_size_bytes` | `5242880` (5 MiB) | Skip files larger than this many bytes with a `safelint: warning:` diagnostic instead of trying to parse them. Guards against OOM on accidentally-huge inputs (binary blobs masquerading as `.py`, very large generated parsers). To allow larger files, raise the bound explicitly — `0` is rejected as a likely typo and falls back to the default with a warning, since `0` would defeat the OOM guard entirely. Must be a non-negative integer. |

```toml
[tool.safelint]
mode = "local"
fail_on = "error"
exclude_paths = ["tests/**", "docs/**"]
ignore = ["SAFE203", "side_effects"]
max_file_size_bytes = 5242880   # 5 MiB; raise explicitly to allow larger files

[tool.safelint.per_file_ignores]
"tests/**" = ["SAFE101", "SAFE103"]
```

## Global ignore list

The `ignore` key lets you suppress one or more rules project-wide without touching each rule's own config section. Both rule codes (e.g. `SAFE101`) and rule names (e.g. `function_length`) are accepted and can be mixed.

```toml
# pyproject.toml
[tool.safelint]
ignore = ["SAFE203", "SAFE304", "side_effects_hidden"]
```

```toml
# safelint.toml (standalone — no [tool.safelint] wrapper)
ignore = ["SAFE203", "SAFE304", "side_effects_hidden"]
```

Rules in the `ignore` list are skipped entirely — they produce no violations and add no overhead.

### `extend_ignore` — grow the list without redeclaring it (1.8.0)

When you only want to *add* to the project's existing ignore list (rather than replace it), use `extend_ignore`. SafeLint folds it into `ignore` at config-load time — downstream consumers only see the merged result.

```toml
[tool.safelint]
ignore = ["SAFE701"]               # baseline ignores
extend_ignore = ["SAFE702", "SAFE801"]   # appended to the above
# Resolved at runtime → ignore = ["SAFE701", "SAFE702", "SAFE801"]
```

This is especially useful in layered configs (e.g. one `safelint.toml` for the project and a developer's local override) — you can extend without losing the baseline.

The same pattern applies to per-file ignores: `extend_per_file_ignores` merges into `per_file_ignores` per glob pattern (entries for an existing pattern are concatenated and deduped; new patterns are added).

In `pyproject.toml`, both keys must live under the fully-qualified `[tool.safelint.*]` table — bare `[per_file_ignores]` would be parsed as a top-level table, not as a child of `[tool.safelint]`:

```toml
[tool.safelint.per_file_ignores]
"tests/**" = ["SAFE101"]

[tool.safelint.extend_per_file_ignores]
"tests/**" = ["SAFE102"]      # tests/** ends up with SAFE101 + SAFE102
"docs/**" = ["SAFE601"]       # new pattern added wholesale
```

In a standalone `safelint.toml` (no `[tool.safelint]` wrapper), drop the prefix:

```toml
[per_file_ignores]
"tests/**" = ["SAFE101"]

[extend_per_file_ignores]
"tests/**" = ["SAFE102"]
"docs/**" = ["SAFE601"]
```

### `ignore` vs. per-rule `enabled: false`

Both achieve the same result, but they serve different purposes:

| | `ignore` | `enabled: false` |
|---|---|---|
| Location | Single top-level list | Inside each rule's own section |
| Accepts | Code or name | — (the key is the name) |
| Best for | Quick, temporary suppression; CI overrides; onboarding | Permanent project policy for a specific rule |
| `--ignore` CLI flag | Yes — stacks on top of the config list | No CLI equivalent |

Use `ignore` (or `--ignore`) when you want to suppress a rule without committing to a permanent config change for that rule. Use `enabled: false` when the rule simply does not apply to your project.

### `--ignore` CLI flag

Pass codes or names on the command line to suppress rules for a single run. These stack on top of whatever is already in the config file's `ignore` list — they do not replace it.

```bash
# Ignore two rules for this run only
safelint check src/ --ignore SAFE203 --ignore side_effects

# Useful in CI to temporarily unblock a branch
safelint check src/ --all-files --fail-on=warning --ignore SAFE801
```

## Per-file ignore list

The `per_file_ignores` key suppresses specific rules for files matching a glob pattern. Unlike the global `ignore` list (which skips rules entirely), per-file ignores let rules run on most of the codebase while silencing them for particular directories or file types.

```toml
# pyproject.toml
[tool.safelint.per_file_ignores]
"tests/**"      = ["SAFE101", "SAFE103", "missing_assertions"]
"migrations/**" = ["SAFE201", "SAFE202"]
"src/legacy/**" = ["SAFE301", "SAFE302", "complexity"]
```

```toml
# safelint.toml (standalone)
[per_file_ignores]
"tests/**"      = ["SAFE101", "SAFE103", "missing_assertions"]
"migrations/**" = ["SAFE201", "SAFE202"]
"src/legacy/**" = ["SAFE301", "SAFE302", "complexity"]
```

Both rule codes (e.g. `SAFE101`) and rule names (e.g. `function_length`) are accepted and can be mixed in the same list. Multiple patterns can match a file — their ignore lists are unioned. Suppressed violations are counted in the end-of-run summary alongside `# nosafe` suppressions.

Patterns follow shell-glob semantics via Python's `fnmatch` module, where `**` matches any number of path segments (including zero), `*` matches within a single segment, and matching is case-sensitive on all platforms. The same dialect applies to `exclude_paths`.

### How it differs from other suppression mechanisms

| Mechanism | Scope | Rule runs? | Counted as suppressed? |
|---|---|---|---|
| `enabled: false` | Project-wide | No | No |
| `ignore` | Project-wide | No | No |
| `per_file_ignores` | Matching files only | Yes | Yes |
| `# nosafe` | One line | Yes | Yes |
| `exclude_paths` | Matching files only | No (file skipped) | No |

Use `per_file_ignores` when a rule is valid for production code but noise in a specific context — for example, test files deliberately use many assertions and long helper functions, or legacy files are under active migration and you do not want to fix every violation before merging.

## Execution options

| Key | Default | What it does |
|---|---|---|
| `fail_fast` | `false` | Stop checking a file as soon as the first violation is found. Faster, but you only see one problem at a time. |
| `order` | see [Rules reference](rules.md) | The order rules run in. Cheap structural rules run first so expensive dataflow checks are skipped when basics already fail. |

```toml
[tool.safelint.execution]
fail_fast = false
```

## Severity model

Every rule has a `severity` setting (`"error"` or `"warning"`). The global `fail_on` threshold controls what actually blocks a commit or CI run:

| `fail_on` | Blocks on | Use case |
|---|---|---|
| `"error"` | errors only | Default — good for onboarding a team |
| `"warning"` | errors and warnings | Strict — recommended for CI |

The `mode` setting is a shorthand:

- `mode = "local"` → `fail_on` defaults to `"error"`
- `mode = "ci"` → `fail_on` defaults to `"warning"`

CLI `--fail-on` always takes priority over the config file.

## JavaScript runtime presets

JavaScript source is the same regardless of where it runs (Node.js, browser, Deno, Cloudflare Workers, Bun, WASM-hosted JS engines), but the *APIs* it interacts with differ. The `[tool.safelint.javascript]` table selects which API surface the JavaScript rule defaults assume — sinks for taint analysis, tracked acquirers for resource-lifecycle, global namespaces for globals, etc.

```toml
# pyproject.toml
[tool.safelint.javascript]
runtime = "browser"   # or "node" (default) / "deno" / "cloudflare-workers" / "bun"
```

In a standalone `safelint.toml` (no `[tool.safelint]` wrapper), drop the prefix — the table name is just `[javascript]`:

```toml
# safelint.toml (standalone — no [tool.safelint] wrapper)
[javascript]
runtime = "browser"
```

| Runtime | When to pick it | What changes |
|---|---|---|
| `node` (default) | Backend Node.js apps, CLIs, serverless functions running on Node-compatible runtimes | Node `fs` / `child_process` / `process` / streams. The `_javascript` config-key defaults you see in the [Rules reference](rules.md). |
| `browser` | Browser-side JS, ES module bundles, anything running in a `<script>` or via a bundler targeting browsers | Web APIs only. DOM lookups (`getElementById`, `querySelector`) for SAFE803; observers, Workers, WebSocket, ReadableStream for SAFE401; `localStorage` / `addEventListener` / `postMessage` for SAFE802; `globalThis` / `window` / `self` / `document` global namespaces for SAFE302. Drops Node `fs` and `child_process` entirely. |
| `deno` | Deno scripts and Deno Deploy applications | `Deno.*` API surface. `Deno.open` / `Deno.connect` / `Deno.listen` for SAFE401; `Deno.run` / `Deno.Command` for SAFE801; `Deno` added to global namespaces; `process` and `window` dropped. |
| `cloudflare-workers` | Cloudflare Workers (V8 isolates); also a reasonable starting point for other Web-API-only edge runtimes | KV / R2 / Durable Object methods (`put` / `delete` / `get` for SAFE802 and SAFE803), `Request` body methods (`json` / `formData` / `arrayBuffer` / `blob`) as taint sources, minimal global-namespace list. No `fs` surface. |
| `bun` | Bun runtime | Node defaults plus Bun-specific extras (`Bun.serve`, `Bun.spawn`). |

User-explicit `_javascript` config keys still win over the preset — the preset only changes the *default* list, not your overrides:

```toml
[tool.safelint.javascript]
runtime = "browser"

[tool.safelint.rules.tainted_sink]
sinks_javascript = ["eval", "Function", "myCustomDangerousFunction"]   # overrides the browser preset
```

Unknown runtime names surface a `safelint: warning:` line on stderr and fall back to `node`. Pure WebAssembly (`.wat` / `.wasm`) and AssemblyScript are out of scope for this configuration — they would land as separate `LanguageDefinition` registrations, not as JavaScript runtimes.

Source-language analysis itself (the parser, the AST walks, the per-rule logic) is identical across runtimes — only the *defaults* change.

## Adoption path

If you are adding SafeLint to an existing project with many existing violations, start permissive and tighten over time:

```text
Week 1  - mode: local,  fail_on: error    - get used to the tool, fix errors only
Week 4  - mode: ci,     fail_on: warning  - enforce warnings in CI
Later   - enable tainted_sink, return_value_ignored, null_dereference as needed
```
