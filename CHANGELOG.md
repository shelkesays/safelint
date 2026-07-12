# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Internal refactor: the rules now import Tree-sitter node-type / operator constants from the `languages/<lang>.py` modules instead of hardcoding raw string literals.** Each language module is the single source of truth for its node types, and every language's rule logic references its own module. **No behaviour change** - every rule's resolved node-type set is byte-identical to before (verified by a deterministic table snapshot), and no rule, code, config key, CLI flag, or output format is affected. Purely additive at the module level (new constants only; none removed or renamed), so any downstream importer of `safelint.languages.*` stays compatible.

## [2.8.1] - 2026-07-12

### Security

- **Skill-install and CI hardening (internal audit items H7-H9), all LOW / defence-in-depth.** None is exploitable in the default no-flag flow; they close residual TOCTOU and supply-chain gaps around the `safelint skill` command and the release pipeline. No change to lint behaviour or public API.
  - Secondary-file (`AGENTS.md`) section writes are now atomic and symlink-safe: the merged text is written to an exclusive-create temp in the same directory and `os.replace`d over the target, so a symlink swapped into the check-then-write window is replaced as a directory entry rather than written through. The original file's permission bits are preserved.
  - `safelint skill remove --path` now resolves its target a single time and removes that same validated path, so a symlinked ancestor swapped in after the shape check can no longer redirect the removal onto a different tree; a terminal-symlink install is still unlinked as the link itself.
  - Every third-party GitHub Action is pinned to a full commit SHA (most importantly the OIDC-privileged `pypa/gh-action-pypi-publish` in the publish workflow), with a Dependabot `github-actions` ecosystem added to keep the pins current.

## [2.8.0] - 2026-07-10

**C++ is now a supported language.** Building on the C support, `.cpp` / `.cxx` / `.cc` / `.hpp` / `.hxx` / `.hh` files are discovered, parsed via `tree-sitter-cpp`, and run against **26 rules**: the cross-language ports, the five C-family rules (SAFE106 / SAFE310-313) widened to C and C++, the three `try` / `catch` / `throw` error-handling rules, and **two new C++-only rules**. Plain `.h` headers stay with C (documented). The additive language work is what justifies this release as a MINOR bump (per the project's semver rules: scope expansion is MINOR, never MAJOR).

### Added

- **C++ language support** via the opt-in `[cpp]` extra (`pip install 'safelint[cpp]'`). `tree-sitter-cpp` is a superset of `tree-sitter-c`, so the C node types and the five C-family rules carry over unchanged.
- **SAFE315 (`raw_new_delete`)** - flags every `new` / `delete` expression; prefer `std::make_unique` / `std::make_shared` and RAII. `make_unique` / `make_shared` never fire; a raw `new` inside a `unique_ptr<T>(new T)` argument still does. Overlaps the widened SAFE310 by design. C++-only, disabled by default.
- **SAFE316 (`dangerous_casts`)** - flags `reinterpret_cast` / `const_cast`; `static_cast` / `dynamic_cast` stay clean. Configurable via `dangerous_casts_cpp`. C++-only, disabled by default.
- **SAFE201 (`bare_except`)** gains its first non-Python home: the `catch (...)` catch-all. SAFE202 (`empty_except`) and SAFE203 (`logging_on_error`) also register for C++; SAFE203 recognises `std::cerr << ...` stream insertion and `spdlog::error`-style calls as logging, and a bare `throw;` / `throw e;` as a re-raise.
- C++-specific behaviour on the widened rules: SAFE302 (`global_mutation`) descends into `namespace_definition` bodies; SAFE310 (`dynamic_allocation`) also flags `new` / `delete`; SAFE313 (`restricted_pointers`) exempts smart pointers; SAFE105 (`no_recursion`) detects `this->m()` self-calls; SAFE801 (`tainted_sink`) seeds reference parameters and reuses the C taint tracker.
- Per-language `_cpp`-suffixed config defaults mirroring C (`nonlocal_jump_calls_cpp`, `allocation_calls_cpp`, `dynamic_exec_calls_cpp`, `io_functions_cpp`, `assertion_calls_cpp`, `sinks_cpp` / `sources_cpp` / `sanitizers_cpp`, `flagged_calls_cpp`, `dangerous_casts_cpp`).
- A bundled `languages/cpp.md` skill addendum and a C++ language reference page; all fourteen client skill files, the CLI / SECURITY / TOML / contributing enumerations, and the pre-commit `types_or` list updated for C++.

## [2.7.1] - 2026-07-06

Post-release hardening of the v2.7.0 C support: one opt-in-rule bugfix (SAFE312 false positives on real-world include guards), documentation-fidelity corrections, and regression tests that backfill gaps found in the C post-release audit.

### Fixed

- **SAFE312 (`conditional_compilation`) no longer false-positives on real-world include guards.** The exemption required `#define X` to be the node immediately after `#ifndef X`, so a licence / SPDX comment or a belt-and-braces `#pragma once` between the two - both widespread header idioms - made the guard fire spuriously. The first-substantive-statement check now skips `comment` and `preproc_call` nodes; an unrelated statement in that position still fires (the anti-disguise tightening is unchanged). Found by review on the 2.7.1 release PR.
- Recorded two Power of Ten paper-fidelity gaps in the C rules so they read as deliberate decisions: SAFE311 (`complex_macro`) does not detect mutually recursive macro definitions, and SAFE313 (`restricted_pointers`), a syntactic declarator check, does not see pointer levels hidden behind a `typedef` or macro. Both need analysis SafeLint does not do; documented in the Power of Ten page, the rules reference, and the C language page.
- Corrected the stale rule-7 fidelity note to name C's literal `(void)` cast (recognised by SAFE802); Go's blank identifier is described as the memory-managed-language analogue.
- Swept lingering "seven languages" enumerations to the eight-language state (CONTRIBUTING, the JSON-schema page, the README pre-commit example, the bundled skill README, and the "all-language core" labels).

### Added

- C regression tests backfilling the post-release audit gaps: a Power of Ten behavioural pin (`tests/rules/test_c_power_of_ten_pin.py`), an engine-level suite (`tests/core/test_engine_c.py`, covering both `.c` and `.h`), config-override tests for the SAFE106 `nonlocal_jump_calls_c` and SAFE310 `allocation_calls_c` list knobs, and a SAFE106 default-on / warning-severity contract lock.

## [2.7.0] - 2026-07-02

**C is now a supported language alongside Python, JavaScript, TypeScript, Java, Rust, Go, and PHP.** `.c` and `.h` files are discovered, parsed via Tree-sitter (`tree-sitter-c`, shipped in the opt-in `[c]` extra), and run against **21 rules** - the 16 cross-language ports plus **5 new C-only rules**, the largest rule addition of any language. C is Holzmann's original "Power of Ten" target, so the new rules express clauses every other language adapts away, literally. safelint grows to **45 rules** and **8 registered languages**. Additive per the project's semver policy (a new language is MINOR); nothing renames, removes, or changes the meaning of any existing rule code, CLI flag, or config key.

### Added

- **C as the 8th registered language.** `.c` / `.h` files dispatch to C-aware implementations of 16 cross-language rules: the 13 all-language core (SAFE101-105, SAFE303, SAFE304, SAFE501, SAFE603, SAFE701, SAFE702, SAFE801, SAFE802) plus SAFE302 (`global_mutation`, a file-scope declaration-site walk), SAFE309 (`dynamic_code_execution`, `dlopen` / `dlsym`), and SAFE601 (`missing_assertions`, the literal `assert` macro). `.h` headers are linted as C (a documented limitation for C++ projects sharing `.h` files). See the [C language page](https://shelkesays.github.io/safelint/languages/c/) for the full reference.
- **Five new C-only rules - the "Power of Ten homecoming".** Clauses every other language adapts away apply literally to C: **SAFE106 `nonlocal_jumps`** (rule 1 - every `goto` and `setjmp` / `longjmp` family call; **enabled at warning severity** because `goto err` cleanup is idiomatic, annotate with `// nosafe: SAFE106`), **SAFE310 `dynamic_allocation`** (rule 3 - the `malloc` family), **SAFE311 `complex_macro`** and **SAFE312 `conditional_compilation`** (rule 8 - the preprocessor), and **SAFE313 `restricted_pointers`** (rule 9 - multi-level and function pointers). All but SAFE106 are disabled by default.
- **C-specific rule adaptations.** SAFE801 models the `argv` / `getenv` -> `system` / `strcpy` / `sprintf` taint flow (a new `analysis/dataflow_c.py` iterative tracker, with `argv` seeded via function parameters); SAFE501 handles `while (1)` / `while (true)` / `for (;;)` and treats a `goto` out of the loop as an exit (C has no labelled break); SAFE802's `(void)f()` cast correctly exempts an explicit discard; SAFE603 flags clang-tidy's bare `// NOLINT`; SAFE701 / SAFE702 use the `<stem>_test.c` / `test_<stem>.c` conventions. Seven rules are deliberately skipped for C (SAFE201/202/203, SAFE301, SAFE305 by language semantics; SAFE401 `resource_lifecycle` and SAFE803 `null_dereference` as documented flow-analysis gaps); the rationale is on the language page.
- **Bundled C skill addendum + per-client docs.** `src/safelint/skill_files/languages/c.md` plus C rows in all 14 AI-client skill files, so every bundled agent knows safelint can lint `.c` / `.h` and how the C-specific rules behave.

## [2.6.1] - 2026-06-26

**Security-hardening release.** Six findings (H1-H6) from the 2026-06-25 internal security audit, all **LOW** severity and none reachable in the default no-flag flow: symlink/TOCTOU defences across `skill remove --path`, `skill install` (copy), the result-cache temp write, and the OpenCode seed step, plus containment of the `test_dirs` config search to the project root and an `os` -> `pathlib` cleanup. No new rules, CLI flags, or config keys, and no change to how any existing rule evaluates code; the only behaviour changes are defensive - relative `test_dirs` entries that escape the project root are now dropped, and a few `skill install` / `remove` edge cases now fail closed. See `plan/security-hardening.md` for the full audit record.

### Security

- **Contain `test_dirs` filesystem search to the project root (audit finding H3).** A relative `test_dirs` config value that climbs out of the project root via `..` (e.g. `["../../etc"]`) previously let SAFE701 / SAFE702's `rglob` probe directories outside the tree (read/stat only - a single existence bit, no exfiltration). Relative entries are now collapsed lexically and dropped if they escape the root; absolute `test_dirs` remain honoured (an explicit, supported config choice). LOW severity, opt-in rules; from the 2026-06-25 internal security audit (see `plan/security-hardening.md`). First of the audit's hardening items.
- **Refuse `skill remove --path` when a symlinked ancestor redirects the delete (audit finding H1).** The `--path` guard matched only the *lexical* tail of the path against a registered install shape, so a path like `~/x/.cursor/rules/safelint.mdc` whose `rules` component is a symlink into an unrelated tree could pass the check and have `_remove_existing` delete a file there. The guard now re-checks the install shape after resolving ancestor symlinks (`Path.resolve` on the parent): a redirect onto a non-install-shaped location is refused, while genuinely unusual *real* parents - and shape-preserving symlinks such as dotfile clones - keep working. LOW severity (requires an attacker-planted symlink under a path the user explicitly names).
- **Use exclusive create for skill-file copy installs (audit finding H2).** `safelint skill install` (copy mode) wrote the destination with `shutil.copyfile`, which follows symlinks and truncates the target - leaving a check-then-write window in which a symlink planted at the destination could redirect the write onto an unrelated file. The copy now writes via an exclusive create (`"xb"` mode, `O_CREAT | O_EXCL`, which POSIX makes fail on a symlink too), so a freshly-appeared target makes the install fail rather than clobber. LOW severity (local check-then-write race on the install destination).
- **Write the result cache through an exclusive-create temp file (audit finding H4).** `LintCache.put` wrote a deterministically-named `<key>.json.tmp` then renamed it into place; in an attacker-writable cache directory a symlink pre-planted at that predictable name would be followed by the write. The temp file is now created via `tempfile.mkstemp` (`O_CREAT | O_EXCL`, plus `O_NOFOLLOW` where the platform provides it, under an unguessable random name) and written through its file descriptor, so a planted symlink / predictable tmp name can no longer be followed. LOW severity (requires write access to the cache dir, which already permits writing the cache files directly).
- **Don't follow a dangling `AGENTS.md` symlink when seeding OpenCode integration (audit finding H5).** The OpenCode auto-seed step guarded only on `Path.exists()`, which returns False for a *dangling* symlink, so a dangling `AGENTS.md` symlink would let the subsequent `touch()` follow the link and create an empty file at the link target. The step now returns early on `is_symlink()` (lstat-based, true for dangling links) and, crucially, seeds via an exclusive create (`"xb"` / `O_CREAT | O_EXCL`) instead of `touch()` - so even a symlink that appears in the check-then-write window is refused (the create fails and is treated as a no-op) rather than followed. LOW severity (needs an attacker-planted symlink, a project with `.opencode/`, and a project-scope install; creates only an empty file).

## [2.6.0] - 2026-06-25

**PHP is now a supported language alongside Python, JavaScript, TypeScript, Java, Rust, and Go.** `.php` files are discovered, parsed via Tree-sitter (using the mixed HTML+PHP grammar so templated files parse), and run against **21 existing rules** - the widest port of the rule set of any language so far. PHP adds NO new rule codes, so safelint stays at **40 rules**; it becomes the 7th registered language. PHP support installs via the new `[php]` extra (`pip install 'safelint[php]'`); the base install still ships no grammars. Additive per the project's semver policy (a new language is MINOR, never MAJOR); nothing renames, removes, or changes the meaning of any existing rule code, CLI flag, or config key.

### Added

- **PHP as the 7th registered language.** `.php` files are dispatched to PHP-aware implementations of 21 cross-language rules: the 13 all-seven core (SAFE101-105, SAFE303, SAFE304, SAFE501, SAFE603, SAFE701, SAFE702, SAFE801, SAFE802) plus SAFE302 (`global_mutation`), SAFE309 (`dynamic_code_execution`), SAFE401 (`resource_lifecycle`), SAFE601 (`missing_assertions`), SAFE803 (`null_dereference`), SAFE202 (`empty_except`), SAFE203 (`logging_on_error`), and SAFE301 (`global_state`). See the [PHP language page](https://shelkesays.github.io/safelint/languages/php/) for the full reference.
- **SAFE301 `global_state` gains its first non-Python registration.** PHP has a literal `global` keyword; the rule now fires on `global $x;` inside PHP functions, and SAFE302 additionally flags `$GLOBALS[...]` superglobal writes.
- **PHP-specific rule adaptations.** SAFE603's headline PHP target is the `@` error-suppression operator (plus bare `phpcs:ignore` / `@phpstan-ignore-line` / `@psalm-suppress all`); SAFE801 models the classic web-taint flow (superglobal `$_GET` / `$_POST` / ... sources into `eval` / `exec` / `system` / `shell_exec` / `unserialize` / `->query` / `mysqli_query` sinks and dynamic `include` / `require`, with `intval` / `escapeshellarg` sanitizers); SAFE501 resolves numeric `break N` levels and flags `while (true)` / `for (;;)` without an exiting break; SAFE401 uses the `try { } finally { }` form (`fopen` / `curl_init` / ...); SAFE701 / SAFE702 use the PHPUnit `<ClassName>Test.php` convention; SAFE803 recognises the nullsafe `?->` operator as the safe form. A new `analysis/dataflow_php.py` taint tracker (iterative worklists) backs SAFE801 (SAFE802 is a separate structural check). Two rules are deliberately skipped for PHP (SAFE201 `bare_except` - PHP 7+ catches always carry a type; SAFE305 `wide_scope_declaration` - no `var` / `let` / `const` distinction); the rationale is in the language page's "Rules not registered" section.
- **Bundled PHP skill addendum + per-client docs.** `src/safelint/skill_files/languages/php.md` plus PHP rows in all 14 AI-client skill files, so every bundled agent knows safelint can lint `.php` and how the PHP rules behave.

## [2.5.0] - 2026-06-18

**Go is now a supported language alongside Python, JavaScript, TypeScript, Java, and Rust.** `.go` files are discovered, parsed via Tree-sitter, and run against 16 cross-language rules plus two new Go-only rules (18 rules total for Go), bringing safelint to **40 rules** (15 on by default, 25 opt-in). Go support installs via the new `[go]` extra (`pip install 'safelint[go]'`); the base install still ships no grammars. Additive per the project's semver policy (a new language is MINOR, never MAJOR); nothing renames, removes, or changes the meaning of any existing rule code, CLI flag, or config key.

### Added

- **Go as the 6th registered language.** `.go` files are discovered, parsed via Tree-sitter (`tree-sitter-go`, shipped in the opt-in `[go]` extra), and dispatched to the Go-aware rule implementations. 16 cross-language rules apply: the 13 all-six core (SAFE101-105, SAFE303, SAFE304, SAFE501, SAFE603, SAFE701, SAFE702, SAFE801, SAFE802) plus SAFE302 (`global_mutation`), SAFE309 (`dynamic_code_execution`), and SAFE401 (`resource_lifecycle`), which Go shares with the JS family and Java. See the [Go language page](https://shelkesays.github.io/safelint/languages/go/) for the full reference.
- **SAFE209 `empty_error_check` (Go-only, disabled by default).** Flags `if err != nil { }` (or `== nil`) with an empty or comment-only body - the error was checked and then silently swallowed. The Go analogue of Rust's SAFE206; the error identifier is configurable via `error_names_go` (default `["err"]`).
- **SAFE211 `panic_calls_outside_tests` (Go-only, disabled by default).** Flags `panic(...)` calls in non-`_test.go` files; production paths should return an `error` rather than unwind the stack. The Go analogue of Rust's SAFE204; configurable via `panic_calls_go` (default `["panic"]`).
- **Go-specific rule adaptations.** SAFE501 flags the bare `for {}` infinite loop (Go's only loop keyword) with labelled-break resolution; SAFE701 / SAFE702 use the sibling `foo_test.go` convention rather than a `tests/` directory; SAFE802's explicit-discard exemption recognises Go's `_ = f()` and `x, _ := f()` forms; SAFE401 checks for a `defer x.Close()` in the same function body; SAFE105 recognises receiver-qualified self-recursion (`s.Walk(...)`). A new `analysis/dataflow_go.py` taint tracker (iterative worklists) backs SAFE801 / SAFE802. Seven rules are deliberately skipped for Go (SAFE201, SAFE202, SAFE203, SAFE301, SAFE305, SAFE601, SAFE803) because their semantics don't translate cleanly; the rationale is in the language page's "Rules not registered" section.
- **Bundled Go skill addendum + per-client docs.** `src/safelint/skill_files/languages/go.md` plus Go rows in all 14 AI-client skill files, so every bundled agent knows safelint can lint `.go` and how the Go-specific rules behave.

### Documentation

- **Development guidance is now version-controlled.** `CLAUDE.md` (the Claude Code project guide), the `add-language-support` development skill (`.claude/skills/add-language-support/`), and the language-expansion plans under `plan/` (`plan/README.md` plus the per-language specs) are tracked, reversing the old keep-CLAUDE.md-local convention: the skill and the plans reference CLAUDE.md's checklists, so the three travel together. Machine-local Claude Code state (`.claude/settings.local.json`, the installed `.claude/skills/safelint/` copy) stays ignored.
- **Contributing guide: framework / runtime preset standard.** `docs/contributing/adding-a-language.md` gains an "Adding a framework / runtime preset" section (config machinery shape, 9xx-band policy for framework rules, preset tests, and the full docs fan-out including both TOML forms), and its Step 8 client-file list is corrected from 12 to all 14 bundled skill files (warp and kiro were missing).

## [2.4.0] - 2026-06-10

**Power of Ten gap-closure: five new / widened rules.** This release adds four new rules and widens one existing rule to close the most prominent gaps between SafeLint's rule set and Holzmann's ten rules, plus a new docs page mapping the ten rules onto the checks. Additive across the board (per the project's semver policy, new rules and widened language coverage are MINOR); nothing renames, removes, or changes the meaning of any existing rule code, CLI flag, or config key.

### Added

- **SAFE105 `no_recursion` (Holzmann rule 1), all five languages, enabled by default at `warning` severity.** Flags direct self-recursion, a function that calls its own name, either bare (`fact(n - 1)`) or self-qualified (`self.walk(...)` / `this.walk(...)`). A call on a different receiver (`other.walk(...)`) does not fire. Indirect / mutual recursion and anonymous-function recursion are documented out-of-scope blind spots. Annotate deliberate recursion with `# nosafe: SAFE105` (or the language's comment form).
- **SAFE307 `interior_mutable_static` (Holzmann rule 6), Rust-only, disabled by default.** Flags a `static` whose type provides safe interior mutability (`Mutex` / `RwLock` / `OnceLock` / `Atomic*` / `RefCell` / `Cell` / `Lazy*`) and `lazy_static!` blocks, the safe-code global mutable state that SAFE602's `unsafe` gate never sees. `const` and `static mut` are not flagged. Configurable via `interior_mutable_types_rust`.
- **SAFE309 `dynamic_code_execution` (Holzmann rule 8), Python / JS / TS / Java, disabled by default.** Structural detection of `eval` / `exec` / `compile` / `__import__` (Python), `eval` / `new Function` (JS/TS), and `Class.forName` / `Method.invoke` / `defineClass` / `loadClass` (Java). Complements the taint-gated SAFE801, both may fire on one line. Rust is excluded (its rule-8 analogue, macros, parses as opaque token trees). Per-language call lists via `dynamic_exec_calls` / `dynamic_exec_calls_javascript` / `dynamic_exec_calls_java`.
- **SAFE603 `blanket_suppression` (Holzmann rule 10), all five languages, disabled by default.** Flags un-scoped suppressions of *other* analysers: bare flake8 `noqa`, `type: ignore` without a code, rule-less `eslint-disable`, `@ts-nocheck` / `@ts-ignore`, `@SuppressWarnings("all")`, `#[allow(clippy::all)]` / `#[allow(warnings)]`. Scoped suppressions are clean, and SafeLint's own `# nosafe` directives are never flagged (SAFE004 polices those).
- **New docs page: [The Power of Ten, adapted](https://shelkesays.github.io/safelint/power-of-ten/).** Maps each of Holzmann's ten rules to the SafeLint rules that implement it, per language, and records the rationale for the adapted-away clauses (rule 3 dynamic allocation, rule 8 preprocessor for non-Rust languages), plus fidelity notes from a re-read of the paper: rule 2's non-terminating-loop exception (the justified `# nosafe: SAFE501` analogue), rule 5's full clause set, rule 7's explicit-discard escape hatch (`let _ =` / `_ =`), rule 9's function-pointer adaptation, rule 10's rewrite-not-suppress policy, and the un-covered Rust `#[cfg]` conditional-compilation analogue.
- **`min_assertions` config knob on SAFE601 `missing_assertions`.** The rule now counts assertions per function instead of only detecting presence. Default `min_assertions = 1` preserves the existing behaviour; set `min_assertions = 2` for the assertion density Holzmann's rule 5 actually asks for. Configurable in `[tool.safelint.rules.missing_assertions]` (pyproject.toml) or `[rules.missing_assertions]` (safelint.toml); a non-integer value fails loud with a `TypeError`.

### Changed

- **SAFE302 `global_mutation` now covers Java** (previously Python / JS / TS only). On Java it flags **non-final `static` field declarations**, Java's shared-mutable-state shape, at the declaration site. `static final` fields are clean (interior mutability of a `final` referent is a documented exclusion needing type resolution); instance fields, locals, and interface fields never fire. This fulfils the Java SAFE302 work previously marked "deferred to a future release" in the language docs. **Heads-up for existing Java users:** because SAFE302 is enabled by default, projects with non-final `static` fields will see new violations after upgrading; suppress per-line with `// nosafe: SAFE302`, per-file, or via `per_file_ignores` if this is not yet a policy you want to enforce. SAFE302 remains unported to Rust (`static mut` is SAFE602's territory; safe interior-mutable statics are the new SAFE307's).

### Documentation

- **Removed the four repo-root redirect stubs** (`AI_CLIENTS.md`, `CONFIGURATION.md`, `ADDING_AN_AI_CLIENT.md`, `ADDING_A_LANGUAGE.md`). These were 7-line "this page has moved" placeholders left behind by the docs-site migration; the live `CONTRIBUTING.md` / `SUPPORT.md` pointers now link straight to the docs site (`shelkesays.github.io/safelint/...`) and code-comment references point at `docs/...` paths. The `mkdocs` build is unaffected (the community-health copies resolve cross-references through `scripts/prepare_docs.py`'s rewrite map, not the stubs).
- **Doc accuracy pass for the new rule set.** Refreshed rule and AI-client counts across `README.md`, `docs/index.md`, `docs/configuration/rules.md`, and the per-language pages (38 rules total: 15 on by default, 23 opt-in; 14 supported AI clients), updated every per-language page, the bundled client skill files, and the language crib sheets to list SAFE105 / SAFE307 / SAFE309 / SAFE603 and the widened SAFE302, and fixed a broken `cli.md#exit-code-2-silent-failure-triggers` anchor referenced from three language pages.

### Internal

- **SafeLint now passes its own rule set with no inline suppressions other than the documented `SAFE203` logging exemptions.** The new `SAFE105 no_recursion` rule fires on intra-procedural tree-walkers in the dataflow analysers, `deep_merge`, and a couple of parse-tree helpers; rather than annotate them, those were converted to explicit iterative worklists / loops (mirroring the existing iterative `walk()`), and the remaining `SAFE501` worklist-drain annotations and one `SAFE304` annotation were likewise refactored away. No behaviour change; recursion depth on the affected helpers was always bounded by source-construct nesting.

## [2.3.0] - 2026-06-09

**Kiro AI client; documentation accuracy pass.** Kiro (`kiro.dev`, AWS's agentic IDE) joins the registry as the fourteenth supported AI client, additive, one `ClientSpec`. This release also folds in the post-2.2.0 documentation work: the per-client docs gaps for Warp and OpenCode are closed, `docs/configuration/cli.md` is restructured into a per-command reference, and the contributing "Adding an AI client" guide plus the AI client integration pages are corrected against the current single-file install architecture. No behaviour change for existing clients or languages.

### Added

- **Kiro (`kiro.dev`) added as a supported AI client.** AWS's agentic IDE reads steering files under `.kiro/steering/*.md`; `safelint skill install --client kiro` writes `.kiro/steering/safelint.md` at project scope (`--project`, recommended for team repos) or `~/.kiro/steering/safelint.md` at user scope. Auto-detection picks up a `.kiro/` directory in the cwd (project) or home (user). One `ClientSpec` addition plus the bundled `skill_files/kiro/safelint.md` template; the `_CLIENT_SPECS` registry, drift-detection contract, and CLI choices all extend automatically. Kiro also honours the `AGENTS.md` standard as a fallback, but safelint installs to its first-class steering file rather than coupling on the shared `AGENTS.md` (owned by the codex client).

### Documentation

- **Warp added to the per-client docs.** New `docs/ai-clients/clients/warp.md` page covering the project-scope-only contract; row added to the client table in `docs/ai-clients/index.md`; mkdocs nav entry under Per-client guides. (Warp itself shipped as a client in 2.2.0; this just closes the docs gap.)
- **OpenCode auto-detection documented in `codex.md`.** New "OpenCode auto-detection" subsection covering the `.opencode/` marker piggyback, the AGENTS.md auto-create vs append cases, and a "Note on OpenClaw" explaining why that agent was evaluated and deliberately not added.
- **Per-client guides reordered by approximate real-world usage** (mainstream / mid / lower / niche tiers) instead of "the order we added support". `_CLIENT_SPECS` order in `_skill_install.py` is unchanged - the registry order drives auto-detection iteration and CLI output; only the docs ordering follows popularity.
- **`docs/configuration/cli.md` restructured into a per-command reference** (one section per command and subcommand, brief style: description + flags table + 1-2 examples). New dedicated sections for `safelint skill install`, `safelint skill path`, `safelint --stdin`, `safelint version`, and `safelint help`. Promoted from "Configuration → CLI flags and commands" to a top-level "CLI commands and flags" nav entry; URL `.../configuration/cli/` unchanged.
- **`docs/json-schema.md` clarifications.** Reframed "stable since v1.5.0" to distinguish shape stability (v1.5.0) from rule-set growth (Java in v2.1.0, Rust in v2.2.0). Added a "Language coverage" note clarifying all five languages produce identical JSON structures.
- **Contributing and integration docs corrected against current code.** The "Adding an AI client" guide dropped a non-existent install primitive and the obsolete `_PEER_CLIENT_DIRS` step, added the required `documentation_relpaths` field to its worked example, documented the project-scope-only client pattern, and refreshed its client / language counts. `docs/ai-clients/lifecycle.md` and `scope.md` now describe the single-file install model (no directory-tree install) and the project-scope-only contract. Contributor pointers no longer instruct editing the moved repo-root redirect stubs (`AI_CLIENTS.md` / `CONFIGURATION.md`).

### Bundled-skill drift after upgrade

`pip install --upgrade safelint` past this release will cause **`safelint skill status` to report DRIFT** on every installed copy. That's because all 13 bundled skill files (the per-client templates under `src/safelint/skill_files/`) were edited to fix two issues:

- The JSON example violation was internally inconsistent (`SAFE101 / function_length` paired with a `bare_except` suggestion). Switched to `SAFE201 / bare_except` so code, rule, and suggestion describe the same defect.
- The "stable since v1.5.0" schema-stability sentence was reworded to acknowledge rule-set expansion (matching `docs/json-schema.md`).

Action for users running `safelint skill install`: after upgrading, run `safelint skill update` (idempotent; refreshes drifted installs to the new bundled content). Symlink-mode installs (`safelint skill install --symlink`) pick up the new bundle automatically with no action needed. See [`safelint skill status`](https://shelkesays.github.io/safelint/configuration/cli/#safelint-skill-status) and [`safelint skill update`](https://shelkesays.github.io/safelint/configuration/cli/#safelint-skill-update) in the CLI reference.

## [2.2.0] - 2026-06-01

**Rust support; rule-catalogue CLI; Warp + OpenCode agents.** Promotion of the rc1 / rc2 / rc3 cycle to GA. Three additive bundles ship together: a fifth supported language, a CLI surface for catalogue introspection, and two more AI clients on the registry. Python / JavaScript / TypeScript / Java users see zero behaviour change beyond an additive grammar option, an additive CLI subcommand, and an additive `--client=warp` choice.

**Install:** `pip install 'safelint[rust]'` to add Rust to an existing setup (PyO3 / maturin polyglot: `pip install 'safelint[python,rust]'`); plain `pip install safelint` ships the engine only (no language grammars), so projects must use the `[<lang>]` extra matching their source files.

### Release model

The `pyproject.toml` version bump that lands on `main` for this release reads as `2.1.0` (the previous GA) to `2.2.0`. That's the diff a reviewer sees against `main`. The full trajectory was tracked on the `release/rust` integration branch instead, so `main` is insulated from the in-flight RC churn:

| Step | Branch | Tag | PyPI |
|---|---|---|---|
| `2.1.0` (previous GA) | `main` | `v2.1.0` | live |
| `2.1.0` to `2.2.0rc1` | `release/rust` | `v2.2.0rc1` | live (pre-release) |
| to `2.2.0rc2` | `release/rust` | `v2.2.0rc2` | live (pre-release) |
| to `2.2.0rc3` | `release/rust` | `v2.2.0rc3` | live (pre-release) |
| to `2.2.0` (this GA) | merges to `main` | `v2.2.0` | published on tag push |

The rc1 / rc2 / rc3 commits never landed on `main` directly; their content arrives wholesale through this GA merge. The detailed rc1 / rc2 / rc3 changelog entries below catalogue when each feature first shipped so anyone tracing a regression can find the originating RC.

### Highlights

- **Rust as the 5th registered language** (from rc1). `.rs` files are discovered, parsed via Tree-sitter, and run against 13 of the cross-language rules (the all-five-languages set). 10 additional Rust-only rules cover Rust-idiom-specific patterns (panic placement, lock poisoning, `unsafe` block documentation, truncating `as` casts, silent `Err` arms, dangerous `mem::*` ops, needless `mut`, unchecked arithmetic on integer params, broad `.unwrap()` outside tests, plus the empty-`Err` / unlogged-`Err` Rust analogues of `empty_except` / `logging_on_error`). Recognises both inline `#[cfg(test)] mod tests` and Cargo `tests/<stem>.rs` integration-test conventions. See the [Rust language page](https://shelkesays.github.io/safelint/languages/rust/) and the rc1 entry below for the full per-rule rationale.
- **`safelint list-rules` subcommand** (from rc2). Prints the rule catalogue so AI agents, CI dashboards, and docs pipelines can introspect what safelint will check. Filters: `--language=python|javascript|typescript|java|rust`, `--enabled-only`. Output formats: `--format=text` (default), `--format=json`, `--format=markdown`, `--format=sarif`. The `--list-rules` flag form works as an alias when placed anywhere in argv. Categories derived from the leading digit of each `SAFExxx` code, matching the rule-numbering policy.
- **Warp as the 13th AI client** (from rc2). `safelint skill install --client=warp` writes `<cwd>/WARP.md` (auto-discovered by Warp's terminal-native AI) or `~/.warp/WARP.md` (user-global). Auto-detection markers: `WARP.md` and `.warp/`.
- **OpenCode auto-detection** (from rc3). `safelint skill install --client=auto` notices OpenCode (`sst/opencode`) projects via `.opencode/` in codex's `cwd_markers`. OpenCode reads `AGENTS.md` for project context, the same file codex's secondary install already populates with a delimited safelint section. No new client spec needed.

### Cumulative scope vs 2.1.0

Every change shipped via the three release candidates is in this GA. Pin to `safelint==2.2.0` for a deterministic install; the rc1 / rc2 / rc3 entries below document the iteration history for anyone who needs to trace when a specific feature landed.

The detailed change lists, default configurations, deliberately-skipped rules, and per-rule rationale live in the rc1 / rc2 / rc3 sections immediately below. They are kept verbatim as historical record rather than reflowed here.

## [2.2.0rc3] - 2026-06-01

**OpenCode auto-detection.** One-line addition to the codex spec's `cwd_markers` extends `safelint skill install --client=auto` to notice OpenCode (sst/opencode) projects. OpenCode reads `AGENTS.md` at the repo root for project context, the same file codex's secondary install populates with a delimited safelint section. An OpenCode-only project (`.opencode/` directory present, no `.codex/`) now auto-detects and gets the safelint section in `AGENTS.md` transparently.

### Added

- **`.opencode` in codex `cwd_markers` and `home_markers`** - OpenCode users get the safelint AGENTS.md section through the existing codex spec machinery; no new client entry needed because both agents read the same shared file. The primary install still lands at `.codex/instructions.md` (a small Markdown file OpenCode itself ignores; users can gitignore it). New test (`test_install_auto_detects_codex_via_opencode_dir`) pins the contract.

### Evaluated and skipped

- **OpenClaw** (https://openclaw.ai) - chat-bridge agent (WhatsApp / Slack / Telegram / iMessage / Discord / Signal) with global-only configuration (`~/.openclaw/openclaw.json` for channel allowlists and mention rules). No project-level instructions / rules file convention, no per-workspace context. Installing a Markdown skill file would create a file nothing reads, so OpenClaw doesn't currently fit the safelint skill abstraction. Revisit when (if) the project adds a per-project rules-file feature.

## [2.2.0rc2] - 2026-05-29

**Two additive features on top of rc1 ahead of the 2.2.0 GA.** Rust support stays exactly as it shipped in rc1 (no behaviour change for the existing language work); this RC adds a CLI rule-catalogue command and brings the AI-client roster to thirteen.

### Added

- **`safelint list-rules` subcommand (and `--list-rules` flag alias)** - prints the full rule catalogue so AI agents, CI dashboards, and docs-generation pipelines can introspect what safelint will check without grepping the per-agent skill files. Filters: `--language=python|javascript|typescript|java|rust` to scope to a single language, `--enabled-only` to drop opt-in rules. Output formats: `--format=text` (default; aligned table grouped by category band), `--format=json` (programmatic catalogue with `version` + per-rule schema), `--format=markdown` (one table per category band, useful for piping into docs), `--format=sarif` (SARIF 2.1.0 catalogue with the rules under `runs[0].tool.driver.rules[]` and an empty `results[]`; consumable by GitHub Code Scanning catalogue UIs). Categories are derived from the leading digit of the rule code so the listing automatically picks up the SafeLint rule-numbering policy (1xx function shape, 2xx error handling, 3xx side effects / state, 4xx resource lifecycle, 5xx loop safety, 6xx documentation, 7xx test coverage, 8xx dataflow, 9xx framework-specific). Default scope shows every shipped rule with a `Default` column marking enabled-by-default vs opt-in; the catalogue stays catalogue-only (severity / enabled defaults from the bundled `DEFAULTS`, not from the user's resolved config). Empty filter combinations exit 2 with a stderr error so a typo in a CI script (`--language=pythn`) can't silently produce an empty document.
- **Warp as a 13th AI client** - `safelint skill install --client=warp` writes `<cwd>/WARP.md` (canonical, auto-discovered by Warp's AI) or `~/.warp/WARP.md` (user-global). The bundled skill file (`src/safelint/skill_files/warp/WARP.md`) mirrors the existing 12 client skill files: the same 8 steps, the same JSON parsing recipe, the same Power-of-Ten rationale crib sheet, plus Warp-specific touches (the AI is in the terminal, so all check / install commands land directly as terminal tasks). Auto-detection markers are `WARP.md` (the canonical project file) and `.warp` (Warp's user-config directory). Listed in the `--client` choices, the `safelint help skill` output, and the `_HELP_COMMANDS` line.

### Changed

- **`safelint list-rules` referenced in every skill file's language-detection step** - the new "to check the live rule list, run `safelint list-rules --format json` and look at the `languages` field" hint replaces the longer Python-snippet fallback in the bundled WARP.md addendum (other agent skill files still carry the legacy form for backwards compatibility with already-installed copies). The Python snippet stays documented as the fallback.
- **Documentation roster updated** - `README.md`, `SUPPORT.md`, `AI_CLIENTS.md`, `docs/index.md`, `docs/configuration/cli.md`, `docs/contributing/adding-an-ai-client.md`, and `src/safelint/skill_files/README.md` now read "thirteen supported AI clients" and add Warp to every per-client install/usage table.

### Internal

- `src/safelint/_rule_listing.py` - new module exposing `iter_rule_specs()`, `filter_specs()`, and four format renderers (`format_text` / `format_json_listing` / `format_markdown_listing` / `format_sarif_listing`). Pure-function design, no engine / config / parser dependencies, so the catalogue is cheap to render in any process the agent is running in.
- `cli.py` - `_build_list_rules_parser` + `_run_list_rules` + `_print_rule_listing` thread the subcommand through the existing argv-routing scanner. `_dispatch_subcommand` refactor moves the per-subcommand-token routing out of `main()` so `main()` stays under the `function_length=60` / `complexity=10` caps safelint enforces on itself.
- `_skill_install.py` - one `_WARP_SPEC` `ClientSpec` entry plus its position in `_CLIENT_SPECS`; the rest of the install / detection / status / remove machinery picks it up automatically because all of those routes iterate over the registry.

## [2.2.0rc1] - 2026-05-27

**Rust is now a supported language.** Second new language landing in the v2.x line. `.rs` files are discovered, parsed via Tree-sitter, and run against 17 of the 20 cross-language rules - plus 10 new Rust-only rules covering Rust-idiom-specific patterns. Python / JavaScript / TypeScript / Java users see zero behaviour change beyond an additive grammar option.

**Install:** `pip install 'safelint[rust]'` (PyO3 / maturin polyglot projects: `pip install 'safelint[python,rust]'`). Tagged as a release candidate so the new language can be exercised against real Rust codebases before promoting to GA.

### Added

- **Rust as a registered language**: 27 rules apply, with the engine's per-language dispatch routing `.rs` files automatically. Source-language analysis (parser, AST walks, per-rule logic) is identical to the other registered languages; only language-idiom-specific detail (macro handling, attribute scanning, pattern matching) is per-language.
- **17 cross-language rules ported to Rust**: `SAFE101 function_length`, `SAFE102 nesting_depth`, `SAFE103 max_arguments`, `SAFE104 complexity`, `SAFE303 side_effects_hidden`, `SAFE304 side_effects`, `SAFE501 unbounded_loops`, `SAFE601 missing_assertions`, `SAFE701 test_existence`, `SAFE702 test_coupling`, `SAFE801 tainted_sink`, `SAFE802 return_value_ignored`, `SAFE803 null_dereference`. Each rule's `language` tuple was widened to include `"rust"` and per-language node-type tables grew a Rust entry. Rust-specific defaults shipped: `io_functions_rust` (covers macros `println` / `eprintln` / `write` / `writeln` / `dbg` alongside fs / io / process / network calls), `assertion_calls_rust` (stdlib `assert*` macros, debug-only variants, proptest's `prop_assert*`), `sinks_rust` / `sources_rust` / `sanitizers_rust` (taint defaults centred on `Command` shell execution, raw-SQL crate verbs, `Library` FFI, `open` paths; narrow sanitizer set), `nullable_methods_rust` (`Map::get` / `Vec::get` / `Iterator::next` / `parse` / `var` / fs::read family / checked arithmetic), `flagged_calls_rust` (io::Write / io::Read / fs mutators / network send / process spawn).
- **10 Rust-only rules** slotted into existing category bands per the SafeLint rule-numbering policy (no new band created for the language):
  - **`SAFE110 needless_mut`** (1xx function-shape, warning, default-disabled): `let mut x = ...` where `x` is never reassigned, never has `&mut x` taken, and is never used as a method receiver / field-access / index target. Conservative skips on ambiguous usages to keep false-positive rate low. Mirrors `clippy::needless_mut`. Holzmann rule 6 (smallest scope).
  - **`SAFE112 unchecked_arithmetic_on_input`** (1xx, warning, default-disabled): `+` / `-` / `*` on integer-typed function parameters can overflow silently in release. Use `checked_*` / `wrapping_*` / `saturating_*` to make the choice explicit. Static-only detection (parameter type annotations); locally-derived integers aren't tracked. Holzmann rule 7.
  - **`SAFE204 panic_macros_outside_tests`** (2xx error-handling, warning, default-disabled): `panic!` / `todo!` / `unimplemented!` macros in non-test code. `unreachable!()` deliberately excluded from defaults (idiomatic for impossible-branch markers). Test code (`#[test]` or `#[cfg(test)] mod`) is exempt.
  - **`SAFE205 lock_poisoning_ignored`** (2xx, warning, default-disabled): `mutex.lock().unwrap()` / `rwlock.read().unwrap()` / `.write().unwrap()` patterns silently cascade `PoisonError` panics across threads. Match on `PoisonResult` or call `.into_inner()` explicitly.
  - **`SAFE206 silent_result_discard`** (2xx, warning, default-disabled): empty `Err(_) => {}` arms and empty `if let Err(_) = ... { }` bodies. The Rust spiritual analogue of `SAFE202 empty_except`. `let _ = result;` and `result.ok();` do NOT fire (those are explicit auditable discards, not silent swallows).
  - **`SAFE207 unlogged_error_branch`** (2xx, warning, default-disabled): `Err` arms / `if let Err(...)` bodies with non-empty bodies that contain no log call. Recognised log calls: `error!` / `warn!` / `info!` / `debug!` / `trace!` / `log!` / `event!` (log + tracing crates), `eprintln!` / `eprint!` / `println!` / `print!` / `dbg!`. Exempts bodies with `return`, panic-like macros, or tail-position `Err(...)` re-raise. The Rust analogue of `SAFE203 logging_on_error`.
  - **`SAFE208 result_unwrap_outside_tests`** (2xx, warning, default-disabled): broad form, fires on any `.unwrap()` / `.expect()` / `.unwrap_unchecked()` outside test code. Catches bare-variable unwraps that the narrower SAFE205 / SAFE803 miss. Documented intentional overlap with those two; users pick strictness level by enabling subsets. Holzmann rule 7.
  - **`SAFE306 dangerous_mem_ops`** (3xx side-effects, error, default-disabled): `std::mem::transmute` / `transmute_copy` / `forget` / `zeroed` / `uninitialized` calls. Path-qualified detection (the function's scoped-identifier path must contain `"mem"`) avoids firing on user-defined helpers of the same name. Bare `transmute(x)` (no `mem::` prefix) is NOT flagged.
  - **`SAFE308 truncating_as_cast`** (3xx, warning, default-disabled): `as u8` / `as u16` / `as u32` / `as i32` / `as f32` casts silently truncate. `TryFrom` / `try_into()` is the checked alternative. `isize` / `usize` / `i128` / `u128` / `f64` are NOT flagged as targets (widest types). Configurable via `truncating_cast_targets_rust`. Holzmann rule 1 + 7.
  - **`SAFE602 undocumented_unsafe`** (6xx documentation, warning, default-disabled): `unsafe { ... }` blocks lacking a `// SAFETY:` comment (case-insensitive) on a preceding line. Mirrors `clippy::undocumented_unsafe_blocks`. `unsafe fn` declarations not covered (separate `/// # Safety` convention; future rule may extend).
- **Rust test-context detection**: SAFE204 / SAFE208 / SAFE701 walk parent `function_item` / `mod_item` for `#[test]` or `#[cfg(test)]` attributes (which parse as preceding-sibling `attribute_item`s, the tree-sitter-rust convention). The detection is correctness-critical for SAFE701 in particular - without it every Rust source with the idiomatic inline `#[cfg(test)] mod tests` would falsely fire asking for an external `tests/<stem>.rs` pair the Rust ecosystem doesn't use.
- **Rust macro handling**: SAFE303 / SAFE304 walk `macro_invocation` nodes alongside `call_expression` (Rust's most common I/O entry points are macros like `println!` / `eprintln!` / `write!` / `writeln!` / `dbg!`). Macro names render with the trailing `!` in violation messages.
- **`languages/rust.md` skill addendum**: parallel to python.md / java.md / javascript.md / typescript.md - the Rust-specific addendum AI clients read when an agent's session is in a Rust project. Covers install nuance, macro handling, test-context detection, per-rule Rust phrasing for all 27 codes, deliberately-skipped rules, idiomatic fix patterns, integration with the Rust tool chain.
- **All 12 AI clients updated**: each per-agent skill file (claude / cursor / copilot / gemini / windsurf / codex / continue / cline / aider / trae / antigravity / zed) gets the `pip install 'safelint[rust]'` row in its install table, the `Rust` → `languages/rust.md` row in its language addendum table, and 10 new SAFE10x / SAFE20x / SAFE30x / SAFE602 rule rows for the Rust-only rules.
- **docs site Rust reference page** (`docs/languages/rust.md`): mkdocs nav now includes Rust alongside the other four languages; the page mirrors the skill addendum content for site readers.

### Cross-language rules deliberately skipped for Rust

These 6 rules are NOT registered for Rust because the Python / JS-family / Java semantics don't translate cleanly:

- **`SAFE201 bare_except`**: Rust has no try/catch. The panic-recovery primitive is `std::panic::catch_unwind` which has its own auditable shape, no bare-catch hazard.
- **`SAFE202 empty_except`**: no try/catch. Spirit ("silently swallow an error") covered by SAFE206 instead.
- **`SAFE203 logging_on_error`**: no try/catch. Spirit ("handle the error without logging") covered by SAFE207 instead.
- **`SAFE301 global_state`** / **`SAFE302 global_mutation`**: Rust has no `global` keyword. `static mut FOO` requires `unsafe { }` access, already audit-gated by SAFE602.
- **`SAFE401 resource_lifecycle`**: Rust's RAII (Drop trait) makes resource cleanup language-enforced. No `with` block / `try-finally` / `try-with-resources` analogue needed.

### Numbering policy clarification

The SafeLint rule-numbering policy is now explicit in `CLAUDE.md`: language-idiom rules slot into existing category bands by closest theme (1xx-8xx) rather than getting per-language bands. 9xx remains reserved for framework-specific rules (Spring today; future axum / actix / Django / Express / Rails framework rules will go here too). This commit's 10 Rust-only rules land in 1xx / 2xx / 3xx / 6xx accordingly, alongside their cross-language siblings.

## [2.1.0] - 2026-05-21

**v2.1.0 GA.** The release candidate cycle is closed. The cumulative scope vs `v2.1.0rc1` is a long list of rule-correctness fixes and doc / skill consistency fixes that landed during the RC review cycle; engine and rule behaviour on the headline Java + Spring Boot surface is now finalised for the 2.1.x line. Functionally `v2.1.0` ships the rc1 feature set (Java as a registered language, the `spring-boot` framework preset, the four new `SAFE901-904` rules, 16 cross-language rules ported to Java) plus the corrections below.

**Install:** RC pins and `--pre` flags are no longer required. `pip install 'safelint[java]'` resolves to `2.1.0` straight from PyPI.

### Rule corrections (vs `2.1.0rc1`)

- **SAFE401 `resource_lifecycle`** for Java's manual `try { ... } finally { ... }` is now strict: the finally clause must contain a direct `<acquired-var>.close()` invocation. The previous heuristic accepted any try with a finally; `try { in = new FileInputStream(p); } finally { audit(); }` silently passed. Bare-expression acquirers (`try { new FileInputStream(p); } finally { ... }`) now always fire. Wrapped acquirers (`br = new BufferedReader(new FileReader(path))`) correctly inherit the outer variable name for cleanup tracking. **Helper-pattern trade-off:** `IOUtils.closeQuietly(in)`, `Try.run(() -> in.close())` style closes are NOT recognised under the strict matcher and will fire; switch to try-with-resources or suppress with `// nosafe: SAFE401`. The strict path applies to Java only; JavaScript retains its documented heuristic.
- **SAFE801 `tainted_sink`** lambda capture analysis: a Java lambda's tracker is now seeded with own-params plus the enclosing method's final tainted set (locals included), so `String dirty = input; run(() -> exec(dirty));` correctly fires. Compound assignments (`sql += " suffix"`) preserve the LHS's existing taint. Chained assignments (`a = b = source()`) propagate the innermost-RHS taint through every LHS. Enhanced-for loops (`for (String arg : args) { exec(arg); }`) taint the loop variable from the iterable. Receiver-as-input now matches generic-type constructors via `generic_type` unwrap (`new MyResource<Foo>(input)`).
- **SAFE801 sanitizers_java defaults narrowed.** Context-specific output encoders (OWASP `forHtml` / `forJavaScript` / `forCssString`, Apache Commons `escapeHtml*` / `escapeXml` / `escapeJava` / `escapeJson`, Spring `htmlEscape`) and URL encoders (`encode` / `encodeURIComponent`) are no longer in defaults. They were creating cross-context false negatives (`Encode.forHtml(name)` before `jdbc.query(...)` silently cleared the SQL-sink warning). Defaults are now `sanitize` / `validate` / `quote` / `escape` only; opt back in via TOML if your project routes everything through a specific encoder.
- **SAFE801 spring-boot preset sinks: collision-prone bare verbs removed.** `put` / `delete` / `update` / `exchange` are no longer in the preset's `sinks_java`; they collided with `HashMap.put` / `File.delete` / `CurrencyExchange.exchange` / project-local helpers under SAFE801's single-set design. Unambiguous Spring names (`query` / `queryForObject` / `queryForList` / `queryForMap` / `queryForRowSet` / `batchUpdate` / `getForObject` / `getForEntity` / `postForObject` / `postForEntity` / `postForLocation` / `patchForObject`) stay. Add the bare verbs explicitly via `[tool.safelint.rules.tainted_sink] sinks_java` if your project needs `restTemplate.put(...)` / `jdbcTemplate.update(...)` coverage.
- **SAFE902 `spring_missing_transactional` receiver-name guard.** The rule now only counts repository-write method calls whose receiver name (lowercased) contains `repo` / `dao` / `jdbctemplate`. Without this, `call_name()` stripped the receiver and unrelated calls like `file.delete()` / `cache.delete()` / `restTemplate.delete(...)` were counted as Spring Data writes. Bare `template` was tested but matched non-DB Spring templates (`restTemplate`, `kafkaTemplate`, `redisTemplate`); `jdbctemplate` is the correct narrower pattern. Recognises `this.userRepo.save(...)` field-access receivers too.
- **SAFE904 `spring_async_checked_exception` class-level `@Async`.** The rule now also fires when the enclosing class carries `@Async` (not only the method). Spring applies class-level `@Async` to every method in the class; the throws clause is just as misleading either way. Docs and rule docstring updated to reflect that the rule flags ANY `throws` clause (checked or unchecked) for simplicity; distinguishing checked vs unchecked needs type-inference safelint doesn't do.
- **SAFE103 `max_arguments` untyped Java lambda params.** `(a, b, c, d, e, f, g, h) -> ...` and `a -> ...` shapes parse as `inferred_parameters` / bare `identifier` in tree-sitter-java; the rule's counter dispatched only on `formal_parameter` / `spread_parameter` and silently counted untyped lambdas as zero-arg. Added the lambda-specific dispatch so over-argument untyped lambdas in stream pipelines correctly fire.
- **SAFE202 `empty_except` Java catch-body shapes.** Empty Java catch bodies with multiple comment children (`{ // a\n // b\n }`) now correctly classify as empty. tree-sitter-java emits each comment as a named block child. Empty-statement (`;`) inside Java catches is also recognised as a no-op. Python / JS / TS retain their single-statement check.
- **SAFE701 / SAFE702 `Test`-prefix Java false-positives removed.** Production classes like `TestDataFactory.java` / `TestConfig.java` under `src/main/java` were being classified as tests (silently skipping coverage enforcement). The `Test`-prefix shortcut is gone; legitimate JUnit 3 tests under the configured `test_dirs` are still picked up via the path-component check.
- **`_node_utils._java_object_creation_name` now handles `generic_type`.** `new MyResource<Foo>(...)` parameterised constructors were silently invisible to SAFE401 tracked-acquirer / SAFE801 constructor-sink / SAFE303-304 I/O-constructor matchers. The unwrap recurses through `generic_type` to the inner `type_identifier` / `scoped_type_identifier`.
- **SAFE303 / 304 default `io_functions_java` cleanups.** `HttpClient` is replaced by the actual matched factory + send method names (`newHttpClient` / `send` / `sendAsync`); the class itself has no public constructor so `call_name()` never returned `"HttpClient"`. `format` removed from SAFE303's set (collided with `String.format` / `MessageFormat.format`). `FileChannel` removed from SAFE401's `tracked_functions_java` for the same receiver-stripping reason.

### Doc / skill alignment

- All Java suppression examples switched from `# nosafe` to `// nosafe`; Java's comment prefix is `//`.
- SAFE801 docs now describe what's actually in `sanitizers_java` defaults (no HTML / URL encoders) and explain why.
- README rule-count totals corrected: 24 rules total (was 20), 14 default-on, 10 opt-in (the four `SAFE9xx` are opt-in under vanilla, default-enabled by the `spring-boot` preset).
- Per-language docs corrected: "16 cross-language rules" (was "17"); SAFE302 is Python / JS / TS only, not cross-all-four.
- SAFE902 / SAFE903 severity rows in the rule reference corrected from `"warning"` to `"error"` (matches the implementation).
- README and the docs landing page now list Java in the "Currently supported languages" table; PyPI keywords + description include `java` / `spring-boot`.
- `docs/configuration/rules.md` got a full `SAFE901` / `SAFE902` / `SAFE903` / `SAFE904` rule-detail section (was missing).
- Project-wide writing-style sweep: em-dashes removed from all docs / skills / README / CHANGELOG re-introduced during the RC cycle.

### Migration

- **From `v2.0.0`:** see the *Migration* table in the [2.1.0rc1] entry below; the only required change is bumping the install command to opt into the new `[java]` extra if you lint Java sources, and bumping `rev: v2.0.0` to `rev: v2.1.0` in pre-commit configs.
- **From `v2.1.0rc1`:** drop any `==2.1.0rc1` pin or `--pre` flag; `pip install -U 'safelint[<lang>]'` is sufficient. Pre-commit users bump `rev: v2.1.0rc1` to `rev: v2.1.0`.

## [2.1.0rc1] - 2026-05-16

**Java is now a supported language, with a dedicated Spring Boot framework preset.** First MINOR release after v2.0.0; ships as a release candidate so the new language can be exercised against real Spring Boot codebases before promoting to GA. Source-language analysis works on every Java file; per-project tuning happens via the new ``[tool.safelint.java] framework = "spring-boot"`` selector that adds Spring-aware taint sinks, nullable methods, and four new structural rules (``SAFE901-904``) covering common Spring Boot misuses. Python / JavaScript / TypeScript users see zero behaviour change.

Install as a RC pre-release:

```bash
pip install 'safelint[java]'
# or, for a polyglot repo:
pip install 'safelint[python,java]'
# or the kitchen-sink:
pip install 'safelint[all]'
```

Pre-commit users update ``rev: v2.0.0`` to ``rev: v2.1.0`` and add ``'safelint[java]==2.1.0rc1'`` to ``additional_dependencies`` (the RC pin is required until v2.1.0 GA so pre-commit's pip resolver does not fall back to v2.0.0 which lacks the ``[java]`` extra).

### Added

- **Java as a fully-registered language**, ``.java`` files are now parsed, walked, and dispatched through the engine the same way as Python / JavaScript / TypeScript. New ``src/safelint/languages/java.py`` exports the per-grammar node-type constants (``METHOD_DECLARATION`` / ``CONSTRUCTOR_DECLARATION`` / ``LAMBDA_EXPRESSION`` / ``CATCH_CLAUSE`` / ``TRY_WITH_RESOURCES_STATEMENT`` / ``METHOD_INVOCATION`` / ``OBJECT_CREATION_EXPRESSION`` / etc.) plus the ``JAVA`` ``LanguageDefinition``. Registered in ``src/safelint/languages/__init__.py`` with the standard available / unavailable gating - missing the ``[java]`` extra surfaces the install hint on first run, same posture as JS / TS.
- **16 cross-language rules ported to Java**: ``SAFE101 function_length``, ``SAFE102 nesting_depth``, ``SAFE103 max_arguments``, ``SAFE104 complexity``, ``SAFE202 empty_except``, ``SAFE203 logging_on_error``, ``SAFE303 side_effects_hidden``, ``SAFE304 side_effects``, ``SAFE401 resource_lifecycle``, ``SAFE501 unbounded_loops``, ``SAFE601 missing_assertions``, ``SAFE701 test_existence``, ``SAFE702 test_coupling``, ``SAFE801 tainted_sink``, ``SAFE802 return_value_ignored``, ``SAFE803 null_dereference``. Each rule's ``language`` tuple was widened to include ``"java"`` and the per-language node-type tables grew a Java entry. Java-specific defaults shipped for the configurable rules: ``io_functions_java`` (``println`` / ``print`` / ``FileInputStream`` / ``Files.readAllBytes`` / ...), ``tracked_functions_java`` (file streams via ``new`` + ``Files`` factory methods + JDBC ``getConnection``), ``assertion_calls_java`` (JUnit 5 ``Assertions.*`` + AssertJ ``assertThat``), ``sinks_java`` / ``sources_java`` (Servlet API for sources; ``Runtime.exec`` / ``executeQuery`` / reflection / SSRF entry points for sinks) and ``sanitizers_java`` (limited to generic validators / wrappers: ``sanitize`` / ``validate`` / ``quote`` / ``escape``. Context-specific encoders are deliberately NOT in the defaults: URL encoders ``encode`` / ``encodeURIComponent`` are URL-only, Apache Commons HTML/XML escapers and Spring ``htmlEscape`` are HTML-only, and the OWASP Java Encoder API is per-context; including any of those as universal sanitizers would suppress SAFE801 on cross-context flows like ``jdbc.query("... " + encode(input))``. Users who route output through one of those encoders can opt them in via TOML), ``flagged_calls_java`` (``File`` mutators + immutable-type methods), ``nullable_methods_java`` (``Map.get`` / ``getParameter`` / ``getHeader`` / reflection getters).
- **Java framework presets** via ``[tool.safelint.java] framework = "<name>"``, mirroring the JS runtime-presets architecture from v1.13.0. Two presets ship today:
  - ``vanilla`` (default) - plain Java stdlib defaults; the four ``SAFE9xx`` Spring rules stay disabled. Existing v2.0.0 users picking up v2.1.0rc1 see no behaviour change unless they explicitly opt in.
  - ``spring-boot`` - extends ``sinks_java`` with unambiguous JdbcTemplate / RestTemplate methods: ``query`` / ``queryForObject`` / ``queryForList`` / ``queryForMap`` / ``queryForRowSet`` / ``batchUpdate``, and ``getForObject`` / ``getForEntity`` / ``postForObject`` / ``postForEntity`` / ``postForLocation`` / ``patchForObject``. Bare ``put`` / ``delete`` / ``update`` / ``exchange`` are deliberately excluded because they collide with HashMap / File / project-local helpers under SAFE801's single-set design (no receiver-aware matching); users who specifically want ``restTemplate.put`` / ``.delete`` / ``.exchange`` SSRF detection or ``jdbcTemplate.update`` SQLi detection can opt in via TOML. Extends ``nullable_methods_java`` with ``queryForObject`` (RowMapper implementations and nullable column values can yield null; the zero-rows case raises ``EmptyResultDataAccessException`` instead). Enables the four ``SAFE9xx`` Spring-specific structural rules below. Source-language analysis is identical across presets - same parser, same AST walks - only the rule *defaults* shift.
- **Four new Spring Boot framework-aware rules** (``SAFE9xx`` band, Java-only, default-disabled under vanilla, enabled by the ``spring-boot`` preset):
  - **``SAFE901 spring_field_injection``** (warning): ``@Autowired`` on a field declaration. Spring's reference docs recommend constructor injection (immutable, testable, fail-fast on missing deps). Both bare ``@Autowired`` and fully-qualified ``@org.springframework.beans.factory.annotation.Autowired`` are recognised.
  - **``SAFE902 spring_missing_transactional``** (error): service-layer method (``@Service`` / ``@Component`` class) doing 2+ Spring Data writes (``save`` / ``saveAll`` / ``saveAndFlush`` / ``delete`` / ``deleteAll`` / ``deleteAllInBatch`` / ``deleteAllById`` / ``deleteAllByIdInBatch`` / ``deleteById`` / ``update``) without ``@Transactional`` on the method or the class. Receiver-name guard constrains matching to receivers whose lowercased name contains ``repo`` / ``dao`` / ``jdbctemplate`` so unrelated calls like ``file.delete()`` / ``restTemplate.delete()`` don't count. Single-write methods are exempt.
  - **``SAFE903 spring_unvalidated_input``** (error): ``@RestController`` / ``@Controller`` method parameter binds ``@RequestBody`` or ``@ModelAttribute`` without ``@Valid`` / ``@Validated``. ``@PathVariable`` and ``@RequestParam`` are deliberately NOT covered (typically bind to primitives). Complements ``SAFE801`` structurally - ``SAFE801`` catches via dataflow, ``SAFE903`` catches at the input boundary.
  - **``SAFE904 spring_async_checked_exception``** (warning): ``@Async`` method declares a ``throws`` clause. Spring runs ``@Async`` on a separate thread and silently swallows exceptions; the caller never sees them, regardless of throws-clause declarations. Fix: catch inside the body and either swallow with logging or return ``CompletableFuture.failedFuture(...)``.
- **``[java]`` PEP 621 extra** in ``pyproject.toml``, pulls ``tree-sitter-java>=0.23.0``. Folded into ``[all]`` alongside ``[python]`` / ``[javascript]`` / ``[typescript]``. ``pip install 'safelint[java]'`` is the typical Java-only invocation during the RC (drop ``--pre`` and the pin once v2.1.0 GA ships); polyglot Python + Java monorepos compose extras via ``'safelint[python,java]==2.1.0rc1'``.
- **Bundled skill addendum** at ``src/safelint/skill_files/languages/java.md`` (~250 lines) shipped in the wheel so every AI client (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed) consults Java-specific guidance on demand via ``safelint skill path``. Covers install nuance, framework presets, per-rule notes for all 20 applicable rules, deliberately-skipped rules with rationale, idiomatic Java + Spring fix patterns, and integration-with-existing-tooling guidance.
- **mkdocs site page** at ``docs/languages/java.md`` mirroring the skill addendum for the user-facing site. Wired into the Languages nav between TypeScript and Configuration; the landing page (``docs/index.md``) gains a Java row in the supported-languages table.
- **Pre-commit ``types_or`` extended** to ``[python, javascript, ts, tsx, java]`` in ``.pre-commit-hooks.yaml`` so the published hook automatically routes ``.java`` files to the engine without users needing to override the filter. The dedicated Pre-commit docs page (``docs/pre-commit.md``) and the root README gain the ``['safelint[java]']`` ``additional_dependencies`` variant.

### Changed

- **Internal helper refactors** to keep the engine surface clean as the per-language tables grew:
  - ``safelint.languages._node_utils.call_name`` switched to a per-call-node-type dispatch table (``_CALL_NAME_DISPATCH``) so adding Java's ``method_invocation`` and ``object_creation_expression`` didn't push the function-return-count past SAFE104's limit. The public API is unchanged.
  - ``CALL_TYPES`` in ``_node_utils`` now includes Java's two call shapes so cross-language rules walking ``node.type in CALL_TYPES`` automatically catch Java method invocations and ``new Foo()`` constructor calls without per-rule edits.
- **Per-rule drift-detection allow-list** in ``tests/core/test_engine.py`` restructured. A new ``_RULES_JAVA_ONLY`` bucket joins ``_RULES_WIDENED_FOR_JS_FAMILY`` / ``_RULES_WIDENED_FOR_JS_FAMILY_AND_JAVA`` / ``_RULES_JS_FAMILY_ONLY``. The four ``SAFE9xx`` rules live in the Java-only bucket; the previously-cross-language rules ported in this release graduated into the ``_AND_JAVA`` bucket as each port landed. Contributors adding a new per-language rule are pointed at the four buckets in the assertion error message.
- **Coverage threshold held at 97** in ``pyproject.toml`` (unchanged from v2.0.0). The Java port temporarily dipped coverage to 95.84% during scaffolding; the defensive AST-guard branches that valid tree-sitter-java grammar doesn't reach were either pragma-annotated (``# pragma: no cover`` with a one-line rationale) or covered by targeted tests in ``tests/analysis/test_dataflow_java.py`` (cast-unwrap / scoped-type / lambda-capture paths). End-to-end coverage of the cross-language Java rule branches is exercised through the integration suite (``tests/integration/test_spring_boot_e2e.py``) plus per-rule Java unit tests (``tests/rules/test_resource_lifecycle_java.py``, ``tests/rules/test_max_arguments_java.py``, ``tests/rules/test_spring_rules.py``). Final coverage: 97.01%.

### Known limitations

- **``SAFE302 global_mutation`` is deliberately NOT registered for Java.** Python's ``global`` keyword and JS's ``globalThis.x = ...`` patterns have no clean Java analogue. The natural Java equivalent (writes to non-final static fields from outside the declaring class's own static initialiser) needs class-scope analysis the rule doesn't yet do. Deferred to a future release pending user feedback.
- **``SAFE304 side_effects`` does NOT exempt ``@Bean`` factory methods** under the ``spring-boot`` preset. Spring ``@Bean`` factory methods that legitimately create side-effectful resources (DB connections, HTTP clients) trigger the warning today. Suppress with ``// nosafe: SAFE304`` on each factory method until a future ``skip_functions_annotated_with`` config knob lands. The preset's docstring spells this out explicitly so the limitation is auditable.
- **Java 21+ string templates are treated conservatively as untainted** by the dataflow tracker. tree-sitter-java does not yet expose the template-substitution shape uniformly, so a ``STR."Hello \{name}"`` form won't propagate taint through the template. A future grammar upgrade can lift this without re-architecting the rule.

### Upgrading from v2.0.0

For Python / JavaScript / TypeScript users, no action needed - v2.1.0rc1 is fully backward-compatible. The new ``[java]`` extra is opt-in, the Java rules are Java-only (no false positives on existing files), and the framework preset is gated on an explicit ``[tool.safelint.java] framework = "..."`` selector that defaults to ``vanilla``.

For Java adopters, the minimal config is:

```toml
# safelint.toml (standalone) - no [tool.safelint] wrapper
[java]
framework = "spring-boot"   # if you're using Spring Boot; omit for vanilla Java

[rules.tainted_sink]
enabled = true              # dataflow rules are opt-in; flip on for security checks

[rules.test_existence]
test_dirs = ["src/test/java"]   # Maven / Gradle convention
```

See [`docs/languages/java.md`](https://shelkesays.github.io/safelint/languages/java/) for the full per-rule reference and idiomatic fix patterns.

## [2.0.0] - 2026-05-15

**v2.0.0 GA.** The release candidate cycle (rc1 / rc2 / rc3) is closed. RC validation surfaced no blocking issues, so the engine and rule behaviour of v2.0.0 is identical to v2.0.0rc3: every rule check, every Tree-sitter walk, every config-resolution path, every CLI flag, every JSON / SARIF emission produces byte-identical output for byte-identical input. The GA bump also folds in one deliberate **skill-install refactor** so the bundled-skill layout and the Claude install shape land symmetric with every peer client before 2.0.0 freezes that surface for the rest of the 2.x line, the change is internal to the install machinery (CLI surface unchanged; existing v1.x Claude installs continue to report fresh on `safelint skill status` because the destination `SKILL.md` path and its bytes both match). The release-time changes are:

- `pyproject.toml` `version` bumped from `2.0.0rc3` to `2.0.0`.
- The RC-pin comment block in `[project.optional-dependencies]` removed; `pip install 'safelint[<lang>]'` now resolves to `2.0.0` straight from PyPI with no pin or `--pre` flag needed.
- Pre-release callouts removed from every install surface: `README.md`, `docs/index.md`, the three `docs/languages/*.md` pages, the wheel-bundled `src/safelint/skill_files/README.md`, all 12 AI-client skill files (under `src/safelint/skill_files/<client>/`), and the three skill language addendums.
- Install pins updated: `'safelint[<lang>]==2.0.0rc3'` to bare `'safelint[<lang>]'`; pre-commit `rev: v2.0.0rc3` to `rev: v2.0.0`.
- `uv.lock` regenerated.
- **Bundled skill-files layout symmetry.** Claude Code's `SKILL.md` moved from the top of `src/safelint/skill_files/` into its own subdirectory at `src/safelint/skill_files/claude/SKILL.md`, joining the per-client siblings (`cursor/`, `copilot/`, `gemini/`, `windsurf/`, `codex/`, `continue/`, `cline/`, `aider/`, `trae/`, `antigravity/`, `zed/`). Every client now ships exactly one bundled file under `skill_files/<client>/`; the shared `languages/<lang>.md` addendums and `README.md` stay at the bundle root and are looked up on demand via `safelint skill path` from every client (Claude included).
- **Claude install destination simplified to a single file.** `safelint skill install --client claude` previously copied a directory tree (`SKILL.md` + `languages/` + `README.md`) to `~/.claude/skills/safelint/`; it now copies a single file to `~/.claude/skills/safelint/SKILL.md`, matching the one-file-in, one-file-out shape every other client already used. The CLI surface is unchanged (same `--client claude`, same `--symlink` / `--force` / `--project` flags, same `update` / `remove` / `status` semantics). Internal Claude-special-case code paths (`_install_symlink_directory_filtered`, `_is_symlink_managed_directory`, the tree-hash freshness check, `_PEER_CLIENT_DIRS`) are gone, the install primitives become single-file across the board. **Upgrading from a v1.x Claude install:** the destination still has `SKILL.md` at the same path, so `safelint skill status` reports fresh as long as content matches; only the orphan `languages/` and `README.md` next to it stay behind on disk. Cleanest cleanup is `safelint skill remove --client claude && safelint skill install --client claude`, but it's optional, the orphans are harmless.

**Cumulative scope since v1.13.0** (the last 1.x release): every supported language ships as an opt-in PEP 621 extra (`[python]` / `[javascript]` / `[typescript]` / `[all]`); TypeScript / TSX / AssemblyScript are first-class; the silent-failure guard exits with code 2 when a run lints zero files because of a missing grammar; hook mode emits one summary per pre-commit invocation rather than one per batch (see issue #52); skill files cover twelve AI clients; the writing-style baseline drops em-dashes from documentation, mkdocs, skills, code, and CLI output (one rule message text changed as documented in the rc3 entry below).

**Upgrading from v1.x:** see the *Migration from v1.13.0* table in the [2.0.0rc1] entry below; the install-command swap from bare `safelint` to `safelint[<lang>]` is the only required change for most users.

**Upgrading from a v2.0.0 RC:** drop any `==2.0.0rcN` pin or `--pre` flag; `pip install -U 'safelint[<lang>]'` is sufficient. Pre-commit users should bump their `rev:` pin to `v2.0.0`.

## [2.0.0rc3] - 2026-05-14

**Iteration on the v2.0.0 RC.** Bug fixes and a project-wide writing-style cleanup found during testing of `2.0.0rc2`. No feature changes; same packaging story, same extras, same rule coverage. Install with `pip install 'safelint[<lang>]==2.0.0rc3'` (or pass `--pre`); pre-commit users update `rev: v2.0.0rc2` to `rev: v2.0.0rc3`.

### Fixed

- **Issue #50: hook-mode summary line duplicated under pre-commit batching.** A clean run with `# nosafe` suppressions printed `All checks passed. (N suppressed)`; pre-commit batches files across multiple hook invocations, so that became one summary line per batch, each showing a misleading partial count. Hook and stdin mode now honour `silent_on_clean` fully: a clean run emits nothing at all, including the `--statistics` table. The aggregated, language-agnostic suppression breakdown stays available via `safelint check` (interactive) and in every `--format json` / `--format sarif` document.
- **Hook mode emitted two messages per invocation in the silent-failure case.** When every passed file was skipped for a missing grammar, each batch printed both a per-extension warning and the silent-failure error, both carrying the same install hint. `_dispatch_hook_mode` now detects the silent-failure case before emitting per-extension warnings: all-skipped runs get only the error; mixed runs still get the warning as context.
- **Issue #52: suppression summary scattered per file batch under pre-commit.** Pre-commit ran the hook in parallel batches across files, so a `pre-commit run safelint --all-files` over a project with `# nosafe` suppressions produced one "Found N errors ... (M SAFE### suppressed)" summary block per batch, each carrying a partial count, with some batches missing the suppression mention entirely. Added `require_serial: true` to the published hook manifest in `.pre-commit-hooks.yaml` so pre-commit runs the hook as a single process and the summary aggregates across the whole run. On very large repos that exceed the OS argv limit pre-commit may still split into sequential invocations, but each batch's summary is then at least internally consistent. **Downstream change of default:** anyone consuming the published `repo: https://github.com/shelkesays/safelint` hook will now see serialized execution (no parallel batches). Cost: no inter-batch parallelism, which is a non-issue in practice because the engine is fast per-file.

### Changed

- **Project-wide writing-style cleanup: em-dashes removed.** Em-dashes (`—`) are gone from documentation, the mkdocs site, AI-client skill files, code comments, docstrings, and CLI output strings. Prose was restructured (comma, colon, parentheses, or a sentence split); a plain hyphen is used only where a dash is genuinely needed. **Heads-up for downstream tooling that string-matches safelint output:** two surfaces saw character-level changes and patterns may need updating. (1) CLI runtime strings (error / warning / install-hint lines from `_diagnostics`, the per-file summary line, the suggestions-available tail), and (2) one rule violation message: `SAFE305 wide_scope_declaration` now reads ``"`var` declaration uses function-scope hoisting - replace with `let` or `const` for block scope"`` (previously the same text with an em-dash before "replace"). No other rule message strings changed.

## [2.0.0rc2] - 2026-05-13

**Iteration on the v2.0.0 RC**, bug fixes and UX polish discovered during real-world testing of `2.0.0rc1`. No feature changes; same packaging story, same extras, same rule coverage. Install with `pip install 'safelint[<lang>]==2.0.0rc2'` (or pass `--pre`); pre-commit users update `rev: v2.0.0rc1` → `rev: v2.0.0rc2`.

### Fixed

- **Pre-commit silent-failure noise.** Hook mode emitted both a per-extension warning AND the silent-failure error per invocation, each carrying the same install hint. Pre-commit batches files across N invocations (one per ~120 KB of argv to stay under OS limits), so an `--all-files` run against a large repo with a missing grammar produced 2 × N near-identical lines of stderr. The error already carries the actionable install hint, so the preceding warning is pure duplication in the silent-failure case. `_dispatch_hook_mode` now detects the silent-failure case *before* emitting per-extension warnings, mixed runs (some files lint, others skipped) still get the warning as actionable context; all-skipped runs get only the error. Halves the noise per invocation. Note: the published hook now sets `require_serial: true` by default (see issue #52 in the [2.0.0rc3] entry above), so multi-invocation runs are uncommon to begin with.
- **`_emit_hook_grammar_warnings` now respects `--format`.** Hook mode unconditionally emitted per-extension stderr warnings even under `safelint --format json <files>`. Editor plugins / CI driving safelint in hook mode and parsing JSON now get clean stderr. Symmetric with the directory-walk variant's existing `silent` kwarg gating.
- **Missing-grammar pre-scan now honours user `exclude_paths` / `extend_exclude_paths`.** Previously the pre-scan ran *before* config load, so an excluded `generated/**` directory full of `.ts` files would either spuriously warn or (worse) trip the silent-failure guard into exit 2, for files safelint would never have linted anyway. Config is now loaded first and the resolved exclude list is threaded through `_emit_missing_grammar_warnings` / `_scan_for_unavailable_extensions`, mirroring the engine's `_is_excluded` / `_is_excluded_dir` semantics.
- **`_filter_modified_under_target` no longer keeps deleted paths.** `git diff --name-only HEAD` reports deleted files; the helper was leaving them in `considered_modified`, so a setup like "deleted the only `.ts` file in `src/python/`, TS grammar unavailable" would trip exit 2 telling the user to install the TS grammar for a file they had just deleted. Mirrors the existence check `_filter_supported_files` already had.
- **Single-file unsupported runs now correctly exit 2.** `safelint check foo.ts` with the TS grammar missing returned `[LintResult(path="foo.ts")]`, a 1-element list whose lone entry was an empty placeholder produced at language-lookup time. The silent-failure guard only fired when `not results`, so the truthy 1-element list bypassed it and the run exited 0 with a "clean" verdict on a file safelint never actually linted. The guard now treats any result whose path-suffix is in `unavailable_found` as skipped.
- **`_handle_no_targets` no longer over-fires on off-target diffs.** The third tuple element of `_get_git_modified_supported_files` was the *repo-wide* raw git-modified set, so `safelint check src/python/` would exit 2 because a `.ts` file modified elsewhere in the repo had an unavailable grammar. Renamed to `considered_modified` and filtered to under-target via new `_filter_modified_under_target` helper.
- **Dataflow string-list config typos now raise instead of silently matching per-character.** `sinks_typescript = "eval"` (note: bare string, not a list) was being coerced into `{'e', 'v', 'a', 'l'}` by `frozenset(...)` and the rule silently stopped matching `eval`. The three JS-family sites in `dataflow.py` (`sinks` / `sanitizers` / `sources`, `flagged_calls`, `nullable_methods`) now route through the established `resolve_lang_config_lookup` + `_validated_string_list` pattern that names the offending key in the `TypeError`.

### Changed

- **JSON schema docs path correction across skill files.** The 11 per-client AI-client skill files plus the wheel-bundled `src/safelint/skill_files/README.md` referenced `docs/JSON_SCHEMA.md`; the file was renamed to `docs/json-schema.md` for the mkdocs site. URLs were 404s on GitHub. Now consistent.
- **`SKILL.md` / `skill_files/README.md` cross-doc links** flipped from `../../<doc>.md` (which resolved to `src/<doc>.md`, wrong by one parent) to absolute GitHub URLs. Works in both source view AND wheel-installed locations (`~/.claude/skills/safelint/`).
- **CI gains a `safelint check src/ --all-files --fail-on=error` step** so a push that bypasses pre-commit can't merge with safelint violations. Matches the local pre-commit hook's args.
- **docs.yml** triggers on `src/safelint/rules/**` so rule add/rename/remove now redeploys the docs site automatically (the rules-at-a-glance snippet is generated from `ALL_RULES`).
- **CI matrix** extends to Python 3.14 alongside 3.11 / 3.12 / 3.13, exercising the implicit support claim from `requires-python = ">=3.11"`.
- **`WideScopeDeclarationRule` docstring** corrected to describe the rule as JS-family (JavaScript and TypeScript), matching the actual `language = ("javascript", "typescript")` class attribute.
- **AssemblyScript pre-commit override recipe** updated across `README.md`, `docs/languages/typescript.md`, and `.pre-commit-hooks.yaml`, the original `types_or: []` form silently never fired because pre-commit treats an empty tag list as "no tag matches" rather than "filter disabled". The working form is `types_or: [text]` plus `files: \.(ts|tsx|as)$`.

### Internal

- **Python grammar registration** in `safelint.languages.__init__` collapsed into a single `if/else` block mirroring the JS / TS shape, reducing future-drift risk when adding a new language.
- 12 new regression tests across `tests/test_cli.py`, `tests/test_main_routing.py`, and `tests/rules/test_dataflow_javascript.py` covering each of the bug fixes above. Total now 980 tests at 97.20% coverage.

## [2.0.0rc1] - 2026-05-12

**v2.0.0 ships TypeScript / AssemblyScript support _and_ restructures packaging so every grammar is an opt-in extra.** The TypeScript work that was prepped as `1.14.0rc1` ships here instead, bundled with the packaging change because both shift the install story. Net behaviour: `pip install safelint` alone installs only the engine, every language grammar (including Python) ships as a separate extra. Users opt in to whichever languages their project actually contains: `pip install 'safelint[python]'`, `pip install 'safelint[javascript]'`, `pip install 'safelint[typescript]'`, `pip install 'safelint[python,javascript]'` for a monorepo, `pip install 'safelint[all]'` for the kitchen sink. Files whose grammar isn't installed are skipped at lint time with a one-line stderr install hint, no hard error *as long as at least one other file gets linted*. When **every** candidate file gets skipped (the typical TS-only or JS-only project against a base install), the silent-failure guard exits with code 2 so CI / pre-commit can't silently report clean.

**This is a packaging-breaking release.** _Every_ v1.x user must update their install command, including Python-only users, who now need `pip install 'safelint[python]'`. The motivation: as v2.0.0 adds TypeScript and future versions add Go / Rust / Java / C / C++ / PHP, baking any one language into the core install means every project pays for languages it doesn't use. The symmetric opt-in model scales: each new language adds an extra and folds into `[all]`; the base install never grows.

**The TypeScript / AssemblyScript work**, originally drafted as v1.14.0rc1, never released to PyPI, folds into this entry below. Same rule coverage (18 rules on TS, 17 cross-language + 1 JS-family for `var`), same per-language config inheritance (`_typescript` keys with TS → JS fallback), same TS-specific rule handling for generics, `as` casts, non-null assertions, and `declare global`. Install with `pip install 'safelint[typescript]'==2.0.0rc1 --pre`.

**Release candidate for v2.0.0**, published as an RC so the packaging change can be validated against real-world install / pre-commit flows before promoting to stable. Same promotion path as 1.13.0: if real-world testing surfaces issues, fixes land in `2.0.0rc2`; otherwise the RC promotes directly to GA. The `--pre` flag is required because `pip install safelint` without it keeps tracking the 1.x line.

### Migration from v1.13.0

> **While v2.0.0 is in RC, the "New command" column needs a pin or `--pre`.** Either append `==2.0.0rc1` (e.g. `pip install 'safelint[python]==2.0.0rc1'`) or pass `--pre` to any of the commands below. An unpinned `pip install 'safelint[python]'` resolves to the latest 1.x release on PyPI, which doesn't define these per-language extras and would install only the engine with no grammar. Drop the pin once v2.0.0 GA ships.

| Your setup | Old command (v1.13.0) | New command (v2.0.0) |
|---|---|---|
| Python-only project | `pip install safelint` | `pip install 'safelint[python]'` |
| JS / Node project | `pip install safelint` | `pip install 'safelint[javascript]'` |
| TypeScript project (any flavour) | `pip install safelint` | `pip install 'safelint[typescript]'` |
| Python + JS monorepo | `pip install safelint` | `pip install 'safelint[python,javascript]'` |
| Anything-and-everything | `pip install safelint` | `pip install 'safelint[all]'` |
| Pre-commit hook (any language) | `additional_dependencies: []` | `additional_dependencies: ['safelint[<lang>]']` |

Forgetting to add the extra is usually a non-fatal mistake: safelint emits one stderr line per skipped file extension, e.g. `safelint: warning: skipping .py files, install with: pip install 'safelint[python]'`, and continues with whatever files it CAN lint. If at least one file gets linted (mixed-language project, one extra installed), the run finishes normally and the skipped files surface only as warnings. **If every candidate file is skipped because no matching grammar is installed, safelint fails the run with exit code 2** (the silent-failure guard, see the *Silent-failure guards* bullet below). That guard fires in pretty *and* JSON / SARIF modes, so a CI pipeline can't accidentally report green when no linting actually happened.

### Added

- **Optional-grammar packaging via PEP 621 extras**, new `pyproject.toml` extras: `[python]` (adds `tree-sitter-python`), `[javascript]` (adds `tree-sitter-javascript`), `[typescript]` (adds `tree-sitter-javascript` *and* `tree-sitter-typescript`; the bundle handles the typical TS project shape where `.js` configs and `.ts` source coexist), and `[all]` (everything currently supported). Multiple extras compose, `pip install 'safelint[python,javascript]'` for monorepos. Adding a new language in the future appends one new extra and folds it into `[all]`; the base install never grows.
- **`safelint.languages.unavailable_extensions()`**, new public registry helper returning `{ext: install_hint}` for extensions whose grammar package isn't installed. Empty when every extra is installed. CLI uses it to surface the install hint at lint time.
- **`safelint.languages.install_hint_for(extension)`**, convenience wrapper around the same map.
- **Per-grammar `GRAMMAR_INSTALL_HINT`** module-level strings on `safelint.languages.javascript` and `safelint.languages.typescript`, the exact `pip install ...` command users should run.
- **CLI install-hint helpers** (`_emit_missing_grammar_warnings`, `_emit_hook_grammar_warnings`, `_scan_for_unavailable_extensions` in `cli.py`), fire one warning line per unique missing-grammar extension at the start of `safelint check` (directory walk) and `safelint <file>` (hook mode). Pretty-mode only; JSON / SARIF stderr stays clean for tooling consumers. Walk excludes the usual vendored / generated dirs (`.git`, `node_modules`, `.venv`, `.tox`, `__pycache__`, `dist`, `build`, `target`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.safelint_cache`) so node_modules / .venv don't trigger spurious hints.
- **Pre-commit-aware install hints.** When safelint detects it's running under pre-commit (via the ``PRE_COMMIT=1`` env var pre-commit sets at hook execution time), the missing-grammar hint message switches from ``install with: pip install 'safelint[python]'`` to ``add 'safelint[python]' to additional_dependencies in your .pre-commit-config.yaml``. Pre-commit users can't run pip directly because the hook environment is managed, the new hint points at the actual lever (``additional_dependencies``) they have. See ``_format_install_action`` in ``cli.py``.
- **`safelint skill install` now auto-detects language grammars too.** Symmetric with the existing AI-client auto-detection: after a successful `safelint skill install`, safelint walks the project tree for source-file extensions, compares them against the grammar extras currently installed, and emits one composed install line covering every missing grammar, e.g. `safelint: warning: Detected source files for 2 languages (python, typescript) whose tree-sitter grammar isn't installed. Run: pip install 'safelint[python,typescript]'`. Single `pip install` command for the multi-language case. Silent (no nudge) when every needed grammar is already present. New module-level constants: `EXTRA_NAME` on each `languages/<lang>.py`; new public helper `safelint.languages.extra_name_for(ext)`; new CLI helpers `_compose_extras_install_command`, `_emit_skill_install_grammar_hint`.
- **Silent-failure guards** for the two ways a missing-grammar run could exit 0 without actually linting anything:
  - **Directory mode** (``safelint check src/``), when file discovery finds files with unavailable-grammar extensions AND zero files actually get linted, ``safelint`` exits with code 2 (configuration error) and prints ``safelint: error: no files linted, every supported file was skipped because its grammar package isn't installed, install with: pip install 'safelint[<lang>]'``. The install hint is embedded in the error itself so the failure is self-explanatory in JSON / SARIF mode (where per-extension stderr warnings are suppressed) and switches to ``add 'safelint[<lang>]' to additional_dependencies in your .pre-commit-config.yaml`` under pre-commit.
  - **Hook mode** (``safelint <files>`` invoked by pre-commit), when every file pre-commit passed had an extension whose grammar isn't installed, ``safelint`` exits with code 2 instead of 0. The error embeds the same install hint. This makes pre-commit show the hook as Failed (red) instead of Passed (green), without this guard, a pre-commit user without ``additional_dependencies`` would see a clean run while no linting actually happened, the worst kind of silent failure.

### Changed (TypeScript work, originally drafted for v1.14.0rc1)

- **TypeScript (`.ts`) and TSX (`.tsx`) as registered languages**, `tree-sitter-typescript>=0.23.0` shipped as the `[typescript]` extra (not in core). Two grammars (`typescript` and `tsx`) under one logical language name (`"typescript"`); both grammars share the same rule dispatch.
- **AssemblyScript (`.as`) ride-along**, `.as` files are parsed with the standard TypeScript grammar; no separate registration, zero parser-side work. AssemblyScript users get the full TypeScript rule suite via the same `[typescript]` extra.
- **TypeScript-specific rule handling** for the AST shapes JS rules didn't recognise:
  - **SAFE103 (max_arguments)**, generic type parameters (`<T, U, V>`) live in a separate `type_parameters` AST node, NOT inside `formal_parameters`, so they correctly don't count toward the limit. New `_TS_COUNTED_PARAM_TYPES` set recognises `required_parameter` / `optional_parameter` / `rest_parameter` wrappers.
  - **SAFE302 (global_mutation)**, new `_PASSTHROUGH_WRAPPER_TYPES` set extends paren-unwrapping with TS-only `as_expression` / `satisfies_expression` / `non_null_expression`. `(globalThis as any).counter = 1` now correctly resolves to `globalThis` and fires. `declare global { ... }` ambient blocks correctly don't fire (no runtime assignments inside).
  - **SAFE801 (tainted_sink)**, `_SPREADING_TYPES` in `JsTaintTracker` extends to TS pass-through wrappers; taint flows through `eval(userInput as string)` / `eval(userInput satisfies T)` / `eval(userInput!)`. The same TS wrapper types (`required_parameter` etc.) are now recognised as parameter shapes, so TS function parameters get seeded into the tainted set.
  - **SAFE803 (null_dereference)**, unwraps every pass-through TS wrapper (`parenthesized_expression`, `as_expression`, `satisfies_expression`, `non_null_expression`) in a loop before checking whether the object is a nullable call. `users.find()!.name`, `(users.find() as User).name`, `(users.find()).name`, and `(users.find() satisfies User).name` all fire correctly.
  - **SAFE701 / SAFE702 (test_existence / test_coupling)**, generate TS test filename patterns (`foo.test.ts` / `foo.spec.ts` / `foo.test.tsx` / `foo.spec.tsx` / `foo.test.as` / `foo.spec.as`).
- **Per-language config-key precedence with TS → JS fallback**, `get_per_language_config` helper in `safelint.core._validators`. For TypeScript files, every `_javascript`-suffixed config key (`sinks_javascript`, `tracked_functions_javascript`, `global_namespaces_javascript`, `io_functions_javascript`, `assertion_calls_javascript`, `nullable_methods_javascript`, `flagged_calls_javascript`, plus `sanitizers_javascript` / `sources_javascript`) is automatically inherited unless an explicit `_typescript`-suffixed key overrides it. The override door is open; most projects won't need to use it because TS and JS share the same runtime threat surface.
- **`resolve_lang_config_lookup`** sibling helper that also returns the actual source key the value came from, used by `_validated_string_list` callers so TypeError diagnostics name the key the user *actually set* (was previously `foo_typescript` even when the bad value came from `foo_javascript` via TS → JS fallback).
- **17 cross-language rules** widened from `language = ("python", "javascript")` to `("python", "javascript", "typescript")`. SAFE305 (`wide_scope_declaration`) widened from `("javascript",)` to `("javascript", "typescript")`, `var` is still hazardous in TypeScript.
- **`docs/languages/typescript.md`**, per-language nav page covering scope (TS / TSX / AS), the 18 rules that fire, TS-specific rule notes, config sharing with JS, the runtime preset story, and the new `[typescript]` install extra.
- **`src/safelint/skill_files/languages/typescript.md`**, bundled AI-client addendum with TS-specific rule notes; all 12 client skill files now reference it from their language registry table.

### Breaking changes

- **`pip install safelint` no longer bundles _any_ tree-sitter grammar package.** Every supported language is opt-in: install the matching extra(s) for the languages your project actually contains. Python is now on equal footing with JavaScript / TypeScript, including Python-only users, who must update their install command to `pip install 'safelint[python]'`. The motivation is forward-looking: as Go / Rust / Java / C / C++ / PHP land in future versions, baking any single language into the base install means every project pays for languages it doesn't use; the symmetric opt-in model keeps the install minimal for every use case. Files whose grammar isn't installed are silently skipped with a clear install hint on stderr, see the Migration table above.

### Fixed

- **SAFE803 silently bypassed by TS pass-through wrappers other than `!`.** `_javascript_deref_hit` only peeled `non_null_expression`; `(call as Foo).bar`, `(call).bar`, and `(call satisfies Foo).bar` slipped past. The new loop unwraps all four pass-through wrappers, the rule now matches the taint tracker's wrapper handling. Regression tests cover bare-paren, `as`, `satisfies`, and stacked-wrapper combinations.
- **TypeError diagnostics named the wrong config key when the TS → JS fallback fired.** A user setting `io_functions_javascript = "log"` (bare string typo) on a TS file used to see a `TypeError` naming `io_functions_typescript`, a key they never set. `resolve_lang_config_lookup` threads the actual source key through so the error message points at the key the user can fix.
- **SAFE303 / SAFE304 on TypeScript**, `side_effects.py:_io_funcs_for_lang` built its config key via `f"io_functions_{lang_name}"`, producing `io_functions_typescript` for TS files. That key wasn't in `DEFAULTS` (only `io_functions_javascript` was), so TS files silently got an empty I/O primitive list and SAFE303 / SAFE304 never fired on TypeScript. The new TS → JS config-key fallback (see Changed above) fixes this. Regression test added (`test_ts_io_functions_inherits_javascript_default`).

## [1.13.0] - 2026-05-12

Previewed as `1.13.0rc1` (2026-05-11) and `1.13.0rc2` (2026-05-11). The RC validation window surfaced one real-world papercut, `safelint check --all-files` would trip over project virtualenvs at `.venv/`, which landed in `1.13.0rc2` (built-in vendor-dir defaults for `exclude_paths`, plus a new `extend_exclude_paths` config key for additive use). No further issues surfaced after rc2, so the GA ships with the same content. Install with `pip install safelint` (the `--pre` flag is no longer needed).

The two new rc2 entries fold in here:

### Added (in the rc2 → GA window)

- **Built-in `exclude_paths` defaults for common vendor / generated directories.** `safelint check` (and `--all-files`) no longer walks into `.venv/`, `venv/`, `.tox/`, `.nox/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.ty_cache/`, `build/`, `dist/`, `htmlcov/`, `node_modules/`, or `site-packages/` by default. Previously these were only excluded if the user listed them explicitly in their config, a `--all-files` run from a project root with a Python virtualenv at `.venv/` would lint thousands of third-party files. The defaults apply at the directory level (`os.walk` prunes descent), so the cost of having them excluded is essentially zero.
- **New `extend_exclude_paths` config key.** Appends to the active exclude list rather than replacing it. Use this for project-specific excludes (`"generated/**"`, `"vendor/**"`, etc.) when you want to keep the built-in vendor-dir defaults. Sister to the existing `extend_tracked_functions` pattern for SAFE401, same additive semantics, same shape.

### Changed (in the rc2 → GA window)

- **`exclude_paths` semantics**, setting `exclude_paths` in your config still replaces the built-in defaults wholesale (existing semantics, backwards-compatible). Most projects should migrate to `extend_exclude_paths` to keep the vendor-dir defaults active. See [Default exclude paths](https://shelkesays.github.io/safelint/configuration/toml/#default-exclude-paths) for the migration guide.

---

The rest of this section describes the JavaScript support that landed in `1.13.0rc1` and is preserved unchanged in the GA.



**JavaScript (Node) is now a supported language alongside Python.** Registry-driven multi-language support: `.js` / `.mjs` / `.cjs` files are discovered, parsed via Tree-sitter, and run against 17 of the 19 existing rules, plus one new JS-only rule (SAFE305 `wide_scope_declaration`) for a total of 20 rules safelint now ships. Python users see no behaviour change beyond the v1.12.2 `.pyw` bugfix; the additive language work is what justifies this release as `1.13.0` (per the project's semver rules: scope expansion is MINOR, never MAJOR).

### Added

- **`safelint.languages.javascript`**, new module registering JavaScript with `LanguageDefinition(name="javascript", file_extensions=frozenset({".js", ".mjs", ".cjs"}), comment_node_type="comment", comment_prefix="//")`. Plus the JS Tree-sitter node-type constants every rule needs (function/control-flow/expression/statement/pattern types).
- **`tree-sitter-javascript>=0.23.0`** runtime dependency. Peer of the existing `tree-sitter-python` dep.
- **`safelint.analysis.dataflow_javascript`**, new module with `JsTaintTracker`, the JavaScript counterpart of the Python `TaintTracker`. Same public surface; per-language node-type vocabulary internally. Handles `const` / `let` / `var` declarations, `assignment_expression` / `augmented_assignment_expression`, template-string interpolation (`` `${expr}` ``), destructuring (array / object / rest / pair patterns), spread elements, member / subscript propagation, and the `assume_taint_preserving` knob.
- **17 rules now lint JavaScript** with `language=("python", "javascript")`:
  - **Structural:** `function_length` (SAFE101), `nesting_depth` (SAFE102), `max_arguments` (SAFE103), `complexity` (SAFE104).
  - **Error handling + side-effects:** `empty_except` (SAFE202, JS empty catch), `logging_on_error` (SAFE203, recognises `console.*` and generic `logger.*` plus `throw <id>;` as re-raise), `side_effects_hidden` (SAFE303), `side_effects` (SAFE304).
  - **State purity:** `global_mutation` (SAFE302, fires on function-body assignments to `globalThis.*` / `window.*` / `global.*` / `self.*` / `process.env.*` and similar configurable namespaces; reading a global is fine; module-level assignments are exempt as legitimate setup).
  - **Loop / tests / assertions:** `unbounded_loops` (SAFE501, only the `while (true)` no-break case fires on JS; the non-comparison-condition heuristic stays Python-only), `missing_assertions` (SAFE601, walks for *calls* to `assert` / `expect` / `console.assert` / Node's `assert.*` helpers), `test_existence` (SAFE701) and `test_coupling` (SAFE702, pair Python `test_<stem>.py` *and* JS `<stem>.test.{js,mjs,cjs}` / `<stem>.spec.{js,mjs,cjs}`).
  - **Resource safety:** `resource_lifecycle` (SAFE401, fires on calls to configurable acquirer names, `createReadStream`, `createWriteStream`, `openSync`, `createServer`, `connect`, etc., that aren't enclosed in a `try { ... } finally { ... }` somewhere up the AST chain; heuristic-only, doesn't verify that the finally actually closes the resource).
  - **Dataflow:** `tainted_sink` (SAFE801), `return_value_ignored` (SAFE802), `null_dereference` (SAFE803, recognises optional chaining `foo?.bar` as the safe form, exempt from the rule).
- **New JavaScript-only rule:** `wide_scope_declaration` (SAFE305) flags every `var` declaration. Holzmann Power-of-Ten Rule 6 ("declare variables at the smallest possible scope") translated to JS's actual scope-control mechanism, `var` is function-scoped (hoisted across blocks), `let` / `const` are block-scoped (the narrower scope). Fires on top-level `var`, function-body `var`, block-level `var`, multi-binding `var x = 1, y = 2;` (single violation per declaration node, the line is the unit of fix), and `for (var i = 0; ...)`. Python has no `var` / `let` / `const` distinction; the rule is registered with `language = ("javascript",)` and the engine's per-language dispatch correctly skips it on `.py` / `.pyw` files. Default enabled, severity `warning`.
- **JavaScript runtime presets**, new `[tool.safelint.javascript] runtime = "<name>"` config key selects which API surface the JS rule defaults assume. Five presets ship: `node` (default, current behaviour), `browser` (Web APIs / DOM / `localStorage` / observers; drops Node `fs`), `deno` (`Deno.*` APIs; drops `process` / `window`), `cloudflare-workers` (Workers Runtime: KV / R2 / Durable Objects / `Request` body methods; minimal global-namespace list), and `bun` (Node-compatible plus `Bun.serve` / `Bun.spawn`). Affects defaults for SAFE302 (`global_namespaces_javascript`), SAFE303 / SAFE304 (`io_functions_javascript`), SAFE401 (`tracked_functions_javascript`), SAFE801 (`sinks_javascript` / `sources_javascript`), SAFE802 (`flagged_calls_javascript`), and SAFE803 (`nullable_methods_javascript`). User-explicit `_javascript` config keys still win over the preset. Unknown runtime names warn on stderr and fall back to `node`. Source is the same JS regardless of runtime, only the rule defaults shift, not the parser or rule logic.
- **Per-language config keys** (additive, existing user TOMLs unchanged):
  - `[tool.safelint.rules.side_effects_hidden]` and `[...].side_effects` get `io_functions_javascript`.
  - `[...].missing_assertions]` gets `assertion_calls_javascript`.
  - `[...].tainted_sink]` gets `sinks_javascript`, `sanitizers_javascript`, `sources_javascript`.
  - `[...].return_value_ignored]` gets `flagged_calls_javascript`.
  - `[...].null_dereference]` gets `nullable_methods_javascript`.
  - `[...].global_mutation]` gets `global_namespaces_javascript`.
  - `[...].resource_lifecycle]` gets `tracked_functions_javascript`.
- **`CALL_TYPES`** frozenset and **`resolve_lang_name`** helper in `safelint.languages._node_utils`, cross-language utilities used by the widened rules.
- **Bundled AI-client skills**, `src/safelint/skill_files/languages/javascript.md` (the JS shared addendum) ships a full per-rule notes table, idiomatic-fix patterns for each of the 15 ported rules, and the "rules that stay Python-only" reference. All 12 client docs (Claude Code's `SKILL.md`, Cursor's `cursor/safelint.mdc`, GitHub Copilot's `copilot/copilot-instructions.md`, Gemini's `gemini/GEMINI.md`, Windsurf's `windsurf/safelint-rules.md`, codex's `codex/instructions.md`, Continue.dev's `continue/safelint.md`, Cline's `cline/safelint.md`, aider's `aider/CONVENTIONS.md`, Trae's `trae/safelint.md`, Antigravity's `antigravity/safelint.md`, Zed's `zed/safelint.md`) gained a JavaScript row in their **Step 2, Identify the language(s) involved** registry tables.
- **115 new tests** distributed across per-rule JS test files (`tests/rules/test_*_javascript.py`) and the engine-level smoke test file (`tests/core/test_engine_javascript.py`). Total: 764 tests pass at 97.25% coverage.

### Changed

- **Pre-commit hook spec** (`.pre-commit-hooks.yaml`) and **the in-tree self-development hook** (`.pre-commit-config.yaml`), `types_or: [python]` becomes `types_or: [python, javascript]`. Downstream users with mixed Python + JS repos automatically have both filetypes routed to safelint after upgrade. Additionally the published `.pre-commit-hooks.yaml` drops its `files: ^src/` filter, that filter was a leak from this repo's in-tree `.pre-commit-config.yaml` (where it's intentional, safelint lints itself only under `src/`) into the published hook spec, where it forced every downstream installer onto the same layout. **Heads-up: this broadens the default scope for downstream consumers.** With it gone, the hook honours only `types_or: [python, javascript]` plus the consumer's own `files:` / `exclude:` keys, so projects with sources at the repo root, in `app/`, in `lib/`, etc. now get linted by default after upgrade. If you previously relied on the `^src/` default to scope safelint to one directory, add the equivalent filter to your local `.pre-commit-config.yaml`:

  ```yaml
  - repo: https://github.com/shelkesays/safelint
    rev: <tag>
    hooks:
      - id: safelint
        files: ^src/   # restore the previous default if needed
  ```
- **`call_name`** in `_node_utils.py` extended to handle JavaScript `member_expression` (`obj.method(...)`) alongside Python `attribute` (`obj.method(...)`). Both `foo(...)` forms (bare identifier function calls) continue to resolve via the existing `identifier` branch.

### Stays Python-only (by design)

Two rules don't have a useful JavaScript translation and remain registered for Python only, they will not fire on `.js` / `.mjs` / `.cjs` files. The decision rationale lives in `src/safelint/skill_files/languages/javascript.md` "Rules that stay Python-only".

- **SAFE201 `bare_except`**, Python `except:` (no exception type) silently catches `KeyboardInterrupt` and `SystemExit`. JavaScript `try/catch` always catches every throw type by language design; the Python-specific process-signal hazard doesn't exist. SAFE202 (empty catch) + SAFE203 (catch must log) cover the related JS concerns.
- **SAFE301 `global_state`**, Python rule fires on the `global` keyword regardless of whether a write follows. JavaScript has no read-only-global declaration form; on JS the rule would always be a strict subset of SAFE302. JS users get the same protection from SAFE302 (global_mutation) alone.

### Behaviour changes (heads-up)

- **JS-only projects**, anyone who had `safelint check` running on a Python repo with stray `.js` files: those files will now be discovered, parsed, and linted (most rules will fire). If that's not what you want, scope-suppress with `[tool.safelint.per_file_ignores]` keyed on the `.js` glob, or set `enabled = false` per rule.
- **Mixed Python + JS projects**, both file types now flow through pre-commit and `safelint check` automatically. The 17 widened rules apply to both languages with their per-language defaults.
- **Pure-Python projects**, no intended default-behaviour change beyond the v1.12.2 `.pyw` bugfix. Some Python codepaths did pick up correctness fixes during the v1.13.0 cycle (e.g. SAFE701/702 now skip test files themselves and gate the coupling check to changed paths under `test_dirs`, SAFE102 now counts `match` blocks for Python 3.10+), but those only affect users who had explicitly enabled the relevant rules, defaults are unchanged.

### Limitations documented for future enhancement

- **Block-style `nosafe` directives** (`/* nosafe */`) are not recognised, only line-style `// nosafe` and `// safelint: ignore`. Documented in the JS shared addendum and `docs/contributing/adding-a-language.md` Step 4.
- **JSX (`.jsx`)** is not registered. `tree-sitter-javascript` parses some JSX leniently as a superset, but flagging it as a separate language registration later avoids accidental drift in rule semantics.
- **TypeScript (`.ts` / `.tsx`)** is a separate language addition, not in this release.
- **Arrow-function naming via variable binding** (`const getX = () => ...`), this remains a limitation only for rules that still read function names solely via `func_node.child_by_field_name("name")` and therefore may report such functions as `<anonymous>` (e.g., SAFE101 `function_length`). SAFE303 (`side_effects_hidden`) and SAFE304 (`side_effects`) already resolve JS arrow-function names through the parent `variable_declarator` via the shared `_func_display_name` helper, so `const getX = () => console.log(...)` correctly reports as `getX` for those rules. Other rules can be enhanced the same way later.

## [1.12.2] - 2026-05-09

Completion of the multi-language readiness work started in v1.12.1. The engine, cache, suppression parser, file discovery, and per-rule dispatch were already registry-driven, but three CLI helpers and the published pre-commit hook spec still hard-coded `.py`. With this release every supported-extension check reads from `safelint.languages.supported_extensions()`, so registering a new language is genuinely additive, drop a `LanguageDefinition` into `languages/<lang>.py`, append it to the registry loop, append the new filetype tag to `types_or` in `.pre-commit-hooks.yaml`, and the CLI discovers it everywhere automatically.

`tuple(supported_extensions())` now contains `.py` and `.pyw` (the registry is a `frozenset`, so iteration order isn't guaranteed); `types_or: [python]` is identical in semantics to the previous `types: [python]` for downstream pre-commit users.

### Fixed

- **`.pyw` files now picked up by git-modified mode and the pre-commit hook.** The old CLI helpers used `str.endswith(".py")` for filtering, which silently dropped `.pyw` files (`"foo.pyw".endswith(".py")` is `False`). The engine's `--all-files` discovery loop already used the registry and handled `.pyw` correctly, so this only affected git-modified runs (`safelint check src/`) and pre-commit hook mode. Existing `.pyw` projects that were getting clean runs in those modes may now see previously-hidden violations on those files; if that's unwelcome on a transitional codebase, scope-suppress with `[tool.safelint.per_file_ignores]` keyed on a `*.pyw` glob.

### Changed (internal: registry-driven)

- **CLI git-status filters now read from the registry.** `_collect_all_py_files` and `_filter_py_files` in `src/safelint/cli.py` are renamed to `_collect_all_supported_files` and `_filter_supported_files` respectively, and both now build `exts = tuple(supported_extensions())` once per call to drive the `str.endswith` check. The hook-mode pre-filter at the bottom of `main()` (`[f for f in args.files if f.endswith(".py")]`) reads from the registry too. So `safelint` invoked by pre-commit with mixed Python + (future) TypeScript files accepts both rather than silently dropping the non-Python ones.
- **Published pre-commit hook spec uses `types_or`.** `.pre-commit-hooks.yaml` previously declared `types: [python]`. Switched to `types_or: [python]` so the add-a-language edit becomes a one-line append (`- ts`) instead of a schema change. Description generalised from "Python files" to "source files"; an inline comment marks `language: python` as the hook *runtime* (a real source of confusion in pre-commit configs), not the language being linted.

### Changed (docs)

- **`docs/contributing/adding-a-language.md`** gains an explicit **Step 6, Update CLI / pre-commit plumbing** that lists the surfaces reading from the registry vs. the one place still requiring a manual edit (the `types_or` line in `.pre-commit-hooks.yaml`). Old Step 6 (tests + docs) is now Step 7; old Step 7 (bundled AI-client skills) is now Step 8.

### Behaviour changes (heads-up)

- **`.pyw` projects**, see *Fixed* above. The bugfix is genuine, but if your `.pyw` files have been quietly accumulating violations because git-modified mode and the pre-commit hook were skipping them, you'll see those surface on the first `safelint check` after upgrade. Workaround if you need a transitional grace period: scope-suppress with `[tool.safelint.per_file_ignores]` keyed on `**/*.pyw`.
- **Pure-`.py` projects**, no change. The renamed CLI helpers are private (underscore-prefixed); the `types_or` change is single-element today, so downstream pre-commit users see no difference until a second filetype tag lands.

## [1.12.1] - 2026-05-09

A small follow-on to v1.12.0. One user-visible bug fix, one perf optimisation, an internal-API cleanup, and pre-emptive engine plumbing for the eventual second-language work. No behaviour change for current users beyond the bug fix.

### Fixed

- **`per_file_ignores = ["*"]` no longer triggers a spurious typo-guard warning.** v1.12.0 added the `"*"` wildcard as a documented blanket-suppress mechanism in toml `per_file_ignores`, but the validation pass in `_parse_per_file_ignores` still treated `"*"` as an unknown entry and emitted `safelint: warning: unknown entries in per_file_ignores...` for the exact value the docs tell users to use. The validation now exempts `"*"` while preserving the typo guard for genuinely unknown codes/names. The pre-existing wildcard test was extended to capture stderr and assert the absence of the warning, so any future regression here surfaces in CI.

### Changed (internal)

- **Single-pass directive parsing.** `_parse_suppressions` (line-level `# nosafe`) and `_parse_file_level_ignores` (file-level `# safelint: ignore`) used to walk the Tree-sitter tree independently, two full passes per file. New `_parse_directives` helper folds both into one O(N) pass; on a 5000-line generated file (a primary use case for file-level ignores), this halves the per-file walk cost. Behaviour is bit-for-bit identical to the two-pass version. The two original helpers are kept as thin wrappers so the existing unit tests in `tests/core/test_suppression.py` continue to work without changes.
- **`_merge_in_file_directives` signature cleanup.** The boolean parameter was forcing surrounding mandatory non-bool params into keyword-only territory unnecessarily. Reordered so only the boolean is keyword-only, matching Python convention (positional mandatory params first, then `*`, then keyword-only).

### Added (pre-emptive: dormant until a second language lands)

- **`BaseRule.language: tuple[str, ...] = ("python",)`**, new class attribute that the engine consults in `_run_rules` before dispatching `check_file`. Rules whose `language` tuple doesn't include the active file's `LanguageDefinition.name` are skipped. Today every rule defaults to `("python",)` and Python is the only registered language, so the filter is a no-op for current usage. The plumbing is the engine half of the per-language dispatch contract documented in `ADDING_A_LANGUAGE.md`; the per-rule audit (which existing rules port cross-language vs. stay Python-only) is per-rule work that ships *with* each new language. Adding TypeScript / Go / Rust now requires only registering a new `LanguageDefinition` and widening `language` on the rules that port, no engine changes.
- 4 new dispatch tests in `tests/core/test_engine.py`: filter skips Python-only rules on a hypothetical-language file (via a monkeypatched fake `LanguageDefinition`), filter doesn't accidentally skip Python rules on Python files (regression guard), `BaseRule.language` default is pinned, every registered rule still inherits the default.

### Behaviour changes (heads-up)

- **None for end-users.** The `"*"` typo-guard fix removes an erroneous warning; the perf and signature-cleanup work is invisible; the dispatch infrastructure is dormant. End-to-end behaviour for `safelint check` and `safelint skill *` commands is identical to v1.12.0.

## [1.12.0] - 2026-05-08

A focused feature release on top of v1.11.0. The suppression model grows from three layers to four with a new in-file `# safelint: ignore` directive that lets users silence rules for a whole file from inside the file itself, matching the established pattern from ruff (`# ruff: noqa`), flake8 (`# flake8: noqa`), pylint (`# pylint: disable=`), and mypy (`# type: ignore`).

### Added

- **In-file `# safelint: ignore` directive**, file-scope suppression placed as a top-of-file (or anywhere alone-on-its-line) comment. Three forms:
  ```python
  # safelint: ignore                        # suppress every rule for this file
  # safelint: ignore: SAFE101               # suppress one code
  # safelint: ignore: SAFE101, SAFE304      # suppress multiple
  # safelint: ignore: function_length       # by rule name (equivalent to the code form)
  ```
  Best for the case "this whole file is intentionally violating", auto-generated code, fixtures, vendor adapters, where toml's `per_file_ignores` is overkill (no glob pattern needed) and inline `# nosafe` is wrong (the violation isn't on a single line).

  - **Tree-sitter parsed**, so `# safelint: ignore` *literals* inside docstrings or string content are correctly ignored.
  - **Comment must be alone on its line.** Trailing comments after code are skipped, those are scope-local and use `# nosafe` instead. This prevents a per-line directive that's typed with the wrong prefix from silently extending to the whole file.
  - **Typo-guarded.** Unknown codes / rule names emit a `safelint: warning:` line on stderr (matching the toml typo guard); the run continues.
  - **Auditable.** Suppressed violations still land in `LintResult.suppressed` and surface in the CLI's per-code breakdown at the end of a run.

- **`"*"` wildcard support in `per_file_ignores`**, falls out of the same machinery the bare file-level directive uses. You can now write `[tool.safelint.per_file_ignores]` with `"some/path/**" = ["*"]` to skip every rule for a path pattern, instead of having to enumerate every code.

### Changed

- **Suppression model is now four layers**, narrowest to widest. They compose, a violation is suppressed if *any* layer matches:
  1. **`# nosafe`** (line scope), same as before.
  2. **`# safelint: ignore`** (file scope), new in 1.12.0.
  3. **`per_file_ignores`** (glob scope), same as before, plus `"*"` wildcard support.
  4. **`ignore`** (project scope), same as before.

### Documentation

- **CONFIGURATION.md**, new *File-level suppression* section with form table, placement rule, typo-guard behaviour, and a four-mechanism comparison table mapping each scope to its right use case.
- **CLAUDE.md**, *Suppression model* section updated from 3 layers to 4 with implementation pointers (`_parse_file_level_ignores`, `_merge_in_file_directives`, `_is_per_file_ignored`'s wildcard short-circuit).

### Behaviour changes (heads-up)

- **None for existing files.** Files without a `# safelint: ignore` directive behave identically to v1.11.0, the new code path is purely additive. The only observable difference is the new wildcard `"*"` interpretation in `per_file_ignores`; if any user was previously writing literal `"*"` as a rule code (would have been a no-op since no rule matches), they'll now find that entry blanket-suppresses every rule. We're not aware of any such usage in the wild.

## [1.11.0] - 2026-05-08

Multi-client expansion, the AI-client skill registry grows from 2 supported clients to 12. The architecture from v1.6.0–v1.10.0 was built for this; each new client is one `ClientSpec` append plus a bundled artefact (and 10 install/lifecycle regression tests). Top-level `safelint help` gains dedicated *Skill subcommands* and *Skill flags* sections so the install / update / remove / status / path surface is discoverable without a second `safelint help skill` round-trip.

### Added

- **Ten new AI-client integrations:** GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed. Every client follows the same install / update / remove / status / path surface and the same project-vs-user-scope semantics, with auto-detection wired into the existing `--client auto` flow. Per-client install destinations:
  - **GitHub Copilot**, `.github/copilot-instructions.md` (auto-loaded by VS Code Copilot Chat)
  - **Gemini**, `GEMINI.md` at repo root (auto-discovered by Gemini CLI)
  - **Windsurf**, `.windsurfrules` at repo root
  - **codex**, `.codex/instructions.md` (primary) **plus** a delimited section in `AGENTS.md` when that file exists (preserves user content; see *Secondary install* below)
  - **Continue.dev**, `.continue/rules/safelint.md`
  - **Cline**, `.clinerules/safelint.md`
  - **aider**, `CONVENTIONS.md` (project or user); requires a one-line `read: [CONVENTIONS.md]` entry in `.aider.conf.yml` since aider doesn't auto-load conventions files. The post-install message reminds users.
  - **Trae**, `.trae/rules/safelint.md`
  - **Antigravity**, `.antigravity/rules/safelint.md`
  - **Zed**, `.rules` at repo root
- **`ClientSpec` secondary-install architecture.** New optional fields `secondary_install_relpath` and `secondary_install_section_markers` let a client write a *delimited HTML-comment section* into a shared cross-agent file (e.g. `AGENTS.md`) when that file already exists at the scope root. Used by codex; the architecture generalises to any future cross-agent shared file. **Lifecycle parity:** install writes the section, update re-renders on drift, status escalates to DIFFERS when section content drifts (even if the primary install is fresh), remove strips just the section (preserving other content; deletes the file only if it becomes empty after stripping). Section-based edits are *always* the contract for the secondary destination, never a full-file overwrite, so user content in shared files is safe.
- **Top-level `safelint help` gains *Skill subcommands* and *Skill flags* sections.** All five lifecycle actions (`install`, `update`, `remove`, `status`, `path`) and the common flags (`--client`, `--project`, `--symlink`, `--force`, plus `--path` and `--dry-run` for `remove`) are now visible at the top level, no second `safelint help skill` round-trip needed to find `--force` etc. `--force` is intentionally placed under *Skill flags* (not *Global options*) since it doesn't apply to `check`.
- **`run_update` performance: hash/walk runs at most once per install per run.** Previously `run_update` and `_update_one` each invoked `_install_status` independently per target, doubling the directory walk and content hash for Claude installs (the most file-heavy bundle). `_update_one` now accepts an optional `status` parameter; `run_update` threads its precomputed value through. Direct callers and tests are unaffected (default `None` means "compute internally").
- **`run_update` no longer falsely prints "all up to date" when every target was OSError-skipped.** New `any_processed` flag gates `_print_update_all_fresh` on at least one target having a readable status. Without the gate, an all-permission-denied run would silently report success.

### Changed

- **`io_functions` in the bundled `safelint.toml` (`[rules.side_effects_hidden]`)**, removed the unmatchable `"subprocess"` entry (the rule walks bare callable names, `subprocess.run(...)` resolves to `"run"`) and replaced it with the actual subprocess callable names (`run`, `Popen`, `call`, `check_call`, `check_output`).
- **Documentation fan-out for the multi-client expansion:** `AI_CLIENTS.md` (Supported clients table + Per-client guides + manual install examples), `src/safelint/skill_files/README.md` (clients list + layout tree + manual install examples), `README.md` (top-level integration block), and `ADDING_AN_AI_CLIENT.md` all enumerate the 12 supported clients. The Roadmap section in `AI_CLIENTS.md` was retired since the previously listed candidates (Copilot, codex, windsurf, antigravity) all shipped.
- **Test coverage threshold remains 97%; current coverage 97.24% across 628 tests.** The 10 new client integrations add 100+ install/symlink/force/overwrite/auto-detect/CLI-routing/path-print/peer-exclusion tests plus 24 codex-specific tests for the secondary-install lifecycle and section helpers.

### Behaviour changes (heads-up)

- **`safelint help` output changed shape**, *Skill subcommands* and *Skill flags* sections now appear between *Commands* and *Options*. Existing users see a longer (more discoverable) help; no commands or flags removed.
- **Auto-detection now scans for 12 client markers, not 2.** A project with markers for several clients gets installs for all of them in registry order. To install for a single client, pass `--client <name>` explicitly.
- **codex's secondary install touches `AGENTS.md` when present.** If you have an existing `AGENTS.md` with content for other agents, `safelint skill install --client codex --project` will *append* a delimited safelint section to it (your other content is preserved). The section sits between `<!-- safelint:begin -->` and `<!-- safelint:end -->` markers; `safelint skill remove --client codex` strips it cleanly. If you don't want any AGENTS.md modification, install codex without `--project` so it lands at user-scope only, or remove the AGENTS.md file before installing.

### Security hardening

- **`safelint skill remove --path PATH` now validates that *PATH*'s tail matches a registered install relpath before deleting.** Without this guard, a typo or shell-expansion accident (`--path ~/.config` instead of `~/.cursor/...`, or an unset env-var that expanded to a sensitive path) could trigger `shutil.rmtree` on the wrong directory. The check accepts every registered client's canonical install path (`.cursor/rules/safelint.mdc`, `.codex/instructions.md`, `.continue/rules/safelint.md`, `.clinerules/safelint.md`, `.trae/rules/safelint.md`, `.antigravity/rules/safelint.md`, `.windsurfrules`, `GEMINI.md`, `.rules`, `CONVENTIONS.md`, `.claude/skills/safelint`, `.github/copilot-instructions.md`) regardless of where the parent directories sit. Truly unrecognisable install locations should be removed manually with `rm` after inspecting their contents.
- **codex secondary install (`AGENTS.md`) refuses to follow symlinks.** Without this guard, an `AGENTS.md` set up as a symlink, intentionally by the user, or maliciously by an attacker with write access to the install scope (e.g. shared CI workspace), would have caused `install`/`update`/`remove` to read and write *through* the symlink, potentially corrupting any user-writable file the link pointed at (e.g. `~/.ssh/authorized_keys`, system files when running as root). All three lifecycle paths (`_install_secondary`, `_remove_secondary`, `_secondary_status`) now check `target.is_symlink()` and refuse with a `safelint: warning: refusing to install/remove safelint section through symlink at ...` line on stderr. The primary `.codex/instructions.md` install is unaffected.

## [1.10.0] - 2026-05-06

Round-out release for the skill-install lifecycle: `update` and `remove` complete the install / status / update / remove quartet so users have a full set of maintenance commands without falling back to manual `rm` / re-install cycles.

### Added
- **`safelint skill update`**, refresh installed skills whose content has drifted from the bundled wheel. Idempotent by default (no-op when fresh), with `--force` to re-install regardless of drift status (useful for reverting customised installs back to bundled). Inherits `--client` / `--project` / `--symlink` / `--force` from install. `--client auto` here resolves via existing install paths, NOT marker files like install does, "what's installed?" vs "what client is the user using?" are separate questions.
- **`safelint skill remove`**, delete detected installs. Inherits `--client` / `--project` from install, plus three remove-specific flags:
  - **`--symlink`**, filter to symlink-shape installs only, leaving copy-mode installs intact ("delete only my symlink installs").
  - **`--path PATH`**, remove one specific location, bypassing every other flag (useful for unusual / forgotten install locations).
  - **`--dry-run`**, preview what would be removed without deleting anything.
- **Shared install-path auto-detection** between `update` and `remove` via new `_detected_installed_clients(*, only_symlink)` helper. Distinct from install's `_detected_clients(directory, marker_attr)` (marker-file scan).

## [1.9.0] - 2026-05-05

A focused follow-on to v1.8.0 covering one practical question users asked: **how do I know my installed AI-client skill is up to date after `pip install --upgrade safelint`?** Two new surfaces answer it. Also lands a build-time drift-detection test pair that prevents bundled-doc rot for every registered AI client (and every future one, the tests parametrise over the registry).

### Added
- **`safelint skill status`**, new subcommand that compares every detected installed AI-client skill (Claude Code at `~/.claude/skills/safelint/`, Cursor at `~/.cursor/rules/safelint.mdc`, project-scoped equivalents) against the bundled artefact in the active wheel. Reports per-location *fresh* / *differs from bundled*, exit 0 when every detected install matches, exit 1 when any differs. Pipe-friendly: `safelint skill status || safelint skill install --force` is the canonical "refresh after upgrade" idiom. Symlink installs always report fresh by construction. Documented in `AI_CLIENTS.md` "Updating after a safelint upgrade" → "Checking whether your installed skill is current".
- **`safelint check --check-skill-freshness`**, opt-in flag that folds the same drift check into a normal lint run. Stale installs surface as `safelint: warning: …` lines on stderr through the diagnostics channel. Informational only, doesn't fail the lint. Off by default so day-to-day `safelint check` invocations stay fast (no extra FS scan).
- **`ClientSpec.documentation_relpaths`** + parametrised drift-detection tests. Each registered AI client declares which files under `skill_files/` collectively must mention every rule code/name in `ALL_RULES` and every extension in `supported_extensions()`. Two parametrised tests (`test_skill_documents_every_active_rule[<client>]`, `test_skill_documents_every_supported_extension[<client>]`) fail CI the moment a contributor adds a rule or language without updating each registered client's bundled docs. New clients added to `_CLIENT_SPECS` automatically inherit both checks.
- Bundled skill crib-sheets (`SKILL.md`, `cursor/safelint.mdc`) backfilled with the eight rules previously absent from their rationale tables: SAFE203, SAFE401, SAFE601, SAFE701, SAFE702, SAFE801, SAFE802, SAFE803. The drift test now passes at 100% rule coverage.

### Changed
- Top-level `safelint --help` "Commands" entry for `skill` now lists `status` alongside `install` and `path`. Same change in the `CONFIGURATION.md` embedded help example.
- Documentation fan-out: the new commands and `--check-skill-freshness` flag are now mentioned in the top-level `README.md`, the bundled-in-wheel `src/safelint/skill_files/README.md`, and the `CONFIGURATION.md` `safelint check` flag table, not only in `AI_CLIENTS.md`.

## [1.8.0] - 2026-05-04

This release bundles three internal milestones (originally tracked as 1.8.0 / 1.9.0 / 1.10.0 during development; only 1.7.0 was published to PyPI) into a single user-visible release. It closes the most-asked-about gaps versus ruff, incremental config, unused-suppression detection, per-rule statistics, broader resource-lifecycle coverage, smarter empty-except detection, configurable global-mutation strictness, configurable function-size counting, *and* tightens the SAFE801 (``tainted_sink``) dataflow analysis *and* introduces advisory suggestions on JSON / SARIF outputs alongside a ruff-style top-level CLI surface. SafeLint stays *review-only*, there is no ``--fix`` flag now or planned.

### Added
#### Configuration ergonomics
- **`extend_ignore` / `extend_per_file_ignores` config keys**, grow the corresponding default lists instead of replacing them. Mirrors ruff's ``extend-select`` ergonomics. Both are folded into the canonical ``ignore`` / ``per_file_ignores`` keys at config-load time and stripped from the resolved dict, so downstream consumers (engine, runner) only see the merged lists. Order-preserving dedupe means duplicates between the base and the extension collapse to a single entry.
- **`extend_tracked_functions` config key on the ``resource_lifecycle`` rule**, appends to the (now-richer) default list instead of replacing it.
- **`strict` config flag on the ``global_mutation`` rule**, ``strict = true`` fires on any ``global`` declaration even without a write, mirroring ruff's ``PLW0603``. Default ``strict = false`` keeps the original Holzmann-aligned behaviour (only flag actual mutations). Useful for teams whose policy is to ban the ``global`` keyword entirely.
- **`count_mode` config option on the ``function_length`` rule**, three counting strategies:
  * ``"lines"`` (default), inclusive source-line span. Original behaviour.
  * ``"logical_lines"``, source lines minus blanks and pure-comment lines. Less game-able than the raw-lines metric.
  * ``"statements"``, count Python statement nodes. Equivalent to ruff's ``PLR0915``; fully formatting-independent. Skips nested function bodies so an inner helper doesn't inflate its outer's count.
- **`assume_taint_preserving` config option on the ``tainted_sink`` rule**, controls how unknown function calls (those whose name is in neither ``sources`` nor ``sanitizers``) propagate taint. ``true`` (default, preserves the historical behaviour) means an unknown call's result is tainted iff any argument is tainted. ``false`` means unknown calls always drop taint, giving a less conservative analysis with fewer false positives but new false negatives where an internal helper does flow tainted data through to a sink. Set to ``false`` when your codebase has many "obviously safe" wrappers and you'd rather miss a flow than report a false positive.

#### New rules and detection improvements
- **`SAFE004` (``unused_suppression``)**, emits a warning for any inline ``# nosafe`` directive that didn't actually suppress anything. Catches stale annotations after refactors. The engine tracks per-(line, code) usage during the rule run; unused entries are reported afterward. Globally disable via ``ignore = ["SAFE004"]`` if your workflow generates many transient suppressions. Self-referential directives (both ``# nosafe: SAFE004`` and ``# nosafe: unused_suppression``, case-insensitive on the code form) are special-cased to avoid recursion.
- **Broader default tracked functions for SAFE401**, covers ``socket``, ``mmap``, ``Lock``/``RLock``/``Semaphore``, ``Pool``/``ThreadPoolExecutor``/``ProcessPoolExecutor``, ``TemporaryFile``/``NamedTemporaryFile``/``TemporaryDirectory``, ``ZipFile``/``TarFile``, plus ``Session`` (PEP-8-cased) alongside the existing ``open``/``connect``/``session``. Extended cleanup-pattern list adds ``release`` and ``shutdown``. Closes the most common ruff-vs-safelint coverage gap on real codebases.
- **`SAFE202` now catches the canonical ``except: pass`` and other no-op idioms**, previously the rule's check was so narrow it effectively never fired on real code (only on the malformed-AST case). Now flags ``pass`` / ``continue`` / ``...`` / single-literal expression bodies (``0``, ``None``, ``True``, ``False``, string-as-comment ``"TODO"`` / ``""`` etc.) when they're the entire body of an except clause. Multi-statement bodies are still allowed (so ``log_message; pass`` doesn't trip).
- **Splatted-arg taint propagation**, ``foo(*tainted_list)`` and ``foo(**tainted_dict)`` now correctly flow the splat operand's taint into the call. Previously ``list_splat`` and ``dictionary_splat`` Tree-sitter nodes weren't matched in ``TaintTracker._is_tainted``, so calls like ``eval(*user_args)`` slipped through without a violation.

#### Advisory suggestions (JSON / SARIF)
- **`suggestions[]` array on every Violation**, a list of advisory ``Suggestion`` objects, each with a one-line ``description`` and zero or more ``TextEdit`` entries (range + replacement). Empty when the rule has no fix to offer. Surfaced in JSON output (``--format json``), in SARIF output (``--format sarif`` → native ``fixes[]`` block, advisory by spec), and via the public Python API (``Violation.suggestions: tuple[Suggestion, ...]``).
- **`SAFE201 (bare_except)` ships the first suggestion**, replace bare ``except:`` with ``except Exception:``. Validates the schema end-to-end with a real rule. More rules can attach suggestions in subsequent releases without further schema changes.
- **`docs/JSON_SCHEMA.md`** documents the new ``Suggestion`` and ``TextEdit`` shapes and dedicates a section to the *advisory only* contract for editor / CI integrations.

#### CLI surface
- **`--statistics` CLI flag**, prints a per-rule count summary at the end of a pretty-mode run (``CODE  RULE  ACTIVE  SUPPRESSED``). Useful for "where do we stand?" snapshots in CI. Sorted by descending total count, ties broken alphabetically by code for deterministic output. Silent on a clean run.
- **Top-level CLI help and version, ruff-style.** New ``safelint help`` and ``safelint version`` commands plus the conventional ``-h`` / ``--help`` / ``-V`` / ``--version`` short and long flags. Help text uses a coloured layout matching ruff's (Commands / Options / Global options sections, bold headers, cyan command names, dim descriptions). Subcommand-level help is reachable via either ``safelint help check`` or ``safelint check --help``. ANSI colour auto-disables when stdout is not a TTY. Documented in ``CONFIGURATION.md`` under "Top-level commands and flags".

#### AI-client integration
- **Cursor support alongside Claude Code.** ``safelint skill install`` gains a ``--client`` flag accepting ``auto`` / ``claude`` / ``cursor``. Cursor installs deliver a single MDC project rule (``safelint.mdc``) to ``~/.cursor/rules/`` (user) or ``<cwd>/.cursor/rules/`` (project), matching Cursor's native Project Rules format. Both clients share the same step-by-step workflow because safelint's CLI surface is the same; the bundled language addendums remain accessible to either client via ``safelint skill path``. The Claude install excludes the ``cursor/`` subdirectory from the materialised skill folder so peer-client bundles don't leak into ``~/.claude/skills/safelint/`` (in both copy *and* symlink modes, symlink mode now per-entry-symlinks the directory contents instead of linking the whole tree).
- **Auto-detection is now the default.** ``safelint skill install`` (no ``--client``) is ``--client auto`` under the hood. It scans cwd for client markers (``CLAUDE.md`` / ``.claude/`` / ``.cursor/`` / ``.cursorrules``); if found, installs each detected client's skill **project-scoped**. Otherwise it scans home (``~/.claude/`` / ``~/.cursor/``) and installs **user-scoped**. If neither has any markers, it errors out with the exact ``--client`` commands the user can run instead. Multi-detection is supported, both Claude and Cursor present means both get installed in registry order. ``--client auto --project`` skips the home fallback. **Behaviour change for users running off the development branch:** prior to 1.8.0 in this branch, bare ``safelint skill install`` always installed Claude unconditionally. The new default may install Cursor or both in some environments. Pass ``--client claude`` explicitly to preserve the prior behaviour. (No PyPI users are affected, only 1.7.0 has shipped to PyPI.)
- **`ClientSpec` registry pattern.** A frozen dataclass + tuple registry in ``safelint._skill_install`` defines each supported client. Adding GitHub Copilot, codex, windsurf, etc. is one ``ClientSpec`` append plus the bundled artefact, no control-flow changes elsewhere. CLI ``--client`` choices are derived from the registry so argparse stays in sync automatically.
- **New top-level user guide:** [`AI_CLIENTS.md`](https://shelkesays.github.io/safelint/ai-clients/) documents auto-detection logic, per-client install / usage, project-vs-user scope, symlink mode, troubleshooting, and the developer guide for adding a new client. The bundled in-wheel reference at ``src/safelint/skill_files/README.md`` stays as a short install-focused doc and links out.

### Changed
- Pretty-mode summary line updated from "No fixes available (safelint does not auto-fix violations)" to either "No suggestions available (safelint does not auto-fix)." (when no rule emitted suggestions) or "*N* advisory suggestion(s) available, view via --format json or --format sarif (safelint does not auto-apply fixes)" (when at least one rule did). Wording deliberately distinguishes "no auto-fix" (a permanent design choice) from "no suggestions available" (a per-run state). Test assertions updated accordingly.
- Cache schema version bumped from "1" to "2". The new ``suggestions[]`` field on ``Violation`` requires a richer reconstruction than ``Violation(**dict)``, which the cache now handles via ``_dict_to_violation`` / ``_dict_to_suggestion`` / ``_dict_to_text_edit``. Existing cache entries written by older safelint versions become unreachable automatically (the version is folded into the engine fingerprint, which is part of the cache key).
- The taint-through-formatting paths (f-strings, ``"…".format(tainted)``, ``"… %s …" % tainted``) now have explicit regression tests covering each form. The behaviour itself was already in place since the original SAFE801 implementation; this release just locks the contract in so it can't silently regress.

### Fixed
- ``SAFE202`` previously only matched empty-named-children blocks (which Tree-sitter doesn't actually produce for valid Python), so the rule was effectively dead code. The broadened detection above fixes this.
- ``ReturnValueIgnoredRule`` now anchors violations on the call node rather than the wrapping ``expression_statement``, so column ranges match the offending call instead of including trailing newline / semicolon tokens.

### Notes
- **The contract is permanent: SafeLint will never ship `--fix`.** This is documented as a project policy in ``docs/JSON_SCHEMA.md`` ("Suggestions are advisory only" section). Editor integrations (Claude Code skill, VSCode plugin) may render suggestions as Quick Fix code actions, but every edit goes through user confirmation. The SARIF ``fixes[]`` block is natively advisory per the SARIF 2.1.0 spec, GitHub code scanning, IDE extensions, and other consumers already implement confirmation flows for it.
- Helper-function inlining (cross-function taint analysis) was considered for the SAFE801 work in this release but deferred. Adding it would require a full call-graph walker bounded by depth limits and constitutes a larger rewrite of ``TaintTracker``. The current intra-procedural-only analysis remains the design contract; if a real-world need emerges for cross-function taint, it can be picked up in a future release.
- Internal milestones 1.9.0 and 1.10.0 were never published to PyPI; their work is included in this 1.8.0 release. Those version numbers remain available for future use.

## [1.7.0] - 2026-05-04

This release adds column-precise positioning to violations, the foundational change needed before a polished VSCode extension can underline the exact span of an offending construct rather than the whole line. No breaking changes; the new fields default to ``null`` for any consumer that doesn't read them.

### Added
- **Fully-resolved range positions on every Violation**: ``end_lineno``, ``column_start``, ``column_end`` (in addition to the existing required ``lineno``). All four are 1-based; the range is half-open ``[start, end)``, matching LSP / VSCode ``Range`` and SARIF ``region`` semantics. ``end_lineno`` correctly anchors ``column_end`` to the end-line of multi-line constructs (function definitions, except clauses, while loops), without it, editors would mis-apply ``column_end`` to the start line. ``lineno`` remains required (no default); the three additional fields default to ``None`` for synthetic violations without a Tree-sitter node (e.g. ``test_existence`` against missing files), which editor consumers should treat as "underline the whole line".
- **`node_range(node)` helper** in ``safelint.languages._node_utils``, returns ``(start_line, end_line, column_start, column_end)`` tuples directly from a Tree-sitter node, so rule code stays free of inline ``start_point[0] + 1`` / ``end_point[1] + 1`` plumbing.
- **`BaseRule._make_violation_for_node(filepath, node, message)`**, convenience wrapper around ``_make_violation`` that auto-extracts the full 4-coordinate position info from a Tree-sitter node. Most rules now use this; the lower-level ``_make_violation`` accepts ``column_start`` / ``column_end`` / ``end_lineno`` kwargs for the few cases (e.g. parse errors) where the node isn't available.

### Changed
- All built-in rules with a Tree-sitter node in scope now populate columns: ``function_length``, ``nesting_depth``, ``max_arguments``, ``complexity``, ``bare_except``, ``empty_except``, ``logging_on_error``, ``side_effects``, ``side_effects_hidden``, ``resource_lifecycle``, ``unbounded_loops``, ``missing_assertions``, ``global_state``, ``global_mutation``, ``tainted_sink``, ``return_value_ignored``, ``null_dereference``. The ``test_existence`` / ``test_coupling`` rules continue to emit file-level violations with no column data (the violation is about the file, not a span).
- ``TaintTracker.sink_hits`` now stores ``(call_node, var_name, sink_name)`` tuples instead of ``(lineno, var_name, sink_name)`` so the consuming rule can derive position info, including columns, from the node directly.
- Parse-error violations (``SAFE000``) now carry the column of the offending token as a zero-width caret (``column_start == column_end``), so editors can render a precise marker.
- JSON output (``--format json``) gains ``end_lineno``, ``column_start``, and ``column_end`` keys on every violation. Existing consumers ignoring unknown keys are unaffected.
- SARIF output (``--format sarif``) populates ``region.startColumn``, ``region.endColumn``, and (for multi-line constructs only) ``region.endLine``. Single-line ``endLine`` is omitted because SARIF spec defaults absent ``endLine`` to ``startLine``.

## [1.6.0] - 2026-05-02

This release ships the Claude Code skill inside the wheel and adds a one-line install command, plus a batch of correctness fixes from the v1.5.0 review cycle (caching, argv routing, SARIF URIs, CLI strictness, clean-run UX).

### Added
- **`safelint skill install`** subcommand, copies the bundled Claude Code skill into `~/.claude/skills/safelint/` (default) or `<cwd>/.claude/skills/safelint/` (with `--project`). Use `--symlink` for a live link to the bundled location, `--force` to replace an existing install. New install flow is `pip install safelint && safelint skill install`.
- **`safelint skill path`** subcommand, prints the on-disk location of the bundled skill files. Useful for inspecting `SKILL.md` directly or debugging install issues.
- **Skill files are now bundled in the wheel** at `safelint/skill_files/` (mirroring `safelint/languages/` one-to-one). `safelint skill install` finds them via `importlib.resources`, so the same code path works for `pip install`, `uv add`, and editable installs from a checkout.
- **`docs/JSON_SCHEMA.md`**, the stable schema for `safelint check --format json`. Documents top-level keys, the Violation object, severity / fail_on / blocking semantics, and example consumers in bash / Python / Node. Versioning policy: additions are non-breaking; removals require a major bump.

### Changed
- The Claude Code skill now lives at `src/safelint/skill_files/` in the source tree (was `skills/safelint/`). The skill itself is also more modular: a language-agnostic core (`SKILL.md`) plus per-language addendums under `languages/<lang>.md`, mirroring `src/safelint/languages/<lang>.py`. To add a new language, follow the new step 7 in [`ADDING_A_LANGUAGE.md`](https://shelkesays.github.io/safelint/contributing/adding-a-language/).

### Fixed
- `per_file_ignores` is now folded into the engine fingerprint, so adding/removing/editing a glob entry between runs invalidates the affected cache entries. Previously a cache hit carried the cached `suppressed` list over unchanged, which meant *removing* a `per_file_ignores` entry left previously suppressed violations stuck in the suppressed list, the user would loosen config and still see the silence applied. The post-hit re-filter (which only walked the active list and never the suppressed list) is now also redundant and has been removed.
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
- **`--format`** flag with three choices: `pretty` (default, unchanged ruff/ty multi-line coloured output), `json`, and `sarif`. The JSON format emits a stable schema with a `version`, `summary` (counts + suppressed breakdown), and flat `violations` / `suppressed` lists. The SARIF format is SARIF 2.1.0 conformant and consumable by GitHub code scanning, Azure DevOps, and similar tools. The flag is available in both `safelint check` and pre-commit hook modes.
- **`--stdin`** / **`--stdin-filename PATH`** flags read source from stdin instead of from disk and lint it as if it came from `PATH`. Designed for editor integrations that need to lint un-saved buffers without round-tripping through a temp file. The pseudo-filename drives language detection by extension and shows up as the violation file path.
- **`SafetyEngine.check_source(filepath, source)`** public method runs the same rule pipeline as `check_file` but on a caller-provided buffer. Used by stdin mode and available to library consumers building editor integrations.
- **Per-file lint-result cache** keyed on `sha256(source + engine fingerprint)` where the engine fingerprint folds in safelint version, an internal cache schema version, and the active rule set with per-rule config. The cache lives at `<config-dir>/.safelint_cache/` (next to `pyproject.toml` / `safelint.toml`, mirroring `.pytest_cache`'s convention) and stores one JSON file per key. Re-runs on unchanged files are essentially instant, important for editor "lint on save" loops.
- **`--no-cache`** flag disables the cache for the current run (e.g. CI where every run is fresh anyway, or when debugging cache-related issues). `.safelint_cache/` added to the project's `.gitignore`.
- **`ADDING_A_LANGUAGE.md`** developer guide: a concrete walkthrough of adding a new language (TypeScript, Go, Rust, …), with a per-rule audit of which Python rules are portable, language-agnostic, or Python-only.

### Notes
- `--stdin` mode unconditionally bypasses the disk cache. Editor keystrokes produce a slightly different buffer every time; caching them would only churn the project tree without ever helping. The `--no-cache` flag is therefore a no-op in stdin mode.
- The new public `LintCache` class accepts `cache_dir=None` to opt out of caching at the engine level, used by `--no-cache`, by stdin mode, and recommended for any tests / library callers that need isolation.

## [1.4.1] - 2026-05-01

### Added
- `max_file_size_bytes` top-level config option (default **5 MiB**). Files larger than the bound are skipped with a `safelint: warning: skipping <path> (<size> bytes exceeds max_file_size_bytes=…)` diagnostic to stderr instead of being read into memory and parsed. Guards against OOM on accidentally-huge inputs (binary blobs masquerading as `.py`, very large generated files). To allow larger files, raise the bound explicitly, `0` is rejected as a likely typo (it would disable the OOM guard entirely) and falls back to the default with an init-time warning. Engine init validates the value: must be a non-negative integer, otherwise `TypeError`/`ValueError` fires before any file is read. Closes #20.

### Fixed
- File discovery is now safe against symlink cycles. `SafetyEngine._discover_files` switched from `Path.rglob('*')` (which follows symlinks and can recurse forever on a cycle like `a/sub -> ..`) to `os.walk(target, followlinks=False)`. Same single-pass O(number_of_files) cost, but safe by construction. Matches what ruff and flake8 do by default. Closes #19.

## [1.4.0] - 2026-05-01

> **Heads-up, breaking library API change.** `LintResult.suppressed` is now `list[Violation]` (was `int`). Library consumers that read this field directly need to switch to `len(result.suppressed)` for the count. CLI users are unaffected. See **Changed** below for details and migration notes.

### Added
- Standalone `safelint.toml` configuration file (top-level keys, no `[tool.safelint]` wrapper). When both `safelint.toml` and `pyproject.toml` `[tool.safelint]` exist in the same directory, `safelint.toml` wins, matching `ruff.toml` / `pyproject.toml` precedence.
- `examples/sample.safelint.toml` reference covering every supported configuration key.
- Public `safelint.languages.supported_extensions() -> frozenset[str]` for callers that need to know which file extensions have a registered language. Use this instead of importing the private `_REGISTRY`.
- `walk()` in `safelint.languages._node_utils` accepts an optional `skip_types` parameter that prunes subtrees rooted at any matching node type (used by per-function rules to avoid descending into nested `def` / `async def` bodies).

### Changed
- `side_effects` (SAFE304) and `side_effects_hidden` (SAFE303) now normalise **both** sides of the name comparison. Function names are lowercased for matching, and user-supplied `io_name_keywords` / `pure_prefixes` are lowercased once at config load, so configurations like `io_name_keywords = ["Write", "Log"]` or `pure_prefixes = ["Get", "Calculate"]` behave the same as their lowercase forms. Previously only the function name was lowered, leaving uppercase config entries silently unmatched.
- `load_config()` now returns a fresh deep copy of the merged config on every call. Mutating the result (e.g. `config["ignore"].append(...)`) no longer corrupts the module-global `DEFAULTS`.
- **Removed** YAML (`.safelint.yaml`) configuration support and the `safelint[yaml]` install extra. Migrate to `[tool.safelint]` in `pyproject.toml` or to a standalone `safelint.toml`.
- CLI summary "All checks passed." is now bold green to match `ruff` / `ty`.
- The "No fixes available …" line is no longer printed on clean runs (with or without suppressions). It only appears when there are active violations a developer might wonder about auto-fixing.
- Suppressed-violation summary now shows a per-code breakdown, e.g. `(2 SAFE501, 1 SAFE304 suppressed)`, instead of a bare `(N suppressed)` count, so it is clear which rules were silenced.
- **Breaking (library API):** `LintResult.suppressed` is now `list[Violation]` (was `int`). Use `len(result.suppressed)` for the count and iterate to inspect codes, rules, file paths, and line numbers of suppressed violations.
- Replaced internal use of Python's `logging` module with a dedicated diagnostics channel that writes formatted single-line messages to stderr (`safelint: warning: …`, `safelint: error: …`). Configuration typos and malformed-TOML errors are now surfaced cleanly instead of leaking through Python's `lastResort` logging handler.
- `walk()` now traverses only `named_children` (skips Tree-sitter's anonymous punctuation/keyword tokens), reducing the number of nodes visited per traversal across every rule and the suppression parser.
- Parse-error violations (`SAFE000`) now include line, column (1-based), and a kind hint such as `missing ':'` or `syntax error`. The lineno on the violation now points at the offending location instead of being hardcoded to 0.
- `MaxArgumentsRule` now counts `*args` and `**kwargs` parameters, each as one argument. Previously they were silently ignored, allowing functions to exceed `max_args` without triggering.
- An empty `[tool.safelint]` section in `pyproject.toml` (or an empty `safelint.toml`) is now treated as a present-but-empty config. Previously the loader fell through to an ancestor directory's config, hiding unintentionally-blank sections.
- Self-development pre-commit hook switched from `repo: https://github.com/shelkesays/safelint @ v1.3.2` to `repo: local`, so contributors run the in-tree code rather than an outdated published release while iterating on safelint itself.

### Fixed
- Per-function rules no longer incorrectly aggregate metrics from nested `def` / `async def` bodies into the enclosing function. Affects `complexity`, `nesting_depth`, `missing_assertions`, `unbounded_loops`, `global_state`, `global_mutation`, `logging_on_error` (a logging call inside a nested helper would have falsely satisfied the rule), and the dataflow `TaintTracker`. Each nested function is scored as its own unit, as the outer-walk loop already intended.
- `state_purity` (`global_state`, `global_mutation`) now also stops at nested class definitions, a `global X` declared inside a nested class body lives in that class's scope, not the enclosing function's.
- `function_length` (SAFE101) reported counts that were off by one (a 60-line function showed `59 lines`). The calculation is now inclusive of the `def` line.
- Dataflow taint tracker now unwraps `keyword_argument` nodes, `eval(code=user_input)` is no longer missed because the tainted value was hidden behind a kwarg wrapper.
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

[Unreleased]: https://github.com/shelkesays/safelint/compare/v2.8.1...HEAD
[2.8.1]: https://github.com/shelkesays/safelint/compare/v2.8.0...v2.8.1
[2.8.0]: https://github.com/shelkesays/safelint/compare/v2.7.1...v2.8.0
[2.7.1]: https://github.com/shelkesays/safelint/compare/v2.7.0...v2.7.1
[2.7.0]: https://github.com/shelkesays/safelint/compare/v2.6.1...v2.7.0
[2.6.1]: https://github.com/shelkesays/safelint/compare/v2.6.0...v2.6.1
[2.6.0]: https://github.com/shelkesays/safelint/compare/v2.5.0...v2.6.0
[2.5.0]: https://github.com/shelkesays/safelint/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/shelkesays/safelint/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/shelkesays/safelint/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/shelkesays/safelint/compare/v2.2.0rc3...v2.2.0
[2.2.0rc3]: https://github.com/shelkesays/safelint/compare/v2.2.0rc2...v2.2.0rc3
[2.2.0rc2]: https://github.com/shelkesays/safelint/compare/v2.2.0rc1...v2.2.0rc2
[2.2.0rc1]: https://github.com/shelkesays/safelint/compare/v2.1.0...v2.2.0rc1
[2.1.0]: https://github.com/shelkesays/safelint/compare/v2.1.0rc1...v2.1.0
[2.1.0rc1]: https://github.com/shelkesays/safelint/compare/v2.0.0...v2.1.0rc1
[2.0.0]: https://github.com/shelkesays/safelint/compare/v2.0.0rc3...v2.0.0
[2.0.0rc3]: https://github.com/shelkesays/safelint/compare/v2.0.0rc2...v2.0.0rc3
[2.0.0rc2]: https://github.com/shelkesays/safelint/compare/v2.0.0rc1...v2.0.0rc2
[2.0.0rc1]: https://github.com/shelkesays/safelint/compare/v1.13.0...v2.0.0rc1
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
