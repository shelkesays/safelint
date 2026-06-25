# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

SafeLint is a static analysis tool that enforces Holzmann "Power of Ten" safety rules adapted for Python, JavaScript, TypeScript (including TSX / AssemblyScript), Java (with a Spring Boot framework preset), Rust, and Go. It uses Tree-sitter (not Python's `ast` module) for parsing; this matters for any rule work because rules walk Tree-sitter trees, not AST nodes. The tool ships as both a CLI (`safelint`) and a pre-commit hook, and lints itself in CI.

## Common commands

This project uses `uv` for dependency management. Most contributors invoke tools through it.

```bash
# Install with dev extras (pre-commit, pytest, ruff, ty)
uv sync --extra dev
# or: pip install -e ".[dev]"

# Tests (uses --cov=src by default per pyproject; coverage gate is fail_under=97)
uv run pytest

# Run a single test file / test
uv run pytest tests/core/test_engine.py
uv run pytest tests/core/test_engine.py::test_name -v

# Lint + format check (CI runs both against src/ and tests/)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type check (ty replaces mypy here: config is [tool.ty] in pyproject.toml)
uv run ty check src/

# Run safelint on itself: must produce zero blocking violations before merging
# (--all-files matches CI; without it the check defaults to git-modified files only)
uv run safelint check src/ --all-files
```

The CLI has two entry points:
- `safelint check <path>`: direct invocation; defaults to git-modified files unless `--all-files` is passed
- `safelint <file1.py> <file2.py> ...`: pre-commit style, lints exact files

`--fail-on=error|warning` overrides the per-rule severity threshold; `--mode=local|ci` sets a default (`local` → fail-on=error, `ci` → fail-on=warning).

## Architecture

The codebase is structured as a pipeline: **config load → parse to Tree-sitter tree → run rules → apply suppressions → partition by severity**.

### Layers

- **`core/`**: orchestration. `config.py` loads TOML config in this order (highest first): standalone `safelint.toml` (top-level keys, no wrapper) → `[tool.safelint]` in `pyproject.toml` → built-in defaults. The loader walks parent directories, so any one of those files at or above the target works. `engine.py` (`SafetyEngine`) builds the active rule list from config, parses files, runs rules, and applies inline (`# nosafe`) and per-file suppressions. `runner.py` is the convenience wrapper used by the CLI and library callers.
- **`languages/`**: language abstraction. Each supported language is a `LanguageDefinition` dataclass (file extensions, comment node type, comment prefix, parser factory) registered in `languages/__init__.py`. Six languages are registered: Python (`.py`, `.pyw`), JavaScript (`.js`, `.mjs`, `.cjs`), TypeScript (`.ts`, `.tsx`, `.as` via two grammars), Java (`.java`), Rust (`.rs`), and Go (`.go`); every grammar ships as an opt-in extra and unregistered-but-known extensions surface a `pip install 'safelint[<lang>]'` hint. Each language module exports node-type string constants (e.g. `FUNCTION_DEF`, `CALL`, per-language `FUNCTION_TYPES` aggregates); **rules should import these constants instead of hardcoding magic strings**. `_node_utils.py` provides shared tree-walking helpers (`walk`, `lineno`, `end_lineno`, `node_text`, `call_name`). The package also exposes a public `supported_extensions() -> frozenset[str]` for callers (currently the engine's file-discovery loop); prefer that over reaching into the private `_REGISTRY`.
- **`rules/`**: one rule per file. Each rule subclasses `BaseRule` and implements `check_file(filepath, tree) -> list[Violation]`. Rules are registered in `ALL_RULES` in `rules/__init__.py`; the order there is the canonical execution order (cheap structural rules first, expensive dataflow rules last). Each rule has a unique `name` (used in config) and `code` (e.g. `SAFE101`).
- **`analysis/`**: shared analyses used by multiple rules. Five intra-procedural taint trackers, one per language family: `dataflow.py` (Python `TaintTracker`), `dataflow_javascript.py`, `dataflow_java.py`, `dataflow_rust.py`, `dataflow_go.py`, consumed by the dataflow rules (`tainted_sink`, `return_value_ignored`, `null_dereference`; Go skips `null_dereference`). All tree-walking in them is iterative (worklists), never recursive - SAFE105 `no_recursion` polices safelint's own source.
- **`cli.py`**: argparse front-end plus ruff/ty-style coloured violation rendering.

### Suppression model

Four layers, narrowest to widest. They compose: a violation is suppressed if *any* layer matches.

1. **Inline `# nosafe` comments**: line-scope. Parsed by querying comment nodes in the Tree-sitter tree (so directives inside string literals are correctly ignored). Forms: `# nosafe` (all rules on this line), `# nosafe: SAFE501`, `# nosafe: unbounded_loops`, `# nosafe: SAFE101, SAFE103`.
2. **In-file `# safelint: ignore` directives**: file-scope. Must be a comment alone on its line (trailing-comment placements are skipped to avoid accidental scope creep). Forms: `# safelint: ignore` (all rules in this file), `# safelint: ignore: SAFE101`, `# safelint: ignore: SAFE101, function_length`. Production parsing goes through `engine._parse_directives`, a single tree walk that produces both line-level `# nosafe` and file-level `# safelint: ignore` results in one O(N) pass; `_parse_file_level_ignores` and `_parse_suppressions` are kept as thin wrappers for narrow unit testing. The file-level result is merged into the per-file ignored sets via `_merge_in_file_directives` before rules run. Bare directives are represented as the `"*"` wildcard in the `ignored_codes` frozenset; `_is_per_file_ignored` short-circuits on that. The same `"*"` wildcard works in toml `per_file_ignores` (e.g. `"vendor/**" = ["*"]` skips every rule for the path); `_parse_per_file_ignores` exempts `"*"` from the unknown-entry typo guard so the documented usage doesn't surface a spurious warning.
3. **Per-file ignores**: glob-scope. `[tool.safelint.per_file_ignores]` with glob patterns (e.g. `"tests/**" = ["SAFE101"]`). The same `"*"` wildcard the file-level directive uses also works here as a blanket "ignore everything for this path".
4. **Global `ignore`**: project-scope. List of rule codes/names suppressed project-wide.

Unknown entries in any layer are surfaced as `safelint: warning:` lines on **stderr** (typo guard) but don't fail the run. Suppressed violations are tracked as `LintResult.suppressed: list[Violation]` (not just a count) so the CLI can surface a per-code breakdown, e.g. `(2 SAFE501, 1 SAFE304 suppressed)`, keeping suppressions auditable regardless of which layer suppressed them. Library callers should use `len(result.suppressed)` for the count.

### Diagnostics channel (no Python `logging`)

The codebase deliberately does **not** use Python's `logging` module. CLI tools that ship through `lastResort` get ugly, format-inconsistent stderr noise and offer no real value over a focused diagnostic helper. Instead:

- `core/_diagnostics.py` exposes `print_warning(msg)` and `print_error(msg)`. Both write a single line to stderr in the form `safelint: warning: <msg>` / `safelint: error: <msg>`.
- Use it for things the user needs to see but that aren't lint violations: config typos, malformed TOML, etc.
- It's a private helper (`_diagnostics`), not part of the public library API.
- The function names contain `print_` so `SAFE304 (side_effects)` exempts them naturally. `SAFE203 (logging_on_error)` only recognises stdlib `logging` method names, so a small number of `# nosafe: SAFE203` annotations sit on `except` blocks that call `_diagnostics.print_*` (the rule's heuristic can't see them as logging). Search for `# nosafe: SAFE203` to find them all; those are intentional, not bugs.

### Per-function rules and `walk(skip_types=...)`

Many rules compute a per-function metric (cyclomatic complexity, nesting depth, asserts present, breaks present, globals declared, taint flow). The pattern is:

1. Outer loop: `for node in walk(tree.root_node)` finds every `FUNCTION_DEF` / `ASYNC_FUNCTION_DEF` in the file, including nested ones.
2. Inner traversal: for each function found, the rule walks its subtree to compute the metric.

The inner traversal **must not descend into nested function definitions**, or it would attribute their content to the enclosing function (e.g., a 12-branch helper inside an otherwise-flat outer function would mark the outer function as too complex). Pass `skip_types=(FUNCTION_DEF, ASYNC_FUNCTION_DEF)` to `walk()` for the inner pass, that's how `complexity`, `documentation`, `state_purity`, the dataflow `TaintTracker`, and the `_first_io_call` helper in `side_effects` all do it. `nesting_depth` keeps a custom traversal because it tracks depth alongside each node, but applies the same skip rule manually. `loop_safety`'s break detection skips at a wider boundary set, `(FOR_STATEMENT, WHILE_STATEMENT, FUNCTION_DEF, ASYNC_FUNCTION_DEF)`, because a `break` inside a nested loop or function exits *that* construct, not the outer `while True` being checked.

### CLI output conventions

The CLI deliberately mirrors `ruff` / `ty` formatting (`_print_violations` and `_make_summary` in `cli.py`). Worth preserving when touching output:

- Violation block: `CODE message [rule]` then `--> path:lineno` then a 3-line source gutter, one blank line between violations.
- Clean run: `All checks passed.` in **bold green**.
- Clean run with suppressions: `All checks passed. (2 SAFE501, 1 SAFE304 suppressed)`.
- Run with violations: `Found N errors, M warnings. [--fail-on=...]` followed by either `No suggestions available (safelint does not auto-fix; see --format json for any advisory edits).` (when no rule emitted suggestions) or `N advisory suggestion(s) available, view via --format json (safelint does not auto-apply fixes).` (when any did). Plus the suppression breakdown when there are suppressions. The line is **only** printed when there are active violations, it's omitted on clean runs because there's nothing to suggest. The wording deliberately distinguishes "no auto-fix" (a permanent design choice, safelint will never ship `--fix`) from "no suggestions available" (a per-run state).
- ANSI colour is auto-disabled when stdout isn't a TTY (`_c` helper).

### Severity model

Each rule has a per-rule `severity` (`error` | `warning`). `SafetyEngine.partition_violations` splits violations by `--fail-on` threshold into blocking vs advisory. `mode = "local"` defaults `fail_on` to `error` (lenient); `mode = "ci"` defaults to `warning` (strict). Precedence: CLI flag > config > mode default.

### Adding a new rule

1. Create `src/safelint/rules/<name>.py` subclassing `BaseRule` (Rust-only rules go in `rules/rust_rules.py`). Set unique `name` and `code`. **Numbering policy**: slot by *category* into the existing 1xx-8xx bands (1xx function shape, 2xx error handling, 3xx state/side effects, 4xx resources, 5xx loops, 6xx documentation/annotations, 7xx tests, 8xx dataflow); `9xx` is reserved for framework-specific rules only (Spring today). Never open a new band per language. Set the `language` tuple; the matching `_RULES_*` allow-list bucket in `tests/core/test_engine.py` must be updated to match it exactly.
2. Register the class in `ALL_RULES` in `rules/__init__.py` (position = execution order, cheap structural first) and in `__all__`; add the rule name to `execution.order` in `DEFAULTS` (cross-language rules only; Rust-only rules are not listed there).
3. Add defaults to `DEFAULTS["rules"]` in `core/config.py`, including any per-language `_<lang>`-suffixed config lists. Default `enabled: false` if the rule is expensive or false-positive-prone (the dataflow and Rust-idiom rules do this).
4. Tests must cover both the violation case and the clean case, per language in the tuple (`tests/rules/test_<rule>_<lang>.py` pattern).
5. Document the rule in `docs/configuration/rules.md` (anchor format `#safeNNN-rule_name`), with **config examples in both forms**: `[tool.safelint.rules.<name>]` for pyproject.toml and `[rules.<name>]` for standalone safelint.toml. Update the applicable `docs/languages/<lang>.md` rules tables (and the "not registered" lists on the other language pages with a rationale).
6. Update **all 14 bundled client skill files** plus the applicable `skill_files/languages/*.md` crib sheets - `tests/test_skill_install.py::test_skill_documents_every_active_rule` fails for every client whose docs miss the new code or name, so land these in the same commit as the registry change.
7. Add a `CHANGELOG.md` entry under `[Unreleased]`. New rules / languages are MINOR, never MAJOR. **The version bump is a mandatory, easily-missed step of finishing the work - do not skip it** (it has been missed twice). Apply it as part of the release flow below; the *number* is derived by convention (additive = next `X.Y.0`), the owner controls release timing and tagging. The static version (no `setuptools_scm`; `publish.yml` refuses to release unless the pushed `vX.Y.Z` tag exactly matches `project.version`) is what makes the bump a deliberate committed edit. See "Release workflow" below for where the RC vs production bump lands. Keep the `CHANGELOG.md` heading as `## [Unreleased]`; it flips to `## [X.Y.Z] - <date>` only at the production tag.

**Critical constraint**: SafeLint must pass itself. `safelint check src/ --all-files` must report zero blocking violations before any merge (the `--all-files` flag matches CI; a bare `safelint check src/` only scans git-modified files and can read clean falsely). This means new rule code must obey its own rules - `no_recursion` (use iterative worklists), `function_length=60`, `nesting_depth=2`, `complexity=10`, etc. The only sanctioned inline suppressions in safelint's source are the documented `# nosafe: SAFE203` logging exemptions; prefer rewriting over annotating (the project's rule-10 stance).

### Adding a new language or framework/runtime preset

Invoke the **`add-language-support`** project skill (`.claude/skills/add-language-support/SKILL.md`) before writing any code - it is the complete development checklist (grammar extra, language module, registry, per-rule portability audit, allow-list buckets, dataflow tracker, pre-commit `types_or`, tests, the full docs fan-out including counts and both-form config examples, the 14 client skill files and shared addendum, drift tests, CHANGELOG). The tracked human walkthrough is `docs/contributing/adding-a-language.md`. Note the documentation work is NOT just the language tables: the skill's A7/A9 call out the *scattered enumerations* that are the most common miss (the v2.5.0 Go addition missed all of them) - the `--all-files` extension list and `--language` value list in `docs/configuration/cli.md`, the supported-versions table + bundled-grammar list + file-types-read list in `SECURITY.md`, and the opt-in-rules walkthrough in `docs/configuration/toml.md`. Run the enumeration sweep (grep the prior language's extension / name (whole-word, `grep -w`, so short names like `go` / `c` don't over-match) / `tree-sitter-<lang>` across `docs/`, `README.md`, `SECURITY.md`, `src/safelint/skill_files/`) as a final step. Framework/runtime presets (the `[tool.safelint.javascript] runtime` / `[tool.safelint.java] framework` pattern) have their own checklist in Part B of the skill: preset dicts merge into the DEFAULTS copy *before* user TOML so explicit user keys win, unknown preset names warn and fall back (never raise), and framework-specific structural rules go in the 9xx band.

### Other invariants

- Don't rename or repurpose existing rule names or codes, downstream users pin to them in config and CI. Add a new rule and deprecate the old one if behaviour must change.
- Tree-sitter parses unfamiliar Python syntax leniently; `tree.root_node.has_error` triggers a `SAFE000` parse-error violation rather than a crash. The violation now carries a real lineno and a kind hint (e.g. `Parse error (missing ':') at line 12, column 14`), `SafetyEngine._first_parse_error` walks the tree (including anonymous tokens, since missing-token errors live on those) to find the earliest issue.
- The `TestCouplingRule` is the one rule that needs CLI/runner context (the list of changed files); it's threaded through via `SafetyEngine(config, changed_files=...)`.

## Pre-commit and CI

`.pre-commit-config.yaml` runs (in order): general file hygiene → ruff (lint + format) → safelint itself → ty (type check via local hook) → pytest with coverage (local hook). Most hooks scope to `^src/`; a few file-hygiene hooks (e.g. `mixed-line-ending`, `fix-byte-order-marker`) deliberately run repo-wide, and `name-tests-test` scopes to `tests/`.

GitHub Actions (`ci.yml`) runs the same lint/format/type checks on a single Python version, then the pytest suite across Python 3.11 / 3.12 / 3.13 / 3.14. Tag pushes (`vX.Y.Z`) trigger `publish.yml`, which uses PyPI Trusted Publishing (OIDC), no token-based publishing.

Release mechanics: the package version is **static** in `pyproject.toml` (no `setuptools_scm` / dynamic version). `publish.yml`'s first step verifies the pushed `vX.Y.Z` tag equals `project.version` and fails the release on a mismatch, so `project.version` must already hold the release number before tagging - nothing bumps it automatically. `publish.yml` matches PEP 440 pre-release tags too (full forms: `v2.6.0rc1`, `v2.6.0a1`, `v2.6.0b2`, `v2.6.0.dev1` - the suffix always follows the base version), so RC tags publish as pre-releases.

**Release workflow (branch flow - do not skip the version bump).** Development happens on a `feature/*` branch, which **PRs into the `development` release branch, NOT directly into `main`**. The version bump is part of this flow and is the step most often missed - it has been missed twice, so treat it as mandatory:

1. `feature/* → PR → development`: this PR **includes** the version bump to the next **RC**, `project.version = "X.Y.0rcN"` (e.g. `2.6.0rc1`); iterate `rcN` (`rc2`, ...) on further RC rounds. CHANGELOG entries go under `## [Unreleased]`; the heading is NOT dated yet. Tagging an RC (`vX.Y.0rcN`) publishes a pre-release.
2. Once everything is validated and merged to `development`: `development → PR → main` flips `project.version` to the **production** `"X.Y.0"`.
3. At the production tag: rename `## [Unreleased]` → `## [X.Y.Z] - <date>`, then `git tag vX.Y.Z && git push origin vX.Y.Z`.

The *number* is derived by convention (additive work = next `X.Y.0`; never MAJOR); the owner controls release timing and tagging. (Exception on record: PHP / v2.6.0 was merged straight to `main`, so its production bump was applied directly on `main` - the `development → RC → main` flow resumes from the C language addition onward.)
