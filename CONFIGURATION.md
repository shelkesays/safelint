# SafeLint Configuration Reference

SafeLint is configured via `[tool.safelint]` in your `pyproject.toml` (preferred) or a `.safelint.yaml` file in your project root.

All keys are optional - anything you leave out falls back to the built-in defaults shown below.

---

## CLI flags

These are passed on the command line and are not part of the config file.

### `safelint check` flags

| Flag | Default | What it does |
|---|---|---|
| `--all-files` | off | Scan every `.py` file under the target. Default (without this flag) is to check only git-modified files. |
| `--fail-on` | from config | Override the minimum severity that blocks the run: `error` or `warning`. |
| `--mode` | from config | `local` (only errors block) or `ci` (warnings block too). |
| `--config` | auto-discovered | Path to a config file (`pyproject.toml`, `.safelint.yaml`) or a directory to use as the config search root. |
| `--ignore` | none | Space-separated rule codes or names to suppress for this run only, e.g. `--ignore SAFE101 function_length`. Stacks on top of the `ignore` list in the config file. |

**When to use `--all-files`:**
- CI pipelines (clean checkout, no modified files in git terms)
- Running a one-off full audit
- `pre-commit run --all-files` already passes all files directly; the hook mode handles this automatically.

### `safelint` hook mode flags (pre-commit)

Pre-commit passes the staged files as positional arguments automatically. `--fail-on`, `--mode`, and `--ignore` are all supported here.

```yaml
- id: safelint
  args: [--fail-on=error]   # or --fail-on=warning for strict CI

# Ignore specific rules in the hook:
- id: safelint
  args: [--fail-on=error, --ignore, SAFE203, side_effects]
```

---

## Inline suppression

Add a `# nosafe` comment to the end of any line to suppress violations on that specific line. This is the escape hatch for the rare case where a violation is a deliberate, justified choice.

Suppressed violations do not appear in output and do not count toward the blocking total, but the number suppressed is always reported at the end of the run so they remain auditable.

### Syntax

| Comment | Effect |
|---|---|
| `# nosafe` | Suppress **all** violations on this line |
| `# nosafe: SAFE101` | Suppress only the rule with code `SAFE101` |
| `# nosafe: function_length` | Suppress only the rule named `function_length` |
| `# nosafe: SAFE101, SAFE103` | Suppress multiple rules (comma-separated codes or names) |

Both rule codes (e.g. `SAFE101`) and rule names (e.g. `function_length`) are accepted and can be mixed in the same comment.

### Examples

**Suppress all violations on a line** — use when a line genuinely triggers multiple unrelated rules and fixing each would make the code worse:
```python
result = eval(user_input)  # nosafe
```

**Suppress a single code** — preferred; makes the intent explicit and leaves other rules active:
```python
while True:  # nosafe: SAFE501
    item = queue.get()     # blocking poll — bounded by the caller's timeout
    if item is None:
        break
```

**Suppress by rule name** — identical behaviour to suppressing by code; use whichever is more readable in context:
```python
while True:  # nosafe: unbounded_loops
    ...
```

**Suppress multiple rules** — keep the list short; a long list is a signal the code needs refactoring:
```python
def get_data(conn, query, p1, p2, p3, p4, p5, p6):  # nosafe: SAFE101, SAFE103
    ...
```

### End-of-run summary

When suppressions are active, the summary line reports the total count:

```text
Found 2 errors, 1 warning. [--fail-on=error].
No fixes available (safelint does not auto-fix violations). (3 suppressed via # nosafe)
```

If all active violations were suppressed:

```text
All checks passed. (3 suppressed via # nosafe)
No fixes available (safelint does not auto-fix violations). (3 suppressed via # nosafe)
```

### When to use suppression

Use `# nosafe` when:
- A violation is correct by design and fixing it would make the code worse (e.g. a deliberate `while True` polling loop with an external timeout).
- A third-party integration forces a pattern safelint flags (e.g. a framework-required function signature with many parameters).
- You are mid-refactor and need to commit a transitional state without breaking CI.

Prefer **config changes** (adjusting thresholds or disabling rules) over `# nosafe` when the exception applies to the entire project or a whole file pattern. Inline suppressions are for line-level exceptions only.

---

## Top-level options

| Key | Default | What it does |
|---|---|---|
| `mode` | `"local"` | Sets the default failure threshold. `"local"` = only errors block. `"ci"` = warnings block too. |
| `fail_on` | `"error"` | Minimum severity that blocks the run. `"error"` or `"warning"`. Overrides `mode`. |
| `exclude_paths` | `[]` | Glob patterns for files to skip entirely, e.g. `["tests/**", "migrations/**"]`. |
| `ignore` | `[]` | List of rule codes or names to suppress globally across the entire project. |

```toml
[tool.safelint]
mode = "local"
fail_on = "error"
exclude_paths = ["tests/**", "docs/**"]
ignore = ["SAFE203", "side_effects"]
```

---

## Global ignore list

The `ignore` key lets you suppress one or more rules project-wide without touching each rule's own config section. Both rule codes (e.g. `SAFE101`) and rule names (e.g. `function_length`) are accepted and can be mixed.

```toml
# pyproject.toml
[tool.safelint]
ignore = ["SAFE203", "SAFE304", "side_effects_hidden"]
```

```yaml
# .safelint.yaml
ignore:
  - SAFE203
  - SAFE304
  - side_effects_hidden
```

Rules in the `ignore` list are skipped entirely — they produce no violations and add no overhead.

### `ignore` vs. per-rule `enabled: false`

Both achieve the same result, but they serve different purposes:

| | `ignore` | `enabled: false` |
|---|---|---|
| Location | Single top-level list | Inside each rule's own section |
| Accepts | Code or name | — (the key is the name) |
| Best for | Quick, temporary suppression; CI overrides; onboarding | Permanent project policy for a specific rule |
| `--ignore` CLI flag | Yes — stacks on top of the config list | No CLI equivalent |

Use `ignore` (or `--ignore`) when you want to suppress a rule without committing to a permanent config change for that rule. Use `enabled: false` when the rule simply does not apply to your project.

### `--ignore` CLI flag

Pass codes or names on the command line to suppress rules for a single run. These stack on top of whatever is already in the config file's `ignore` list — they do not replace it.

```bash
# Ignore two rules for this run only
safelint check src/ --ignore SAFE203 side_effects

# Useful in CI to temporarily unblock a branch
safelint check src/ --all-files --fail-on=warning --ignore SAFE801
```

---

## Execution options

| Key | Default | What it does |
|---|---|---|
| `fail_fast` | `false` | Stop checking a file as soon as the first violation is found. Faster, but you only see one problem at a time. |
| `order` | see below | The order rules run in. Cheap structural rules run first so expensive dataflow checks are skipped when basics already fail. |

```toml
[tool.safelint.execution]
fail_fast = false
```

---

## Rules

Each rule has:
- A **code** - short identifier like `SAFE101`, shown in the output. Use this to search docs or issues.
- A **name** - the key used in config files.
- An **enabled** flag - set to `false` to turn the rule off.
- A **severity** - `"error"` blocks the commit; `"warning"` is informational.
- Rule-specific options documented below.

---

### Structural rules

These check the shape of your functions. They are cheap to run and always go first.

---

#### SAFE101 - `function_length`

**What it flags:** Functions longer than `max_lines` lines.

Long functions are hard to read, test, and reason about. The Holzmann rule says a function should fit on one printed page.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `max_lines` | `60` | Maximum allowed function length in lines |

```toml
[tool.safelint.rules.function_length]
enabled = true
severity = "error"
max_lines = 60
```

---

#### SAFE102 - `nesting_depth`

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

---

#### SAFE103 - `max_arguments`

**What it flags:** Functions with more than `max_args` parameters.

Too many arguments usually means a function is doing too much, or needs a config object. `self` and `cls` are excluded from the count.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `max_args` | `7` | Maximum number of parameters (excluding `self`/`cls`) |

```toml
[tool.safelint.rules.max_arguments]
enabled = true
severity = "error"
max_args = 7
```

---

#### SAFE104 - `complexity`

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

---

### Error handling rules

These check that exceptions are handled clearly and not swallowed silently.

---

#### SAFE201 - `bare_except`

**What it flags:** `except:` clauses with no exception type.

A bare `except:` catches everything including `KeyboardInterrupt` and `SystemExit`, which are signals - not bugs. Always specify the exception type you expect.

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

---

#### SAFE202 - `empty_except`

**What it flags:** `except` blocks with no statements in the body (just `pass`).

An empty except block silently swallows the error. The caller has no idea something went wrong.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.empty_except]
enabled = true
severity = "error"
```

---

#### SAFE203 - `logging_on_error`

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

---

### State and purity rules

These check for use of global variables and unexpected side effects in functions.

---

#### SAFE301 - `global_state`

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

---

#### SAFE302 - `global_mutation`

**What it flags:** Functions that declare `global x` and then assign to `x`.

This is stricter than `SAFE301`. A function that both declares a variable global *and* writes to it is mutating shared state - the most dangerous form of global use.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.global_mutation]
enabled = true
severity = "error"
```

---

#### SAFE303 - `side_effects_hidden`

**What it flags:** Functions with "pure-sounding" names that perform I/O.

A function named `calculate_total` or `get_user` implies it just computes and returns a value. If it secretly calls `open()`, `print()`, or `input()`, it is hiding a side effect. This is a core Holzmann risk - callers cannot reason about the function's behaviour.

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

---

#### SAFE304 - `side_effects`

**What it flags:** Any function that calls an I/O primitive and is not named to signal that fact.

Broader than `SAFE303` - applies to *all* functions, not just pure-named ones. A function named `process_order` that calls `print()` should be renamed to `log_order` or refactored to use dependency injection.

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

---

### Resource safety rules

---

#### SAFE401 - `resource_lifecycle`

**What it flags:** Calls to resource-acquisition functions (like `open()`) that are not inside a `with` block.

Resources that are opened must be closed. If an exception occurs between `open()` and `close()`, the resource leaks. A `with` block guarantees cleanup even if an exception is raised.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `tracked_functions` | `["open", "connect", "session"]` | Calls that must be inside a `with` block |
| `cleanup_patterns` | `["close", "commit", "rollback"]` | Acceptable cleanup method names as an alternative |

```toml
[tool.safelint.rules.resource_lifecycle]
enabled = true
severity = "error"
tracked_functions = ["open", "connect", "session", "cursor"]
cleanup_patterns = ["close", "commit", "rollback"]
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

---

### Loop safety rules

---

#### SAFE501 - `unbounded_loops`

**What it flags:** `while` loops that may run forever.

Two cases are flagged:
1. `while True:` with no `break` inside - guaranteed infinite loop.
2. `while <condition>:` where the condition is not a comparison - the loop bound is unclear.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.unbounded_loops]
enabled = true
severity = "warning"
```

---

### Documentation rules

---

#### SAFE601 - `missing_assertions`

**What it flags:** Functions that contain no `assert` statements.

Based on Holzmann rule 5: every function should have at least two assertions to validate its assumptions. This is a heuristic - disabled by default because many functions legitimately have no assertions (e.g. simple data transformations).

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default - opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.missing_assertions]
enabled = true
severity = "warning"
```

---

### Test coverage rules

These are disabled by default. Enable them in CI to enforce test discipline.

---

#### SAFE701 - `test_existence`

**What it flags:** Source files that have no corresponding test file.

For every file `src/mymodule/foo.py` it looks for `test_foo.py` under the configured `test_dirs`. If no matching test file is found, it flags the source file.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default - opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `test_dirs` | `["tests"]` | Directories to search for test files |

```toml
[tool.safelint.rules.test_existence]
enabled = true
severity = "warning"
test_dirs = ["tests", "test"]
```

---

#### SAFE702 - `test_coupling`

**What it flags:** Source files that were changed without a corresponding change to their test file.

If you modify `src/foo.py`, you must also modify `tests/test_foo.py` in the same commit. This enforces the discipline that source changes come with test updates. Unlike `SAFE701`, this requires the test file to exist - if it does not, `SAFE701` fires instead.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default - opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `test_dirs` | `["tests"]` | Directories to search for test files |

```toml
[tool.safelint.rules.test_coupling]
enabled = true
severity = "warning"
test_dirs = ["tests"]
```

---

### Dataflow rules

These combine AST analysis with intra-procedural taint tracking. They are more expensive than structural rules and **disabled by default**. Enable them when you need deeper security or correctness guarantees.

---

#### SAFE801 - `tainted_sink`

**What it flags:** User-controlled input (function parameters, `input()` calls) flowing into dangerous functions like `eval`, `exec`, or `subprocess` without being sanitized first.

The rule tracks data flow through assignments: if `x = user_data` then `x` is tainted. If `y = x + "_suffix"` then `y` is tainted too. Calling `eval(y)` then triggers a violation. Passing the value through a configured sanitizer (e.g. `escape(x)`) clears the taint.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default - opt-in |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `sinks` | see below | Call names considered dangerous |
| `sanitizers` | see below | Call names that clear taint |
| `sources` | see below | Call names that inject taint (in addition to parameters) |

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
```

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

---

#### SAFE802 - `return_value_ignored`

**What it flags:** Calls to functions whose return value signals success or failure, where the return value is discarded.

Calling `subprocess.run(["rm", "-rf", path])` as a bare statement (not assigning the result) means you never check whether the command succeeded. Same with `file.write()` - it returns the number of bytes written, and silently ignoring it means you may have written nothing.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default - opt-in |
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

---

#### SAFE803 - `null_dereference`

**What it flags:** Chained attribute access or subscript directly on a call that can return `None`, without a guard.

`dict.get()` returns `None` when the key is absent. Calling `.strip()` on the result without checking for `None` first will raise `AttributeError` at runtime. Same with ORM methods like `session.scalar()` or `cursor.fetchone()`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default - opt-in |
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

---

## Severity model

Every rule has a `severity` setting (`"error"` or `"warning"`). The global `fail_on` threshold controls what actually blocks a commit or CI run:

| `fail_on` | Blocks on | Use case |
|---|---|---|
| `"error"` | errors only | Default - good for onboarding a team |
| `"warning"` | errors and warnings | Strict - recommended for CI |

The `mode` setting is a shorthand:
- `mode = "local"` → `fail_on` defaults to `"error"`
- `mode = "ci"` → `fail_on` defaults to `"warning"`

CLI `--fail-on` always takes priority over the config file.

---

## Adoption path

If you are adding SafeLint to an existing project with many existing violations, start permissive and tighten over time:

```
Week 1  - mode: local,  fail_on: error    - get used to the tool, fix errors only
Week 4  - mode: ci,     fail_on: warning  - enforce warnings in CI
Later   - enable tainted_sink, return_value_ignored, null_dereference as needed
```
