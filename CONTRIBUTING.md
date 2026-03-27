# Contributing to SafeLint

Contributions are welcome - bug fixes, new rules, documentation improvements, or ideas.

---

## Getting started

1. Fork the repository and clone your fork
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Create a branch: `git checkout -b your-feature-name`
4. Make your changes, then run the full check suite:
   ```bash
   pytest                  # all tests must pass
   safelint check src/     # zero blocking violations
   ruff check src/         # zero lint errors
   ```
5. Open a pull request against the `main` branch

---

## Adding a new rule

Each rule lives in its own class inside `src/safelint/rules/`. Follow this checklist:

- Subclass `BaseRule` and implement `check_file(filepath, tree) -> list[Violation]`
- Set a unique `name` (used in config files) and `code` (e.g. `SAFE9xx`)
- Keep nesting depth ≤ 2 and cyclomatic complexity ≤ 10 - safelint checks itself
- Add the rule to `ALL_RULES` in `src/safelint/rules/__init__.py`
- Add default config to `DEFAULTS["rules"]` in `src/safelint/core/config.py`
- Write tests - aim to keep overall coverage above 80%
- Document the rule in `CONFIGURATION.md` following the existing format

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
