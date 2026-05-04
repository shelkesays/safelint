# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- **Cursor support alongside Claude Code.** ``safelint skill install`` gains a ``--client {claude,cursor}`` flag (default ``claude`` — backwards compatible). Cursor installs deliver a single MDC project rule (``safelint.mdc``) to ``~/.cursor/rules/`` (user) or ``<cwd>/.cursor/rules/`` (project), matching Cursor's native Project Rules format. Both clients share the same step-by-step workflow because safelint's CLI surface is the same; the bundled language addendums remain accessible to either client via ``safelint skill path``. The Claude install excludes the ``cursor/`` subdirectory from the materialised skill folder so peer-client bundles don't leak into ``~/.claude/skills/safelint/``.

### Changed
- Pretty-mode summary line updated from "No fixes available (safelint does not auto-fix violations)" to either "No suggestions available (safelint does not auto-fix; see --format json for any advisory edits)" (when no rule emitted suggestions) or "*N* advisory suggestion(s) available — view via --format json (safelint does not auto-apply fixes)" (when at least one rule did). Wording deliberately distinguishes "no auto-fix" (a permanent design choice) from "no suggestions available" (a per-run state). Test assertions updated accordingly.
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

[Unreleased]: https://github.com/shelkesays/safelint/compare/v1.8.0...HEAD
[1.8.0]: https://github.com/shelkesays/safelint/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/shelkesays/safelint/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/shelkesays/safelint/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/shelkesays/safelint/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/shelkesays/safelint/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/shelkesays/safelint/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/shelkesays/safelint/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/shelkesays/safelint/releases/tag/v1.3.0
