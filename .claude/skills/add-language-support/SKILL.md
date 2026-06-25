---
name: add-language-support
description: Use when adding support for a NEW LANGUAGE (Go, C, C++, PHP, ...) or a NEW FRAMEWORK / RUNTIME PRESET (like spring-boot or the JS runtimes) to safelint itself. Walks the complete development checklist so nothing is missed - registry, rule audit, tests, docs, config examples, bundled skill files, drift tests, counts. Invoke before writing any code for such a change.
---

# Adding a language or framework preset to safelint

This is the **development** checklist for extending safelint itself. The
tracked human walkthrough is `docs/contributing/adding-a-language.md` (read it
first; it has a worked TypeScript example). This skill is the enforcement
layer: every item below must be done or explicitly recorded as deliberately
skipped with a rationale. History shows the misses are never the engine code -
they are the docs fan-out, the counts, the examples, and the bundled skill
files.

Two workflows: **Part A** (new language), **Part B** (framework / runtime
preset). Part C lists the conventions and the validation gate shared by both.

---

## Part A: Adding a new language

### A1. Grammar packaging

- [ ] `pyproject.toml`: add `tree-sitter-<lang>` as its **own optional extra**
      (every language is opt-in; the base install ships no grammars), fold it
      into the `[all]` extra (single source of truth - `dev` pulls
      `safelint[all]`), and extend the extras comment block.
- [ ] `uv lock` regenerates; commit `uv.lock`.

### A2. Language module: `src/safelint/languages/<lang>.py`

- [ ] Optional grammar import with `_GRAMMAR_AVAILABLE` flag (silent
      `except ImportError` fallback carries `# nosafe: SAFE203`, matching the
      five existing modules).
- [ ] `EXTRA_NAME`, `GRAMMAR_INSTALL_HINT`, parser factory raising
      `ImportError` with the hint when the grammar is absent.
- [ ] `LanguageDefinition` (extensions, `comment_node_type`,
      `comment_prefix`). Line-comment directives only; block-comment `nosafe`
      is a documented non-feature.
- [ ] Node-type string constants (rules must import these, never hardcode
      strings) and a `FUNCTION_TYPES` aggregate containing **body-bearing**
      function nodes only (see the Rust module's note on excluding signatures).

### A3. Registry: `src/safelint/languages/__init__.py`

- [ ] Add the parallel registration block (grammar present -> `_REGISTRY`;
      absent -> `_UNAVAILABLE_EXTENSIONS` + `_UNAVAILABLE_EXTRA_NAMES` so the
      CLI can hint `pip install 'safelint[<lang>]'`). Keep the blocks
      grep-parallel with the existing five.
- [ ] Export the definition in `__all__`. Do NOT reach into `_REGISTRY` from
      elsewhere; `supported_extensions()` is the public surface.

### A4. Per-rule portability audit (the core design work)

- [ ] For every rule in `ALL_RULES`, decide: ports cleanly (widen its
      `language` tuple, add a per-language node-type table entry), needs a
      language-specific replacement (new rule, category band 1xx-8xx), or is
      deliberately skipped (record the rationale - it will be needed in A7).
- [ ] Add `_<lang>`-suffixed config defaults in `DEFAULTS["rules"]` for every
      configurable list the ported rules consult (`io_functions_<lang>`,
      `sinks_<lang>`, `assertion_calls_<lang>`, ...). Python uses bare keys;
      every other language uses the suffix. TS inherits JS via the fallback in
      `core/_validators.py` - a new language gets no fallback unless designed.
- [ ] Dataflow rules (8xx) need a per-language tracker:
      `analysis/dataflow_<lang>.py` modelled on the four existing ones
      (iterative worklists, NOT recursion - SAFE105 polices the codebase).
- [ ] `tests/core/test_engine.py`: the `_RULES_*` allow-list buckets assert
      every rule's `language` tuple EXACTLY. Every widened tuple must move its
      rule to the matching bucket or the suite fails.

### A5. Plumbing

- [ ] `.pre-commit-config.yaml` AND `.pre-commit-hooks.yaml`: add the
      language's pre-commit tag to `types_or` (both files).
- [ ] `safelint list-rules` and the at-a-glance docs table derive from the
      registry automatically - verify the new language shows up, no manual
      edit expected.

### A6. Tests

- [ ] Per-rule, per-language test files (`tests/rules/test_<rule>_<lang>.py`):
      violation case AND clean case for every ported rule.
- [ ] Engine-level file: discovery picks up the extensions, `// nosafe`
      (or the language's comment form) suppression works, one known-bad file
      fires.
- [ ] `tests/core/test_optional_grammars.py`: the missing-grammar hint path.
- [ ] Coverage gate is `fail_under = 97` (pyproject), not the 80 some older
      notes claim.

### A7. Documentation fan-out (where additions historically go missing)

- [ ] `docs/languages/<lang>.md`: full language page - extensions, quick
      start, rules table with per-language notes, **"rules not registered"
      list with rationale per skipped rule**, per-language config keys.
- [ ] `mkdocs.yml`: nav entry under Languages.
- [ ] `docs/configuration/rules.md`: "Currently supported" bullet, the
      "Rule scope (current languages)" table, and REMOVE the language from
      the "Planned" list.
- [ ] `README.md` + `docs/index.md`: language tables, the "Rule coverage"
      paragraph, and every count ("N rules", "N languages", "the
      all-five-languages set" wording will need rewording at six languages).
- [ ] `docs/power-of-ten.md`: per-language fidelity notes if the language
      changes any Holzmann-rule mapping (e.g. its analogue of rule 8/9).
- [ ] **Config examples in BOTH forms** for every new `_<lang>` key:
      `[tool.safelint.rules.<rule>]` (pyproject.toml) and `[rules.<rule>]`
      (standalone safelint.toml). Check `docs/configuration/toml.md` too if
      the language gains a preset axis (see Part B).
- [ ] **Scattered enumerations** (the docs that list *every* language's
      extension / grammar / `--language` value OUTSIDE the headline language
      tables - the v2.5.0 Go addition missed all of these; they are not
      caught by the language-table edits above):
      - `docs/configuration/cli.md`: the `--all-files` supported-extension
        list AND the `--language <LANG>` accepted-value list.
      - `SECURITY.md` (repo root - `docs/project/security.md` is a
        build-time copy, edit the root): the supported-versions table
        ("current" row), the bundled-grammar supply-chain list
        (`tree-sitter-<lang>`), and the "files read from the working tree"
        extension list.
      - `docs/configuration/toml.md`: the "enable opt-in rules" walkthrough
        (add the language's new opt-in / language-only rules).

### A8. Bundled AI-client skill files (drift-test enforced)

- [ ] Shared addendum `src/safelint/skill_files/languages/<lang>.md`
      (modelled on the five existing; covers install nuance, extensions,
      per-rule phrasing, idiomatic fix patterns).
- [ ] Step-2 registry table row in **all 14 client files** (claude, cursor,
      copilot, gemini, windsurf, codex, continue, cline, aider, trae,
      antigravity, zed, warp, kiro).
- [ ] `src/safelint/skill_files/README.md`: counts and layout tree.
- [ ] The drift tests in `tests/test_skill_install.py`
      (`test_skill_documents_every_supported_extension` and
      `..._every_active_rule`) fail per client until every extension and
      every rule code+name appears - land skill-file updates in the SAME
      commit as the registry change or the suite is red.

### A9. Bookkeeping

- [ ] `CHANGELOG.md` under `[Unreleased]` -> Added. New language = MINOR,
      never MAJOR (project semver policy; JS itself shipped as 1.13.0).
- [ ] **`pyproject.toml` package metadata**: `project.description` and
      `project.keywords` enumerate the supported languages - add the new one
      to both (the v2.6.0 PHP release missed this; PyPI showed a stale
      language list). These are part of the scattered-enumeration family.
- [ ] Stale-count + enumeration sweep: `grep -rn` for the old counts
      ("N rules", "five languages", "N cross-language") AND for the
      previous language's tokens - its extension (e.g. `.rs`), its name as a
      whole word (`grep -w rust`, since plain `grep` does not treat `\b` as
      a word boundary), and its grammar (`tree-sitter-rust`) - across
      `docs/`, `README.md`, `SECURITY.md`, `pyproject.toml`, `plan/README.md`
      (the roadmap title / table / counts go stale too),
      `src/safelint/skill_files/`.
      Every extension list, grammar list, `--language` value list, and
      rule-set enumeration that names the prior languages must gain the new
      one; these scattered lists (NOT the headline language tables) are the
      most common miss. Tip - substitute the previous language's extension
      for `<prev-ext>` and the new one for `<new-ext>` (e.g. `.rs` and `.go`
      when Go follows Rust): `for f in $(grep -rl '<prev-ext>' docs README.md SECURITY.md pyproject.toml plan/README.md src/safelint/skill_files); do grep -L '<new-ext>' "$f"; done`
      surfaces files that mention the old extension but not the new one.
- [ ] **Bump the version - this is the most-missed step (missed twice).** A
      new language is additive = next `X.Y.0`. The work lands via the release
      branch flow (see CLAUDE.md "Release workflow"): the `feature/* ->
      development` PR carries the **RC** bump (`project.version = "X.Y.0rcN"`,
      e.g. `2.6.0rc1`); the later `development -> main` PR flips it to the
      production `"X.Y.0"`. Do NOT leave `project.version` at the previous
      release. Keep the `CHANGELOG.md` heading at `## [Unreleased]` - it is
      dated only at the production tag. The owner controls release timing and
      tagging; the number itself is derived by the additive=MINOR convention,
      so apply it as part of finishing the work rather than waiting to be
      reminded.
- [ ] **`SECURITY.md` supported-versions table**: add the new release line as
      "current" (e.g. `**X.Y.x** (current; <Lang> support)`) and demote the
      prior current line into the maintained band. This rides in the
      production (`development -> main`) bump, and is part of the same
      scattered-enumeration family as the sweep above.

### A10. Common pitfalls (review-caught in the Go port - design for these upfront)

Real bugs the bot reviewers caught *after* the Go PR opened. They generalise;
build them in from the start rather than waiting for review:

- [ ] **Validate config lists.** A new language-only rule that reads a config
      list (`error_names_<lang>`, `panic_calls_<lang>`, ...) must pass it
      through `_validated_string_list(...)`. A mistyped scalar
      (`error_names_go = "err"`) otherwise becomes a set of single characters
      and silently disables matching.
- [ ] **Test samples must be VALID in the target language.** Tree-sitter
      parses leniently, so a *type*-invalid sample (a value returned from a
      void function, a single-target bind of a multi-value call) does NOT
      raise a parse error - the test then passes for the wrong reason. Write
      samples that would actually compile.
- [ ] **Resolve callee names with `call_name`, not a hand-rolled
      `identifier`-only check.** It covers BOTH bare calls (`panic(...)`) and
      qualified / selector / method calls (`log.Fatal(...)`, `pkg.Fn(...)`).
      Matching only the bare-identifier shape silently drops every configured
      qualified-call name (this hit SAFE211's `Fatal` / `Exit`).
- [ ] **Resource-cleanup detection (SAFE401-family).** The cleanup must occur
      *after* the acquisition and on *all* exit paths - reject cleanups that
      precede the acquire or sit inside a conditional branch; map a
      multi-acquirer statement positionally to each handle; a directly
      returned acquirer transfers ownership (not a local leak). Tailor the
      message to the shape (no-handle / package-scope cases can't use the
      normal `defer`/`with`/`finally` fix).
- [ ] **Declaration-site walks (global-state-family).** Iterate the
      declaration's direct children; do NOT `walk()` into initializer
      expressions (a nested local declaration is not module/package-level
      state). Skip blank / discard identifiers (`_`).
- [ ] **Compound assignments preserve taint** in the dataflow tracker:
      `x += clean` is read-modify-write, so it must OR with x's prior taint,
      not overwrite it.
- [ ] **Keep the Python that implements all this passing safelint's own
      rules** - new helpers must obey `function_length` / `nesting_depth` /
      `complexity` / `no_recursion`; factor into small helpers rather than
      annotating (the Go port needed several such splits).

---

## Part B: Adding a framework / runtime preset

Precedents: `[tool.safelint.javascript] runtime` (node / browser / deno /
cloudflare-workers / bun) and `[tool.safelint.java] framework` (vanilla /
spring-boot). A preset changes rule DEFAULTS for an existing language; it
never changes parsing or rule logic.

### B1. Config machinery (`core/config.py`)

- [ ] Preset dict whose nested shape mirrors `DEFAULTS["rules"]`, containing
      ONLY the keys it overrides (the baseline preset, e.g. `node` /
      `vanilla`, is the empty dict).
- [ ] A `frozenset` of valid preset names.
- [ ] `_resolve_<lang>_<axis>()`: reads `cfg["<lang>"]["<axis>"]`, validates,
      and on unknown / non-string / non-table values surfaces a
      `safelint: warning:` via `core/_diagnostics` and falls back to the
      default preset. Never raise for a bad preset name.
- [ ] `_apply_*` merges the preset into the DEFAULTS copy **before** the
      user's TOML is overlaid, so explicit user keys always win.

### B2. Framework-specific structural rules (if any)

- [ ] New structural rules tied to the framework go in the **9xx band**
      (9xx is reserved for framework-specific rules - Spring today; never
      open a per-language band). Disabled by default; the preset enables
      them.
- [ ] Each follows the full "Adding a new rule" checklist in CLAUDE.md
      (registry, defaults, order list, tests, rules.md, language page, all
      14 skill files - the rule drift test enforces the last).

### B3. Tests

- [ ] Preset-resolution tests modelled on
      `tests/core/test_javascript_runtime_presets.py` /
      `tests/core/test_java_framework_presets.py`: each preset's overrides land,
      user TOML beats the preset, unknown names warn + fall back.
- [ ] An e2e fixture if structural rules ship (precedent:
      `tests/fixtures/spring_boot/` + `tests/integration/test_spring_boot_e2e.py`).

### B4. Documentation

- [ ] Language page (`docs/languages/<lang>.md`): preset table (when to pick
      it, what changes).
- [ ] `docs/configuration/toml.md`: a preset section with **both TOML forms**
      (`[tool.safelint.<lang>]` and bare `[<lang>]` for standalone
      safelint.toml) - the Java framework section was missed for two releases;
      do not repeat that.
- [ ] `docs/configuration/rules.md`: sections for any new 9xx rules.
- [ ] `README.md` / `docs/index.md`: mention on the language row.
- [ ] Shared language addendum (`skill_files/languages/<lang>.md`): preset
      table; client rule tables gain rows for any new 9xx codes.
- [ ] `CHANGELOG.md` under `[Unreleased]`.

---

## Part C: Conventions and the validation gate (both workflows)

Non-negotiables (full detail in CLAUDE.md):

- safelint must pass itself: `uv run safelint check src/ --all-files` with zero
  blocking violations (the `--all-files` flag matches CI; without it the check
  only scans git-modified files and can read clean falsely) - including the new
  rules on the new code (no recursion, nesting <= 2, complexity <= 10, function
  length <= 60).
- Never rename or repurpose existing rule names / codes.
- No auto-fix, ever; fixes are advisory `Suggestion`s only.
- Rule numbering: slot by CATEGORY into 1xx-8xx; 9xx is framework-specific
  only.
- Indian English ("behaviour", "-ise"); NO em-dashes anywhere.
- Additive scope = MINOR semver, always.

Final gate, run all in order; every one must pass:

```bash
uv run pytest                                  # coverage gate fail_under = 97
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/ --all-files         # zero blocking violations
uv run mkdocs build --strict                   # docs integrity, broken anchors fail
```

After merging: refresh installed skills with
`safelint skill install --force` (bundled docs changed), and remind users in
the changelog when bundled skill content drifts.
