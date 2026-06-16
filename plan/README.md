# Language-expansion plan: Go, C, C++, PHP

**Audience**: the AI coding agent (or human contributor) implementing the next
language. Each language has its own self-contained spec in this directory.
Implement **one language per spec, in this exact sequence** (it matches the
project's published roadmap in `docs/configuration/rules.md` "Planned", and
C++ has a hard dependency on C):

| # | Spec | Language | Status | Depends on |
|---|---|---|---|---|
| 1 | `plan/01-go.md` | Go (`.go`) | **shipped** (Unreleased; 18 cross-language rules + SAFE209 / SAFE211) | nothing |
| 2 | `plan/02-c.md` | C (`.c`, `.h`) | not started | nothing (Go recommended first, roadmap order) |
| 3 | `plan/03-cpp.md` | C++ (`.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`) | not started | **C shipped** (shared grammar family, shared new rules, `.h` ownership) |
| 4 | `plan/04-php.md` | PHP (`.php`) | not started | nothing |

Update the Status column (and the per-spec status header) as work lands.

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
   not split a language across releases, and do not bump the version
   (releases are the owner's call).

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
- **Verify Tree-sitter node types by probing, never from memory.** The specs
  name expected node types; confirm each with a quick probe before relying
  on it:

  ```bash
  uv run python - <<'PY'
  import tree_sitter, tree_sitter_go  # adjust per language
  lang = tree_sitter.Language(tree_sitter_go.language())
  tree = tree_sitter.Parser(lang).parse(b"func main() { go run() }")
  # Iterative on purpose - the same worklist shape production code must use
  # (safelint's own no_recursion rule polices the codebase).
  stack = [(tree.root_node, 0)]
  while len(stack) > 0:
      node, depth = stack.pop()
      print("  " * depth + node.type)
      stack.extend((c, depth + 1) for c in reversed(node.named_children))
  PY
  ```

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
Holzmann-rule mapping, the shared `skill_files/languages/<lang>.md` addendum,
the Step-2 registry row in **all 14 client files**, `skill_files/README.md`
counts / layout, `CHANGELOG.md` under `[Unreleased]`, and the validation
gate.
