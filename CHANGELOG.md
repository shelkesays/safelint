# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.13.0] - 2026-05-09

**JavaScript (Node) is now a supported language alongside Python.** Registry-driven multi-language support: `.js` / `.mjs` / `.cjs` files are discovered, parsed via Tree-sitter, and run against 17 of the 19 existing rules — plus one new JS-only rule (SAFE305 `wide_scope_declaration`) for a total of 20 rules safelint now ships. Python users see no behaviour change beyond the v1.12.2 `.pyw` bugfix; the additive language work is what justifies this release as `1.13.0` (per the project's semver rules: scope expansion is MINOR, never MAJOR).

### Added

- **`safelint.languages.javascript`** — new module registering JavaScript with `LanguageDefinition(name="javascript", file_extensions=frozenset({".js", ".mjs", ".cjs"}), comment_node_type="comment", comment_prefix="//")`. Plus the JS Tree-sitter node-type constants every rule needs (function/control-flow/expression/statement/pattern types).
- **`tree-sitter-javascript>=0.23.0`** runtime dependency. Peer of the existing `tree-sitter-python` dep.
- **`safelint.analysis.dataflow_javascript`** — new module with `JsTaintTracker`, the JavaScript counterpart of the Python `TaintTracker`. Same public surface; per-language node-type vocabulary internally. Handles `const` / `let` / `var` declarations, `assignment_expression` / `augmented_assignment_expression`, template-string interpolation (`\`${expr}\``), destructuring (array / object / rest / pair patterns), spread elements, member / subscript propagation, and the `assume_taint_preserving` knob.
- **17 rules now lint JavaScript** with `language=("python", "javascript")`:
  - **Structural:** `function_length` (SAFE101), `nesting_depth` (SAFE102), `max_arguments` (SAFE103), `complexity` (SAFE104).
  - **Error handling + side-effects:** `empty_except` (SAFE202 — JS empty catch), `logging_on_error` (SAFE203 — recognises `console.*` and generic `logger.*` plus `throw <id>;` as re-raise), `side_effects_hidden` (SAFE303), `side_effects` (SAFE304).
  - **State purity:** `global_mutation` (SAFE302 — fires on function-body assignments to `globalThis.*` / `window.*` / `global.*` / `self.*` / `process.env.*` and similar configurable namespaces; reading a global is fine; module-level assignments are exempt as legitimate setup).
  - **Loop / tests / assertions:** `unbounded_loops` (SAFE501 — only the `while (true)` no-break case fires on JS; the non-comparison-condition heuristic stays Python-only), `missing_assertions` (SAFE601 — walks for *calls* to `assert` / `expect` / `console.assert` / Node's `assert.*` helpers), `test_existence` (SAFE701) and `test_coupling` (SAFE702 — pair Python `test_<stem>.py` *and* JS `<stem>.test.{js,mjs,cjs}` / `<stem>.spec.{js,mjs,cjs}`).
  - **Resource safety:** `resource_lifecycle` (SAFE401 — fires on calls to configurable acquirer names — `createReadStream`, `createWriteStream`, `openSync`, `createServer`, `connect`, etc. — that aren't enclosed in a `try { ... } finally { ... }` somewhere up the AST chain; heuristic-only, doesn't verify that the finally actually closes the resource).
  - **Dataflow:** `tainted_sink` (SAFE801), `return_value_ignored` (SAFE802), `null_dereference` (SAFE803 — recognises optional chaining `foo?.bar` as the safe form, exempt from the rule).
- **New JavaScript-only rule:** `wide_scope_declaration` (SAFE305) flags every `var` declaration. Holzmann Power-of-Ten Rule 6 ("declare variables at the smallest possible scope") translated to JS's actual scope-control mechanism — `var` is function-scoped (hoisted across blocks), `let` / `const` are block-scoped (the narrower scope). Fires on top-level `var`, function-body `var`, block-level `var`, multi-binding `var x = 1, y = 2;` (single violation per declaration node — the line is the unit of fix), and `for (var i = 0; ...)`. Python has no `var` / `let` / `const` distinction; the rule is registered with `language = ("javascript",)` and the engine's per-language dispatch correctly skips it on `.py` / `.pyw` files. Default enabled, severity `warning`.
- **JavaScript runtime presets** — new `[tool.safelint.javascript] runtime = "<name>"` config key selects which API surface the JS rule defaults assume. Five presets ship: `node` (default — current behaviour), `browser` (Web APIs / DOM / `localStorage` / observers; drops Node `fs`), `deno` (`Deno.*` APIs; drops `process` / `window`), `cloudflare-workers` (Workers Runtime: KV / R2 / Durable Objects / `Request` body methods; minimal global-namespace list), and `bun` (Node-compatible plus `Bun.serve` / `Bun.spawn`). Affects defaults for SAFE302 (`global_namespaces_javascript`), SAFE303 / SAFE304 (`io_functions_javascript`), SAFE401 (`tracked_functions_javascript`), SAFE801 (`sinks_javascript` / `sources_javascript`), SAFE802 (`flagged_calls_javascript`), and SAFE803 (`nullable_methods_javascript`). User-explicit `_javascript` config keys still win over the preset. Unknown runtime names warn on stderr and fall back to `node`. Source is the same JS regardless of runtime — only the rule defaults shift, not the parser or rule logic.
- **Per-language config keys** (additive — existing user TOMLs unchanged):
  - `[tool.safelint.rules.side_effects_hidden]` and `[...].side_effects` get `io_functions_javascript`.
  - `[...].missing_assertions]` gets `assertion_calls_javascript`.
  - `[...].tainted_sink]` gets `sinks_javascript`, `sanitizers_javascript`, `sources_javascript`.
  - `[...].return_value_ignored]` gets `flagged_calls_javascript`.
  - `[...].null_dereference]` gets `nullable_methods_javascript`.
  - `[...].global_mutation]` gets `global_namespaces_javascript`.
  - `[...].resource_lifecycle]` gets `tracked_functions_javascript`.
- **`CALL_TYPES`** frozenset and **`resolve_lang_name`** helper in `safelint.languages._node_utils` — cross-language utilities used by the widened rules.
- **Bundled AI-client skills** — `src/safelint/skill_files/languages/javascript.md` (the JS shared addendum) ships a full per-rule notes table, idiomatic-fix patterns for each of the 15 ported rules, and the "rules that stay Python-only" reference. All 12 client docs (Claude Code's `SKILL.md`, Cursor's `cursor/safelint.mdc`, GitHub Copilot's `copilot/copilot-instructions.md`, Gemini's `gemini/GEMINI.md`, Windsurf's `windsurf/safelint-rules.md`, codex's `codex/instructions.md`, Continue.dev's `continue/safelint.md`, Cline's `cline/safelint.md`, aider's `aider/CONVENTIONS.md`, Trae's `trae/safelint.md`, Antigravity's `antigravity/safelint.md`, Zed's `zed/safelint.md`) gained a JavaScript row in their **Step 2 — Identify the language(s) involved** registry tables.
- **115 new tests** distributed across per-rule JS test files (`tests/rules/test_*_javascript.py`) and the engine-level smoke test file (`tests/core/test_engine_javascript.py`). Total: 764 tests pass at 97.25% coverage.

### Changed

- **Pre-commit hook spec** (`.pre-commit-hooks.yaml`) and **the in-tree self-development hook** (`.pre-commit-config.yaml`) — `types_or: [python]` becomes `types_or: [python, javascript]`. Downstream users with mixed Python + JS repos automatically have both filetypes routed to safelint after upgrade.
- **`call_name`** in `_node_utils.py` extended (during Slice 3) to handle JavaScript `member_expression` (`obj.method(...)`) alongside Python `attribute` (`obj.method(...)`). Both `foo(...)` forms (bare identifier function calls) continue to resolve via the existing `identifier` branch.

### Stays Python-only (by design)

Two rules don't have a useful JavaScript translation and remain registered for Python only — they will not fire on `.js` / `.mjs` / `.cjs` files. The decision rationale lives in `src/safelint/skill_files/languages/javascript.md` "Rules that stay Python-only".

- **SAFE201 `bare_except`** — Python `except:` (no exception type) silently catches `KeyboardInterrupt` and `SystemExit`. JavaScript `try/catch` always catches every throw type by language design; the Python-specific process-signal hazard doesn't exist. SAFE202 (empty catch) + SAFE203 (catch must log) cover the related JS concerns.
- **SAFE301 `global_state`** — Python rule fires on the `global` keyword regardless of whether a write follows. JavaScript has no read-only-global declaration form; on JS the rule would always be a strict subset of SAFE302. JS users get the same protection from SAFE302 (global_mutation) alone.

### Behaviour changes (heads-up)

- **JS-only projects** — anyone who had `safelint check` running on a Python repo with stray `.js` files: those files will now be discovered, parsed, and linted (most rules will fire). If that's not what you want, scope-suppress with `[tool.safelint.per_file_ignores]` keyed on the `.js` glob, or set `enabled = false` per rule.
- **Mixed Python + JS projects** — both file types now flow through pre-commit and `safelint check` automatically. The 15 widened rules apply to both languages with their per-language defaults.
- **Pure-Python projects** — no behaviour change. Every rule's Python codepath is byte-equivalent to v1.12.2.

### Limitations documented for future enhancement

- **Block-style `nosafe` directives** (`/* nosafe */`) are not recognised — only line-style `// nosafe` and `// safelint: ignore`. Documented in the JS shared addendum and `docs/contributing/adding-a-language.md` Step 4.
- **JSX (`.jsx`)** is not registered. `tree-sitter-javascript` parses some JSX leniently as a superset, but flagging it as a separate language registration later avoids accidental drift in rule semantics.
- **TypeScript (`.ts` / `.tsx`)** is a separate language addition — not in this release.
- **Arrow-function naming via variable binding** (`const getX = () => ...`) — the rules that read function names via `func_node.child_by_field_name("name")` don't resolve through the parent `variable_declarator`. SAFE303 (pure-named function with hidden I/O) doesn't fire on `getX = () => console.log(...)`. Documented limitation; can be enhanced later by walking up to the binding.

## [1.12.2] - 2026-05-09

Completion of the multi-language readiness work started in v1.12.1. The engine, cache, suppression parser, file discovery, and per-rule dispatch were already registry-driven, but three CLI helpers and the published pre-commit hook spec still hard-coded `.py`. With this release every supported-extension check reads from `safelint.languages.supported_extensions()`, so registering a new language is genuinely additive — drop a `LanguageDefinition` into `languages/<lang>.py`, append it to the registry loop, append the new filetype tag to `types_or` in `.pre-commit-hooks.yaml`, and the CLI discovers it everywhere automatically.

`tuple(supported_extensions())` now contains `.py` and `.pyw` (the registry is a `frozenset`, so iteration order isn't guaranteed); `types_or: [python]` is identical in semantics to the previous `types: [python]` for downstream pre-commit users.

### Fixed

- **`.pyw` files now picked up by git-modified mode and the pre-commit hook.** The old CLI helpers used `str.endswith(".py")` for filtering, which silently dropped `.pyw` files (`"foo.pyw".endswith(".py")` is `False`). The engine's `--all-files` discovery loop already used the registry and handled `.pyw` correctly, so this only affected git-modified runs (`safelint check src/`) and pre-commit hook mode. Existing `.pyw` projects that were getting clean runs in those modes may now see previously-hidden violations on those files; if that's unwelcome on a transitional codebase, scope-suppress with `[tool.safelint.per_file_ignores]` keyed on a `*.pyw` glob.

### Changed (internal — registry-driven)

- **CLI git-status filters now read from the registry.** `_collect_all_py_files` and `_filter_py_files` in `src/safelint/cli.py` are renamed to `_collect_all_supported_files` and `_filter_supported_files` respectively, and both now build `exts = tuple(supported_extensions())` once per call to drive the `str.endswith` check. The hook-mode pre-filter at the bottom of `main()` (`[f for f in args.files if f.endswith(".py")]`) reads from the registry too. So `safelint` invoked by pre-commit with mixed Python + (future) TypeScript files accepts both rather than silently dropping the non-Python ones.
- **Published pre-commit hook spec uses `types_or`.** `.pre-commit-hooks.yaml` previously declared `types: [python]`. Switched to `types_or: [python]` so the add-a-language edit becomes a one-line append (`- ts`) instead of a schema change. Description generalised from "Python files" to "source files"; an inline comment marks `language: python` as the hook *runtime* (a real source of confusion in pre-commit configs), not the language being linted.

### Changed (docs)

- **`docs/contributing/adding-a-language.md`** gains an explicit **Step 6 — Update CLI / pre-commit plumbing** that lists the surfaces reading from the registry vs. the one place still requiring a manual edit (the `types_or` line in `.pre-commit-hooks.yaml`). Old Step 6 (tests + docs) is now Step 7; old Step 7 (bundled AI-client skills) is now Step 8.

### Behaviour changes (heads-up)

- **`.pyw` projects** — see *Fixed* above. The bugfix is genuine, but if your `.pyw` files have been quietly accumulating violations because git-modified mode and the pre-commit hook were skipping them, you'll see those surface on the first `safelint check` after upgrade. Workaround if you need a transitional grace period: scope-suppress with `[tool.safelint.per_file_ignores]` keyed on `**/*.pyw`.
- **Pure-`.py` projects** — no change. The renamed CLI helpers are private (underscore-prefixed); the `types_or` change is single-element today, so downstream pre-commit users see no difference until a second filetype tag lands.

## [1.12.1] - 2026-05-09

A small follow-on to v1.12.0. One user-visible bug fix, one perf optimisation, an internal-API cleanup, and pre-emptive engine plumbing for the eventual second-language work. No behaviour change for current users beyond the bug fix.

### Fixed

- **`per_file_ignores = ["*"]` no longer triggers a spurious typo-guard warning.** v1.12.0 added the `"*"` wildcard as a documented blanket-suppress mechanism in toml `per_file_ignores`, but the validation pass in `_parse_per_file_ignores` still treated `"*"` as an unknown entry and emitted `safelint: warning: unknown entries in per_file_ignores...` for the exact value the docs tell users to use. The validation now exempts `"*"` while preserving the typo guard for genuinely unknown codes/names. The pre-existing wildcard test was extended to capture stderr and assert the absence of the warning, so any future regression here surfaces in CI.

### Changed (internal)

- **Single-pass directive parsing.** `_parse_suppressions` (line-level `# nosafe`) and `_parse_file_level_ignores` (file-level `# safelint: ignore`) used to walk the Tree-sitter tree independently — two full passes per file. New `_parse_directives` helper folds both into one O(N) pass; on a 5000-line generated file (a primary use case for file-level ignores), this halves the per-file walk cost. Behaviour is bit-for-bit identical to the two-pass version. The two original helpers are kept as thin wrappers so the existing unit tests in `tests/core/test_suppression.py` continue to work without changes.
- **`_merge_in_file_directives` signature cleanup.** The boolean parameter was forcing surrounding mandatory non-bool params into keyword-only territory unnecessarily. Reordered so only the boolean is keyword-only, matching Python convention (positional mandatory params first, then `*`, then keyword-only).

### Added (pre-emptive — dormant until a second language lands)

- **`BaseRule.language: tuple[str, ...] = ("python",)`** — new class attribute that the engine consults in `_run_rules` before dispatching `check_file`. Rules whose `language` tuple doesn't include the active file's `LanguageDefinition.name` are skipped. Today every rule defaults to `("python",)` and Python is the only registered language, so the filter is a no-op for current usage. The plumbing is the engine half of the per-language dispatch contract documented in `ADDING_A_LANGUAGE.md`; the per-rule audit (which existing rules port cross-language vs. stay Python-only) is per-rule work that ships *with* each new language. Adding TypeScript / Go / Rust now requires only registering a new `LanguageDefinition` and widening `language` on the rules that port — no engine changes.
- 4 new dispatch tests in `tests/core/test_engine.py`: filter skips Python-only rules on a hypothetical-language file (via a monkeypatched fake `LanguageDefinition`), filter doesn't accidentally skip Python rules on Python files (regression guard), `BaseRule.language` default is pinned, every registered rule still inherits the default.

### Behaviour changes (heads-up)

- **None for end-users.** The `"*"` typo-guard fix removes an erroneous warning; the perf and signature-cleanup work is invisible; the dispatch infrastructure is dormant. End-to-end behaviour for `safelint check` and `safelint skill *` commands is identical to v1.12.0.

## [1.12.0] - 2026-05-08

A focused feature release on top of v1.11.0. The suppression model grows from three layers to four with a new in-file `# safelint: ignore` directive that lets users silence rules for a whole file from inside the file itself — matching the established pattern from ruff (`# ruff: noqa`), flake8 (`# flake8: noqa`), pylint (`# pylint: disable=`), and mypy (`# type: ignore`).

### Added

- **In-file `# safelint: ignore` directive** — file-scope suppression placed as a top-of-file (or anywhere alone-on-its-line) comment. Three forms:
  ```python
  # safelint: ignore                        # suppress every rule for this file
  # safelint: ignore: SAFE101               # suppress one code
  # safelint: ignore: SAFE101, SAFE304      # suppress multiple
  # safelint: ignore: function_length       # by rule name (equivalent to the code form)
  ```
  Best for the case "this whole file is intentionally violating" — auto-generated code, fixtures, vendor adapters — where toml's `per_file_ignores` is overkill (no glob pattern needed) and inline `# nosafe` is wrong (the violation isn't on a single line).

  - **Tree-sitter parsed**, so `# safelint: ignore` *literals* inside docstrings or string content are correctly ignored.
  - **Comment must be alone on its line.** Trailing comments after code are skipped — those are scope-local and use `# nosafe` instead. This prevents a per-line directive that's typed with the wrong prefix from silently extending to the whole file.
  - **Typo-guarded.** Unknown codes / rule names emit a `safelint: warning:` line on stderr (matching the toml typo guard); the run continues.
  - **Auditable.** Suppressed violations still land in `LintResult.suppressed` and surface in the CLI's per-code breakdown at the end of a run.

- **`"*"` wildcard support in `per_file_ignores`** — falls out of the same machinery the bare file-level directive uses. You can now write `[tool.safelint.per_file_ignores]` with `"some/path/**" = ["*"]` to skip every rule for a path pattern, instead of having to enumerate every code.

### Changed

- **Suppression model is now four layers**, narrowest to widest. They compose — a violation is suppressed if *any* layer matches:
  1. **`# nosafe`** (line scope) — same as before.
  2. **`# safelint: ignore`** (file scope) — new in 1.12.0.
  3. **`per_file_ignores`** (glob scope) — same as before, plus `"*"` wildcard support.
  4. **`ignore`** (project scope) — same as before.

### Documentation

- **CONFIGURATION.md** — new *File-level suppression* section with form table, placement rule, typo-guard behaviour, and a four-mechanism comparison table mapping each scope to its right use case.
- **CLAUDE.md** — *Suppression model* section updated from 3 layers to 4 with implementation pointers (`_parse_file_level_ignores`, `_merge_in_file_directives`, `_is_per_file_ignored`'s wildcard short-circuit).

### Behaviour changes (heads-up)

- **None for existing files.** Files without a `# safelint: ignore` directive behave identically to v1.11.0 — the new code path is purely additive. The only observable difference is the new wildcard `"*"` interpretation in `per_file_ignores`; if any user was previously writing literal `"*"` as a rule code (would have been a no-op since no rule matches), they'll now find that entry blanket-suppresses every rule. We're not aware of any such usage in the wild.

## [1.11.0] - 2026-05-08

Multi-client expansion — the AI-client skill registry grows from 2 supported clients to 12. The architecture from v1.6.0–v1.10.0 was built for this; each new client is one `ClientSpec` append plus a bundled artefact (and 10 install/lifecycle regression tests). Top-level `safelint help` gains dedicated *Skill subcommands* and *Skill flags* sections so the install / update / remove / status / path surface is discoverable without a second `safelint help skill` round-trip.

### Added

- **Ten new AI-client integrations:** GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed. Every client follows the same install / update / remove / status / path surface and the same project-vs-user-scope semantics, with auto-detection wired into the existing `--client auto` flow. Per-client install destinations:
  - **GitHub Copilot** — `.github/copilot-instructions.md` (auto-loaded by VS Code Copilot Chat)
  - **Gemini** — `GEMINI.md` at repo root (auto-discovered by Gemini CLI)
  - **Windsurf** — `.windsurfrules` at repo root
  - **codex** — `.codex/instructions.md` (primary) **plus** a delimited section in `AGENTS.md` when that file exists (preserves user content; see *Secondary install* below)
  - **Continue.dev** — `.continue/rules/safelint.md`
  - **Cline** — `.clinerules/safelint.md`
  - **aider** — `CONVENTIONS.md` (project or user); requires a one-line `read: [CONVENTIONS.md]` entry in `.aider.conf.yml` since aider doesn't auto-load conventions files. The post-install message reminds users.
  - **Trae** — `.trae/rules/safelint.md`
  - **Antigravity** — `.antigravity/rules/safelint.md`
  - **Zed** — `.rules` at repo root
- **`ClientSpec` secondary-install architecture.** New optional fields `secondary_install_relpath` and `secondary_install_section_markers` let a client write a *delimited HTML-comment section* into a shared cross-agent file (e.g. `AGENTS.md`) when that file already exists at the scope root. Used by codex; the architecture generalises to any future cross-agent shared file. **Lifecycle parity:** install writes the section, update re-renders on drift, status escalates to DIFFERS when section content drifts (even if the primary install is fresh), remove strips just the section (preserving other content; deletes the file only if it becomes empty after stripping). Section-based edits are *always* the contract for the secondary destination — never a full-file overwrite — so user content in shared files is safe.
- **Top-level `safelint help` gains *Skill subcommands* and *Skill flags* sections.** All five lifecycle actions (`install`, `update`, `remove`, `status`, `path`) and the common flags (`--client`, `--project`, `--symlink`, `--force`, plus `--path` and `--dry-run` for `remove`) are now visible at the top level — no second `safelint help skill` round-trip needed to find `--force` etc. `--force` is intentionally placed under *Skill flags* (not *Global options*) since it doesn't apply to `check`.
- **`run_update` performance: hash/walk runs at most once per install per run.** Previously `run_update` and `_update_one` each invoked `_install_status` independently per target, doubling the directory walk and content hash for Claude installs (the most file-heavy bundle). `_update_one` now accepts an optional `status` parameter; `run_update` threads its precomputed value through. Direct callers and tests are unaffected (default `None` means "compute internally").
- **`run_update` no longer falsely prints "all up to date" when every target was OSError-skipped.** New `any_processed` flag gates `_print_update_all_fresh` on at least one target having a readable status. Without the gate, an all-permission-denied run would silently report success.

### Changed

- **`io_functions` in the bundled `safelint.toml` (`[rules.side_effects_hidden]`)** — removed the unmatchable `"subprocess"` entry (the rule walks bare callable names — `subprocess.run(...)` resolves to `"run"`) and replaced it with the actual subprocess callable names (`run`, `Popen`, `call`, `check_call`, `check_output`).
- **Documentation fan-out for the multi-client expansion:** `AI_CLIENTS.md` (Supported clients table + Per-client guides + manual install examples), `src/safelint/skill_files/README.md` (clients list + layout tree + manual install examples), `README.md` (top-level integration block), and `ADDING_AN_AI_CLIENT.md` all enumerate the 12 supported clients. The Roadmap section in `AI_CLIENTS.md` was retired since the previously listed candidates (Copilot, codex, windsurf, antigravity) all shipped.
- **Test coverage threshold remains 97%; current coverage 97.24% across 628 tests.** The 10 new client integrations add 100+ install/symlink/force/overwrite/auto-detect/CLI-routing/path-print/peer-exclusion tests plus 24 codex-specific tests for the secondary-install lifecycle and section helpers.

### Behaviour changes (heads-up)

- **`safelint help` output changed shape** — *Skill subcommands* and *Skill flags* sections now appear between *Commands* and *Options*. Existing users see a longer (more discoverable) help; no commands or flags removed.
- **Auto-detection now scans for 12 client markers, not 2.** A project with markers for several clients gets installs for all of them in registry order. To install for a single client, pass `--client <name>` explicitly.
- **codex's secondary install touches `AGENTS.md` when present.** If you have an existing `AGENTS.md` with content for other agents, `safelint skill install --client codex --project` will *append* a delimited safelint section to it (your other content is preserved). The section sits between `<!-- safelint:begin -->` and `<!-- safelint:end -->` markers; `safelint skill remove --client codex` strips it cleanly. If you don't want any AGENTS.md modification, install codex without `--project` so it lands at user-scope only, or remove the AGENTS.md file before installing.

### Security hardening

- **`safelint skill remove --path PATH` now validates that *PATH*'s tail matches a registered install relpath before deleting.** Without this guard, a typo or shell-expansion accident (`--path ~/.config` instead of `~/.cursor/...`, or an unset env-var that expanded to a sensitive path) could trigger `shutil.rmtree` on the wrong directory. The check accepts every registered client's canonical install path (`.cursor/rules/safelint.mdc`, `.codex/instructions.md`, `.continue/rules/safelint.md`, `.clinerules/safelint.md`, `.trae/rules/safelint.md`, `.antigravity/rules/safelint.md`, `.windsurfrules`, `GEMINI.md`, `.rules`, `CONVENTIONS.md`, `.claude/skills/safelint`, `.github/copilot-instructions.md`) regardless of where the parent directories sit. Truly unrecognisable install locations should be removed manually with `rm` after inspecting their contents.
- **codex secondary install (`AGENTS.md`) refuses to follow symlinks.** Without this guard, an `AGENTS.md` set up as a symlink — intentionally by the user, or maliciously by an attacker with write access to the install scope (e.g. shared CI workspace) — would have caused `install`/`update`/`remove` to read and write *through* the symlink, potentially corrupting any user-writable file the link pointed at (e.g. `~/.ssh/authorized_keys`, system files when running as root). All three lifecycle paths (`_install_secondary`, `_remove_secondary`, `_secondary_status`) now check `target.is_symlink()` and refuse with a `safelint: warning: refusing to install/remove safelint section through symlink at ...` line on stderr. The primary `.codex/instructions.md` install is unaffected.

## [1.10.0] - 2026-05-06

Round-out release for the skill-install lifecycle: `update` and `remove` complete the install / status / update / remove quartet so users have a full set of maintenance commands without falling back to manual `rm` / re-install cycles.

### Added
- **`safelint skill update`** — refresh installed skills whose content has drifted from the bundled wheel. Idempotent by default (no-op when fresh), with `--force` to re-install regardless of drift status (useful for reverting customised installs back to bundled). Inherits `--client` / `--project` / `--symlink` / `--force` from install. `--client auto` here resolves via existing install paths, NOT marker files like install does — "what's installed?" vs "what client is the user using?" are separate questions.
- **`safelint skill remove`** — delete detected installs. Inherits `--client` / `--project` from install, plus three remove-specific flags:
  - **`--symlink`** — filter to symlink-shape installs only, leaving copy-mode installs intact ("delete only my symlink installs").
  - **`--path PATH`** — remove one specific location, bypassing every other flag (useful for unusual / forgotten install locations).
  - **`--dry-run`** — preview what would be removed without deleting anything.
- **Shared install-path auto-detection** between `update` and `remove` via new `_detected_installed_clients(*, only_symlink)` helper. Distinct from install's `_detected_clients(directory, marker_attr)` (marker-file scan).

## [1.9.0] - 2026-05-05

A focused follow-on to v1.8.0 covering one practical question users asked: **how do I know my installed AI-client skill is up to date after `pip install --upgrade safelint`?** Two new surfaces answer it. Also lands a build-time drift-detection test pair that prevents bundled-doc rot for every registered AI client (and every future one — the tests parametrise over the registry).

### Added
- **`safelint skill status`** — new subcommand that compares every detected installed AI-client skill (Claude Code at `~/.claude/skills/safelint/`, Cursor at `~/.cursor/rules/safelint.mdc`, project-scoped equivalents) against the bundled artefact in the active wheel. Reports per-location *fresh* / *differs from bundled*, exit 0 when every detected install matches, exit 1 when any differs. Pipe-friendly: `safelint skill status || safelint skill install --force` is the canonical "refresh after upgrade" idiom. Symlink installs always report fresh by construction. Documented in `AI_CLIENTS.md` "Updating after a safelint upgrade" → "Checking whether your installed skill is current".
- **`safelint check --check-skill-freshness`** — opt-in flag that folds the same drift check into a normal lint run. Stale installs surface as `safelint: warning: …` lines on stderr through the diagnostics channel. Informational only — doesn't fail the lint. Off by default so day-to-day `safelint check` invocations stay fast (no extra FS scan).
- **`ClientSpec.documentation_relpaths`** + parametrised drift-detection tests. Each registered AI client declares which files under `skill_files/` collectively must mention every rule code/name in `ALL_RULES` and every extension in `supported_extensions()`. Two parametrised tests (`test_skill_documents_every_active_rule[<client>]`, `test_skill_documents_every_supported_extension[<client>]`) fail CI the moment a contributor adds a rule or language without updating each registered client's bundled docs. New clients added to `_CLIENT_SPECS` automatically inherit both checks.
- Bundled skill crib-sheets (`SKILL.md`, `cursor/safelint.mdc`) backfilled with the eight rules previously absent from their rationale tables: SAFE203, SAFE401, SAFE601, SAFE701, SAFE702, SAFE801, SAFE802, SAFE803. The drift test now passes at 100% rule coverage.

### Changed
- Top-level `safelint --help` "Commands" entry for `skill` now lists `status` alongside `install` and `path`. Same change in the `CONFIGURATION.md` embedded help example.
- Documentation fan-out: the new commands and `--check-skill-freshness` flag are now mentioned in the top-level `README.md`, the bundled-in-wheel `src/safelint/skill_files/README.md`, and the `CONFIGURATION.md` `safelint check` flag table — not only in `AI_CLIENTS.md`.

## [1.8.0] - 2026-05-04

This release bundles three internal milestones (originally tracked as 1.8.0 / 1.9.0 / 1.10.0 during development; only 1.7.0 was published to PyPI) into a single user-visible release. It closes the most-asked-about gaps versus ruff — incremental config, unused-suppression detection, per-rule statistics, broader resource-lifecycle coverage, smarter empty-except detection, configurable global-mutation strictness, configurable function-size counting — *and* tightens the SAFE801 (``tainted_sink``) dataflow analysis *and* introduces advisory suggestions on JSON / SARIF outputs alongside a ruff-style top-level CLI surface. SafeLint stays *review-only* — there is no ``--fix`` flag now or planned.

### Added
#### Configuration ergonomics
- **`extend_ignore` / `extend_per_file_ignores` config keys** — grow the corresponding default lists instead of replacing them. Mirrors ruff's ``extend-select`` ergonomics. Both are folded into the canonical ``ignore`` / ``per_file_ignores`` keys at config-load time and stripped from the resolved dict, so downstream consumers (engine, runner) only see the merged lists. Order-preserving dedupe means duplicates between the base and the extension collapse to a single entry.
- **`extend_tracked_functions` config key on the ``resource_lifecycle`` rule** — appends to the (now-richer) default list instead of replacing it.
- **`strict` config flag on the ``global_mutation`` rule** — ``strict = true`` fires on any ``global`` declaration even without a write, mirroring ruff's ``PLW0603``. Default ``strict = false`` keeps the original Holzmann-aligned behaviour (only flag actual mutations). Useful for teams whose policy is to ban the ``global`` keyword entirely.
- **`count_mode` config option on the ``function_length`` rule** — three counting strategies:
  * ``"lines"`` (default) — inclusive source-line span. Original behaviour.
  * ``"logical_lines"`` — source lines minus blanks and pure-comment lines. Less game-able than the raw-lines metric.
  * ``"statements"`` — count Python statement nodes. Equivalent to ruff's ``PLR0915``; fully formatting-independent. Skips nested function bodies so an inner helper doesn't inflate its outer's count.
- **`assume_taint_preserving` config option on the ``tainted_sink`` rule** — controls how unknown function calls (those whose name is in neither ``sources`` nor ``sanitizers``) propagate taint. ``true`` (default — preserves the historical behaviour) means an unknown call's result is tainted iff any argument is tainted. ``false`` means unknown calls always drop taint, giving a less conservative analysis with fewer false positives but new false negatives where an internal helper does flow tainted data through to a sink. Set to ``false`` when your codebase has many "obviously safe" wrappers and you'd rather miss a flow than report a false positive.

#### New rules and detection improvements
- **`SAFE004` (``unused_suppression``)** — emits a warning for any inline ``# nosafe`` directive that didn't actually suppress anything. Catches stale annotations after refactors. The engine tracks per-(line, code) usage during the rule run; unused entries are reported afterward. Globally disable via ``ignore = ["SAFE004"]`` if your workflow generates many transient suppressions. Self-referential directives (both ``# nosafe: SAFE004`` and ``# nosafe: unused_suppression``, case-insensitive on the code form) are special-cased to avoid recursion.
- **Broader default tracked functions for SAFE401** — covers ``socket``, ``mmap``, ``Lock``/``RLock``/``Semaphore``, ``Pool``/``ThreadPoolExecutor``/``ProcessPoolExecutor``, ``TemporaryFile``/``NamedTemporaryFile``/``TemporaryDirectory``, ``ZipFile``/``TarFile``, plus ``Session`` (PEP-8-cased) alongside the existing ``open``/``connect``/``session``. Extended cleanup-pattern list adds ``release`` and ``shutdown``. Closes the most common ruff-vs-safelint coverage gap on real codebases.
- **`SAFE202` now catches the canonical ``except: pass`` and other no-op idioms** — previously the rule's check was so narrow it effectively never fired on real code (only on the malformed-AST case). Now flags ``pass`` / ``continue`` / ``...`` / single-literal expression bodies (``0``, ``None``, ``True``, ``False``, string-as-comment ``"TODO"`` / ``""`` etc.) when they're the entire body of an except clause. Multi-statement bodies are still allowed (so ``log_message; pass`` doesn't trip).
- **Splatted-arg taint propagation** — ``foo(*tainted_list)`` and ``foo(**tainted_dict)`` now correctly flow the splat operand's taint into the call. Previously ``list_splat`` and ``dictionary_splat`` Tree-sitter nodes weren't matched in ``TaintTracker._is_tainted``, so calls like ``eval(*user_args)`` slipped through without a violation.

#### Advisory suggestions (JSON / SARIF)
- **`suggestions[]` array on every Violation** — a list of advisory ``Suggestion`` objects, each with a one-line ``description`` and zero or more ``TextEdit`` entries (range + replacement). Empty when the rule has no fix to offer. Surfaced in JSON output (``--format json``), in SARIF output (``--format sarif`` → native ``fixes[]`` block, advisory by spec), and via the public Python API (``Violation.suggestions: tuple[Suggestion, ...]``).
- **`SAFE201 (bare_except)` ships the first suggestion** — replace bare ``except:`` with ``except Exception:``. Validates the schema end-to-end with a real rule. More rules can attach suggestions in subsequent releases without further schema changes.
- **`docs/JSON_SCHEMA.md`** documents the new ``Suggestion`` and ``TextEdit`` shapes and dedicates a section to the *advisory only* contract for editor / CI integrations.

#### CLI surface
- **`--statistics` CLI flag** — prints a per-rule count summary at the end of a pretty-mode run (``CODE  RULE  ACTIVE  SUPPRESSED``). Useful for "where do we stand?" snapshots in CI. Sorted by descending total count, ties broken alphabetically by code for deterministic output. Silent on a clean run.
- **Top-level CLI help and version, ruff-style.** New ``safelint help`` and ``safelint version`` commands plus the conventional ``-h`` / ``--help`` / ``-V`` / ``--version`` short and long flags. Help text uses a coloured layout matching ruff's (Commands / Options / Global options sections, bold headers, cyan command names, dim descriptions). Subcommand-level help is reachable via either ``safelint help check`` or ``safelint check --help``. ANSI colour auto-disables when stdout is not a TTY. Documented in ``CONFIGURATION.md`` under "Top-level commands and flags".

#### AI-client integration
- **Cursor support alongside Claude Code.** ``safelint skill install`` gains a ``--client`` flag accepting ``auto`` / ``claude`` / ``cursor``. Cursor installs deliver a single MDC project rule (``safelint.mdc``) to ``~/.cursor/rules/`` (user) or ``<cwd>/.cursor/rules/`` (project), matching Cursor's native Project Rules format. Both clients share the same step-by-step workflow because safelint's CLI surface is the same; the bundled language addendums remain accessible to either client via ``safelint skill path``. The Claude install excludes the ``cursor/`` subdirectory from the materialised skill folder so peer-client bundles don't leak into ``~/.claude/skills/safelint/`` (in both copy *and* symlink modes — symlink mode now per-entry-symlinks the directory contents instead of linking the whole tree).
- **Auto-detection is now the default.** ``safelint skill install`` (no ``--client``) is ``--client auto`` under the hood. It scans cwd for client markers (``CLAUDE.md`` / ``.claude/`` / ``.cursor/`` / ``.cursorrules``); if found, installs each detected client's skill **project-scoped**. Otherwise it scans home (``~/.claude/`` / ``~/.cursor/``) and installs **user-scoped**. If neither has any markers, it errors out with the exact ``--client`` commands the user can run instead. Multi-detection is supported — both Claude and Cursor present means both get installed in registry order. ``--client auto --project`` skips the home fallback. **Behaviour change for users running off the development branch:** prior to 1.8.0 in this branch, bare ``safelint skill install`` always installed Claude unconditionally. The new default may install Cursor or both in some environments. Pass ``--client claude`` explicitly to preserve the prior behaviour. (No PyPI users are affected — only 1.7.0 has shipped to PyPI.)
- **`ClientSpec` registry pattern.** A frozen dataclass + tuple registry in ``safelint._skill_install`` defines each supported client. Adding GitHub Copilot, codex, windsurf, etc. is one ``ClientSpec`` append plus the bundled artefact — no control-flow changes elsewhere. CLI ``--client`` choices are derived from the registry so argparse stays in sync automatically.
- **New top-level user guide:** [`AI_CLIENTS.md`](AI_CLIENTS.md) documents auto-detection logic, per-client install / usage, project-vs-user scope, symlink mode, troubleshooting, and the developer guide for adding a new client. The bundled in-wheel reference at ``src/safelint/skill_files/README.md`` stays as a short install-focused doc and links out.

### Changed
- Pretty-mode summary line updated from "No fixes available (safelint does not auto-fix violations)" to either "No suggestions available (safelint does not auto-fix)." (when no rule emitted suggestions) or "*N* advisory suggestion(s) available — view via --format json or --format sarif (safelint does not auto-apply fixes)" (when at least one rule did). Wording deliberately distinguishes "no auto-fix" (a permanent design choice) from "no suggestions available" (a per-run state). Test assertions updated accordingly.
- Cache schema version bumped from "1" to "2". The new ``suggestions[]`` field on ``Violation`` requires a richer reconstruction than ``Violation(**dict)``, which the cache now handles via ``_dict_to_violation`` / ``_dict_to_suggestion`` / ``_dict_to_text_edit``. Existing cache entries written by older safelint versions become unreachable automatically (the version is folded into the engine fingerprint, which is part of the cache key).
- The taint-through-formatting paths (f-strings, ``"…".format(tainted)``, ``"… %s …" % tainted``) now have explicit regression tests covering each form. The behaviour itself was already in place since the original SAFE801 implementation; this release just locks the contract in so it can't silently regress.

### Fixed
- ``SAFE202`` previously only matched empty-named-children blocks (which Tree-sitter doesn't actually produce for valid Python), so the rule was effectively dead code. The broadened detection above fixes this.
- ``ReturnValueIgnoredRule`` now anchors violations on the call node rather than the wrapping ``expression_statement``, so column ranges match the offending call instead of including trailing newline / semicolon tokens.

### Notes
- **The contract is permanent: SafeLint will never ship `--fix`.** This is documented as a project policy in ``docs/JSON_SCHEMA.md`` ("Suggestions are advisory only" section). Editor integrations (Claude Code skill, VSCode plugin) may render suggestions as Quick Fix code actions, but every edit goes through user confirmation. The SARIF ``fixes[]`` block is natively advisory per the SARIF 2.1.0 spec — GitHub code scanning, IDE extensions, and other consumers already implement confirmation flows for it.
- Helper-function inlining (cross-function taint analysis) was considered for the SAFE801 work in this release but deferred. Adding it would require a full call-graph walker bounded by depth limits and constitutes a larger rewrite of ``TaintTracker``. The current intra-procedural-only analysis remains the design contract; if a real-world need emerges for cross-function taint, it can be picked up in a future release.
- Internal milestones 1.9.0 and 1.10.0 were never published to PyPI; their work is included in this 1.8.0 release. Those version numbers remain available for future use.

## [1.7.0] - 2026-05-04

This release adds column-precise positioning to violations — the foundational change needed before a polished VSCode extension can underline the exact span of an offending construct rather than the whole line. No breaking changes; the new fields default to ``null`` for any consumer that doesn't read them.

### Added
- **Fully-resolved range positions on every Violation**: ``end_lineno``, ``column_start``, ``column_end`` (in addition to the existing required ``lineno``). All four are 1-based; the range is half-open ``[start, end)``, matching LSP / VSCode ``Range`` and SARIF ``region`` semantics. ``end_lineno`` correctly anchors ``column_end`` to the end-line of multi-line constructs (function definitions, except clauses, while loops) — without it, editors would mis-apply ``column_end`` to the start line. ``lineno`` remains required (no default); the three additional fields default to ``None`` for synthetic violations without a Tree-sitter node (e.g. ``test_existence`` against missing files), which editor consumers should treat as "underline the whole line".
- **`node_range(node)` helper** in ``safelint.languages._node_utils`` — returns ``(start_line, end_line, column_start, column_end)`` tuples directly from a Tree-sitter node, so rule code stays free of inline ``start_point[0] + 1`` / ``end_point[1] + 1`` plumbing.
- **`BaseRule._make_violation_for_node(filepath, node, message)`** — convenience wrapper around ``_make_violation`` that auto-extracts the full 4-coordinate position info from a Tree-sitter node. Most rules now use this; the lower-level ``_make_violation`` accepts ``column_start`` / ``column_end`` / ``end_lineno`` kwargs for the few cases (e.g. parse errors) where the node isn't available.

### Changed
- All built-in rules with a Tree-sitter node in scope now populate columns: ``function_length``, ``nesting_depth``, ``max_arguments``, ``complexity``, ``bare_except``, ``empty_except``, ``logging_on_error``, ``side_effects``, ``side_effects_hidden``, ``resource_lifecycle``, ``unbounded_loops``, ``missing_assertions``, ``global_state``, ``global_mutation``, ``tainted_sink``, ``return_value_ignored``, ``null_dereference``. The ``test_existence`` / ``test_coupling`` rules continue to emit file-level violations with no column data (the violation is about the file, not a span).
- ``TaintTracker.sink_hits`` now stores ``(call_node, var_name, sink_name)`` tuples instead of ``(lineno, var_name, sink_name)`` so the consuming rule can derive position info — including columns — from the node directly.
- Parse-error violations (``SAFE000``) now carry the column of the offending token as a zero-width caret (``column_start == column_end``), so editors can render a precise marker.
- JSON output (``--format json``) gains ``end_lineno``, ``column_start``, and ``column_end`` keys on every violation. Existing consumers ignoring unknown keys are unaffected.
- SARIF output (``--format sarif``) populates ``region.startColumn``, ``region.endColumn``, and (for multi-line constructs only) ``region.endLine``. Single-line ``endLine`` is omitted because SARIF spec defaults absent ``endLine`` to ``startLine``.

## [1.6.0] - 2026-05-02

This release ships the Claude Code skill inside the wheel and adds a one-line install command, plus a batch of correctness fixes from the v1.5.0 review cycle (caching, argv routing, SARIF URIs, CLI strictness, clean-run UX).

### Added
- **`safelint skill install`** subcommand — copies the bundled Claude Code skill into `~/.claude/skills/safelint/` (default) or `<cwd>/.claude/skills/safelint/` (with `--project`). Use `--symlink` for a live link to the bundled location, `--force` to replace an existing install. New install flow is `pip install safelint && safelint skill install`.
- **`safelint skill path`** subcommand — prints the on-disk location of the bundled skill files. Useful for inspecting `SKILL.md` directly or debugging install issues.
- **Skill files are now bundled in the wheel** at `safelint/skill_files/` (mirroring `safelint/languages/` one-to-one). `safelint skill install` finds them via `importlib.resources`, so the same code path works for `pip install`, `uv add`, and editable installs from a checkout.
- **`docs/JSON_SCHEMA.md`** — the stable schema for `safelint check --format json`. Documents top-level keys, the Violation object, severity / fail_on / blocking semantics, and example consumers in bash / Python / Node. Versioning policy: additions are non-breaking; removals require a major bump.

### Changed
- The Claude Code skill now lives at `src/safelint/skill_files/` in the source tree (was `skills/safelint/`). The skill itself is also more modular: a language-agnostic core (`SKILL.md`) plus per-language addendums under `languages/<lang>.md`, mirroring `src/safelint/languages/<lang>.py`. To add a new language, follow the new step 7 in [`ADDING_A_LANGUAGE.md`](ADDING_A_LANGUAGE.md).

### Fixed
- `per_file_ignores` is now folded into the engine fingerprint, so adding/removing/editing a glob entry between runs invalidates the affected cache entries. Previously a cache hit carried the cached `suppressed` list over unchanged, which meant *removing* a `per_file_ignores` entry left previously suppressed violations stuck in the suppressed list — the user would loosen config and still see the silence applied. The post-hit re-filter (which only walked the active list and never the suppressed list) is now also redundant and has been removed.
- Argv routing no longer breaks when a value-taking global flag precedes the `check` subcommand. Previously `safelint --format json check src` saw `json` as the first non-`-` token and fell into hook mode, silently no-oping (`json` and `check` aren't `.py`) with exit 0. The router now recognises the value-taking flags (`--format`, `--fail-on`, `--mode`, `--ignore`, `--config`, `--stdin-filename`) and skips their values when looking for the subcommand.
- Cache key now includes the normalised filepath (in addition to source bytes and engine fingerprint), so two files with identical contents under different paths no longer share a cache entry. Without this, every emitted `Violation` from the second-served file would carry the *first* file's path, and path-dependent rules (`test_existence`, `test_coupling`) would draw conclusions from the wrong file.
- Cache directory now anchors to the *discovered* config root (where `safelint.toml` or `[tool.safelint]` was actually found while walking up), not to the directory the user happened to pass to `safelint check`. Hook mode resolves the location the same way as check mode, so a single project can no longer end up with multiple `.safelint_cache/` directories scattered across subdirectories.
- `safelint check` in pretty mode now prints the `All checks passed.` summary on a clean run (matching ruff/ty's UX). Pre-commit hook mode and `--stdin` mode stay silent on success via a new `silent_on_clean` flag.
- SARIF `artifactLocation.uri` now emits a valid URI reference: backslash separators are normalised to forward slashes, absolute paths are made cwd-relative when possible, and special characters are percent-encoded. GitHub code scanning previously rejected SARIF docs produced on Windows hosts.
- CLI now fails loudly on unknown flags. `--formta=json` and similar typos used to be silently ignored (because hook/stdin parsing called `parse_known_args`); they now surface as `error: unrecognized arguments: --formta=json`.
- In `--format json`/`--format sarif`, status messages from the git-modified-files probe go to stderr instead of stdout, so machine-readable output stays a single parseable document. The "no modified Python files" early-return now also emits an empty JSON/SARIF doc on stdout in those modes.

### Migration

If you installed the v1.5.0 skill by symlinking `skills/safelint/` from a git checkout, that path no longer exists in v1.6.0. To migrate:

```bash
rm ~/.claude/skills/safelint           # remove the stale symlink
pip install --upgrade safelint
safelint skill install
```

## [1.5.0] - 2026-05-02

This release adds the foundations needed by editor integrations and the upcoming Claude Code skill / VSCode plugin: structured output formats, an in-process stdin mode, and a content-addressed result cache. No breaking changes.

### Added
- **`--format`** flag with three choices: `pretty` (default — unchanged ruff/ty multi-line coloured output), `json`, and `sarif`. The JSON format emits a stable schema with a `version`, `summary` (counts + suppressed breakdown), and flat `violations` / `suppressed` lists. The SARIF format is SARIF 2.1.0 conformant and consumable by GitHub code scanning, Azure DevOps, and similar tools. The flag is available in both `safelint check` and pre-commit hook modes.
- **`--stdin`** / **`--stdin-filename PATH`** flags read source from stdin instead of from disk and lint it as if it came from `PATH`. Designed for editor integrations that need to lint un-saved buffers without round-tripping through a temp file. The pseudo-filename drives language detection by extension and shows up as the violation file path.
- **`SafetyEngine.check_source(filepath, source)`** public method runs the same rule pipeline as `check_file` but on a caller-provided buffer. Used by stdin mode and available to library consumers building editor integrations.
- **Per-file lint-result cache** keyed on `sha256(source + engine fingerprint)` where the engine fingerprint folds in safelint version, an internal cache schema version, and the active rule set with per-rule config. The cache lives at `<config-dir>/.safelint_cache/` (next to `pyproject.toml` / `safelint.toml`, mirroring `.pytest_cache`'s convention) and stores one JSON file per key. Re-runs on unchanged files are essentially instant — important for editor "lint on save" loops.
- **`--no-cache`** flag disables the cache for the current run (e.g. CI where every run is fresh anyway, or when debugging cache-related issues). `.safelint_cache/` added to the project's `.gitignore`.
- **`ADDING_A_LANGUAGE.md`** developer guide: a concrete walkthrough of adding a new language (TypeScript, Go, Rust, …), with a per-rule audit of which Python rules are portable, language-agnostic, or Python-only.

### Notes
- `--stdin` mode unconditionally bypasses the disk cache. Editor keystrokes produce a slightly different buffer every time; caching them would only churn the project tree without ever helping. The `--no-cache` flag is therefore a no-op in stdin mode.
- The new public `LintCache` class accepts `cache_dir=None` to opt out of caching at the engine level — used by `--no-cache`, by stdin mode, and recommended for any tests / library callers that need isolation.

## [1.4.1] - 2026-05-01

### Added
- `max_file_size_bytes` top-level config option (default **5 MiB**). Files larger than the bound are skipped with a `safelint: warning: skipping <path> (<size> bytes exceeds max_file_size_bytes=…)` diagnostic to stderr instead of being read into memory and parsed. Guards against OOM on accidentally-huge inputs (binary blobs masquerading as `.py`, very large generated files). To allow larger files, raise the bound explicitly — `0` is rejected as a likely typo (it would disable the OOM guard entirely) and falls back to the default with an init-time warning. Engine init validates the value: must be a non-negative integer, otherwise `TypeError`/`ValueError` fires before any file is read. Closes #20.

### Fixed
- File discovery is now safe against symlink cycles. `SafetyEngine._discover_files` switched from `Path.rglob('*')` (which follows symlinks and can recurse forever on a cycle like `a/sub -> ..`) to `os.walk(target, followlinks=False)`. Same single-pass O(number_of_files) cost, but safe by construction. Matches what ruff and flake8 do by default. Closes #19.

## [1.4.0] - 2026-05-01

> **Heads-up — breaking library API change.** `LintResult.suppressed` is now `list[Violation]` (was `int`). Library consumers that read this field directly need to switch to `len(result.suppressed)` for the count. CLI users are unaffected. See **Changed** below for details and migration notes.

### Added
- Standalone `safelint.toml` configuration file (top-level keys, no `[tool.safelint]` wrapper). When both `safelint.toml` and `pyproject.toml` `[tool.safelint]` exist in the same directory, `safelint.toml` wins — matching `ruff.toml` / `pyproject.toml` precedence.
- `examples/sample.safelint.toml` reference covering every supported configuration key.
- Public `safelint.languages.supported_extensions() -> frozenset[str]` for callers that need to know which file extensions have a registered language. Use this instead of importing the private `_REGISTRY`.
- `walk()` in `safelint.languages._node_utils` accepts an optional `skip_types` parameter that prunes subtrees rooted at any matching node type (used by per-function rules to avoid descending into nested `def` / `async def` bodies).

### Changed
- `side_effects` (SAFE304) and `side_effects_hidden` (SAFE303) now normalise **both** sides of the name comparison. Function names are lowercased for matching, and user-supplied `io_name_keywords` / `pure_prefixes` are lowercased once at config load — so configurations like `io_name_keywords = ["Write", "Log"]` or `pure_prefixes = ["Get", "Calculate"]` behave the same as their lowercase forms. Previously only the function name was lowered, leaving uppercase config entries silently unmatched.
- `load_config()` now returns a fresh deep copy of the merged config on every call. Mutating the result (e.g. `config["ignore"].append(...)`) no longer corrupts the module-global `DEFAULTS`.
- **Removed** YAML (`.safelint.yaml`) configuration support and the `safelint[yaml]` install extra. Migrate to `[tool.safelint]` in `pyproject.toml` or to a standalone `safelint.toml`.
- CLI summary "All checks passed." is now bold green to match `ruff` / `ty`.
- The "No fixes available …" line is no longer printed on clean runs (with or without suppressions). It only appears when there are active violations a developer might wonder about auto-fixing.
- Suppressed-violation summary now shows a per-code breakdown — e.g. `(2 SAFE501, 1 SAFE304 suppressed)` — instead of a bare `(N suppressed)` count, so it is clear which rules were silenced.
- **Breaking (library API):** `LintResult.suppressed` is now `list[Violation]` (was `int`). Use `len(result.suppressed)` for the count and iterate to inspect codes, rules, file paths, and line numbers of suppressed violations.
- Replaced internal use of Python's `logging` module with a dedicated diagnostics channel that writes formatted single-line messages to stderr (`safelint: warning: …`, `safelint: error: …`). Configuration typos and malformed-TOML errors are now surfaced cleanly instead of leaking through Python's `lastResort` logging handler.
- `walk()` now traverses only `named_children` (skips Tree-sitter's anonymous punctuation/keyword tokens), reducing the number of nodes visited per traversal across every rule and the suppression parser.
- Parse-error violations (`SAFE000`) now include line, column (1-based), and a kind hint such as `missing ':'` or `syntax error`. The lineno on the violation now points at the offending location instead of being hardcoded to 0.
- `MaxArgumentsRule` now counts `*args` and `**kwargs` parameters, each as one argument. Previously they were silently ignored, allowing functions to exceed `max_args` without triggering.
- An empty `[tool.safelint]` section in `pyproject.toml` (or an empty `safelint.toml`) is now treated as a present-but-empty config. Previously the loader fell through to an ancestor directory's config, hiding unintentionally-blank sections.
- Self-development pre-commit hook switched from `repo: https://github.com/shelkesays/safelint @ v1.3.2` to `repo: local`, so contributors run the in-tree code rather than an outdated published release while iterating on safelint itself.

### Fixed
- Per-function rules no longer incorrectly aggregate metrics from nested `def` / `async def` bodies into the enclosing function. Affects `complexity`, `nesting_depth`, `missing_assertions`, `unbounded_loops`, `global_state`, `global_mutation`, `logging_on_error` (a logging call inside a nested helper would have falsely satisfied the rule), and the dataflow `TaintTracker`. Each nested function is scored as its own unit, as the outer-walk loop already intended.
- `state_purity` (`global_state`, `global_mutation`) now also stops at nested class definitions — a `global X` declared inside a nested class body lives in that class's scope, not the enclosing function's.
- `function_length` (SAFE101) reported counts that were off by one (a 60-line function showed `59 lines`). The calculation is now inclusive of the `def` line.
- Dataflow taint tracker now unwraps `keyword_argument` nodes — `eval(code=user_input)` is no longer missed because the tainted value was hidden behind a kwarg wrapper.
- Dataflow taint tracker now propagates taint through tuple/list destructure targets (`a, b = tainted`, `[a, b] = tainted`, `(a, b) = tainted`), starred destructures (`a, *rest = tainted`), and chained assignments (`a = b = tainted`). Previously the LHS shape was assumed to be a single bare identifier, so every other form silently dropped the taint.
- Top-level `ignore` and `per_file_ignores` entries now validate that every value is a string. Non-string elements (e.g. `["SAFE101", 42]`) and wrong-shape values (e.g. `ignore = "SAFE101"`) are reported with a clear `TypeError` at engine init instead of crashing later on `.upper()`.
- File discovery now does a single `rglob('*')` pass and filters by suffix, instead of one `rglob('*<ext>')` per registered extension. Discovery is now O(number_of_files) rather than O(number_of_extensions * number_of_files). No behaviour change on a single-language registry, but matters as more languages are added.

## [1.3.1] - 2026-04-24

### Added
- `ignore` config key and `--ignore` CLI flag: suppress rules globally by code (`SAFE101`) or name (`function_length`); unknown entries log a warning at startup.
- `per_file_ignores` config key: suppress specific rules for files matching a glob pattern (e.g. `"tests/**" = ["SAFE101", "SAFE103"]`); multiple patterns union their ignore lists.
- `# nosafe: RULE, CODE` inline suppression: codes and rule names can now be mixed in the same comma-separated list on a single `# nosafe:` comment.
- Suppressed violation count (from both `# nosafe` and `per_file_ignores`) reported in the end-of-run summary so suppressions remain auditable.

### Changed
- `SafetyEngine.__init__` extracted into two focused static methods (`_build_active_rules`, `_parse_per_file_ignores`) to keep complexity within bounds.
- Pattern matching for `exclude_paths` and `per_file_ignores` switched from `pathlib.Path.match` to `fnmatch.fnmatchcase(path.as_posix(), pattern)`, fixing incorrect `**` handling on Python ≤ 3.12.
- `--ignore` CLI flag changed from `nargs="+"` to `action="append"` so it can be repeated (`--ignore SAFE101 --ignore SAFE103`).
- CLI summary now shows `(N suppressed)` instead of `(N suppressed via # nosafe)` to cover all suppression mechanisms.

### Fixed
- `per_file_ignores` patterns with `**` (e.g. `tests/**`) now correctly match files in nested subdirectories on Python ≤ 3.12.
- Pre-commit hook no longer shows a success message for files that were silently excluded.

## [1.3.0] - 2026-03-01

### Added
- Initial public release with 16 built-in rules covering function length, nesting depth, cyclomatic complexity, error handling, global state, side effects, resource lifecycle, loop safety, and opt-in dataflow analysis.
- TOML (`pyproject.toml`) and YAML (`.safelint.yaml`) configuration with deep-merge against built-in defaults.
- `# nosafe` inline suppression (bare and with specific codes).
- `exclude_paths` glob patterns to skip directories entirely.
- `fail_fast` execution option.
- Pre-commit hook integration.
- `--mode=ci` and `--fail-on` CLI flags.

[Unreleased]: https://github.com/shelkesays/safelint/compare/v1.13.0...HEAD
[1.13.0]: https://github.com/shelkesays/safelint/compare/v1.12.2...v1.13.0
[1.12.2]: https://github.com/shelkesays/safelint/compare/v1.12.1...v1.12.2
[1.12.1]: https://github.com/shelkesays/safelint/compare/v1.12.0...v1.12.1
[1.12.0]: https://github.com/shelkesays/safelint/compare/v1.11.0...v1.12.0
[1.11.0]: https://github.com/shelkesays/safelint/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/shelkesays/safelint/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/shelkesays/safelint/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/shelkesays/safelint/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/shelkesays/safelint/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/shelkesays/safelint/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/shelkesays/safelint/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/shelkesays/safelint/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/shelkesays/safelint/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/shelkesays/safelint/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/shelkesays/safelint/releases/tag/v1.3.0
