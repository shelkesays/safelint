# Contributing to SafeLint

Contributions are welcome - bug fixes, new rules, new AI clients, new languages, documentation improvements, or ideas.

By participating in this project you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). If you use safelint in academic or scientific work, see [CITATION.cff](CITATION.cff) for canonical citation metadata. If you're stuck and not sure whether to file a bug, request a feature, or just ask a question, see [SUPPORT.md](SUPPORT.md) for a guide to the right channel.

---

## Getting started

1. Fork the repository and clone your fork.
2. Install dev dependencies. The project uses [`uv`](https://docs.astral.sh/uv/) for dependency management, most contributors invoke tools through it:
   ```bash
   uv sync --extra dev          # recommended (matches CI)
   # or, if you prefer pip:
   pip install -e ".[dev]"
   ```
3. Create a branch: `git checkout -b your-feature-name`.
4. Make your changes, then run the full check suite, every command must pass before you open a PR:
   ```bash
   uv run pytest                       # all tests pass; coverage stays at ≥97%
   uv run ruff check src/ tests/       # zero lint errors
   uv run ruff format --check src/ tests/   # consistent formatting
   uv run ty check src/                # zero type errors
   uv run safelint check src/          # zero blocking violations (safelint lints itself)
   ```
5. Open a pull request against the `main` branch.

---

## Three contribution paths

Most contributions to safelint fall into one of three categories. Each has its own checklist below; pick the one that matches what you're adding.

| You want to add… | Read this | What you'll touch |
|---|---|---|
| A new **safety rule** (e.g. another Power-of-Ten check) | The "Adding a new rule" checklist below | `src/safelint/rules/`, `core/config.py`, `docs/configuration/rules.md`, every bundled AI-client doc |
| A new **AI-client integration** (e.g. JetBrains AI Assistant, a brand-new IDE) | [Adding an AI client](https://shelkesays.github.io/safelint/contributing/adding-an-ai-client/), full walkthrough with a worked example | `src/safelint/_skill_install.py` (one `ClientSpec` append), `src/safelint/skill_files/<client>/`, `tests/test_skill_install.py`, `docs/ai-clients/`, `src/safelint/skill_files/README.md`, `CHANGELOG.md` |
| A new **language** safelint can lint (e.g. Kotlin, Ruby, Swift) | [Adding a language](https://shelkesays.github.io/safelint/contributing/adding-a-language/), full walkthrough | `src/safelint/languages/<lang>.py`, the Tree-sitter grammar dependency in `pyproject.toml`, per-rule audit, `tests/`, `docs/configuration/`, every bundled AI-client doc |

The architecture for each path is open-ended: rules go into one tuple (`ALL_RULES`), AI clients go into one tuple (`_CLIENT_SPECS`), languages go into one registry (`safelint.languages._REGISTRY`). Drift-detection tests parametrise over those registries automatically, when you add a new rule, the bundled-doc-coverage tests fail until *every* registered AI client mentions the new rule. When you add a new AI client, the parametrised tests fail until *its* bundled doc mentions every existing rule + extension. The architecture pulls you toward consistency rather than relying on memory.

---

## Adding a new rule

Each rule lives in its own class inside `src/safelint/rules/`. Follow this checklist:

- Subclass `BaseRule` and implement `check_file(filepath, tree) -> list[Violation]`. The `tree` argument is a Tree-sitter parse tree, not a Python `ast` tree; see existing rules for traversal patterns (`walk`, `lineno`, `node_text` in `safelint.languages._node_utils`).
- Set a unique `name` (the human-friendly key users put in their config, e.g. `function_length`) and `code` (the short identifier, e.g. `SAFE105`, pick the next free number in the appropriate `SAFE9xx` band).
- *(Default suffices for now)* Each rule inherits `BaseRule.language = ("python",)`. Leave it alone unless your rule applies to a *non-Python* language too; that's only relevant once a second language is registered (see [Adding a language](https://shelkesays.github.io/safelint/contributing/adding-a-language/)). The engine consults this tuple in `_run_rules` and skips rules whose `language` doesn't include the active file's `LanguageDefinition.name`.
- Add the rule's class to `ALL_RULES` in `src/safelint/rules/__init__.py`. The position in this tuple is the execution order, keep cheap structural rules first, expensive dataflow rules last.
- Add default config to `DEFAULTS["rules"]` in `src/safelint/core/config.py`. Set `enabled: false` if your rule is expensive or false-positive-prone (the dataflow rules do this).
- Write tests covering both the violation case *and* the clean case. Coverage must stay at ≥97% (the project's enforced threshold).
- Document the rule in `docs/configuration/rules.md` under the matching category, following the format used by existing rules.
- Update every bundled AI-client artefact under `src/safelint/skill_files/` to mention the new rule code + name. The drift-detection tests (`test_skill_documents_every_active_rule[<client>]`) parametrise over the registry and will fail CI for every client whose docs are missing the new rule.

**Self-imposed constraints:** safelint runs itself in CI, so your new rule's source code must obey the same rules it enforces: `function_length ≤ 60`, `nesting_depth ≤ 2`, `complexity ≤ 10`, etc. If `safelint check src/` fails on the new rule's own implementation, that's a meta-bug; refactor the rule's code until it passes.

---

## Adding a new AI client

Fourteen clients ship today (Claude Code, Cursor, GitHub Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed, Warp, Kiro). Adding the next is one `ClientSpec` append plus a bundled artefact and ~10 regression tests, no control-flow changes elsewhere. The full walkthrough with a worked example lives in [Adding an AI client](https://shelkesays.github.io/safelint/contributing/adding-an-ai-client/). The short version:

- Decide on the bundled artefact shape. Every client installs a single file under `skill_files/<client>/<filename>` (Claude Code is `claude/SKILL.md`, Cursor is `cursor/safelint.mdc`, and so on); the shared `languages/` addendums at the bundle root are looked up on demand via `safelint skill path`.
- Write the bundled file by adapting an existing one (Cursor's `cursor/safelint.mdc` is a clean single-file template). Strip MDC frontmatter if your client doesn't use it.
- Append one `ClientSpec` entry to `_CLIENT_SPECS` in `src/safelint/_skill_install.py`, fields: `name`, `display_name`, `artefact_label`, `cwd_markers`, `home_markers`, `install_relpath`, `bundled_relpath`, `restart_hint`, `usage_hint`, `documentation_relpaths`. If your client also writes to a *cross-agent* shared file (like codex's `AGENTS.md`), set `secondary_install_relpath` and `secondary_install_section_markers`, the install primitives handle the rest.
- Mirror an existing client's test block (10–12 tests covering install / symlink / force / overwrite / auto-detect / CLI routing / path-print / peer-exclusion).
- Update the docs-site AI-client pages under `docs/ai-clients/` (index table, new per-client page, manual-install, mkdocs nav), `src/safelint/skill_files/README.md`, and `CHANGELOG.md`.

The security guards (symlink refusal at the secondary destination, `skill remove --path PATH` install-shape validation, etc.) live in `_skill_install.py` and apply to your client automatically, no per-client implementation needed.

---

## Adding a new language

Nine languages are registered today (Python, JavaScript, TypeScript, Java, Rust, Go, PHP, C, C++). Adding a new one (Kotlin, etc.) needs three things: a Tree-sitter grammar package for the language, a per-language module exposing node-type constants, and a per-rule audit to identify which rules port cleanly. The full walkthrough with a worked TypeScript example lives in [Adding a language](https://shelkesays.github.io/safelint/contributing/adding-a-language/) - note its "scattered enumerations" step (the docs that list every language's extension / grammar / `--language` value outside the headline tables), which is the easiest part to miss.

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
