# Adding a new language to safelint

This guide is the cheat sheet for adding support for a new programming language (TypeScript, Go, Rust, etc.) to safelint. The architecture was prepared with multi-language in mind; the moving parts you need to understand and the steps you need to follow are below.

> [!NOTE]
> Today only Python is registered. The supporting structure (parser hookup, file-discovery loop, suppression parser) is already language-agnostic. To add a new language you need three pieces: (a) a Tree-sitter grammar package for that language, (b) a per-language module that exports the grammar's node-type names as constants, and (c) a rule-by-rule audit to identify which existing rules port cleanly and which are Python-specific.

> [!IMPORTANT]
> Adding a new language also requires updating the bundled AI-client skills (`SKILL.md` and `cursor/safelint.mdc`) to list the new language and its file extensions in their **Step 2** registry tables. The drift-detection test `test_skill_documents_every_supported_extension` fails the moment a new extension lands in `supported_extensions()` without the corresponding bundled-doc update — and the test is parametrised over every registered AI client, so you only need to make the additions once per skill file.

## The architecture, in five sentences

1. `safelint.languages.LanguageDefinition` is a frozen dataclass holding everything the engine needs about a language: file extensions, parser factory, comment node type, comment prefix.
2. Adding a language = creating one new module under `src/safelint/languages/` (e.g. `typescript.py`), instantiating a `LanguageDefinition`, and registering it in `languages/__init__.py`.
3. The engine's parse-and-walk loop is language-agnostic — it reads `lang.create_parser()`, queries `lang.comment_node_type` for `# nosafe` directives, and runs every active rule against the resulting Tree-sitter tree.
4. **Rules** import per-language node-type constants directly (e.g. `from safelint.languages.python import FUNCTION_DEF`). Most existing rules are Python-specific because they reference Python-only constructs like `global`, `assert`, or specific exception node types. Each rule has to be audited for whether its concept maps cleanly to the new language and, if so, port the node type lookups.
5. Suppressions are parsed via `_parse_suppressions` which uses `lang.comment_node_type` and `lang.comment_prefix` from the `LanguageDefinition` — so `# nosafe` works automatically wherever you point it. **The literal token form** (`# nosafe`, `// nosafe`, etc.) follows from `comment_prefix`.

## Step-by-step: adding TypeScript as an example

### 1. Add the Tree-sitter grammar dependency

Add the grammar to `pyproject.toml`:

```toml
dependencies = [
    "tree-sitter>=0.23.0",
    "tree-sitter-python>=0.23.0",
    "tree-sitter-typescript>=0.23.0",   # ← new
]
```

Run `uv sync` to pull it.

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


# Per-language node type constants — one per rule concept that maps to TS.
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

That's enough for safelint to **discover and parse** TypeScript files. None of the existing rules will fire on them yet — see step 5.

### 4. Watch out for: block-comment `nosafe` directives

The current `_parse_suppressions` in `core/engine.py` walks `comment` nodes from the Tree-sitter tree and treats each as a single line-style directive. For languages with `/* … */` block comments (TypeScript, Go, Rust, C, …), a multi-line `nosafe` block comment **may need extra handling** — the directive should still apply to the line containing the closing `*/` (or whatever line carries the violation).

If the grammar emits block comments as the same `comment` node type and the parser's `start_point[0]` aligns with the violation's line, you're fine. Otherwise, the safest path is to add per-language helpers for "extract suppression line ranges from a comment node" rather than the current single-line assumption. A future refactor — flag and handle when you hit it.

### 5. Audit each rule for language portability

Most safelint rules read like Python concepts but the underlying ideas generalise. Audit each rule and decide: **port**, **port-with-rename**, or **Python-only** (skip for this language).

Rule-by-rule guide:

| Rule | Concept | Likely portable to TS? |
|---|---|---|
| `function_length` (SAFE101) | function body line count | yes — same idea, just `function_declaration` / `arrow_function` / `method_definition` instead of `function_definition` |
| `nesting_depth` (SAFE102) | depth of if/for/while/with/try | yes — TS has same control-flow constructs (`if_statement`, `for_statement`, etc.) |
| `max_arguments` (SAFE103) | parameter count | yes — TS has `formal_parameters` instead of `parameters`; rest-spread / default-value forms differ |
| `complexity` (SAFE104) | McCabe cyclomatic complexity | yes — same set of branch nodes (modulo TS-specific like `switch_statement`) |
| `bare_except` (SAFE201) | bare `except:` | yes, but this is Python-specific syntax. TS equivalent: `catch` without `Error` filter — different shape |
| `empty_except` (SAFE202) | empty except body | port: `catch (e) {}` is the TS equivalent |
| `logging_on_error` (SAFE203) | error swallow without log | port: same idea, but log-call detection needs TS console / library names |
| `global_state` / `global_mutation` (SAFE301/302) | use of `global` keyword | **Python-only** — TS doesn't have this construct |
| `side_effects_hidden` / `side_effects` (SAFE303/304) | pure-named function doing I/O | port: same idea, just rename the I/O primitive list (`fs.readFile`, `console.log`) |
| `resource_lifecycle` (SAFE401) | resource opened outside `with` | port: TS equivalent is `using` (TC39 stage 4 / TS 5.2+) or manual `try/finally close()` |
| `unbounded_loops` (SAFE501) | `while True` without break | port: `while (true)` matches the same shape |
| `missing_assertions` (SAFE601) | function lacks assertions | port: TS doesn't have `assert` keyword but has `console.assert` and test-framework assertions |
| `test_existence` / `test_coupling` (SAFE701/702) | source change without test change | port: just different test-file naming convention |
| `tainted_sink`, `return_value_ignored`, `null_dereference` (SAFE801–803) | dataflow rules | port: requires non-trivial work — `analysis/dataflow.py` walks Python-specific node types and would need a TS counterpart |

For each rule that ports, the work is:

1. Identify the matching node types in the new grammar. The parser-dump trick is the fastest way to find them — feed a small snippet to the new grammar and inspect the resulting tree:
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
3. Update the rule to dispatch on the file's language. Today rules import constants directly from `safelint.languages.python` because Python is the only registered language. When a second language lands, the cleanest path is **per-language rule classes** (e.g. `FunctionLengthRulePython`, `FunctionLengthRuleTypeScript`) — same logic, different constants imported. Direct imports were chosen over a runtime dispatch table because they keep each rule's node-type assumptions explicit at the import site, which makes auditing easier.

Alternative: a `language` field on `BaseRule` indicating which language the rule supports (default: `("python",)`), and the engine filters rules by file's language. Add this when a 2nd language actually exists.

### 6. Update tests and docs

* Tests under `tests/` should add a per-language test file (e.g. `test_engine_typescript.py`) covering at minimum: discovery picks up the extension, the suppression parser recognises `// nosafe`, and at least one rule fires on a known-bad TS file.
* `CONFIGURATION.md` rule-by-rule table should grow a "Languages" column.
* `README.md` should list the supported languages prominently.
* `CHANGELOG.md` gets an entry under **Added**.

### 7. Update the bundled AI-client skills

The bundle at `src/safelint/skill_files/` ships one Markdown artefact per registered AI client (12 today: Claude Code's `SKILL.md`, plus a per-client file under each of `cursor/`, `copilot/`, `gemini/`, `windsurf/`, `codex/`, `continue/`, `cline/`, `aider/`, `trae/`, `antigravity/`, `zed/`). Every one of them has a **Step 2 — Identify the language(s) involved** section with a registry table listing the languages safelint can lint. When you add a new language, all twelve files need a new row in that table.

You also need to ship a new shared addendum file describing the language. The `languages/` subdirectory at the bundle root mirrors the `safelint/languages/` package one-to-one and is *shared* across every client — there's only one copy of the addendum, and every client references it via `safelint skill path`.

Concretely:

1. **Create the shared addendum** at `src/safelint/skill_files/languages/<lang>.md` modelled on `languages/python.md`. Cover install nuance (if any — e.g. ecosystem-specific packaging), the file extensions safelint will pick up, language-specific phrasing for the universal rule rationales, and idiomatic fix patterns for the rules most likely to fire on that language.

2. **Update every client's Step 2 registry table** with a row pointing at the new addendum. The 12 files to touch:

   ```text
   src/safelint/skill_files/SKILL.md
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
   ```

3. **Keep each client's *core* language-neutral** — the Step 2 table is the only language-specific part. Per-language detail belongs in the shared `languages/<lang>.md` addendum, not in any client's entry-point file. Every client tells its agent "for deeper language-specific guidance, read `languages/<lang>.md` from the bundled skill directory" — so you only write the deep guidance once.

**The drift-detection test catches you if you miss any.** `test_skill_documents_every_supported_extension` is parametrised over `_CLIENT_SPECS` and fails CI for every client whose bundled doc doesn't mention every extension in `supported_extensions()`. So the moment you add the new extension to `safelint.languages` but forget to update one of the 12 client files, that client's parametrised test fails with a clear error.

**Smoke testing:** the bundled docs are just Markdown; no test harness needed beyond the parametrised drift tests. After `safelint skill install --client <name> --force`, ask the relevant agent to "run safelint" on a sample `<lang>` project and confirm it picks up the new file extensions and produces sensible output. Bundling is automatic via `[tool.setuptools.package-data]` in `pyproject.toml` (`skill_files/**/*.md`), so new addendum files ship in the next wheel without further config.

## Things to leave alone

* Don't touch `_parse_suppressions` itself unless block-comment handling is genuinely needed; the current impl is generic via `LanguageDefinition`.
* Don't touch the cache layer — keys are content-hashed and language-agnostic.
* Don't refactor the rule registry to support per-language filtering pre-emptively. Add it the first time a Python-only rule needs to be skipped on a non-Python file.

## A useful sanity test

Once registered, run:

```bash
echo 'function x() { if (true) { if (true) { console.log("hi"); } } }' \
  | uv run safelint --stdin --stdin-filename buf.ts --format json
```

If the JSON output's `summary.files_checked` is `1` (rather than `0` for "no language match"), discovery is working. The `violations` list will be empty until you port at least one rule's node-type lookups to the new language.

## When to involve maintainers

Open a draft PR early — even before any rules port. The discovery/parser side landing first is a great forcing function for the rule-porting work, and it's much easier to review incrementally than as one massive change.
