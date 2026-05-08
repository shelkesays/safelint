# Contributing to SafeLint

Contributions are welcome - bug fixes, new rules, documentation improvements, or ideas.

---

## Getting started

1. Fork the repository and clone your fork.
2. Install dev dependencies. The project uses [`uv`](https://docs.astral.sh/uv/) for dependency management — most contributors invoke tools through it:
   ```bash
   uv sync --extra dev          # recommended (matches CI)
   # or, if you prefer pip:
   pip install -e ".[dev]"
   ```
3. Create a branch: `git checkout -b your-feature-name`.
4. Make your changes, then run the full check suite — every command must pass before you open a PR:
   ```bash
   uv run pytest                       # all tests pass; coverage stays at ≥97%
   uv run ruff check src/ tests/       # zero lint errors
   uv run ruff format --check src/ tests/   # consistent formatting
   uv run ty check src/                # zero type errors
   uv run safelint check src/          # zero blocking violations (safelint lints itself)
   ```
5. Open a pull request against the `main` branch.

---

## Adding a new rule

Each rule lives in its own class inside `src/safelint/rules/`. Follow this checklist:

- Subclass `BaseRule` and implement `check_file(filepath, tree) -> list[Violation]`. The `tree` argument is a Tree-sitter parse tree, not a Python `ast` tree — see existing rules for traversal patterns (`walk`, `lineno`, `node_text` in `safelint.languages._node_utils`).
- Set a unique `name` (the human-friendly key users put in their config, e.g. `function_length`) and `code` (the short identifier, e.g. `SAFE105` — pick the next free number in the appropriate `SAFE9xx` band).
- Add the rule's class to `ALL_RULES` in `src/safelint/rules/__init__.py`. The position in this tuple is the execution order — keep cheap structural rules first, expensive dataflow rules last.
- Add default config to `DEFAULTS["rules"]` in `src/safelint/core/config.py`. Set `enabled: false` if your rule is expensive or false-positive-prone (the dataflow rules do this).
- Write tests covering both the violation case *and* the clean case. Coverage must stay at ≥97% (the project's enforced threshold).
- Document the rule in `CONFIGURATION.md` under the matching category, following the format used by existing rules.
- Update every bundled AI-client artefact under `src/safelint/skill_files/` to mention the new rule code + name. The drift-detection tests (`test_skill_documents_every_active_rule[<client>]`) parametrise over the registry and will fail CI for every client whose docs are missing the new rule.

**Self-imposed constraints:** safelint runs itself in CI, so your new rule's source code must obey the same rules it enforces — `function_length ≤ 60`, `nesting_depth ≤ 2`, `complexity ≤ 10`, etc. If `safelint check src/` fails on the new rule's own implementation, that's a meta-bug; refactor the rule's code until it passes.

---

## Ground rules

- **SafeLint must pass itself.** Zero blocking violations on `src/` at all times. Run `safelint check src/` before opening a PR.
- **Tests are not optional.** Every rule needs at least one test for the violation case and one for the clean case.
- **No breaking changes to rule names or codes.** Downstream users pin to these in config files and CI scripts. If a rule needs to change, add a new one and deprecate the old.
- **Keep rules focused.** One rule, one concern. If you find yourself adding multiple `if` branches for different failure modes, it is probably two rules.
- **Defaults must be safe.** New rules should default to `enabled: false` if they have a high false-positive rate or are expensive to run. Let users opt in.

---

## Reporting issues

Open an issue at [github.com/shelkesays/safelint/issues](https://github.com/shelkesays/safelint/issues) with:

- The SafeLint version (`pip show safelint`)
- The rule code that fired (e.g. `SAFE101`)
- A minimal code example that reproduces the problem
- Whether it is a false positive or a missed violation
