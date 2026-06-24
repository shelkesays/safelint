# Language-expansion plan: PHP, C, C++

**Audience**: the AI coding agent (or human contributor) implementing the next
language. Each language has its own self-contained spec in this directory.
Implement **one language per spec, in working-priority order**. **PHP is next**
(it has no dependencies and ports the largest share of the existing rule set);
C and C++ follow. The one hard ordering rule is that **C must ship before C++**
(shared grammar family, shared new rules, `.h` ownership) - PHP is independent
of both. This order matches the project's published roadmap in
`docs/configuration/rules.md` "Planned":

> **Go (`.go`) shipped in v2.5.0** (6th registered language: 16 cross-language
> rules + the Go-only SAFE209 `empty_error_check` / SAFE211
> `panic_calls_outside_tests`). Its spec, `plan/01-go.md`, was removed on
> completion - the design decisions now live in the
> [Go language page](../docs/languages/go.md), the
> `src/safelint/skill_files/languages/go.md` addendum, and the shipped code.

Rows are in working-priority order; the **Spec #** column is the stable file
number, not the priority rank.

| Priority | Spec # | File | Language | Status | Depends on |
|---|---|---|---|---|---|
| 1 | 4 | `plan/04-php.md` | PHP (`.php`) | **in review (PR #75)** | nothing |
| 2 | 2 | `plan/02-c.md` | C (`.c`, `.h`) | not started | nothing |
| 3 | 3 | `plan/03-cpp.md` | C++ (`.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`) | not started | **C shipped** (shared grammar family, shared new rules, `.h` ownership) |

Update the Status column (and the per-spec status header) as work lands; remove
a spec file once its language ships (as was done for Go).

## Deferred cross-language refactors (run AFTER the languages above)

These are not language additions; they are codebase-wide sweeps best done once
the language set is stable, so they don't have to be redone per language.

| File | What | Run when |
|---|---|---|
| `plan/refactor-node-type-constants.md` | Convert the per-language node-type / operator tables in `src/safelint/rules/` from raw Tree-sitter string literals to imported `src/safelint/languages/<lang>.py` constants, for **all** languages at once (pure refactor, no behaviour change). Deferred out of the PHP PR because it is cross-language, not PHP-specific. | After C **and** C++ ship. |

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
