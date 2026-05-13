# Python

SafeLint analyses Python source for the Holzmann "Power of Ten" safety rules — function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bug that style linters like ruff don't catch. Python is SafeLint's original target language and stays the most fully covered.

## File extensions

`.py`, `.pyw`. Both are picked up by `safelint check` (directory mode, `--all-files` mode, and the pre-commit hook). Notebook formats (`.ipynb`) are not yet registered.

## Quick start

```bash
pip install 'safelint[python]'    # or: uv add 'safelint[python]'
safelint check src/               # lint a directory (git-modified files by default)
safelint check --all-files .      # lint everything
safelint check --format json src/ # machine-readable for editors / CI
```

v2.0.0 ships every language grammar as an opt-in extra — the `[python]` extra installs `tree-sitter-python` alongside the engine. Plain `pip install safelint` installs only the engine and emits an install hint on first run.

## Rules that fire on Python

All 19 user-facing rules apply to Python — the 17 cross-language rules plus the 2 Python-only rules. The 1 JavaScript-only rule (SAFE305 `wide_scope_declaration`) is skipped automatically by the engine's per-language dispatch.

| Code | Rule | Notes for Python |
|---|---|---|
| [SAFE101](../configuration/rules.md#safe101-function_length) | `function_length` | Default cap 60 lines; `count_mode` supports `lines` / `logical_lines` / `statements` (Python-only mode). |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | `nesting_depth` | Counts `if` / `for` / `while` / `with` / `try` / `match` blocks. Default max 2. |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | `max_arguments` | Counts positional, keyword, `*args`, `**kwargs` separately. Excludes `self` / `cls`. Default cap 7. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | `complexity` | Cyclomatic complexity — every `if` / `elif` / `for` / `while` / `except` / `case` / ternary / `and` / `or` adds one. Default cap 10. |
| [SAFE201](../configuration/rules.md#safe201-bare_except) | `bare_except` | **Python-only.** Fires on `except:` with no exception type — catches `KeyboardInterrupt` and `SystemExit`. |
| [SAFE202](../configuration/rules.md#safe202-empty_except) | `empty_except` | Fires on `except: pass`, `except: ...`, `except: 0`, `except: "TODO"`. |
| [SAFE203](../configuration/rules.md#safe203-logging_on_error) | `logging_on_error` | Requires a call to `logger.{debug,info,warning,error,exception,critical}` (or bare `raise`) in every except handler. |
| [SAFE301](../configuration/rules.md#safe301-global_state) | `global_state` | **Python-only.** Fires on the `global` keyword. With `strict = true`, fires on every declaration; default is "declaration + write". |
| [SAFE302](../configuration/rules.md#safe302-global_mutation) | `global_mutation` | Function-body writes that follow a `global` declaration. Reading a global doesn't fire. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | `side_effects_hidden` | Functions named with a pure-prefix (`calculate_`, `get_`, `is_`, …) that secretly call `open()` / `print()` / `input()`. |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | `side_effects` | Any function calling an I/O primitive whose name doesn't signal I/O (no `log_` / `write_` / `read_` / etc. infix). |
| [SAFE401](../configuration/rules.md#safe401-resource_lifecycle) | `resource_lifecycle` | Tracked acquirer calls (`open`, `connect`, `Lock`, `Pool`, …) must be inside a `with` statement. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | `unbounded_loops` | `while True:` with no `break`. Also fires on `while <non-comparison>:` — a heuristic that stays Python-only. |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | `missing_assertions` | Functions with zero `assert` statements. Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | `test_existence` | Every source file should have a matching `test_<stem>.py` under `test_dirs`. Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | `test_coupling` | If you change `src/foo.py`, you must also change `tests/test_foo.py` in the same commit. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | `tainted_sink` | Function parameters / `input()` flowing into `eval` / `exec` / `subprocess` / `cursor.execute`. Disabled by default. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | `return_value_ignored` | Bare calls to `subprocess.run`, `f.write`, `socket.send`, `os.rename`, etc. — return value carries success/failure. Disabled by default. |
| [SAFE803](../configuration/rules.md#safe803-null_dereference) | `null_dereference` | `config.get("k").strip()` — dereferencing a call that can return `None`. Disabled by default. |

The 1 rule **not registered for Python:** [SAFE305 `wide_scope_declaration`](../configuration/rules.md#safe305-wide_scope_declaration) — JavaScript-only; Python has no `var` / `let` / `const` distinction.

## Configuration

SafeLint reads its config from `[tool.safelint]` in `pyproject.toml`, or from a standalone `safelint.toml` at the project root. Standalone wins when both are present.

**`pyproject.toml`:**

```toml
[tool.safelint]
mode = "ci"                 # "local" (fail-on=error) or "ci" (fail-on=warning)
ignore = ["SAFE701"]        # rules suppressed project-wide

[tool.safelint.per_file_ignores]
"tests/**" = ["SAFE101", "SAFE601"]   # tests routinely have longer functions
"migrations/**" = ["*"]                # ignore everything under migrations/

[tool.safelint.rules.function_length]
max_lines = 80              # raise the default cap
count_mode = "logical_lines"

[tool.safelint.rules.tainted_sink]
enabled = true              # opt into the dataflow rules
```

**Standalone `safelint.toml`:**

```toml
# Same content but drop the [tool.safelint] prefix
mode = "ci"
ignore = ["SAFE701"]

[per_file_ignores]
"tests/**" = ["SAFE101", "SAFE601"]

[rules.function_length]
max_lines = 80
```

See [Configuration file](../configuration/toml.md) for the full list of top-level keys and [Rules reference](../configuration/rules.md) for every per-rule option.

## Installing the Python extra

v2.0.0 ships every language grammar — Python included — as an opt-in extra so projects only install what they actually lint:

```bash
pip install 'safelint[python]'              # Python-only project
pip install 'safelint[python,javascript]'   # Python + JS monorepo
pip install 'safelint[all]'                 # kitchen-sink
```

`pip install safelint` (no extras) installs only the engine. safelint will emit `safelint: warning: skipping .py files — install with: pip install 'safelint[python]'` on first run when it finds Python files but the grammar isn't installed. **Heads-up for CI:** in a Python-only project that pattern means *every* candidate file gets skipped, which fires the [silent-failure guard](../configuration/cli.md#exit-code-2--silent-failure-triggers) and exits with code 2 plus the install hint embedded in the error — so CI / pre-commit can't accidentally report green on an un-linted run.

## Pre-commit integration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/shelkesays/safelint
    rev: v2.0.0rc1         # pin to a release (replace with the GA tag once v2.0.0 ships)
    hooks:
      - id: safelint
        # Every safelint hook needs an extra in v2.0.0+ — including Python-only projects.
        additional_dependencies: ['safelint[python]']
        # Optional: scope to a directory
        files: ^src/
```

The published hook spec sets `types_or: [python, javascript, ts, tsx]` and no `files:` filter — add your own `files:` / `exclude:` keys to scope it. Mixed-language projects compose extras: `additional_dependencies: ['safelint[python,javascript]']` (or `[all]`).

## Python-specific config keys

Most rule options work uniformly across languages, but a few are Python-only:

- **`[tool.safelint.rules.function_length]`** — `count_mode = "statements"` (counts AST statement nodes) is Python-only. JavaScript files use `lines` (default) or `logical_lines`.
- **`[tool.safelint.rules.global_mutation]`** — `strict = true` (fire on every `global` declaration regardless of write) is Python-only.
- **`[tool.safelint.rules.side_effects_hidden]`** — `pure_prefixes` defaults match Python `snake_case` (`calculate_`, `get_`, `is_`, `has_`, `find_`). For mixed-language repos the same list applies to both — the substring check is case-insensitive.
- **`[tool.safelint.rules.resource_lifecycle]`** — `tracked_functions`, `extend_tracked_functions`, and `cleanup_patterns` are Python-only keys. The JavaScript equivalent is `tracked_functions_javascript`.
- **`[tool.safelint.rules.tainted_sink]`** — `sinks`, `sanitizers`, `sources` default to Python's threat surface (`eval`, `exec`, `subprocess`, …). The `_javascript`-suffixed equivalents are independent lists.

## Contributing

Want to refine a rule's Python behaviour, add a Python-specific config option, or fix a Python parser edge case? See [Adding a language](../contributing/adding-a-language.md) for the architecture overview, or open an issue / PR against the [main repo](https://github.com/shelkesays/safelint).
