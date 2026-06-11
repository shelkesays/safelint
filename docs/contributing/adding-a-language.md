# Adding a new language to SafeLint

This guide is the cheat sheet for adding support for a new programming language (TypeScript, Go, Rust, etc.) to SafeLint. The architecture was prepared with multi-language in mind; the moving parts you need to understand and the steps you need to follow are below.

!!! note

    Today Python, JavaScript, and TypeScript (including TSX and AssemblyScript) are all registered. The supporting structure (parser hookup, file-discovery loop, suppression parser, optional-grammar extras) is fully language-agnostic. To add a new language you need three pieces: (a) a Tree-sitter grammar package for that language, (b) a per-language module that exports the grammar's node-type names as constants and gates the grammar import behind the matching `[project.optional-dependencies]` extra (see Step 1 + Step 6b), and (c) a rule-by-rule audit to identify which existing rules port cleanly and which are Python-specific.

!!! warning "Bundled AI-client skills also need an update"

    Adding a new language also requires updating the bundled AI-client skills (`claude/SKILL.md`, `cursor/safelint.mdc`, and every other per-client file under `skill_files/<client>/`) to list the new language and its file extensions in their **Step 2** registry tables. The drift-detection test `test_skill_documents_every_supported_extension` fails the moment a new extension lands in `supported_extensions()` without the corresponding bundled-doc update, and the test is parametrised over every registered AI client, so you only need to make the additions once per skill file.

## The architecture, in six sentences

1. `safelint.languages.LanguageDefinition` is a frozen dataclass holding everything the engine needs about a language: file extensions, parser factory, comment node type, comment prefix.
2. Adding a language = creating one new module under `src/safelint/languages/` (e.g. `typescript.py`), instantiating a `LanguageDefinition`, and registering it in `languages/__init__.py`.
3. The engine's parse-and-walk loop is language-agnostic, it reads `lang.create_parser()`, queries `lang.comment_node_type` for both `# nosafe` and `# safelint: ignore` directives, and dispatches the configured rules against the resulting Tree-sitter tree. *Dispatch is per-language*: in `_run_rules` the engine checks `lang.name in rule.language` before invoking `check_file` and skips any rule whose `BaseRule.language` tuple doesn't include the active language.
4. **Per-language rule dispatch is built into the engine.** Each `BaseRule` subclass declares a `language: tuple[str, ...]` class attribute (default `("python",)`); the engine in `_run_rules` checks `lang.name in rule.language` before calling `check_file` and skips the rule otherwise. So rules referencing Python-only constructs (`global`, `assert`, bare `except:`, etc.) keep the default and are auto-exempt from new languages, no code change needed. Rules that *should* port widen the tuple per-rule (`language = ("python", "typescript")`) and adapt their node-type lookups; see Step 5 of the walkthrough for the two patterns (per-language rule classes vs. runtime dispatch).
5. **Rules** import per-language node-type constants directly today (e.g. `from safelint.languages.python import FUNCTION_DEF`). Most existing rules import Python's constants because Python is the only registered language. Per-rule porting is what each new language triggers; the engine plumbing for it is already in place.
6. Suppressions are parsed via `_parse_directives` (a single tree walk producing both line-level `# nosafe` and file-level `# safelint: ignore` results) which uses `lang.comment_node_type` and `lang.comment_prefix` from the `LanguageDefinition`, so directives work automatically wherever you point them. **The literal token form** (`# nosafe`, `// nosafe`, etc.) follows from `comment_prefix`.

## Step-by-step: adding TypeScript as an example

### 1. Add the Tree-sitter grammar as an opt-in extra

v2.0.0+ ships every language grammar as a PEP 621 optional extra so projects only install what they need. Grammars go under `[project.optional-dependencies]` in `pyproject.toml`, **not** under top-level `dependencies` (which keeps only `tree-sitter` itself, the engine that loads grammars at runtime). See Step 6b for the full wiring; the minimal pyproject delta is:

```toml
[project]
dependencies = [
    "tree-sitter>=0.23.0",        # core engine; required for every install
]

[project.optional-dependencies]
typescript = [                    # ← new extra named after the language
    "tree-sitter-typescript>=0.23.0",
]
all = [                           # append the new grammar to ``[all]`` too
    "tree-sitter-python>=0.23.0",
    "tree-sitter-javascript>=0.23.0",
    "tree-sitter-typescript>=0.23.0",   # ← keep in sync with the per-language extra above
]
```

Run `uv sync --extra dev` to pull the new grammar into the dev environment (the `dev` extra self-references `[all]`).

### 2. Create the language module

`src/safelint/languages/typescript.py`:

```python
"""TypeScript language definition for safelint."""

from __future__ import annotations

import tree_sitter
import tree_sitter_typescript

from safelint.languages._types import LanguageDefinition


_TS_LANGUAGE = tree_sitter.Language(tree_sitter_typescript.language_typescript())


def _create_typescript_parser() -> tree_sitter.Parser:
    return tree_sitter.Parser(_TS_LANGUAGE)


TYPESCRIPT: LanguageDefinition = LanguageDefinition(
    name="typescript",
    file_extensions=frozenset({".ts", ".tsx"}),
    comment_node_type="comment",        # tree-sitter-typescript also calls them "comment"
    comment_prefix="//",                # for line-comment-style nosafe directives
    create_parser=_create_typescript_parser,
)


# Per-language node type constants: one per rule concept that maps to TS.
FUNCTION_DEF = "function_declaration"   # vs Python's "function_definition"
ARROW_FUNCTION = "arrow_function"
METHOD_DEF = "method_definition"
# … fill in whatever the rules will need
```

### 3. Register in `languages/__init__.py`

```python
from safelint.languages.python import PYTHON
from safelint.languages.typescript import TYPESCRIPT


_REGISTRY: dict[str, LanguageDefinition] = {}

for _lang in [PYTHON, TYPESCRIPT]:        # ← add TYPESCRIPT
    for _ext in _lang.file_extensions:
        _REGISTRY[_ext] = _lang
```

That's enough for safelint to **discover and parse** TypeScript files. None of the existing rules will fire on them yet, see step 5.

### 4. Watch out for: block-comment `nosafe` directives

The current `_parse_directives` in `core/engine.py` walks `comment` nodes from the Tree-sitter tree and treats each as a single line-style directive. For languages with `/* … */` block comments (TypeScript, Go, Rust, C, …), a multi-line `nosafe` block comment **may need extra handling**, the directive should still apply to the line containing the closing `*/` (or whatever line carries the violation).

If the grammar emits block comments as the same `comment` node type and the parser's `start_point[0]` aligns with the violation's line, you're fine. Otherwise, the safest path is to add per-language helpers for "extract suppression line ranges from a comment node" rather than the current single-line assumption. A future refactor, flag and handle when you hit it.

### 5. Audit each rule for language portability

Most safelint rules read like Python concepts but the underlying ideas generalise. Audit each rule and decide: **port**, **port-with-rename**, or **Python-only** (skip for this language).

Rule-by-rule guide:

| Rule | Concept | Likely portable to TS? |
|---|---|---|
| `function_length` (SAFE101) | function body line count | yes, same idea, just `function_declaration` / `arrow_function` / `method_definition` instead of `function_definition` |
| `nesting_depth` (SAFE102) | depth of if/for/while/with/try | yes, TS has same control-flow constructs (`if_statement`, `for_statement`, etc.) |
| `max_arguments` (SAFE103) | parameter count | yes, TS has `formal_parameters` instead of `parameters`; rest-spread / default-value forms differ |
| `complexity` (SAFE104) | McCabe cyclomatic complexity | yes, same set of branch nodes (modulo TS-specific like `switch_statement`) |
| `bare_except` (SAFE201) | bare `except:` | yes, but this is Python-specific syntax. TS equivalent: `catch` without `Error` filter, different shape |
| `empty_except` (SAFE202) | empty except body | port: `catch (e) {}` is the TS equivalent |
| `logging_on_error` (SAFE203) | error swallow without log | port: same idea, but log-call detection needs TS console / library names |
| `global_state` / `global_mutation` (SAFE301/302) | use of `global` keyword | **Python-only**, TS doesn't have this construct |
| `side_effects_hidden` / `side_effects` (SAFE303/304) | pure-named function doing I/O | port: same idea, just rename the I/O primitive list (`fs.readFile`, `console.log`) |
| `resource_lifecycle` (SAFE401) | resource opened outside `with` | port: TS equivalent is `using` (TC39 stage 4 / TS 5.2+) or manual `try/finally close()` |
| `unbounded_loops` (SAFE501) | `while True` without break | port: `while (true)` matches the same shape |
| `missing_assertions` (SAFE601) | function lacks assertions | port: TS doesn't have `assert` keyword but has `console.assert` and test-framework assertions |
| `test_existence` / `test_coupling` (SAFE701/702) | source change without test change | port: just different test-file naming convention |
| `tainted_sink`, `return_value_ignored`, `null_dereference` (SAFE801–803) | dataflow rules | port: requires non-trivial work, `analysis/dataflow.py` walks Python-specific node types and would need a TS counterpart |

For each rule that ports, the work is:

1. Identify the matching node types in the new grammar. The parser-dump trick is the fastest way to find them, feed a small snippet to the new grammar and inspect the resulting tree:
   ```python
   import tree_sitter_typescript
   from tree_sitter import Parser, Language
   p = Parser(Language(tree_sitter_typescript.language_typescript()))
   print(p.parse(b"function foo() {}").root_node)
   ```
   Output (truncated for clarity):

   ```text
   (program (function_declaration name: (identifier) parameters: (formal_parameters) body: (statement_block)))
   ```
   The node type for "function" in this grammar is `function_declaration` (Python's grammar calls it `function_definition`). Use that string in step 2.
2. Add per-language constants in the language module (e.g. `typescript.FUNCTION_DEF = "function_declaration"`). One constant per node type the rules need.
3. Decide whether the rule **ports** to the new language and update its `language` tuple accordingly:
   - The engine consults `BaseRule.language` (a class attribute, defaults to `("python",)`) before calling `check_file`. Rules whose tuple doesn't include the file's language name are skipped entirely. So genuinely Python-only-syntax rules (e.g. `bare_except`, bare `except:` doesn't exist in JS/TS; `global_state`, Python's `global` statement is Python-specific) keep `("python",)` and are *automatically* exempt from the new language, no per-rule code change needed. (Note: `empty_except` *does* port, every try/catch language can have an empty catch body, see the rule table above.)
   - For rules that *should* port, widen the tuple: `language = ("python", "typescript")`. The rule's `check_file` then needs to handle both, pick one of the two patterns below.

   **Pattern A, per-language rule classes** (cleanest separation): split the rule into `FunctionLengthRulePython` and `FunctionLengthRuleTypeScript`, each importing constants from its own language module. Same logic, different node-type imports. Doubles class count but keeps each rule's assumptions explicit at the import site.

   **Pattern B, runtime dispatch within `check_file`**: single class, look up the right node-type constants based on `tree.language` (or pass `lang_name` through). Less code; more cross-language coupling per rule.

   The engine is agnostic to which pattern you pick, both satisfy the `BaseRule` interface. Direct constant imports were the original architectural choice because they keep node-type assumptions explicit at the import site; pattern A preserves that property while pattern B trades it for code reuse.

### 6. Update CLI / pre-commit plumbing

A handful of edges read the supported-language list from the registry; two pre-commit surfaces still need manual edits. The engine's own file-discovery loop, the suppression parser, the cache layer, and the per-rule dispatch are *already* registry-driven, the new language plugs in via Step 3 alone.

Update both of these:

* **`.pre-commit-hooks.yaml`**, `types_or` lists the pre-commit filetype tags downstream users of `pre-commit-hooks` will get matched against (today: `[python, javascript, ts, tsx]`). Append the new tag so users who configure the hook in their `.pre-commit-config.yaml` get the new files passed in. SafeLint itself still drops anything not in `supported_extensions()` defensively, but pre-commit's own filter happens first and would otherwise hide the new files from the hook.
* **`.pre-commit-config.yaml`**: this repo's own in-tree `safelint (in-tree)` hook also has its own `types_or` filter (today: `[python, javascript]`, since the safelint source tree itself is Python + JS only). Add the new language's tag there too if the in-repo source tree starts containing that language. (The peer hooks in the same file, `ty`, `pytest-cov`, are tooling-only and can stay `types: [python]`.)

The CLI's git-status filters (`_collect_all_supported_files`, `_filter_supported_files` in `cli.py`, plus the hook-mode pre-filter at the bottom of `main()`) call `supported_extensions()` directly and need no edit.

### 6b. Wire the grammar package as an optional extra

Tree-sitter grammar packages ship as **optional extras** so a Python-only project never pays for a grammar it'll never use. Adding a new language means adding a new extra alongside `[javascript]` / `[typescript]` / `[all]`:

1. **`pyproject.toml`**, add a `<lang> = ["tree-sitter-<lang>>=…"]` entry under `[project.optional-dependencies]`. If the new language is *typically* paired with another (the way TS is paired with JS), include the paired grammar in the same extra. Append the new grammar package(s) to the existing `all` extra so `pip install 'safelint[all]'` continues to cover the whole supported set. Also add them to `dev` so `uv sync --extra dev` keeps the full test suite working.

2. **`src/safelint/languages/<lang>.py`**, gate the grammar import with `try` / `except ImportError`, mirroring `javascript.py` / `typescript.py`. Set a `_GRAMMAR_AVAILABLE` flag and a `GRAMMAR_INSTALL_HINT` module-level string (e.g. `"pip install 'safelint[go]'"`). The parser-factory function raises `ImportError` with that same hint when invoked without the grammar installed.

3. **`src/safelint/languages/__init__.py`**, gate the new language's registry entry on `<lang>_mod._GRAMMAR_AVAILABLE`, mirroring the JS / TS blocks. When the grammar isn't installed, register the extensions in `_UNAVAILABLE_EXTENSIONS` (mapped to the hint string) so the CLI can surface a per-language install hint at lint time.

The user-facing flow then becomes: `pip install 'safelint[python]'` (or `pip install 'safelint[all]'`) → `pip install 'safelint[go]'` to add Go → the CLI emits `safelint: warning: skipping .go files, install with: pip install 'safelint[go]'` if the user has `.go` files but hasn't installed the extra yet.

The CLI's missing-grammar hint helpers (`_emit_missing_grammar_warnings`, `_emit_hook_grammar_warnings`, `_scan_for_unavailable_extensions`) are language-agnostic; they read directly from `unavailable_extensions()` and need no edit when a new language lands.

#### Optional: runtime presets

Some languages have meaningfully different default API surfaces depending on where the code runs, JavaScript is the canonical example: the same `.js` source can target Node.js (with `fs` / `child_process` / `process`), browsers (with DOM / Web APIs), Deno (`Deno.*`), Cloudflare Workers (Web APIs + KV / R2), or Bun. SafeLint exposes this via the `[tool.safelint.javascript] runtime = "..."` config table and a `_JS_RUNTIME_PRESETS` dict in `core/config.py`.

If your new language has the same kind of runtime fragmentation, mirror the pattern:

1. Add a `_<LANG>_RUNTIME_PRESETS` dict alongside `_JS_RUNTIME_PRESETS`. Each entry's nested shape mirrors `DEFAULTS["rules"]`; only override the keys that should differ per runtime.
2. Add `_<LANG>_VALID_RUNTIMES` so unknown-runtime names surface as a warning.
3. Add a `_resolve_<lang>_runtime(cfg)` helper that reads `cfg["<lang>"]["runtime"]`, validates against the allowlist, defaults to a sensible baseline, and falls back with a stderr warning on bad input.
4. Wire it into `load_config` *before* the user's TOML is deep-merged on top; that way the user's explicit `_<lang>` config keys still win over the preset.

If the new language's API surface is uniform across runtimes (or the runtime fragmentation is small enough that one set of defaults is fine), skip this step entirely. Most languages, TypeScript, Go, Rust, would not need runtime presets.

### 7. Update tests and docs

* Tests under `tests/` should add a per-language test file (e.g. `test_engine_typescript.py`) covering at minimum: discovery picks up the extension, the suppression parser recognises `// nosafe`, and at least one rule fires on a known-bad TS file.
* The [Rules reference](../configuration/rules.md) rule-by-rule table should grow a "Languages" column.
* `README.md` should list the supported languages prominently.
* `CHANGELOG.md` gets an entry under **Added**.

### 8. Update the bundled AI-client skills

The bundle at `src/safelint/skill_files/` ships one Markdown artefact per registered AI client (14 today, one each under `claude/`, `cursor/`, `copilot/`, `gemini/`, `windsurf/`, `codex/`, `continue/`, `cline/`, `aider/`, `trae/`, `antigravity/`, `zed/`, `warp/`, `kiro/`). Every one of them has a **Step 2, Identify the language(s) involved** section with a registry table listing the languages safelint can lint. When you add a new language, all fourteen files need a new row in that table.

You also need to ship a new shared addendum file describing the language. The `languages/` subdirectory at the bundle root mirrors the `safelint/languages/` package one-to-one and is *shared* across every client, there's only one copy of the addendum, and every client references it via `safelint skill path`.

Concretely:

1. **Create the shared addendum** at `src/safelint/skill_files/languages/<lang>.md` modelled on `languages/python.md`. Cover install nuance (if any, e.g. ecosystem-specific packaging), the file extensions safelint will pick up, language-specific phrasing for the universal rule rationales, and idiomatic fix patterns for the rules most likely to fire on that language.

2. **Update every client's Step 2 registry table** with a row pointing at the new addendum. The 14 files to touch:

   ```text
   src/safelint/skill_files/claude/SKILL.md
   src/safelint/skill_files/cursor/safelint.mdc
   src/safelint/skill_files/copilot/copilot-instructions.md
   src/safelint/skill_files/gemini/GEMINI.md
   src/safelint/skill_files/windsurf/safelint-rules.md
   src/safelint/skill_files/codex/instructions.md
   src/safelint/skill_files/continue/safelint.md
   src/safelint/skill_files/cline/safelint.md
   src/safelint/skill_files/aider/CONVENTIONS.md
   src/safelint/skill_files/trae/safelint.md
   src/safelint/skill_files/antigravity/safelint.md
   src/safelint/skill_files/zed/safelint.md
   src/safelint/skill_files/warp/WARP.md
   src/safelint/skill_files/kiro/safelint.md
   ```

3. **Keep each client's *core* language-neutral**, the Step 2 table is the only language-specific part. Per-language detail belongs in the shared `languages/<lang>.md` addendum, not in any client's entry-point file. Every client tells its agent "for deeper language-specific guidance, read `languages/<lang>.md` from the bundled skill directory", so you only write the deep guidance once.

**The drift-detection test catches you if you miss any.** `test_skill_documents_every_supported_extension` is parametrised over `_CLIENT_SPECS` and fails CI for every client whose bundled doc doesn't mention every extension in `supported_extensions()`. So the moment you add the new extension to `safelint.languages` but forget to update one of the 14 client files, that client's parametrised test fails with a clear error.

**Smoke testing:** the bundled docs are just Markdown; no test harness needed beyond the parametrised drift tests. After `safelint skill install --client <name> --force`, ask the relevant agent to "run safelint" on a sample `<lang>` project and confirm it picks up the new file extensions and produces sensible output. Bundling is automatic via `[tool.setuptools.package-data]` in `pyproject.toml` (`skill_files/**/*.md`), so new addendum files ship in the next wheel without further config.

## Adding a framework / runtime preset to an existing language

Presets change rule *defaults* for a language without touching parsing or rule logic. Two precedents ship today: `[tool.safelint.javascript] runtime` (`node` / `browser` / `deno` / `cloudflare-workers` / `bun`) and `[tool.safelint.java] framework` (`vanilla` / `spring-boot`). To add one (a new runtime, or a framework preset like Django / Rails / axum):

1. **Config machinery in `core/config.py`**: a preset dict whose nested shape mirrors `DEFAULTS["rules"]` and contains *only* the keys it overrides (the baseline preset, e.g. `node` / `vanilla`, is the empty dict); a `frozenset` of valid preset names; a `_resolve_*` function that validates `cfg["<lang>"]["<axis>"]` and, on unknown / non-string / non-table values, surfaces a `safelint: warning:` via `core/_diagnostics` and falls back to the default (never raise for a bad preset name); and an `_apply_*` step that merges the preset into the DEFAULTS copy **before** the user's TOML is overlaid, so explicit user keys always win.
2. **Framework-specific structural rules** (if the preset warrants them) go in the **9xx band**, which is reserved for framework rules (Spring's SAFE901-904 today). They ship disabled by default and are enabled by the preset. Each follows the full "Adding a new rule" checklist, including the 14 client skill files (the rule drift test enforces this).
3. **Tests**: preset-resolution tests modelled on `tests/core/test_javascript_runtime_presets.py` / `tests/core/test_java_framework_presets.py` (each preset's overrides land; user TOML beats the preset; unknown names warn and fall back), plus an e2e fixture when structural rules ship (precedent: `tests/fixtures/spring_boot/` + `tests/integration/test_spring_boot_e2e.py`).
4. **Documentation fan-out**: the language page gains a preset table (when to pick it, what changes); [Configuration file](../configuration/toml.md) gains a preset section showing **both TOML forms** (`[tool.safelint.<lang>]` in pyproject.toml and bare `[<lang>]` in standalone safelint.toml); [Rules reference](../configuration/rules.md) documents any new 9xx rules; `README.md` / `docs/index.md` mention the preset on the language row; the shared `skill_files/languages/<lang>.md` addendum gains the preset table; and `CHANGELOG.md` records it under `[Unreleased]`.

## Things to leave alone

* Don't touch `_parse_directives` itself unless block-comment handling is genuinely needed; the current impl is generic via `LanguageDefinition`. (The `_parse_suppressions` / `_parse_file_level_ignores` wrappers it backs are thin re-exports for unit tests, modify the underlying `_parse_directives` if you need to change the comment-walk logic.)
* Don't touch the cache layer, keys are content-hashed and language-agnostic.
* Don't refactor the rule registry to support per-language filtering pre-emptively. Add it the first time a Python-only rule needs to be skipped on a non-Python file.

## A useful sanity test

Once registered, run:

```bash
echo 'function x() { if (true) { if (true) { console.log("hi"); } } }' \
  | uv run safelint --stdin --stdin-filename buf.ts --format json
```

If the JSON output's `summary.files_checked` is `1` (rather than `0` for "no language match"), discovery is working. The `violations` list will be empty until you port at least one rule's node-type lookups to the new language.

## When to involve maintainers

Open a draft PR early, even before any rules port. The discovery/parser side landing first is a great forcing function for the rule-porting work, and it's much easier to review incrementally than as one massive change.
