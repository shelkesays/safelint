# Rules reference

Each rule has:

- A **code** — short identifier like `SAFE101`, shown in the output. Use this to search docs or issues.
- A **name** — the key used in config files.
- An **enabled** flag — set to `false` to turn the rule off.
- A **severity** — `"error"` blocks the commit; `"warning"` is informational.
- A **language scope** — most rules apply to both Python and JavaScript; a few are language-specific (see below).
- Rule-specific options documented below.

For top-level config keys (`mode`, `ignore`, `per_file_ignores`, …) see the [Configuration file](toml.md). For inline / file-level suppression see [Suppression mechanisms](suppression.md). JavaScript projects may also want to set a [runtime preset](toml.md#javascript-runtime-presets) so rule defaults match the deployment target (browser / Deno / Cloudflare Workers / Bun).

## Language coverage

| Scope | Count | Codes |
|---|---|---|
| **Cross-language** (Python and JavaScript) | 17 | SAFE101, SAFE102, SAFE103, SAFE104, SAFE202, SAFE203, SAFE302, SAFE303, SAFE304, SAFE401, SAFE501, SAFE601, SAFE701, SAFE702, SAFE801, SAFE802, SAFE803 |
| **Python-only** | 2 | SAFE201 (`bare_except` — JS catches always bind the error; no `KeyboardInterrupt` hijack hazard), SAFE301 (`global_state` — JS has no `global` keyword; SAFE302 covers JS's "writes to module-level state" cases) |
| **JavaScript-only** | 1 | SAFE305 (`wide_scope_declaration` — Python has no `var` / `let` / `const` distinction) |

The engine's per-language dispatch automatically skips rules whose `language` tuple doesn't include the active file's language. There's no manual configuration to do — drop a `.py` file in a JS project (or vice versa) and the right rules fire on each.

## At a glance

The table below is generated from the live rule registry (`safelint.rules.ALL_RULES`) and the per-rule defaults in `safelint.core.config.DEFAULTS` — it can't drift from the implementation. Click any code to jump to the detailed section below.

--8<-- "_rules_at_a_glance.md"

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

**What it flags:** `except` / `catch` blocks that handle an error without any logging call. Cross-language.

If you catch an exception and do something with it but never log it, the error is invisible. This rule requires at least one call to a logger method (`debug`, `info`, `warning`, `error`, `exception`, `critical`, plus the JavaScript `console.*` family of `log` / `info` / `warn` / `error` / `debug` / `trace`) inside the handler. Blocks that simply re-raise the exact caught binding (Python `raise`; JavaScript `throw e;` where `e` is the catch parameter) are exempt — throwing a *different* identifier or `new Error(...)` still requires logging.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.logging_on_error]
enabled = true
severity = "warning"
```

**Python — Bad:**

```python
try:
    risky()
except Exception:
    pass            # SAFE203 - error swallowed silently
```

**Python — Good:**

```python
try:
    risky()
except Exception:
    logger.exception("risky() failed")
```

**JavaScript — Bad:**

```javascript
try {
  risky();
} catch (e) {
  // SAFE203 - error swallowed silently
}
```

**JavaScript — Good:**

```javascript
try {
  risky();
} catch (e) {
  console.error("risky() failed", e);
}
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

**What it flags:** writes to module-level state from inside a function. Cross-language — the *intent* is the same in Python and JavaScript, but the syntactic shape differs.

**Python:** by default, functions that declare `global x` and then assign to `x`. With `strict = true`, *any* `global` declaration is flagged regardless of whether a write follows. This is stricter than `SAFE301`. The default behaviour is more nuanced than ruff's `PLW0603` (which fires on any `global`); set `strict = true` if your team's policy is to ban the keyword entirely.

**JavaScript:** function-body writes — `assignment_expression`, `augmented_assignment_expression`, or `update_expression` (`++` / `--`) — whose target is a `member_expression` or `subscript_expression` rooted in a configured global namespace. The receiver chain is walked leftward — `process.env.NODE_ENV = '...'`, `process.env['NODE_ENV'] = '...'`, and `process.exitCode++` all resolve to `process` and fire. Bracket-notation writes (`globalThis['x'] = 1`, `window["config"] = {}`) work the same way as dot access. The default namespace list (`global_namespaces_javascript`) is `["globalThis", "window", "global", "self", "process"]`; runtime presets adjust this (browser drops `process`, adds `document`; Deno adds `Deno`, drops `window` and `process`). Module-level (top-of-file) writes do NOT fire — that's setup, not the bug pattern. Reading a global (`return globalThis.env;`) does NOT fire — only writes.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `strict` | `false` | (Python only.) When `true`, fire on every `global` declaration even without a subsequent write — mirrors ruff's `PLW0603`. *Added in 1.8.0.* |
| `global_namespaces_javascript` | see above | (JavaScript only.) Receiver names that count as "global namespace" — function-body assignments rooted in any of these fire. *Added in 1.13.0.* |

```toml
[tool.safelint.rules.global_mutation]
enabled = true
severity = "error"
strict = false                                                       # Python: ban global keyword outright when true
global_namespaces_javascript = ["globalThis", "window", "process"]   # JavaScript: tighten or relax the namespace list
```

**Python — Bad:**

```python
COUNTER = 0

def bump():
    global COUNTER
    COUNTER += 1   # SAFE302 - function-body write to module-level state
```

**Python — Good:**

```python
def increment(counter):
    return counter + 1   # state flows through arguments / returns, not globals
```

**JavaScript — Bad:**

```javascript
// Bad — function-body write to a global namespace
function setupCache() {
  globalThis.cache = new Map();   // SAFE302
  process.env.READY = "true";     // SAFE302
}
```

**JavaScript — Good:**

```javascript
// Good — encapsulate state, return rather than mutate
function buildCache() {
  return new Map();
}
const cache = buildCache();   // module-level setup is fine; not flagged
```

### SAFE303 — `side_effects_hidden`

**What it flags:** Functions with "pure-sounding" names that perform I/O. Cross-language.

A function named `calculate_total` (Python) or `calculateTotal` (JavaScript) implies it just computes and returns a value. If it secretly calls `open()` / `print()` / `input()` (Python) or `console.log` / `fetch` / `fs.readFile` (JavaScript), it is hiding a side effect. This is a core Holzmann risk — callers cannot reason about the function's behaviour. The prefix-match check is case-insensitive on the lowercased function name, so it works equally on `snake_case` (Python convention) and `camelCase` (JavaScript convention).

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
| `io_functions` | `["open", "print", "input"]` | (Python.) Call names considered I/O |
| `io_functions_javascript` | see below | (JavaScript.) Call names considered I/O. Runtime presets (`[tool.safelint.javascript] runtime`) adjust this default. *Added in 1.13.0.* |
| `io_name_keywords` | see below | Functions whose names contain these words are exempt (cross-language) |

Default `io_name_keywords`: `print`, `log`, `write`, `read`, `save`, `load`, `send`, `fetch`, `export`, `import`. The substring check is case-insensitive, so it matches `writeData` (camelCase) the same way as `write_data` (snake_case).

Default `io_functions_javascript` (Node — the default): `["log", "error", "warn", "info", "debug", "fetch", "readFile", "writeFile", "readFileSync", "writeFileSync"]`. The browser / deno / cloudflare-workers presets swap in different verbs — see [JavaScript runtime presets](toml.md#javascript-runtime-presets).

```toml
[tool.safelint.rules.side_effects]
enabled = true
severity = "warning"
io_functions = ["open", "print", "input"]                                  # Python list
io_functions_javascript = ["log", "error", "warn", "fetch", "writeFile"]   # JavaScript list (overrides the runtime preset)
io_name_keywords = ["print", "log", "write", "read", "save", "load", "send", "fetch"]
```

**Python — Bad:**

```python
def process_order(order):
    print(f"processing {order}")   # SAFE304 - non-io-named function calls I/O
    return order
```

**Python — Good:**

```python
def log_order(order):              # name signals I/O — exempt
    print(f"processing {order}")
    return order
```

**JavaScript — Bad:**

```javascript
function processOrder(order) {
  console.log(`processing ${order}`);   // SAFE304 - non-io-named function calls I/O
  return order;
}
```

**JavaScript — Good:**

```javascript
function logOrder(order) {              // name contains ``log`` — exempt
  console.log(`processing ${order}`);
  return order;
}
```

### SAFE305 — `wide_scope_declaration`

**What it flags:** JavaScript `var` declarations. **JavaScript-only** — Python has no `var` / `let` / `const` distinction.

`var` is **function-scoped**: a `var` declared inside one branch of an `if` is visible throughout the entire enclosing function (and at module top, throughout the module), because the declaration is hoisted to the top of its containing function. `let` and `const` are **block-scoped**: they only exist inside the `{ ... }` they're declared in. The rule's intent matches Holzmann Power-of-Ten Rule 6 ("declare variables at the smallest possible scope") translated to JS's actual scope-control mechanism.

The fix is mechanical: replace `var` with `let` (when the binding is reassigned later) or `const` (when it isn't). The rule fires once per `variable_declaration` node — a multi-binding form like `var x = 1, y = 2;` produces a single violation (the line is the unit of fix, not each bound name).

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.wide_scope_declaration]
enabled = true
severity = "warning"
```

**Bad:**

```javascript
function f(items) {
  if (items.length > 0) {
    var first = items[0];   // SAFE305 - hoists; visible after the if
  }
  return first;             // accidentally accessible — exactly the bug
}

function doubleAndReturnLastIndex(arr) {
  for (var i = 0; i < arr.length; i++) {   // SAFE305 - i leaks out of the loop
    arr[i] = i * 2;
  }
  return i;                                 // i is still accessible — that's the bug
}
```

**Good:**

```javascript
function f(items) {
  if (items.length > 0) {
    const first = items[0];   // block-scoped to the if
    return first;
  }
  return undefined;
}

function doubleEach(arr) {
  for (let i = 0; i < arr.length; i++) {   // i is block-scoped to the loop
    arr[i] = i * 2;
  }
}
```

## Resource safety rules

### SAFE401 — `resource_lifecycle`

**What it flags:** Resource-acquisition calls that aren't wrapped in a cleanup-guaranteed scope. Cross-language with language-specific scope semantics.

**Python:** the call must appear inside a `with` statement (`with open(path) as f:`). Bare assignments without `with` fire even when paired with manual `f.close()` — Python's idiom is context-manager-first.

**JavaScript:** the call must appear inside a `try` block whose `try_statement` has a `finally_clause` somewhere up the AST ancestor chain. Heuristic-only — the rule doesn't verify that the `finally` block actually closes the specific resource. Captures the most common "I created a stream and didn't think about cleanup at all" leak. JavaScript's newer `using` declarations (Stage 3 / Node 22+) aren't yet recognised as a safe form; for now, wrap inside `try { ... } finally { ... }`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `tracked_functions` | (see below) | (Python.) Calls that must be inside a `with` block. Replaces the default list when set. |
| `extend_tracked_functions` | `[]` | (Python.) Appended to the default list — use this when you want to *add* custom functions without losing the defaults. *Added in 1.8.0.* |
| `cleanup_patterns` | `["close", "commit", "rollback", "release", "shutdown"]` | (Python.) Acceptable cleanup method names as an alternative |
| `tracked_functions_javascript` | (see below) | (JavaScript.) Calls that must be inside a `try { ... } finally { ... }`. Runtime presets (`[tool.safelint.javascript] runtime`) adjust this default. *Added in 1.13.0.* |

**Default `tracked_functions`** (Python, expanded in 1.8.0):

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

**Default `tracked_functions_javascript`** (Node — the default runtime):

```toml
tracked_functions_javascript = [
    "createReadStream", "createWriteStream", "openSync",   # fs
    "createServer", "createConnection", "connect",         # net / DB drivers
    "createWorker",                                        # worker pools
]
```

The browser / deno / cloudflare-workers presets swap in different lists — see [JavaScript runtime presets](toml.md#javascript-runtime-presets).

```toml
# Add custom Python acquirers without losing the defaults
[tool.safelint.rules.resource_lifecycle]
extend_tracked_functions = ["acquire_widget", "rent_db_handle"]
```

```toml
# Replace the JS tracked list entirely (overrides the runtime preset)
[tool.safelint.rules.resource_lifecycle]
tracked_functions_javascript = ["openSync", "createServer", "myCustomAcquirer"]
```

**Python — Bad:**

```python
f = open("data.txt")   # SAFE401 - not in a with block
data = f.read()
f.close()              # won't run if f.read() raises
```

**Python — Good:**

```python
with open("data.txt") as f:
    data = f.read()
```

**JavaScript — Bad:**

```javascript
function readData(path) {
  const stream = fs.createReadStream(path);   // SAFE401 - not wrapped in try/finally
  return processStream(stream);
}
```

**JavaScript — Good:**

```javascript
function readData(path) {
  let stream;
  try {
    stream = fs.createReadStream(path);
    return processStream(stream);
  } finally {
    if (stream) stream.close();
  }
}
```

## Loop safety rules

### SAFE501 — `unbounded_loops`

**What it flags:** `while` loops that may run forever. Cross-language.

Two cases are flagged:

1. **Literal-`true` condition with no `break` inside** — applies to both `while True:` (Python) and `while (true)` (JavaScript). Guaranteed infinite loop unless something inside the body breaks out.
2. **Non-comparison condition** — applies to Python only (`while x:` where `x` isn't a comparison expression). JS idioms like `while (queue.length)` and `while (token)` are commonly bounded, so the heuristic stays Python-only — flagging them on JS files would produce too much noise.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.unbounded_loops]
enabled = true
severity = "warning"
```

**Python — Bad:**

```python
def poll():
    while True:        # SAFE501 - no break inside
        check()
```

**Python — Good:**

```python
def poll():
    while True:
        if done():
            break       # break exits the loop — rule satisfied
        check()
```

**JavaScript — Bad:**

```javascript
function poll() {
  while (true) {   // SAFE501 - no break inside
    check();
  }
}
```

**JavaScript — Good:**

```javascript
function poll() {
  while (true) {
    if (done()) break;
    check();
  }
}
```

## Documentation rules

### SAFE601 — `missing_assertions`

**What it flags:** Functions that contain no assertion calls. Cross-language.

Based on Holzmann rule 5: every function should have at least two assertions to validate its assumptions. This is a heuristic — disabled by default because many functions legitimately have no assertions (e.g. simple data transformations).

Python walks for the AST `assert_statement` (built-in keyword). JavaScript has no built-in `assert` keyword, so the rule walks for *calls* to a configured set of assertion-function names — Node's `assert` module (`assert`, `ok`, `equal`, `strictEqual`, `deepEqual`, `match`, ...), `console.assert`, and test-framework idioms (`expect` for Jest / Chai-via-`expect`, `should` for Should.js, `vi.expect` for Vitest). Configure via `assertion_calls_javascript`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default — opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `assertion_calls_javascript` | (see default JS list above) | (JavaScript only.) Call names that satisfy the assertion check. *Added in 1.13.0.* |

```toml
[tool.safelint.rules.missing_assertions]
enabled = true
severity = "warning"
assertion_calls_javascript = ["assert", "expect", "should"]
```

**Python — Bad:**

```python
def transfer(amount, src, dst):    # SAFE601 - no assert statements
    src.balance -= amount
    dst.balance += amount
```

**Python — Good:**

```python
def transfer(amount, src, dst):
    assert amount > 0
    assert src.balance >= amount
    src.balance -= amount
    dst.balance += amount
```

**JavaScript — Bad:**

```javascript
function transfer(amount, src, dst) {   // SAFE601 - no assertion calls
  src.balance -= amount;
  dst.balance += amount;
}
```

**JavaScript — Good:**

```javascript
function transfer(amount, src, dst) {
  assert(amount > 0);
  assert(src.balance >= amount);
  src.balance -= amount;
  dst.balance += amount;
}
```

## Test coverage rules

These are disabled by default. Enable them in CI to enforce test discipline.

### SAFE701 — `test_existence`

**What it flags:** Source files that have no corresponding test file. Cross-language.

The expected test filename pattern is language-aware:

- **Python** — looks for `test_<stem>.py` (e.g. `src/mymodule/foo.py` pairs with `test_foo.py`).
- **JavaScript** — looks for `<stem>.test.<ext>` (Jest convention) or `<stem>.spec.<ext>` (Mocha / Karma convention) across all registered JS extensions (`.js` / `.mjs` / `.cjs`). For example `src/app/foo.js` pairs with `foo.test.js` *or* `foo.spec.js`.

The rule searches under the configured `test_dirs` for any of these patterns. Test files themselves (files under a `test_dirs` entry, or files whose names already match the pattern) are skipped — the rule doesn't ask a test to have its own test.

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

**What it flags:** Source files that were changed without a corresponding change to their test file. Cross-language.

If you modify `src/foo.py`, you must also modify `tests/test_foo.py` in the same commit. For JavaScript, modifying `src/foo.js` requires updating `foo.test.js` or `foo.spec.js`. This enforces the discipline that source changes come with test updates. Same filename patterns as SAFE701. Unlike `SAFE701`, this requires the test file to exist — if it does not, `SAFE701` fires instead.

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

**Python — Bad:**

```python
def run_query(user_input):
    cursor.execute(user_input)   # SAFE801 - tainted param reaches execute()
```

**Python — Good:**

```python
def run_query(user_input):
    safe = sanitize(user_input)
    cursor.execute(safe)          # sanitizer clears taint - no violation
```

**JavaScript — Bad:**

```javascript
function runQuery(userInput) {
  eval(userInput);                // SAFE801 - tainted param reaches eval()
}

function buildFn(userInput) {
  return new Function(userInput); // SAFE801 - Function constructor is a sink too
}
```

**JavaScript — Good:**

```javascript
function runQuery(userInput) {
  const safe = sanitize(userInput);
  someApi.run(safe);              // sanitizer clears taint - no violation
}
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

**Python — Bad:**

```python
subprocess.run(["deploy.sh"])    # SAFE802 - return value discarded
f.write(data)                    # SAFE802 - bytes written not checked
```

**Python — Good:**

```python
result = subprocess.run(["deploy.sh"])
if result.returncode != 0:
    raise RuntimeError("Deploy failed")
```

**JavaScript — Bad:**

```javascript
fs.writeFile("out.txt", data, cb);   // SAFE802 - the returned Promise is discarded
stream.write(buf);                   // SAFE802 - backpressure signal ignored
```

**JavaScript — Good:**

```javascript
await fs.promises.writeFile("out.txt", data);   // await surfaces failure
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

**Python — Bad:**

```python
name = config.get("username").strip()   # SAFE803 - .get() can return None
row = cursor.fetchone().value           # SAFE803 - fetchone() can return None
```

**Python — Good:**

```python
username = config.get("username")
name = username.strip() if username is not None else ""
```

**JavaScript — Bad:**

```javascript
const text = document.getElementById("title").textContent;   // SAFE803 - getElementById can return null
const first = users.find(u => u.id === id).name;             // SAFE803 - .find() can return undefined
```

**JavaScript — Good:**

```javascript
// Optional chaining — the modern guard
const text = document.getElementById("title")?.textContent;
const first = users.find(u => u.id === id)?.name;

// Or explicit check (catches both null and undefined via loose !=)
const el = document.getElementById("title");
if (el != null) {
  process(el.textContent);
}
```
