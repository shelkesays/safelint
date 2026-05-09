# Rules reference

Each rule has:

- A **code** — short identifier like `SAFE101`, shown in the output. Use this to search docs or issues.
- A **name** — the key used in config files.
- An **enabled** flag — set to `false` to turn the rule off.
- A **severity** — `"error"` blocks the commit; `"warning"` is informational.
- Rule-specific options documented below.

For top-level config keys (`mode`, `ignore`, `per_file_ignores`, …) see the [Configuration file](toml.md). For inline / file-level suppression see [Suppression mechanisms](suppression.md).

## Engine-internal codes

A few codes are emitted by the engine directly rather than by registered `BaseRule` subclasses. They don't have their own config section and follow the global `ignore` list. Inline `# nosafe: SAFE0xx` works for codes emitted *after* parsing (such as SAFE004 — see below) but **not** for SAFE000, because parse errors are raised before the engine has a chance to read suppression directives off the tree.

### SAFE000 — `parse`

**What it flags:** Tree-sitter parse errors (syntax errors, broken indentation, missing tokens). The violation carries the offending token's column as a zero-width caret so editors can mark the precise location.

Always severity `error`. Cannot be configured per-rule.

**Inline `# nosafe: SAFE000` does *not* work.** Parse errors are raised by `SafetyEngine._lint_parsed_source` *before* it parses inline suppression directives off the Tree-sitter tree (see the early-return at the parse-error check). The only way to silence SAFE000 is the global `ignore` list, which is read at engine init from your config file:

```toml
[tool.safelint]
ignore = ["SAFE000"]   # or ignore = ["parse"] — rule name also accepted
```

Use this when you genuinely don't want parse errors surfaced (rare — usually you *do* want to know when a file failed to parse).

### SAFE004 — `unused_suppression` *(added in 1.8.0)*

**What it flags:** A `# nosafe` directive on a line where no violation actually fired — i.e. the suppression is stale (e.g. left over after a refactor that removed the offending code).

```python
def f():
    x = 1   # nosafe: SAFE304   ← SAFE304 doesn't fire here; SAFE004 reports
    return x
```

Severity is fixed at `warning`. Disable globally via `ignore = ["SAFE004"]` if your workflow involves many transient suppressions you'd rather not police. **Per-file ignores do not apply to SAFE004** — like SAFE000, it's an engine-internal code gated solely on the global `ignore` list (configuring it inside `per_file_ignores` will surface a typo-guard warning and otherwise do nothing). Self-referential `# nosafe: SAFE004` is special-cased — a directive that only mentions SAFE004 is always considered "used" to avoid recursion.

## Structural rules

These check the shape of your functions. They are cheap to run and always go first.

### SAFE101 — `function_length`

**What it flags:** Functions longer than `max_lines` (interpreted under the configured `count_mode`).

Long functions are hard to read, test, and reason about. The Holzmann rule says a function should fit on one printed page.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `max_lines` | `60` | Maximum allowed function size (units depend on `count_mode`) |
| `count_mode` | `"lines"` | How to measure size: `"lines"` (raw source lines incl. blanks/comments — Holzmann's original framing), `"logical_lines"` (lines minus blanks and pure-comment lines — less game-able), or `"statements"` (count Python statement nodes — robust to formatting, equivalent to ruff's `PLR0915`). *Added in 1.8.0.* |

```toml
[tool.safelint.rules.function_length]
enabled = true
severity = "error"
max_lines = 60
count_mode = "lines"      # default; alternatives: "logical_lines", "statements"
```

When switching to `"statements"`, lower `max_lines` accordingly — a function with 60 source lines typically corresponds to ~25–35 statement nodes. Pick a value that matches the spirit of "function fits on a page" for your codebase.

### SAFE102 — `nesting_depth`

**What it flags:** Functions with control-flow nested more than `max_depth` levels deep.

Deep nesting (if inside for inside if inside while…) makes code hard to follow and test. Two levels is enough for most real functions.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `max_depth` | `2` | Maximum allowed nesting depth of `if`, `for`, `while`, `with`, `try` |

```toml
[tool.safelint.rules.nesting_depth]
enabled = true
severity = "error"
max_depth = 2
```

### SAFE103 — `max_arguments`

**What it flags:** Functions with more than `max_args` parameters.

Too many arguments usually means a function is doing too much, or needs a config object. `self` and `cls` are excluded from the count. `*args` and `**kwargs` each count as one parameter — they bring real callers, just an unbounded number of them, so they cannot be free.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `max_args` | `7` | Maximum number of parameters (excluding `self`/`cls`; `*args`/`**kwargs` each count as one) |

```toml
[tool.safelint.rules.max_arguments]
enabled = true
severity = "error"
max_args = 7
```

### SAFE104 — `complexity`

**What it flags:** Functions with cyclomatic complexity above `max_complexity`.

Cyclomatic complexity counts the number of independent paths through a function. It starts at 1 and goes up by 1 for every `if`, `elif`, `for`, `while`, `except`, ternary expression, `and`/`or` operator, and comprehension condition. A score above 10 means the function has too many possible paths to test reliably.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `max_complexity` | `10` | Maximum cyclomatic complexity (McCabe score) |

```toml
[tool.safelint.rules.complexity]
enabled = true
severity = "error"
max_complexity = 10
```

## Error handling rules

These check that exceptions are handled clearly and not swallowed silently.

### SAFE201 — `bare_except`

**What it flags:** `except:` clauses with no exception type.

A bare `except:` catches everything including `KeyboardInterrupt` and `SystemExit`, which are signals — not bugs. Always specify the exception type you expect.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.bare_except]
enabled = true
severity = "error"
```

**Bad:**

```python
try:
    connect()
except:          # SAFE201 - catches KeyboardInterrupt too
    pass
```

**Good:**

```python
try:
    connect()
except ConnectionError as exc:
    log.error("Connection failed: %s", exc)
```

### SAFE202 — `empty_except`

**What it flags:** `except` blocks whose body is effectively a no-op:

- `except E: pass`
- `except E: continue`
- `except E: ...` (Ellipsis)
- `except E: 0` / `None` / `True` / `False` (constant literals)
- `except E: "TODO"` / `""` (string-as-comment idiom)

An empty except block silently swallows the error. The caller has no idea something went wrong. *Broadened in 1.8.0* — earlier versions only matched a literally empty body which Tree-sitter doesn't actually produce for valid Python, so the rule was effectively dead code.

Multi-statement bodies are not flagged even if every statement looks trivial — two consecutive no-ops suggest *some* intentional structure and would generate false positives.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.empty_except]
enabled = true
severity = "error"
```

### SAFE203 — `logging_on_error`

**What it flags:** `except` blocks that handle an error without any logging call.

If you catch an exception and do something with it but never log it, the error is invisible. This rule requires at least one call to a logger method (`debug`, `info`, `warning`, `error`, `exception`, `critical`) inside the except block. Blocks that simply re-raise are exempt.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.logging_on_error]
enabled = true
severity = "warning"
```

## State and purity rules

These check for use of global variables and unexpected side effects in functions.

### SAFE301 — `global_state`

**What it flags:** Functions that declare the `global` keyword.

Using `global` means a function reads or writes shared state outside its own scope. This makes functions hard to test and creates hidden dependencies between parts of your code. Pass values as arguments instead.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.global_state]
enabled = true
severity = "warning"
```

### SAFE302 — `global_mutation`

**What it flags:** By default, functions that declare `global x` and then assign to `x`. With `strict = true`, *any* `global` declaration is flagged regardless of whether a write follows.

This is stricter than `SAFE301`. A function that both declares a variable global *and* writes to it is mutating shared state — the most dangerous form of global use. The default behaviour is more nuanced than ruff's `PLW0603` (which fires on any `global`); set `strict = true` if your team's policy is to ban the keyword entirely.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `strict` | `false` | When `true`, fire on every `global` declaration even without a subsequent write — mirrors ruff's `PLW0603`. *Added in 1.8.0.* |

```toml
[tool.safelint.rules.global_mutation]
enabled = true
severity = "error"
strict = false   # set true to ban the `global` keyword outright
```

### SAFE303 — `side_effects_hidden`

**What it flags:** Functions with "pure-sounding" names that perform I/O.

A function named `calculate_total` or `get_user` implies it just computes and returns a value. If it secretly calls `open()`, `print()`, or `input()`, it is hiding a side effect. This is a core Holzmann risk — callers cannot reason about the function's behaviour.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `io_functions` | `["open", "print", "input", "subprocess"]` | Call names considered I/O |
| `pure_prefixes` | see below | Function name prefixes that imply purity |

Default `pure_prefixes`: `calculate`, `compute`, `get`, `check`, `validate`, `is`, `has`, `find`, `parse`, `transform`, `convert`, `format`, `build`, `resolve`, `detect`

```toml
[tool.safelint.rules.side_effects_hidden]
enabled = true
severity = "error"
io_functions = ["open", "print", "input", "subprocess"]
pure_prefixes = ["calculate", "compute", "get", "check", "validate", "is", "has"]
```

### SAFE304 — `side_effects`

**What it flags:** Any function that calls an I/O primitive and is not named to signal that fact.

Broader than `SAFE303` — applies to *all* functions, not just pure-named ones. A function named `process_order` that calls `print()` should be renamed to `log_order` or refactored to use dependency injection.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `io_functions` | `["open", "print", "input"]` | Call names considered I/O |
| `io_name_keywords` | see below | Functions whose names contain these words are exempt |

Default `io_name_keywords`: `print`, `log`, `write`, `read`, `save`, `load`, `send`, `fetch`, `export`, `import`

```toml
[tool.safelint.rules.side_effects]
enabled = true
severity = "warning"
io_functions = ["open", "print", "input"]
io_name_keywords = ["print", "log", "write", "read", "save", "load", "send", "fetch"]
```

## Resource safety rules

### SAFE401 — `resource_lifecycle`

**What it flags:** Calls to resource-acquisition functions (like `open()`) that are not inside a `with` block.

Resources that are opened must be closed. If an exception occurs between `open()` and `close()`, the resource leaks. A `with` block guarantees cleanup even if an exception is raised.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `tracked_functions` | (see below) | Calls that must be inside a `with` block. Replaces the default list when set. |
| `extend_tracked_functions` | `[]` | Appended to the default list — use this when you want to *add* custom functions without losing the defaults. *Added in 1.8.0.* |
| `cleanup_patterns` | `["close", "commit", "rollback", "release", "shutdown"]` | Acceptable cleanup method names as an alternative |

**Default `tracked_functions`** (expanded in 1.8.0):

```toml
tracked_functions = [
    "open", "connect", "session", "Session",          # files, DBs, HTTP
    "Lock", "RLock", "Semaphore",                     # synchronisation
    "Pool", "ThreadPoolExecutor", "ProcessPoolExecutor",  # work pools
    "socket", "mmap",                                 # network / memory
    "TemporaryFile", "NamedTemporaryFile", "TemporaryDirectory",
    "ZipFile", "TarFile",                             # archives
]
```

```toml
# Add custom acquirers without losing the defaults
[tool.safelint.rules.resource_lifecycle]
extend_tracked_functions = ["acquire_widget", "rent_db_handle"]
```

```toml
# Or replace the list entirely (overrides the built-in defaults)
[tool.safelint.rules.resource_lifecycle]
tracked_functions = ["open", "connect"]
```

**Bad:**

```python
f = open("data.txt")   # SAFE401 - not in a with block
data = f.read()
f.close()              # won't run if f.read() raises
```

**Good:**

```python
with open("data.txt") as f:
    data = f.read()
```

## Loop safety rules

### SAFE501 — `unbounded_loops`

**What it flags:** `while` loops that may run forever.

Two cases are flagged:

1. `while True:` with no `break` inside — guaranteed infinite loop.
2. `while <condition>:` where the condition is not a comparison — the loop bound is unclear.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.unbounded_loops]
enabled = true
severity = "warning"
```

## Documentation rules

### SAFE601 — `missing_assertions`

**What it flags:** Functions that contain no `assert` statements.

Based on Holzmann rule 5: every function should have at least two assertions to validate its assumptions. This is a heuristic — disabled by default because many functions legitimately have no assertions (e.g. simple data transformations).

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default — opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.missing_assertions]
enabled = true
severity = "warning"
```

## Test coverage rules

These are disabled by default. Enable them in CI to enforce test discipline.

### SAFE701 — `test_existence`

**What it flags:** Source files that have no corresponding test file.

For every file `src/mymodule/foo.py` it looks for `test_foo.py` under the configured `test_dirs`. If no matching test file is found, it flags the source file.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default — opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `test_dirs` | `["tests"]` | Directories to search for test files |

```toml
[tool.safelint.rules.test_existence]
enabled = true
severity = "warning"
test_dirs = ["tests", "test"]
```

### SAFE702 — `test_coupling`

**What it flags:** Source files that were changed without a corresponding change to their test file.

If you modify `src/foo.py`, you must also modify `tests/test_foo.py` in the same commit. This enforces the discipline that source changes come with test updates. Unlike `SAFE701`, this requires the test file to exist — if it does not, `SAFE701` fires instead.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default — opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `test_dirs` | `["tests"]` | Directories to search for test files |

```toml
[tool.safelint.rules.test_coupling]
enabled = true
severity = "warning"
test_dirs = ["tests"]
```

## Dataflow rules

These combine AST analysis with intra-procedural taint tracking. They are more expensive than structural rules and **disabled by default**. Enable them when you need deeper security or correctness guarantees.

### SAFE801 — `tainted_sink`

**What it flags:** User-controlled input (function parameters, `input()` calls) flowing into dangerous functions like `eval`, `exec`, or `subprocess` without being sanitized first.

The rule tracks data flow through assignments: if `x = user_data` then `x` is tainted. If `y = x + "_suffix"` then `y` is tainted too. Calling `eval(y)` then triggers a violation. Passing the value through a configured sanitizer (e.g. `escape(x)`) clears the taint.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default — opt-in |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `sinks` | see below | Call names considered dangerous |
| `sanitizers` | see below | Call names that clear taint |
| `sources` | see below | Call names that inject taint (in addition to parameters) |
| `assume_taint_preserving` | `true` | How unknown calls (neither sanitizer nor source) propagate taint. *Added in 1.8.0.* |

Default `sinks`: `eval`, `exec`, `compile`, `system`, `popen`, `Popen`, `run`, `call`, `check_output`, `execute`

Default `sanitizers`: `escape`, `sanitize`, `clean`, `validate`, `quote`, `encode`, `bleach`

Default `sources`: `input`, `readline`, `recv`, `recvfrom`, `read`

```toml
[tool.safelint.rules.tainted_sink]
enabled = true
severity = "error"
sinks = ["eval", "exec", "system", "execute"]
sanitizers = ["escape", "sanitize", "quote"]
sources = ["input", "readline"]
assume_taint_preserving = true   # default; set false for taint-dropping mode
```

#### `assume_taint_preserving` modes (1.8.0)

Most real codebases pass tainted data through internal helper functions before it reaches a sink. The `assume_taint_preserving` config flag controls how those *unknown* calls (i.e. calls whose name isn't in `sources` or `sanitizers`) are analysed.

The naming says it directly: when ``assume_taint_preserving = true``, the analyser assumes any unknown call preserves the taint of its arguments — the more **conservative** stance, fewer false negatives, more false positives:

- **`true` (default)** — conservative / taint-preserving. An unknown call's result is tainted iff any of its arguments are tainted. ``eval(user_input)`` fires (direct flow). ``eval(wrap(user_input))`` *also* fires (taint flows through the unknown ``wrap``). Cost: false positives when ``wrap`` is in fact safe.
- **`false`** — taint-dropping (less conservative — *weaker* detection). Unknown calls always drop taint. ``eval(user_input)`` still fires (direct flow). ``eval(wrap(user_input))`` does **not** fire — the unknown ``wrap`` resets taint, even if it does in fact pass user input through. Use when your codebase has many internal-only wrappers and you'd rather miss a flow than chase down false positives.

Note the asymmetry: `false` is the *less* conservative setting (fewer reports, more chance of missing real issues), not "stricter". The trade-off is fundamental to intra-procedural analysis — there's no way to know whether ``wrap`` actually preserves the taint without inlining it. Switch modes based on which failure mode hurts more in your codebase.

**Bad:**

```python
def run_query(user_input):
    cursor.execute(user_input)   # SAFE801 - tainted param reaches execute()
```

**Good:**

```python
def run_query(user_input):
    safe = sanitize(user_input)
    cursor.execute(safe)          # sanitizer clears taint - no violation
```

### SAFE802 — `return_value_ignored`

**What it flags:** Calls to functions whose return value signals success or failure, where the return value is discarded.

Calling `subprocess.run(["rm", "-rf", path])` as a bare statement (not assigning the result) means you never check whether the command succeeded. Same with `file.write()` — it returns the number of bytes written, and silently ignoring it means you may have written nothing.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default — opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `flagged_calls` | see below | Call names whose return value must not be discarded |

Default `flagged_calls`: `run`, `call`, `check_output`, `write`, `send`, `sendall`, `sendfile`, `seek`, `truncate`, `remove`, `unlink`, `rename`, `replace`, `makedirs`, `mkdir`, `rmdir`

```toml
[tool.safelint.rules.return_value_ignored]
enabled = true
severity = "warning"
flagged_calls = ["run", "write", "send", "remove", "unlink"]
```

**Bad:**

```python
subprocess.run(["deploy.sh"])    # SAFE802 - return value discarded
f.write(data)                    # SAFE802 - bytes written not checked
```

**Good:**

```python
result = subprocess.run(["deploy.sh"])
if result.returncode != 0:
    raise RuntimeError("Deploy failed")
```

### SAFE803 — `null_dereference`

**What it flags:** Chained attribute access or subscript directly on a call that can return `None`, without a guard.

`dict.get()` returns `None` when the key is absent. Calling `.strip()` on the result without checking for `None` first will raise `AttributeError` at runtime. Same with ORM methods like `session.scalar()` or `cursor.fetchone()`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default — opt-in |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `nullable_methods` | see below | Method names whose return value may be `None` |

Default `nullable_methods`: `get`, `pop`, `find`, `next`, `first`, `one_or_none`, `scalar`, `scalar_one_or_none`, `fetchone`

```toml
[tool.safelint.rules.null_dereference]
enabled = true
severity = "error"
nullable_methods = ["get", "pop", "find", "fetchone", "first"]
```

**Bad:**

```python
name = config.get("username").strip()   # SAFE803 - .get() can return None
row = cursor.fetchone().value           # SAFE803 - fetchone() can return None
```

**Good:**

```python
username = config.get("username")
name = username.strip() if username is not None else ""
```
