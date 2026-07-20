# Language-expansion plan

**Audience**: the AI coding agent (or human contributor) implementing the next
piece of work. Each item has its own self-contained spec in this directory.
Implement **one spec at a time, in working-priority order**.

**No language addition is currently planned.** C++ shipped in v2.8.0 (see the
blockquote below); the remaining work in this directory is the deferred
cross-language refactors listed further down. `docs/configuration/rules.md`
"Planned" reflects the same empty near-term roadmap. The blockquotes below
record the shipped-language history and the convention this plan directory
follows: a spec file is removed once its language ships.

> **Go (`.go`) shipped in v2.5.0** (6th registered language: 16 cross-language
> rules + the Go-only SAFE209 `empty_error_check` / SAFE211
> `panic_calls_outside_tests`). Its spec, `plan/01-go.md`, was removed on
> completion - the design decisions now live in the
> [Go language page](../docs/languages/go.md), the
> `src/safelint/skill_files/languages/go.md` addendum, and the shipped code.

> **PHP (`.php`) shipped in v2.6.0** (7th registered language: 21
> cross-language rules - the widest port yet, including SAFE301
> `global_state`'s first non-Python home; only SAFE201 `bare_except` and
> SAFE305 `wide_scope_declaration` are skipped). Its spec, `plan/04-php.md`,
> was removed on completion - the design decisions now live in the
> [PHP language page](../docs/languages/php.md), the
> `src/safelint/skill_files/languages/php.md` addendum, and the shipped code.

> **C (`.c`, `.h`) shipped in v2.7.0** (8th registered language: 21 rules = 16
> cross-language ports + 5 C-only SAFE106/310-313, the "Power of Ten homecoming").
> Post-release audit gaps closed in 2.7.1. Its spec, `plan/02-c.md`, and the
> 2.7.1 remediation spec, `plan/c-audit-remediation.md`, were both removed on
> completion - the design decisions now live in the
> [C language page](../docs/languages/c.md), the
> `src/safelint/skill_files/languages/c.md` addendum, and the shipped code.

> **C++ (`.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`) shipped in v2.8.0** (9th
> registered language: 26 rules = the cross-language ports + the five C-family
> rules SAFE106 / SAFE310-313 widened to C and C++ + the try/catch rules
> SAFE201-203 + two new C++-only rules SAFE315 `raw_new_delete` / SAFE316
> `dangerous_casts`). Its spec, `plan/03-cpp.md`, was removed on completion -
> the design decisions now live in the
> [C++ language page](../docs/languages/cpp.md), the
> `src/safelint/skill_files/languages/cpp.md` addendum, and the shipped code.

No active language specs remain in this directory. When a new language is
planned, add its spec file and (re)introduce a status table here listing it in
working-priority order (and remove the spec once the language ships, as was done
for Go, PHP, C, and C++).

## Planned: release automation (CI/CD, not a code change)

| Spec | Scope | Status |
|---|---|---|
| [`release-automation.md`](release-automation.md) | Auto-tag + PyPI + GitHub release on a version bump (rc from `development`, final from `main`); post-merge `development`->`main` reset-if-safe; CHANGELOG-section release notes; local `bin/sync.sh` | Planned - not started |

Removes the manual `pull -> tag -> push -> release` steps and the recurring
`development` / `main` divergence that forces squash-over-rebase. Confirmed
design decisions: release notes from the CHANGELOG section, reset dev to main
only when safe. High-stakes (PyPI + branch protection) - read the spec's setup
(section 4) and open decisions (section 8) before implementing.

## Deferred cross-language refactors (run AFTER the languages above)

These were not language additions; they were codebase-wide sweeps best done once
the language set is stable, so they didn't have to be redone per language. The
three below have **shipped**, so - following the same convention as the shipped
languages above - their spec files were removed on completion (the design
decisions now live in the referenced CHANGELOG entries and the shipped code). One
new cross-language enhancement remains **planned**, listed in the table after
them.

> **Node-type / operator constants shipped in v2.8.2** (PR #107). Converted the
> per-language node-type / operator tables in `src/safelint/rules/` from raw
> Tree-sitter string literals to imported `src/safelint/languages/<lang>.py`
> constants, for all languages at once. Pure refactor, no behaviour change. Its
> spec, `plan/refactor-node-type-constants.md`, was removed on completion.
>
> **Module-access constants shipped in v2.8.3** (PR #111). Follow-up to the
> above: switched the rules from ~1,350 per-constant aliased imports
> (`... import IF_STATEMENT as _CPP_IF_STATEMENT`) to module-access
> (`from safelint.languages import cpp as _cpp`; `_cpp.IF_STATEMENT`); the
> language modules stayed unchanged. Pure refactor, no behaviour change - gives
> the `Namespace.CONSTANT` ergonomics without a wrapper class and deletes the
> alias soup. Its spec, `plan/refactor-module-access-constants.md`, was removed
> on completion.
>
> **Security hardening shipped across v2.7.x / v2.8.1** (findings H1-H9). Defence
> -in-depth fixes from the 2026-06-25 internal audit: `test_dirs` containment,
> `skill install/remove` symlink/TOCTOU hardening, cache `mkstemp`. No HIGH /
> MEDIUM findings and none default-flow-exploitable; the backlog is empty. Its
> spec, `plan/security-hardening.md`, was removed on completion.

| Spec | Scope | Status |
|---|---|---|
| [`taint-attribute-propagation.md`](taint-attribute-propagation.md) | Make the intra-procedural taint trackers carry taint through attribute / subscript / tainted-receiver chains (`request.GET["q"]`, `$request->input('x')`), so the framework-preset (and Spring / JS-runtime) SAFE801 sink extensions actually fire on realistic request-driven code instead of only direct-parameter flows | Planned - not started |

Surfaced by the v2.9.0 framework-presets code review: the added sinks are inert
on idiomatic web-framework code because taint is lost at the first `request.<attr>`
access (a pre-existing, cross-language tracker limitation the Spring preset shares).
Cross-cutting change to all six trackers - read the spec's "Risks and open
decisions" (whether to gate the noisy method-call-on-tainted-receiver step behind
a config knob) before implementing.

## How to use these specs

1. Read the project's three standing references **before** the language spec:
   - `docs/contributing/adding-a-language.md` - the tracked human walkthrough
     (worked TypeScript example) **including its "Adding a framework /
     runtime preset" section**.
   - `.claude/skills/add-language-support/SKILL.md` - the enforcement
     checklist this plan is built on (Parts A, B, C).
   - `CLAUDE.md` - hard constraints, commands, and the "Adding a new rule"
     checklist (language-specific rules follow it too).
2. Then read your language's spec end to end. It contains the
   language-specific *design decisions* (the per-rule portability audit, the
   new-rule proposals, the dataflow lists). The generic mechanics live in the
   references above; the spec does not repeat them except where the language
   deviates.
3. Each spec ships as **one comprehensive MINOR release** worth of work. Do
   not split a language across releases. **Do bump the version - it is the
   most-missed step.** A new language is additive = next `X.Y.0`. Land the
   work via the release-branch flow (see CLAUDE.md "Release workflow"):
   the `feature/* → development` PR carries the **RC** bump
   (`project.version = "X.Y.0rcN"`), and the later `development → main` PR
   flips it to the production `"X.Y.0"`; the `CHANGELOG.md` heading stays
   `## [Unreleased]` until the production tag. The owner controls release
   timing and tagging, but do not leave `project.version` at the previous
   release.

## Non-negotiables (digest; full detail in CLAUDE.md)

- **SafeLint must pass itself**: `uv run safelint check src/ --all-files` with
  zero blocking violations (the `--all-files` flag matches CI; without it the
  check only scans git-modified files and can read clean falsely), including
  the new code obeying `no_recursion`
  (iterative worklists, never recursion), `nesting_depth=2`, `complexity=10`,
  `function_length=60`.
- **Never rename or repurpose existing rule names / codes.** New rules slot
  by *category* into the 1xx-8xx bands; **9xx is framework-specific only**.
  Proposed codes in these specs were free as of v2.4.0; **re-verify with
  `uv run safelint list-rules` at implementation time** and renumber if
  taken.
- **No auto-fix, ever.** Advisory `Suggestion`s only.
- **Indian English** ("behaviour", "-ise"); **no em-dashes anywhere**.
- **Drift tests land in the same commit** as the change that triggers them:
  registering an extension or a rule makes
  `tests/test_skill_install.py::test_skill_documents_every_supported_extension`
  / `::test_skill_documents_every_active_rule` fail for all 14 clients until
  every client doc carries the new extensions / rule code + name.
- **Config examples in BOTH forms** for every new key:
  `[tool.safelint.rules.<rule>]` (pyproject.toml) and `[rules.<rule>]`
  (standalone safelint.toml). Preset tables get `[tool.safelint.<lang>]` and
  bare `[<lang>]` forms in `docs/configuration/toml.md`.
- **Counts cascade.** Every language addition invalidates "N languages",
  "N rules", "the all-five-languages set" phrasing across `README.md`,
  `docs/index.md`, `docs/configuration/rules.md`, the language pages, and
  the skill files. Do not trust counts written in these specs; run the
  stale-count sweep (grep for the previous numbers) as a final step.
- **Enumerations cascade too** (the v2.5.0 Go miss). Beyond counts and the
  headline language tables, several docs list *every* language's extension
  / grammar / `--language` value and must each gain the new one:
  `docs/configuration/cli.md` (`--all-files` extension list, `--language`
  values), `SECURITY.md` (supported-versions table, `tree-sitter-<lang>`
  grammar list, files-read extension list), and `docs/configuration/toml.md`
  (the opt-in-rules walkthrough). Run an enumeration sweep alongside the
  count sweep: grep the previous language's extension / name /
  `tree-sitter-<lang>` across `docs/`, `README.md`, `SECURITY.md`, and
  `src/safelint/skill_files/`.
- **Verify Tree-sitter node types by probing, never from memory.** The specs
  name expected node types; confirm each with a quick probe before relying
  on it:

  ```bash
  uv run python - <<'PY'
  import tree_sitter, tree_sitter_c  # adjust per language (next up: C)
  lang = tree_sitter.Language(tree_sitter_c.language())
  tree = tree_sitter.Parser(lang).parse(b"int main(void) { return f(); }")
  # Iterative on purpose - the same worklist shape production code must use
  # (safelint's own no_recursion rule polices the codebase).
  stack = [(tree.root_node, 0)]
  while len(stack) > 0:
      node, depth = stack.pop()
      print("  " * depth + node.type)
      stack.extend((c, depth + 1) for c in reversed(node.named_children))
  PY
  ```

## Review-caught pitfalls from the Go port (avoid these upfront)

These are real bugs the bot reviewers caught *after* the Go PR opened. They
generalise, so design for them from the start rather than waiting for review:

- **Validate config lists.** Any new language-only rule that reads a config
  list (`error_names_<lang>`, `panic_calls_<lang>`, ...) must pass it through
  `_validated_string_list(...)`; a mistyped scalar (`error_names_go = "err"`)
  otherwise becomes a set of single characters and silently breaks matching.
- **Test samples must be VALID in the target language.** Tree-sitter parses
  leniently, so a *type*-invalid sample (a value returned from a void
  function, a single-target bind of a multi-value call) does NOT raise a
  parse error - the test passes for the wrong reason. Write samples that
  would actually compile.
- **Resolve callee names with `call_name`, not a hand-rolled identifier
  check.** It covers BOTH bare calls (`panic(...)`) and qualified / selector /
  method calls (`log.Fatal(...)`, `pkg.Fn(...)`). Matching only the bare
  shape silently drops every configured qualified-call name.
- **Resource-cleanup detection (SAFE401-family).** The cleanup must occur
  *after* the acquisition and on *all* exit paths - reject cleanups that
  precede the acquire or sit inside a conditional branch, and map a
  multi-acquirer statement positionally to each handle. A returned acquirer
  transfers ownership (not a local leak). Tailor the message to the shape
  (no-handle / package-scope cases can't use the normal fix).
- **Declaration-site walks (global-state-family).** Iterate the declaration's
  direct children; do NOT `walk()` into initializer expressions (a nested
  local declaration is not module/package-level state). Skip blank / discard
  identifiers (`_`).
- **Compound assignments preserve taint** in the dataflow tracker: `x += clean`
  is read-modify-write, so it must OR with x's prior taint, not overwrite it.

## Validation gate (every spec, run all, in order)

```bash
uv run pytest                                  # coverage gate fail_under = 97
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/ --all-files         # zero blocking violations
uv run mkdocs build --strict                   # broken anchors fail the build
```

## Shared deliverable checklist (summary; Part A of the skill is canonical)

Per language: grammar extra in `pyproject.toml` (+ `[all]`), language module,
registry block, per-rule portability audit (tuples + per-language node tables
+ `_<lang>` config defaults + `tests/core/test_engine.py` allow-list buckets),
dataflow tracker for 8xx ports, pre-commit `types_or` in **both**
`.pre-commit-config.yaml` and `.pre-commit-hooks.yaml` (verify the `identify`
tag name for the language), per-rule per-language tests (violation + clean),
`docs/languages/<lang>.md` + mkdocs nav, `rules.md` scope table + **remove
the language from "Planned"**, README / index tables and counts,
`docs/power-of-ten.md` fidelity notes where the language changes a
Holzmann-rule mapping, the **scattered enumerations** (`cli.md` `--all-files`
+ `--language` lists, `SECURITY.md` versions / grammars / extensions,
`toml.md` opt-in-rules walkthrough), the shared
`src/safelint/skill_files/languages/<lang>.md` addendum, the Step-2 registry
row in **all 14 client files**, `src/safelint/skill_files/README.md` counts /
layout,
`CHANGELOG.md` under `[Unreleased]`, and the validation gate.
