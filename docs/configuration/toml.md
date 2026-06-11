# Configuration file

SafeLint is configured via `[tool.safelint]` in your `pyproject.toml`, or a standalone `safelint.toml` in your project root (TOML keys at the top level, no `[tool.safelint]` wrapper). When both files are present, `safelint.toml` wins.

All keys are optional, anything you leave out falls back to the built-in defaults.

For per-rule TOML options (`[tool.safelint.rules.<name>]`) see the [Rules reference](rules.md). For in-source suppression (`# nosafe`, `# safelint: ignore`) see [Suppression mechanisms](suppression.md).

## Top-level options

| Key | Default | What it does |
|---|---|---|
| `mode` | `"local"` | Sets the default failure threshold. `"local"` = only errors block. `"ci"` = warnings block too. |
| `fail_on` | `"error"` | Minimum severity that blocks the run. `"error"` or `"warning"`. Overrides `mode`. |
| `exclude_paths` | (see [defaults](#default-exclude-paths)) | Glob patterns for files / directories to skip entirely. **Setting this in your config REPLACES the built-in defaults**, use `extend_exclude_paths` instead if you want to keep them. |
| `extend_exclude_paths` | `[]` | Glob patterns appended to whatever `exclude_paths` resolves to. Use this for project-specific excludes when you want to keep the vendor-dir defaults active. |
| `ignore` | `[]` | List of rule codes or names to suppress globally across the entire project. |
| `per_file_ignores` | `{}` | Map of glob pattern → list of codes/names to suppress only for matching files. |
| `max_file_size_bytes` | `5242880` (5 MiB) | Skip files larger than this many bytes with a `safelint: warning:` diagnostic instead of trying to parse them. Guards against OOM on accidentally-huge inputs (binary blobs masquerading as `.py`, very large generated parsers). To allow larger files, raise the bound explicitly, `0` is rejected as a likely typo and falls back to the default with a warning, since `0` would defeat the OOM guard entirely. Must be a non-negative integer. |

```toml
[tool.safelint]
mode = "local"
fail_on = "error"
# Keep the built-in vendor-dir defaults AND add tests/docs:
extend_exclude_paths = ["tests/**", "docs/**"]
ignore = ["SAFE203", "side_effects"]
max_file_size_bytes = 5242880   # 5 MiB; raise explicitly to allow larger files

[tool.safelint.per_file_ignores]
"tests/**" = ["SAFE101", "SAFE103"]
```

## Default exclude paths

SafeLint ships a built-in list of vendor and generated directories that almost no project wants linted. These are pruned during file discovery, `os.walk` doesn't even descend into them, so the cost of having them excluded is essentially free.

**Built-in defaults** (each name expands to two patterns, `<name>/**` for top-level and `**/<name>/**` for nested occurrences):

- **Python virtual environments:** `.venv`, `venv`
- **Python test / build tooling:** `.tox`, `.nox`
- **Python caches:** `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.ty_cache`
- **Python build outputs:** `build`, `dist`
- **Coverage outputs:** `htmlcov`
- **JavaScript / Node:** `node_modules`
- **Site packages:** `site-packages` (defensive, sometimes pip installs into the project tree)

### Two config keys: `exclude_paths` and `extend_exclude_paths`

SafeLint lets you customise which directories are excluded through two TOML keys. **Both can coexist.** The right one to use depends on what you want to achieve. Here are the four scenarios you're likely to hit, ordered from most to least common:

#### Scenario 1: "I want to keep the defaults and add my own dirs" → use `extend_exclude_paths`

This is the **most common case**. SafeLint keeps excluding `.venv/`, `node_modules/`, `build/`, `dist/`, etc. (the built-in defaults above), and your patterns are added on top. Nothing is lost; everything you specify is added.

```toml
# pyproject.toml: common case
[tool.safelint]
# .venv/, node_modules/, build/, dist/, __pycache__/, etc. STILL excluded
# (built-in defaults preserved). Your additions stack on top.
extend_exclude_paths = ["tests/**", "generated/**"]
```

#### Scenario 2: "I want full control: define exactly what's excluded, ignore the defaults" → use `exclude_paths`

Setting `exclude_paths` **replaces** the built-in defaults entirely. The list you supply IS the final list. SafeLint stops excluding `.venv/`, `node_modules/`, etc. unless you list them yourself.

```toml
# pyproject.toml: power-user case
[tool.safelint]
# Built-in defaults REPLACED. SafeLint now only excludes what's in this list.
# Note: .venv/ and node_modules/ are no longer excluded: add them yourself
# if you don't want them linted.
exclude_paths = ["build/**", "dist/**", "**/.venv/**", "**/node_modules/**"]
```

#### Scenario 3: "I want to lint files inside normally-excluded directories" (rare) → use `exclude_paths = []`

Setting `exclude_paths` to an empty list explicitly clears every default. SafeLint walks into everything. Useful when you genuinely want to audit, say, a vendored library inside `.venv/`.

```toml
# pyproject.toml: opt out of all defaults
[tool.safelint]
exclude_paths = []   # lints EVERYTHING, including .venv/ if present
```

#### Scenario 4: "I want a custom baseline AND personal additions" (advanced) → use both

Real example: a project's checked-in `safelint.toml` defines a baseline via `exclude_paths`, and individual developers (or overlay configs) add their own dev-only excludes via `extend_exclude_paths` without modifying the project's baseline. The two keys compose, your additions stack on top of whatever `exclude_paths` resolves to.

```toml
# Project's safelint.toml (checked into git)
exclude_paths = ["build/**", "dist/**", "vendor/**"]   # team-wide baseline

# A developer's personal overlay can add:
extend_exclude_paths = ["my-scratch/**", "experiments/**"]   # personal additions
# Final exclude list = ["build/**", "dist/**", "vendor/**", "my-scratch/**", "experiments/**"]
```

### Resolution truth table

For when you need the exact rule, the resolution is:

> **final exclude list = (`exclude_paths` if set, else built-in defaults) + `extend_exclude_paths`**

| `exclude_paths` setting | `extend_exclude_paths` setting | Final exclude list |
|---|---|---|
| (unset) | (unset) | Built-in vendor-dir defaults |
| (unset) | `["generated/**"]` | Defaults + `generated/**` |
| `["build/**"]` | (unset) | Just `build/**` (defaults dropped) |
| `["build/**"]` | `["generated/**"]` | `build/**` + `generated/**` (defaults dropped; both user lists active) |
| `[]` | (unset) | Empty, lints everything |
| `[]` | `["generated/**"]` | Just `generated/**` (defaults dropped, only extend active) |

### Rule of thumb

- **If you can satisfy your needs with `extend_exclude_paths` alone, do that.** Most projects can. You inherit improvements to the built-in defaults automatically (e.g., if a future safelint version adds `.terraform/` to the defaults, your project gets it for free).
- **Reach for `exclude_paths` only when you have a specific reason** to take control of the baseline (auditing vendored code, project policy requires explicit lists, etc.).
- **Combine both when a project baseline and a personal overlay are both needed**, they're additive in the documented order.

## Global ignore list

The `ignore` key lets you suppress one or more rules project-wide without touching each rule's own config section. Both rule codes (e.g. `SAFE101`) and rule names (e.g. `function_length`) are accepted and can be mixed.

```toml
# pyproject.toml
[tool.safelint]
ignore = ["SAFE203", "SAFE304", "side_effects_hidden"]
```

```toml
# safelint.toml (standalone: no [tool.safelint] wrapper)
ignore = ["SAFE203", "SAFE304", "side_effects_hidden"]
```

Rules in the `ignore` list are skipped entirely; they produce no violations and add no overhead.

### `extend_ignore`: grow the list without redeclaring it (1.8.0)

When you only want to *add* to the project's existing ignore list (rather than replace it), use `extend_ignore`. SafeLint folds it into `ignore` at config-load time, downstream consumers only see the merged result.

```toml
[tool.safelint]
ignore = ["SAFE701"]               # baseline ignores
extend_ignore = ["SAFE702", "SAFE801"]   # appended to the above
# Resolved at runtime → ignore = ["SAFE701", "SAFE702", "SAFE801"]
```

This is especially useful in layered configs (e.g. one `safelint.toml` for the project and a developer's local override), you can extend without losing the baseline.

The same pattern applies to per-file ignores: `extend_per_file_ignores` merges into `per_file_ignores` per glob pattern (entries for an existing pattern are concatenated and deduped; new patterns are added).

In `pyproject.toml`, both keys must live under the fully-qualified `[tool.safelint.*]` table, bare `[per_file_ignores]` would be parsed as a top-level table, not as a child of `[tool.safelint]`:

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
| Accepts | Code or name | (the key is the name) |
| Best for | Quick, temporary suppression; CI overrides; onboarding | Permanent project policy for a specific rule |
| `--ignore` CLI flag | Yes, stacks on top of the config list | No CLI equivalent |

Use `ignore` (or `--ignore`) when you want to suppress a rule without committing to a permanent config change for that rule. Use `enabled: false` when the rule simply does not apply to your project.

### `--ignore` CLI flag

Pass codes or names on the command line to suppress rules for a single run. These stack on top of whatever is already in the config file's `ignore` list; they do not replace it.

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

Both rule codes (e.g. `SAFE101`) and rule names (e.g. `function_length`) are accepted and can be mixed in the same list. Multiple patterns can match a file, their ignore lists are unioned. Suppressed violations are counted in the end-of-run summary alongside `# nosafe` suppressions.

Patterns are matched via Python's `fnmatch.fnmatchcase`. The match is **anchored at both ends** (the entire path string must match the pattern) and **case-sensitive on all platforms**. The same matcher applies to `exclude_paths` and `extend_exclude_paths`.

Important, `fnmatch` is not segment-aware:

- **`*`** matches any sequence of characters, **including `/`**. So `*.py` matches not just `foo.py` but also `deep/nested/foo.py`, the `*` happily spans path separators.
- **`**`** has no special meaning in `fnmatch`; it's just `*` written twice and behaves identically to a single `*`. **This is a notable departure from gitignore / shell-glob conventions**, where `**` is the explicit "match across directory boundaries" wildcard. In safelint's matcher, `**` is *not* segment-aware; patterns like `.venv/**` work only because the literal `/` before `**` forces a slash to appear at that position (the `**` itself is just matching the rest of the path the same way a plain `*` would).
- **`?`** matches exactly one character (including `/`).
- **`[abc]`** matches one character from the set.

Practical consequences:

- `"tests/**"` matches anything starting with `tests/` (the literal `tests/` is anchored, then `**` matches the rest). This is what you want.
- `"*.py"` matches any `.py` file at any depth, likely NOT what you want if you intended "only at the top level." **There is no reliable `fnmatch` pattern that means "match only files at the top level of the project."** The engine matches against `Path(filepath).as_posix()`, which normalises away any leading `./` (so a hypothetical `"./*.py"` pattern would never match anything), and `*` already spans `/` (so `"*.py"` already matches at any depth). The practical alternatives when you really need a single-level scope are:
    - **Explicitly list the files on the CLI** (e.g. let your shell expand `*.py` to a concrete file list: `safelint check *.py`).
    - **Exclude the subdirectories you don't want** via `exclude_paths` / `extend_exclude_paths` (e.g. exclude `src/**`, `tests/**`, etc. to leave only top-level files).
- `"**/*.py"` is equivalent to `"*.py"` for the same reason, neither pattern is limited to a single directory level; both match any `.py` file at any depth.
- The vendor-dir defaults ship as `<dir>/**` plus `**/<dir>/**` per entry (see [Default exclude paths](#default-exclude-paths) above) because the literal `/` in each pattern is what does the work, not the `*` / `**` wildcards.

### How it differs from other suppression mechanisms

| Mechanism | Scope | Rule runs? | Counted as suppressed? |
|---|---|---|---|
| `enabled: false` | Project-wide | No | No |
| `ignore` | Project-wide | No | No |
| `per_file_ignores` | Matching files only | Yes | Yes |
| `# nosafe` | One line | Yes | Yes |
| `exclude_paths` / `extend_exclude_paths` | Matching files only | No (file skipped) | No |

Use `per_file_ignores` when a rule is valid for production code but noise in a specific context, for example, test files deliberately use many assertions and long helper functions, or legacy files are under active migration and you do not want to fix every violation before merging.

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
| `"error"` | errors only | Default, good for onboarding a team |
| `"warning"` | errors and warnings | Strict, recommended for CI |

The `mode` setting is a shorthand:

- `mode = "local"` → `fail_on` defaults to `"error"`
- `mode = "ci"` → `fail_on` defaults to `"warning"`

CLI `--fail-on` always takes priority over the config file.

## JavaScript runtime presets

JavaScript source is the same regardless of where it runs (Node.js, browser, Deno, Cloudflare Workers, Bun, WASM-hosted JS engines), but the *APIs* it interacts with differ. The `[tool.safelint.javascript]` table selects which API surface the JavaScript rule defaults assume, sinks for taint analysis, tracked acquirers for resource-lifecycle, global namespaces for globals, etc.

```toml
# pyproject.toml
[tool.safelint.javascript]
runtime = "browser"   # or "node" (default) / "deno" / "cloudflare-workers" / "bun"
```

In a standalone `safelint.toml` (no `[tool.safelint]` wrapper), drop the prefix, the table name is just `[javascript]`:

```toml
# safelint.toml (standalone: no [tool.safelint] wrapper)
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

User-explicit `_javascript` config keys still win over the preset, the preset only changes the *default* list, not your overrides:

```toml
[tool.safelint.javascript]
runtime = "browser"

[tool.safelint.rules.tainted_sink]
sinks_javascript = ["eval", "Function", "myCustomDangerousFunction"]   # overrides the browser preset
```

Unknown runtime names surface a `safelint: warning:` line on stderr and fall back to `node`. Pure WebAssembly (`.wat` / `.wasm`) is out of scope for this configuration. **AssemblyScript** (`.as`) is supported, it parses with the same Tree-sitter grammar as TypeScript and is treated as a TS variant; the runtime preset that applies depends on where the compiled WebAssembly module runs.

Source-language analysis itself (the parser, the AST walks, the per-rule logic) is identical across runtimes, only the *defaults* change.

### TypeScript and the `_javascript` config keys

TypeScript (`.ts` / `.tsx` / `.as` files) **shares the JavaScript runtime presets** because TS compiles to JS at runtime, the sink lists, taint sources, global namespaces, and I/O primitives are properties of the runtime environment, not the source language.

By default, every TS file reads the `_javascript`-suffixed config keys directly:

| TS file reads | when … |
|---|---|
| `<key>_typescript` | the user has set it explicitly (e.g. `sinks_typescript`, `sanitizers_typescript`, `sources_typescript`) |
| `<key>_javascript` | `<key>_typescript` is unset (the default, TS inherits the JS list for every key listed below) |
| (the rule's built-in default) | neither is set |

Same precedence applies to every other `_javascript`-suffixed key (`sanitizers_javascript`, `sources_javascript`, `tracked_functions_javascript`, `global_namespaces_javascript`, `io_functions_javascript`, `assertion_calls_javascript`, `nullable_methods_javascript`, `flagged_calls_javascript`).

**Most projects don't need TS-specific config.** TS inherits JS defaults / overrides automatically, running `safelint check src/` on a mixed `.js` / `.ts` codebase gives the right behaviour out of the box. Set `_typescript`-suffixed keys only when you have a concrete reason for `.ts` files to behave differently from `.js` files in the same project (a stricter sink list for new TS code, a different test-framework's assertion functions, etc.).

**Typical project**, no TS-specific config needed. Both `.js` and `.ts` files use the same sink list via the TS → JS fallback:

```toml
# pyproject.toml
[tool.safelint.javascript]
runtime = "node"

[tool.safelint.rules.tainted_sink]
sinks_javascript = ["eval", "Function", "myCustomDangerousFunction"]
# .ts files inherit this list automatically: no _typescript key needed.
```

**Rare**, a project wants a stricter sink list for TS only, while legacy JS keeps its existing list. Set both keys; the `_typescript` key is consulted first for `.ts` files:

```toml
# pyproject.toml
[tool.safelint.rules.tainted_sink]
sinks_javascript = ["eval", "Function"]                                # legacy JS
sinks_typescript = ["eval", "Function", "Object.assign", "innerHTML"]  # stricter for TS
```

(Two separate snippets above, each is a complete, self-contained pyproject excerpt. Don't paste them into the same `[tool.safelint.rules.tainted_sink]` block: TOML rejects duplicate table headers, and the rule's config is *one* table no matter how many language-suffixed keys it carries.)

## Java framework presets

Java source is framework-agnostic to parse, but the *defaults* baked into the rules (taint sinks, nullable methods, and which structural rules are active) shift with the framework. The `[tool.safelint.java]` table selects the preset:

```toml
# pyproject.toml
[tool.safelint.java]
framework = "spring-boot"   # or "vanilla" (default)
```

In a standalone `safelint.toml` (no `[tool.safelint]` wrapper), drop the prefix, the table name is just `[java]`:

```toml
# safelint.toml (standalone: no [tool.safelint] wrapper)
[java]
framework = "spring-boot"
```

| Framework | When to pick it | What changes |
|---|---|---|
| `vanilla` (default) | Plain Java, Jakarta EE, Android, Spring-free libraries | Stdlib-only defaults. The four `SAFE901-904` Spring rules stay disabled. |
| `spring-boot` | Spring Boot 2.x / 3.x apps (Spring MVC, Spring Data JPA, Spring JDBC, Spring WebFlux) | Adds unambiguous `JdbcTemplate` / `RestTemplate` methods to SAFE801 sinks (`query*` / `batchUpdate` / `*ForObject` / `*ForEntity` / `postForLocation` / `patchForObject`), adds `queryForObject` to SAFE803 nullable methods, and **enables the four `SAFE901-904` Spring structural rules**. |

The preset only changes *defaults*, an explicit `[tool.safelint.rules.tainted_sink] sinks_java = [...]` still wins. Unknown framework names surface a `safelint: warning:` line on stderr and fall back to `vanilla`. See the [Java language page](../languages/java.md#framework-presets) for the full per-rule effect.

## Adoption path

If you are adding SafeLint to an existing project with many existing violations, start permissive and tighten over time:

```text
Week 1  - mode: local,  fail_on: error    - get used to the tool, fix errors only
Week 4  - mode: ci,     fail_on: warning  - enforce warnings in CI
Later   - enable opt-in rules as needed:
          - dataflow:   tainted_sink, return_value_ignored, null_dereference
          - rule 8/10:  dynamic_code_execution, blanket_suppression (all languages)
          - Rust:       interior_mutable_static and the other Rust-only rules
          - test discipline: missing_assertions (set min_assertions = 2 for the
                        Holzmann density), test_existence, test_coupling
```

All of these are off by default; see the [Rules reference](rules.md) for each rule's config knobs. `no_recursion` (SAFE105) is the one new rule that is **on by default** (at `warning` severity), so no opt-in step is needed for it.
