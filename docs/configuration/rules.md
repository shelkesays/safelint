# Rules reference

Each rule has:

- A **code**, short identifier like `SAFE101`, shown in the output. Use this to search docs or issues.
- A **name**, the key used in config files.
- An **enabled** flag, set to `false` to turn the rule off.
- A **severity**, `"error"` blocks the commit; `"warning"` is informational.
- A **language scope**, most rules apply to Python, JavaScript, and TypeScript; a few are language-specific (see below).
- Rule-specific options documented below.

For top-level config keys (`mode`, `ignore`, `per_file_ignores`, …) see the [Configuration file](toml.md). For inline / file-level suppression see [Suppression mechanisms](suppression.md). JavaScript projects may also want to set a [runtime preset](toml.md#javascript-runtime-presets) so rule defaults match the deployment target (browser / Deno / Cloudflare Workers / Bun).

## Language coverage

### Currently supported

- **Python** (`.py`, `.pyw`).
- **JavaScript** (`.js`, `.mjs`, `.cjs`), source analysis is runtime-agnostic and runs identically against Node.js, browser, Deno, Cloudflare Workers, Bun, and any WASM-hosted JS engine (QuickJS-WASM, Boa, etc.). Per-runtime *defaults* (the lists of tracked acquirers, sinks, sources, global namespaces, etc.) are switchable via the [`[tool.safelint.javascript] runtime = "..."`](toml.md#javascript-runtime-presets) preset, the source-language rules themselves don't change.
- **TypeScript** (`.ts`, `.tsx`), and **AssemblyScript** (`.as`, TypeScript-syntax language compiling to WebAssembly, parsed by the same grammar). Reuses the JavaScript rule implementations end-to-end (TS compiles to JS at runtime; AST is a superset), with TS-specific handling for type-only constructs the JS rules wouldn't otherwise recognise (generic type parameters, `as` casts, non-null assertions, `declare global` ambient declarations, etc.). Shares the JavaScript runtime presets, TS doesn't get its own runtime config because TS source executes in the same runtimes JS does. See [TypeScript](../languages/typescript.md) for the full language reference.
- **Java** (`.java`), new in v2.1.0. 20 rules apply (the 15 cross-language core plus the 5 also registered for Python / JS / TS) plus 4 Spring Boot framework-specific structural rules (`SAFE901-904`) target Spring annotation patterns. Per-framework *defaults* (sinks, nullable methods, structural rule enablement) are switchable via the [`[tool.safelint.java] framework = "..."`](../languages/java.md#framework-presets) preset (`vanilla` / `spring-boot`). See [Java](../languages/java.md) for the full language reference.
- **Rust** (`.rs`), new in v2.2.0. 15 of the cross-language rules port cleanly (the all-five-languages set) plus 11 Rust-only rules cover Rust-idiom-specific patterns (panic-in-non-test, lock poisoning, `unsafe` block documentation, truncating `as` casts, silent `Err` arms, dangerous `mem::*` ops, needless `mut`, unchecked arithmetic on integer parameters, broad `.unwrap()` outside tests, interior-mutable `static`s, plus the empty-`Err` / unlogged-`Err` Rust analogues of `empty_except` / `logging_on_error`). 7 rules deliberately skipped for Rust because their semantics don't translate cleanly (Rust has no try/catch / `global` keyword, RAII / Drop covers resource cleanup, and macros are opaque to the rule-8 dynamic-execution check). Recognises both inline `#[cfg(test)] mod tests` and Cargo `tests/<stem>.rs` integration-test conventions. See [Rust](../languages/rust.md) for the full language reference.
- **Go** (`.go`), new in v2.5.0. 16 cross-language rules apply (the 13 all-language core plus SAFE302 / SAFE309 / SAFE401, which Go shares with Python / JS / TS / Java / PHP but Rust skips) and 2 Go-only rules cover Go-idiom patterns: SAFE209 (`empty_error_check`, the empty `if err != nil {}` swallow) and SAFE211 (`panic_calls_outside_tests`). 7 rules deliberately skipped for Go because their semantics don't translate cleanly (no try/catch, no `global` keyword, no `var` hoisting, no production assertion idiom, no chained-nullable idiom). Headline Go adaptations: the bare `for {}` infinite loop (SAFE501), the sibling `foo_test.go` convention (SAFE701 / SAFE702), the `_ = f()` explicit-discard exemption (SAFE802), and the `defer x.Close()` resource form (SAFE401). See [Go](../languages/go.md) for the full language reference.
- **PHP** (`.php`), new in v2.6.0. 21 rules apply and only 2 are skipped (SAFE201 `bare_except` and SAFE305 `wide_scope_declaration`), the widest rule coverage of any non-Python language because PHP ports the largest share of the existing rule set. PHP is the **first non-Python home for SAFE301 (`global_state`)**: PHP has a literal `global` keyword, so the rule fires on `global $config;`-style declarations exactly as it does on Python. PHP also has try/catch (SAFE202 / SAFE203 apply), `eval` and dynamic-call surfaces (SAFE309), and resource lifecycles (SAFE401). Headline PHP highlights: the `@`-operator error-suppression idiom, superglobal taint sources (`$_GET` / `$_POST` / `$_REQUEST` / etc.) feeding SAFE801, and the `break N;` / `continue N;` multi-level loop forms. See [PHP](../languages/php.md) for the full language reference.

- **C** (`.c`, `.h`), new in v2.7.0. Holzmann's original target language. 21 rules apply: the 16 cross-language ports plus **5 new C-family rules** (the "homecoming", shared with C++) that express clauses every other language adapts away - SAFE106 (`nonlocal_jumps`, `goto` / `setjmp`), SAFE310 (`dynamic_allocation`, the `malloc` family), SAFE311 (`complex_macro`) and SAFE312 (`conditional_compilation`) for the preprocessor, and SAFE313 (`restricted_pointers`). SAFE106 is the only one enabled by default (warning severity, because `goto err` cleanup is idiomatic); the other four are opt-in. `.h` headers are linted as C. 5 rules are skipped (SAFE201/202/203, SAFE301, SAFE305) plus SAFE401 and SAFE803 (documented gaps - C cleanup and nil analysis need flow analysis). See [C](../languages/c.md) for the full language reference.
- **C++** (`.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`), new in v2.8.0. Builds on C: the five C-family rules widen to C and C++, plus C++ gains its `try` / `catch` / `throw` rules (SAFE201 catch-all, SAFE202, SAFE203) and **two new C++-only rules** - SAFE315 (`raw_new_delete`) and SAFE316 (`dangerous_casts`). 26 rules apply. Plain `.h` headers are linted as C; use `.hpp` / `.hxx` / `.hh` for C++ headers. See [C++](../languages/cpp.md) for the full language reference.

### Planned

No languages are currently on the near-term roadmap. SafeLint's registry-driven architecture (see [Adding a language](../contributing/adding-a-language.md)) makes each new language incremental, community contributions are welcome.

### Rule scope (current languages)

| Scope | Count | Codes |
|---|---|---|
| **Cross-language** (all nine: Python, JavaScript, TypeScript, Java, Rust, Go, PHP, C, C++) | 13 | SAFE101, SAFE102, SAFE103, SAFE104, SAFE105 (`no_recursion`), SAFE303, SAFE304, SAFE501, SAFE603 (`blanket_suppression`), SAFE701, SAFE702, SAFE801, SAFE802 (apply to all nine). |
| **Python / JS / TS / Java / Rust / PHP / C / C++** (not Go) | 1 | SAFE601 (`missing_assertions`); Go has no production assertion idiom. C / C++ have the literal `assert` macro. |
| **Python / JS / TS / Java / Rust / PHP** (not Go, not C, not C++) | 1 | SAFE803 (`null_dereference`); no chained-nullable idiom in Go, and C / C++ nil analysis needs flow analysis (documented gap). |
| **Python / JS / TS / Java / Go / PHP / C / C++** (not Rust) | 2 | SAFE302 (`global_mutation`), SAFE309 (`dynamic_code_execution`). Rust's analogues are SAFE307 + SAFE602 (mutable statics) and an opaque token-tree limitation for rule 8. C / C++ fire on file-scope (and, for C++, namespace-scope) mutable declarations (SAFE302) and `dlopen` / `dlsym` (SAFE309). |
| **Python / JS / TS / Java / Go / PHP** (not Rust, not C, not C++) | 1 | SAFE401 (`resource_lifecycle`). Rust and C++ use Drop / RAII; C cleanup (`goto err`, explicit `fclose` / `free`) needs flow analysis the rule does not do (documented gap - allocation discipline is C's SAFE310, C++'s is SAFE310 / SAFE315). |
| **Python / JS / TS / Java / PHP / C++** (not Rust, not Go, not C) | 2 | SAFE202 (`empty_except`), SAFE203 (`logging_on_error`). C++ gains `try` / `catch`; C has no try/catch. Neither Rust nor Go has try/catch; Rust's analogues are SAFE206 / SAFE207, and Go's empty-`if err != nil` swallow is covered by SAFE209. |
| **Python + PHP** | 1 | SAFE301 (`global_state`); both have a literal `global` keyword, JS / TS / Java / Rust / Go / C / C++ do not. |
| **Python + C++** | 1 | SAFE201 (`bare_except`); Python's bare `except:` and C++'s `catch (...)` catch-all. JS / TS / Java catches always bind the error, and Rust / Go / PHP / C have no bare-catch equivalent. |
| **JavaScript-family-only** (JS and TS) | 1 | SAFE305 (`wide_scope_declaration`); Python / Java / Rust / Go / PHP have no `var` / `let` / `const` distinction. |
| **Java + Spring Boot only** | 4 | SAFE901 (`spring_field_injection`), SAFE902 (`spring_missing_transactional`), SAFE903 (`spring_unvalidated_input`), SAFE904 (`spring_async_checked_exception`); all default-disabled under vanilla, default-enabled by the `spring-boot` framework preset. |
| **Rust-only** | 11 | SAFE110 (`needless_mut`), SAFE112 (`unchecked_arithmetic_on_input`), SAFE204 (`panic_macros_outside_tests`), SAFE205 (`lock_poisoning_ignored`), SAFE206 (`silent_result_discard`, the Rust analogue of SAFE202), SAFE207 (`unlogged_error_branch`, the Rust analogue of SAFE203), SAFE208 (`result_unwrap_outside_tests`), SAFE306 (`dangerous_mem_ops`), SAFE307 (`interior_mutable_static`), SAFE308 (`truncating_as_cast`), SAFE602 (`undocumented_unsafe`); all default-disabled. |
| **Go-only** | 2 | SAFE209 (`empty_error_check`, the Go analogue of SAFE206), SAFE211 (`panic_calls_outside_tests`, the Go analogue of SAFE204); both default-disabled. |
| **C-family** (C and C++) | 5 | SAFE106 (`nonlocal_jumps`, `goto` / `setjmp`; **enabled at warning severity**), SAFE310 (`dynamic_allocation`; on C++ also `new` / `delete`), SAFE311 (`complex_macro`), SAFE312 (`conditional_compilation`), SAFE313 (`restricted_pointers`; smart pointers exempt on C++); the last four default-disabled. The Power-of-Ten clauses (rules 1, 3, 8, 9) every other language adapts away. |
| **C++-only** | 2 | SAFE315 (`raw_new_delete`), SAFE316 (`dangerous_casts`); both default-disabled. Modern-C++ ownership / type-safety idioms (3xx band). |

The engine's per-language dispatch automatically skips rules whose `language` tuple doesn't include the active file's language. There's no manual configuration to do, drop a `.py` file in a JS / TS project (or vice versa) and the right rules fire on each.

## At a glance

The table below is generated from the live rule registry (`safelint.rules.ALL_RULES`) and the per-rule defaults in `safelint.core.config.DEFAULTS`, it can't drift from the implementation. Click any code to jump to the detailed section below.

--8<-- "_rules_at_a_glance.md"

## Engine-internal codes

A few codes are emitted by the engine directly rather than by registered `BaseRule` subclasses. They don't have their own config section and follow the global `ignore` list. Inline `# nosafe: SAFE0xx` works for codes emitted *after* parsing (such as SAFE004, see below) but **not** for SAFE000, because parse errors are raised before the engine has a chance to read suppression directives off the tree.

### SAFE000: `parse`

**What it flags:** Tree-sitter parse errors (syntax errors, broken indentation, missing tokens). The violation carries the offending token's column as a zero-width caret so editors can mark the precise location.

Always severity `error`. Cannot be configured per-rule.

**Inline `# nosafe: SAFE000` does *not* work.** Parse errors are raised by `SafetyEngine._lint_parsed_source` *before* it parses inline suppression directives off the Tree-sitter tree (see the early-return at the parse-error check). The only way to silence SAFE000 is the global `ignore` list, which is read at engine init from your config file:

```toml
[tool.safelint]
ignore = ["SAFE000"]   # or ignore = ["parse"], rule name also accepted
```

Use this when you genuinely don't want parse errors surfaced (rare, usually you *do* want to know when a file failed to parse).

### SAFE004: `unused_suppression` *(added in 1.8.0)*

**What it flags:** A `# nosafe` directive on a line where no violation actually fired, i.e. the suppression is stale (e.g. left over after a refactor that removed the offending code).

```python
def f():
    x = 1   # nosafe: SAFE304   ← SAFE304 doesn't fire here; SAFE004 reports
    return x
```

Severity is fixed at `warning`. Disable globally via `ignore = ["SAFE004"]` if your workflow involves many transient suppressions you'd rather not police. **Per-file ignores do not apply to SAFE004**: like SAFE000, it's an engine-internal code gated solely on the global `ignore` list (configuring it inside `per_file_ignores` will surface a typo-guard warning and otherwise do nothing). Self-referential `# nosafe: SAFE004` is special-cased; a directive that only mentions SAFE004 is always considered "used" to avoid recursion.

## Structural rules

These check the shape of your functions. They are cheap to run and always go first.

### SAFE101: `function_length`

**What it flags:** Functions longer than `max_lines` (interpreted under the configured `count_mode`). Cross-language.

Long functions are hard to read, test, and reason about. The Holzmann rule says a function should fit on one printed page.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `max_lines` | `60` | Maximum allowed function size (units depend on `count_mode`) |
| `count_mode` | `"lines"` | How to measure size: `"lines"` (raw source lines incl. blanks/comments, Holzmann's original framing), `"logical_lines"` (lines minus blanks and pure-comment lines, less game-able), or `"statements"` (count Python statement nodes, robust to formatting, equivalent to ruff's `PLR0915`). *Added in 1.8.0.* |

```toml
[tool.safelint.rules.function_length]
enabled = true
severity = "error"
max_lines = 60
count_mode = "lines"      # default; alternatives: "logical_lines", "statements"
```

When switching to `"statements"`, lower `max_lines` accordingly, a function with 60 source lines typically corresponds to ~25–35 statement nodes. Pick a value that matches the spirit of "function fits on a page" for your codebase.

### SAFE102: `nesting_depth`

**What it flags:** Functions with control-flow nested more than `max_depth` levels deep. Cross-language.

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

### SAFE103: `max_arguments`

**What it flags:** Functions with more than `max_args` parameters. Cross-language.

Too many arguments usually means a function is doing too much, or needs a config object. `self` and `cls` are excluded from the count. `*args` and `**kwargs` each count as one parameter; they bring real callers, just an unbounded number of them, so they cannot be free.

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

### SAFE104: `complexity`

**What it flags:** Functions with cyclomatic complexity above `max_complexity`. Cross-language.

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

### SAFE105: `no_recursion`

**What it flags:** Functions that call themselves directly. Cross-language.

Holzmann's Power of Ten rule 1 ("restrict all code to very simple control flow constructs") bans recursion outright: recursion without a guaranteed bound makes the call stack an unbounded resource, so worst-case depth (and therefore termination and memory behaviour) cannot be proven by inspection. An explicit loop with a worklist makes the bound visible.

The rule fires on **direct self-recursion** - a function whose body contains a call to its own name, either bare (`fact(n - 1)`) or self-qualified (`self.walk(...)` in Python / Rust, `this.walk(...)` in JS / TS / Java). A call on a different receiver (`other.walk(...)`) does not fire. Two cases are intentionally out of scope and documented as blind spots: **indirect / mutual recursion** (`a` calls `b` calls `a`), which needs a call graph, and **anonymous-function recursion** through a binding (`const f = () => f()`), since the function has no name to match.

Enabled by default at `warning` severity (mirrors `unbounded_loops`), so intentional recursion (tree walks, divide-and-conquer) does not block a local run. Annotate deliberate recursion with `# nosafe: SAFE105` (or the language's comment form) and a one-line justification.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.no_recursion]
enabled = true
severity = "warning"
```

### SAFE106: `nonlocal_jumps`

**What it flags:** `goto` statements and `setjmp` / `longjmp` family calls. **C and C++**, new in v2.7.0 (widened to C++ in v2.8.0). This is Holzmann's rule 1 ("restrict all code to very simple control flow constructs") expressed literally - C and C++ are the registered languages with `goto` / `setjmp`.

`goto` and the `setjmp` / `longjmp` non-local-jump pair bypass structured control flow, so worst-case control paths cannot be reasoned about by inspection. The rule fires on every `goto_statement` and every call to a configured non-local-jump function (`setjmp` / `longjmp` / `sigsetjmp` / `siglongjmp`).

**Enabled by default at `warning` severity.** The paper bans `goto` outright, but the `goto err` cleanup chain is pervasive, idiomatic C; shipping it as a non-blocking warning surfaces every jump without breaking `--fail-on=error` builds. Annotate a sanctioned cleanup with `// nosafe: SAFE106`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `nonlocal_jump_calls_c` | `["setjmp", "longjmp", "sigsetjmp", "siglongjmp"]` | Call names treated as non-local jumps alongside `goto` |

```toml
# pyproject.toml
[tool.safelint.rules.nonlocal_jumps]
nonlocal_jump_calls_c = ["setjmp", "longjmp", "sigsetjmp", "siglongjmp"]
```

```toml
# safelint.toml
[rules.nonlocal_jumps]
nonlocal_jump_calls_c = ["setjmp", "longjmp", "sigsetjmp", "siglongjmp"]
```

## Error handling rules

These check that exceptions are handled clearly and not swallowed silently.

### SAFE201: `bare_except`

**What it flags:** `except:` clauses with no exception type. **Python and C++** - Python's `except:` and C++'s `catch (...)` catch-all (its first non-Python home). JavaScript `catch` clauses always bind the caught error (and don't have the `KeyboardInterrupt` / `SystemExit` hijack hazard), so there's no equivalent hazard to flag on JS files; SAFE202 + SAFE203 cover the related JS concerns.

A bare `except:` catches everything including `KeyboardInterrupt` and `SystemExit`, which are signals, not bugs. Always specify the exception type you expect.

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

### SAFE202: `empty_except`

**What it flags:** `except` / `catch` blocks whose body is effectively a no-op. Cross-language.

- `except E: pass`
- `except E: continue`
- `except E: ...` (Ellipsis)
- `except E: 0` / `None` / `True` / `False` (constant literals)
- `except E: "TODO"` / `""` (string-as-comment idiom)

An empty except block silently swallows the error. The caller has no idea something went wrong. *Broadened in 1.8.0*, earlier versions only matched a literally empty body which Tree-sitter doesn't actually produce for valid Python, so the rule was effectively dead code.

Multi-statement bodies are not flagged even if every statement looks trivial, two consecutive no-ops suggest *some* intentional structure and would generate false positives.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.empty_except]
enabled = true
severity = "error"
```

### SAFE203: `logging_on_error`

**What it flags:** `except` / `catch` blocks that handle an error without any logging call. Cross-language.

If you catch an exception and do something with it but never log it, the error is invisible. This rule requires at least one call to a logger method (`debug`, `info`, `warning`, `error`, `exception`, `critical`, plus the JavaScript `console.*` family of `log` / `info` / `warn` / `error` / `debug` / `trace`) inside the handler. Blocks that simply re-raise the exact caught binding (Python `raise`; JavaScript `throw e;` where `e` is the catch parameter) are exempt; throwing a *different* identifier or `new Error(...)` still requires logging.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.logging_on_error]
enabled = true
severity = "warning"
```

**Python, Bad:**

```python
try:
    risky()
except Exception:
    pass            # SAFE203 - error swallowed silently
```

**Python, Good:**

```python
try:
    risky()
except Exception:
    logger.exception("risky() failed")
```

**JavaScript, Bad:**

```javascript
try {
  risky();
} catch (e) {
  // SAFE203 - error swallowed silently
}
```

**JavaScript, Good:**

```javascript
try {
  risky();
} catch (e) {
  console.error("risky() failed", e);
}
```

## State and purity rules

These check for use of global variables and unexpected side effects in functions.

### SAFE301: `global_state`

**What it flags:** Functions that declare the `global` keyword. **Python and PHP** (the two languages with a literal `global` declaration form). JavaScript has no `global` read-only declaration form; on JS this rule would always be a strict subset of SAFE302 (`global_mutation`), so it isn't separately registered. JS users get the same protection from SAFE302 alone.

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

### SAFE302: `global_mutation`

**What it flags:** shared module / global mutable state. Cross-language (Python, JavaScript, TypeScript, Java), the *intent* (Holzmann rule 6: declare data at the smallest possible scope) is the same, but the syntactic shape differs per language.

**Python:** by default, functions that declare `global x` and then assign to `x`. With `strict = true`, *any* `global` declaration is flagged regardless of whether a write follows. This is stricter than `SAFE301`. The default behaviour is more nuanced than ruff's `PLW0603` (which fires on any `global`); set `strict = true` if your team's policy is to ban the keyword entirely.

**JavaScript:** function-body writes, `assignment_expression`, `augmented_assignment_expression`, or `update_expression` (`++` / `--`), whose target is a `member_expression` or `subscript_expression` rooted in a configured global namespace. The receiver chain is walked leftward, `process.env.NODE_ENV = '...'`, `process.env['NODE_ENV'] = '...'`, and `process.exitCode++` all resolve to `process` and fire. Bracket-notation writes (`globalThis['x'] = 1`, `window["config"] = {}`) work the same way as dot access. The default namespace list (`global_namespaces_javascript`) is `["globalThis", "window", "global", "self", "process"]`; runtime presets adjust this (browser drops `process`, adds `document`; Deno adds `Deno`, drops `window` and `process`). Module-level (top-of-file) writes do NOT fire, that's setup, not the bug pattern. Reading a global (`return globalThis.env;`) does NOT fire, only writes.

**Java** *(added in 2.4.0):* non-final `static` field declarations. This is **declaration-site** detection, not write-site: a mutable static field IS the smallest-scope violation regardless of where it is written, and a single tree walk over field declarations has near-zero false positives (the same shape PMD's `MutableStaticState` flags). `static final` fields are clean, even when the referent is interiorly mutable (`static final List<String> CACHE = new ArrayList<>()`) - detecting interior mutability would need type resolution safelint does not do, so it is a documented exclusion. Instance fields and local variables never fire. Interface fields are implicitly `public static final` and so are never flagged. This fulfils the Java SAFE302 work previously deferred in the language docs. **Rust** is not covered by SAFE302: `static mut` is unsafe-gated (SAFE602's territory) and safe interior-mutable statics are covered by SAFE307 (`interior_mutable_static`). **Go** *(added in 2.5.0):* declaration-site detection on every package-level `var`, including sentinel errors (`var ErrNotFound = errors.New(...)`) - the rule does not special-case the initialiser, so treat sentinels as immutable by suppressing with a per-file ignore or `//nosafe` if desired. `const` declarations and block-scoped `var` / `:=` inside functions are clean.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `strict` | `false` | (Python only.) When `true`, fire on every `global` declaration even without a subsequent write, mirrors ruff's `PLW0603`. *Added in 1.8.0.* |
| `global_namespaces_javascript` | see above | (JavaScript only.) Receiver names that count as "global namespace", function-body assignments rooted in any of these fire. *Added in 1.13.0.* |

```toml
[tool.safelint.rules.global_mutation]
enabled = true
severity = "error"
strict = false                                                       # Python: ban global keyword outright when true
global_namespaces_javascript = ["globalThis", "window", "process"]   # JavaScript: tighten or relax the namespace list
```

**Python, Bad:**

```python
COUNTER = 0

def bump():
    global COUNTER
    COUNTER += 1   # SAFE302 - function-body write to module-level state
```

**Python, Good:**

```python
def increment(counter):
    return counter + 1   # state flows through arguments / returns, not globals
```

**JavaScript, Bad:**

```javascript
// Bad, function-body write to a global namespace
function setupCache() {
  globalThis.cache = new Map();   // SAFE302
  process.env.READY = "true";     // SAFE302
}
```

**JavaScript, Good:**

```javascript
// Good, encapsulate state, return rather than mutate
function buildCache() {
  return new Map();
}
const cache = buildCache();   // module-level setup is fine; not flagged
```

### SAFE303: `side_effects_hidden`

**What it flags:** Functions with "pure-sounding" names that perform I/O. Cross-language.

A function named `calculate_total` (Python) or `calculateTotal` (JavaScript) implies it just computes and returns a value. If it secretly calls `open()` / `print()` / `input()` (Python) or `console.log` / `fetch` / `fs.readFile` (JavaScript), it is hiding a side effect. This is a core Holzmann risk, callers cannot reason about the function's behaviour. The prefix-match check is case-insensitive on the lowercased function name, so it works equally on `snake_case` (Python convention) and `camelCase` (JavaScript convention).

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

### SAFE304: `side_effects`

**What it flags:** Any function that calls an I/O primitive and is not named to signal that fact. Cross-language.

Broader than `SAFE303`, applies to *all* functions, not just pure-named ones. A function named `process_order` that calls `print()` should be renamed to `log_order` or refactored to use dependency injection.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `io_functions` | `["open", "print", "input"]` | (Python.) Call names considered I/O |
| `io_functions_javascript` | see below | (JavaScript.) Call names considered I/O. Runtime presets (`[tool.safelint.javascript] runtime`) adjust this default. *Added in 1.13.0.* |
| `io_name_keywords` | see below | Functions whose names contain these words are exempt (cross-language) |

Default `io_name_keywords`: `print`, `log`, `write`, `read`, `save`, `load`, `send`, `fetch`, `export`, `import`. The substring check is case-insensitive, so it matches `writeData` (camelCase) the same way as `write_data` (snake_case).

Default `io_functions_javascript` (Node, the default): `["log", "error", "warn", "info", "debug", "fetch", "readFile", "writeFile", "readFileSync", "writeFileSync"]`. The browser / deno / cloudflare-workers presets swap in different verbs, see [JavaScript runtime presets](toml.md#javascript-runtime-presets).

```toml
[tool.safelint.rules.side_effects]
enabled = true
severity = "warning"
io_functions = ["open", "print", "input"]                                  # Python list
io_functions_javascript = ["log", "error", "warn", "fetch", "writeFile"]   # JavaScript list (overrides the runtime preset)
io_name_keywords = ["print", "log", "write", "read", "save", "load", "send", "fetch"]
```

**Python, Bad:**

```python
def process_order(order):
    print(f"processing {order}")   # SAFE304 - non-io-named function calls I/O
    return order
```

**Python, Good:**

```python
def log_order(order):              # name signals I/O, exempt
    print(f"processing {order}")
    return order
```

**JavaScript, Bad:**

```javascript
function processOrder(order) {
  console.log(`processing ${order}`);   // SAFE304 - non-io-named function calls I/O
  return order;
}
```

**JavaScript, Good:**

```javascript
function logOrder(order) {              // name contains ``log``, exempt
  console.log(`processing ${order}`);
  return order;
}
```

### SAFE305: `wide_scope_declaration`

**What it flags:** JavaScript `var` declarations. **JavaScript-only**, Python has no `var` / `let` / `const` distinction.

`var` is **function-scoped**: a `var` declared inside one branch of an `if` is visible throughout the entire enclosing function (and at module top, throughout the module), because the declaration is hoisted to the top of its containing function. `let` and `const` are **block-scoped**: they only exist inside the `{ ... }` they're declared in. The rule's intent matches Holzmann Power-of-Ten Rule 6 ("declare variables at the smallest possible scope") translated to JS's actual scope-control mechanism.

The fix is mechanical: replace `var` with `let` (when the binding is reassigned later) or `const` (when it isn't). The rule fires once per `variable_declaration` node, a multi-binding form like `var x = 1, y = 2;` produces a single violation (the line is the unit of fix, not each bound name).

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
  return first;             // accidentally accessible, exactly the bug
}

function doubleAndReturnLastIndex(arr) {
  for (var i = 0; i < arr.length; i++) {   // SAFE305 - i leaks out of the loop
    arr[i] = i * 2;
  }
  return i;                                 // i is still accessible, that's the bug
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

### SAFE309: `dynamic_code_execution`

**What it flags:** runtime code generation and reflection. Python, JavaScript, TypeScript, Java. Disabled by default.

Holzmann's rule 8 restricts the preprocessor because textual code generation defeats static analysis: a tool cannot reason about code that does not exist until runtime. The modern equivalent is `eval` / `exec`-style execution and reflection. SAFE309 is **structural**, it flags the construct wherever it appears, with no dataflow. That is the difference from SAFE801 (`tainted_sink`), which fires only when user input demonstrably reaches one of these sinks. The two are complementary and may both fire on the same line; an untainted `eval(config_string)` still destroys analysability, which is what rule 8 cares about.

Per-language defaults (call names):

- **Python** (`dynamic_exec_calls`): `eval`, `exec`, `compile`, `__import__`. Only **bare** calls and `builtins.`-qualified calls fire, so `model.eval()` (a method call) does not. `getattr` / `setattr` are deliberately excluded (far too common, and they do not generate code).
- **JavaScript / TypeScript** (`dynamic_exec_calls_javascript`): `eval`, `Function` (both `new Function(...)` and the bare `Function(...)` call), `execScript`. A bare-identifier callee is required, so `obj.eval()` does not fire. `setTimeout` / `setInterval` with a string first argument (the implicit-eval form) are deliberately not in the defaults: flagging every `setTimeout` would be noise, and detecting only the string-argument form is not worth the complexity for a near-extinct idiom; add them via the config list if your codebase still uses the string form.
- **Java** (`dynamic_exec_calls_java`): `forName` (`Class.forName`), `invoke` (`Method.invoke`), `eval` (JSR-223 `ScriptEngine`), `defineClass`, `loadClass`. Matched by method name regardless of receiver, so a user-defined `forName` would also match (acceptable for an off-by-default rule).

**Rust** is excluded: its rule-8 analogue is the macro system, whose bodies parse as opaque token trees (a documented limitation shared with SAFE801), and `panic`-family macros already have SAFE204. **Go** *(added in 2.5.0):* Go has no `eval`; the rule-8 surface is reflection (`reflect` `Call` / `CallSlice` / `MethodByName`) and plugin loading (`plugin` `Open` / `Lookup`), via `dynamic_exec_calls_go`. Matching is by bare method name, so `Open` also matches `os.Open` - narrow the list if noisy.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `dynamic_exec_calls` | see above | (Python) call names that count as dynamic execution |
| `dynamic_exec_calls_javascript` | see above | (JS / TS) call / constructor names |
| `dynamic_exec_calls_java` | see above | (Java) reflection method names |

```toml
# pyproject.toml
[tool.safelint.rules.dynamic_code_execution]
enabled = true
severity = "warning"
# Per-language call lists (each replaces that language's default):
dynamic_exec_calls = ["eval", "exec", "compile", "__import__"]        # Python (bare key)
dynamic_exec_calls_javascript = ["eval", "Function", "execScript"]    # JS / TS (TS inherits via fallback)
dynamic_exec_calls_java = ["forName", "invoke", "defineClass", "loadClass"]   # Java
```

```toml
# standalone safelint.toml (same keys, no [tool.safelint] prefix)
[rules.dynamic_code_execution]
enabled = true
```

### SAFE310: `dynamic_allocation`

**What it flags:** Calls to the heap-allocation / free family. **C and C++**, new in v2.7.0 (widened to C++ in v2.8.0). Holzmann's rule 3 ("do not use dynamic memory allocation after initialisation") expressed literally - on C++ it additionally flags `new` / `delete` expressions.

Fires on every call to a configured allocator (`malloc` / `calloc` / `realloc` / `aligned_alloc` / `free` / `strdup`). **Disabled by default** - embedded and safety-critical projects opt in; most application C uses the heap freely. Pre-allocate fixed pools / arenas at init and hand out slots to satisfy the rule.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Turn rule on/off |
| `allocation_calls_c` | `["malloc", "calloc", "realloc", "aligned_alloc", "free", "strdup"]` | Allocator call names |

```toml
# pyproject.toml
[tool.safelint.rules.dynamic_allocation]
enabled = true
allocation_calls_c = ["malloc", "calloc", "realloc", "aligned_alloc", "free", "strdup", "xmalloc"]
```

```toml
# safelint.toml
[rules.dynamic_allocation]
enabled = true
allocation_calls_c = ["malloc", "calloc", "realloc", "aligned_alloc", "free", "strdup", "xmalloc"]
```

### SAFE311: `complex_macro`

**What it flags:** Preprocessor macros that are not simple, complete syntactic units. **C and C++**, new in v2.7.0 (widened to C++ in v2.8.0). Holzmann's rule 8 ("limit the preprocessor to header files and simple macros").

Fires on function-like macros that use token pasting (`##`) or variadic `__VA_ARGS__`, and on object-like macros whose replacement text is not a balanced syntactic unit (heuristic: unbalanced `()` / `{}` / `[]`, ignoring brackets inside string and character literals). Mutually recursive macro definitions (the paper's third banned construct) are not detected; that needs macro-table analysis. **Disabled by default.**

```toml
# pyproject.toml
[tool.safelint.rules.complex_macro]
enabled = true
```

```toml
# safelint.toml
[rules.complex_macro]
enabled = true
```

### SAFE312: `conditional_compilation`

**What it flags:** `#if` / `#ifdef` / `#ifndef` directives beyond the include-guard idiom. **C and C++**, new in v2.7.0 (widened to C++ in v2.8.0). Holzmann's rule 8 again: each conditional-compilation directive doubles the number of build configurations that must be tested (2^n versions from n flags).

An `#ifndef X` + `#define X` pair (a header include guard) is exempt; the matching `#define` must be the first substantive statement of the block, with comments (e.g. an SPDX / licence header) and `#pragma` lines (a belt-and-braces `#pragma once`) allowed in between. Every other `#if` / `#ifdef` / `#ifndef` fires. **Disabled by default.** Prefer runtime configuration over compile-time flags.

```toml
# pyproject.toml
[tool.safelint.rules.conditional_compilation]
enabled = true
```

```toml
# safelint.toml
[rules.conditional_compilation]
enabled = true
```

### SAFE313: `restricted_pointers`

**What it flags:** Declarators with more than one level of pointer indirection (`int **p`) and function-pointer declarators (`void (*fp)(int)`). **C and C++**, new in v2.7.0 (widened to C++ in v2.8.0; smart pointers exempt on C++). Holzmann's rule 9 ("limit pointer use to a single dereference, and do not use function pointers") expressed literally. The check is syntactic (declarator shape only): a pointer level hidden behind a `typedef` or a macro is not counted - the paper's no-hidden-dereference clause needs type resolution and is a documented gap.

**Disabled by default** - it is deliberately strict (`char **argv` fires too). Opt in for the highest-assurance profiles; collapse multi-level pointers behind a struct or out-parameter, and replace function pointers with tagged dispatch.

```toml
# pyproject.toml
[tool.safelint.rules.restricted_pointers]
enabled = true
```

```toml
# safelint.toml
[rules.restricted_pointers]
enabled = true
```

## C++ idiom rules

Two C++-only rules capture modern-C++ ownership / type-safety idioms that have no analogue in the other languages. Both are **disabled by default**. New in v2.8.0.

### SAFE315: `raw_new_delete`

**What it flags:** Every `new` and `delete` expression. **C++-only.** The modern-ownership rule: prefer `std::make_unique` / `std::make_shared` and RAII so a scoped owner releases memory automatically and cannot be forgotten on an early return or exception. `std::make_unique` / `std::make_shared` contain no `new` expression and never fire; a raw `new` inside a `std::unique_ptr<T>(new T)` argument still fires (prefer `make_unique`).

It **overlaps the widened SAFE310** (`dynamic_allocation`) by design: SAFE310 is the Holzmann no-allocation-after-init posture (embedded / safety-critical), SAFE315 the ownership posture (leak safety). Enabling both double-reports a raw `new`, the same intentional overlap as SAFE205 / SAFE208.

```toml
# pyproject.toml
[tool.safelint.rules.raw_new_delete]
enabled = true
```

```toml
# safelint.toml
[rules.raw_new_delete]
enabled = true
```

### SAFE316: `dangerous_casts`

**What it flags:** `reinterpret_cast` and `const_cast` expressions. **C++-only.** These defeat the type / const system: `reinterpret_cast` reinterprets a bit pattern with no checking, `const_cast` strips `const` (undefined behaviour if the underlying object is truly `const`). `static_cast` and `dynamic_cast` are compiler-checked and stay clean. The named casts parse as a `call_expression` whose callee is a `template_function`, so the rule matches on the template callee name.

The flagged list is configurable via `dangerous_casts_cpp` - narrow it, or add `static_cast` if your profile forbids all named casts.

```toml
# pyproject.toml
[tool.safelint.rules.dangerous_casts]
enabled = true
dangerous_casts_cpp = ["reinterpret_cast", "const_cast"]
```

```toml
# safelint.toml
[rules.dangerous_casts]
enabled = true
dangerous_casts_cpp = ["reinterpret_cast", "const_cast"]
```

## Resource safety rules

### SAFE401: `resource_lifecycle`

**What it flags:** Resource-acquisition calls that aren't wrapped in a cleanup-guaranteed scope. Cross-language with language-specific scope semantics.

**Python:** the call must appear inside a `with` statement (`with open(path) as f:`). Bare assignments without `with` fire even when paired with manual `f.close()`, Python's idiom is context-manager-first.

**JavaScript:** the call must appear inside a `try` block whose `try_statement` has a `finally_clause` somewhere up the AST ancestor chain. Heuristic-only: the rule doesn't verify that the `finally` block actually closes the specific resource. Captures the most common "I created a stream and didn't think about cleanup at all" leak. JavaScript's newer `using` declarations (Stage 3 / Node 22+) aren't yet recognised as a safe form; for now, wrap inside `try { ... } finally { ... }`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `tracked_functions` | (see below) | (Python.) Calls that must be inside a `with` block. Replaces the default list when set. |
| `extend_tracked_functions` | `[]` | (Python.) Appended to the default list, use this when you want to *add* custom functions without losing the defaults. *Added in 1.8.0.* |
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

**Default `tracked_functions_javascript`** (Node, the default runtime):

```toml
tracked_functions_javascript = [
    "createReadStream", "createWriteStream", "openSync",   # fs
    "createServer", "createConnection", "connect",         # net / DB drivers
    "createWorker",                                        # worker pools
]
```

The browser / deno / cloudflare-workers presets swap in different lists, see [JavaScript runtime presets](toml.md#javascript-runtime-presets).

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

**Python, Bad:**

```python
f = open("data.txt")   # SAFE401 - not in a with block
data = f.read()
f.close()              # won't run if f.read() raises
```

**Python, Good:**

```python
with open("data.txt") as f:
    data = f.read()
```

**JavaScript, Bad:**

```javascript
function readData(path) {
  const stream = fs.createReadStream(path);   // SAFE401 - not wrapped in try/finally
  return processStream(stream);
}
```

**JavaScript, Good:**

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

### SAFE501: `unbounded_loops`

**What it flags:** `while` loops that may run forever. Cross-language.

Two cases are flagged:

1. **Literal-`true` condition with no `break` inside**, applies to both `while True:` (Python) and `while (true)` (JavaScript). Guaranteed infinite loop unless something inside the body breaks out.
2. **Non-comparison condition**, applies to Python only (`while x:` where `x` isn't a comparison expression). JS idioms like `while (queue.length)` and `while (token)` are commonly bounded, so the heuristic stays Python-only, flagging them on JS files would produce too much noise.

| Option | Default | Description |
|---|---|---|
| `enabled` | `true` | Turn rule on/off |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.unbounded_loops]
enabled = true
severity = "warning"
```

**Python, Bad:**

```python
def poll():
    while True:        # SAFE501 - no break inside
        check()
```

**Python, Good:**

```python
def poll():
    while True:
        if done():
            break       # break exits the loop, rule satisfied
        check()
```

**JavaScript, Bad:**

```javascript
function poll() {
  while (true) {   // SAFE501 - no break inside
    check();
  }
}
```

**JavaScript, Good:**

```javascript
function poll() {
  while (true) {
    if (done()) break;
    check();
  }
}
```

## Documentation rules

### SAFE601: `missing_assertions`

**What it flags:** Functions with fewer than `min_assertions` assertions. Cross-language.

Based on Holzmann rule 5: the paper asks for an assertion density averaging a minimum of **two** assertions per function. The rule defaults to `min_assertions = 1` (any assertion satisfies it) to keep noise low; paper-strict projects set `min_assertions = 2`. Disabled by default because many functions legitimately have no assertions (e.g. simple data transformations).

Two further clauses of the paper's rule 5 are intentionally out of scope: assertions must be **side-effect free** (safelint does not analyse assertion expressions for effects), and a trivially-true assertion (`assert True`) **counts toward the threshold** even though the paper disallows assertions a static checker can prove never fail. Both need analysis machinery (effect inference, constant propagation) that does not fit a structural rule; review remains the guard there.

Python walks for the AST `assert_statement` (built-in keyword). JavaScript has no built-in `assert` keyword, so the rule walks for *calls* to a configured set of assertion-function names, Node's `assert` module (`assert`, `ok`, `equal`, `strictEqual`, `deepEqual`, `match`, ...), `console.assert`, and test-framework idioms (`expect` for Jest / Chai-via-`expect`, `should` for Should.js, `vi.expect` for Vitest). Configure via `assertion_calls_javascript`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default, opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `min_assertions` | `1` | Minimum assertions per function; set `2` for the paper's density. *Added in 2.4.0.* |
| `assertion_calls_javascript` | (see default JS list above) | (JavaScript only.) Call names that satisfy the assertion check. *Added in 1.13.0.* |

```toml
# pyproject.toml
[tool.safelint.rules.missing_assertions]
enabled = true
severity = "warning"
min_assertions = 2                # Holzmann rule 5 density; default is 1
assertion_calls_javascript = ["assert", "expect", "should"]
```

```toml
# standalone safelint.toml (same keys, no [tool.safelint] prefix)
[rules.missing_assertions]
enabled = true
min_assertions = 2
```

**Python, Bad:**

```python
def transfer(amount, src, dst):    # SAFE601 - no assert statements
    src.balance -= amount
    dst.balance += amount
```

**Python, Good:**

```python
def transfer(amount, src, dst):
    assert amount > 0
    assert src.balance >= amount
    src.balance -= amount
    dst.balance += amount
```

**JavaScript, Bad:**

```javascript
function transfer(amount, src, dst) {   // SAFE601 - no assertion calls
  src.balance -= amount;
  dst.balance += amount;
}
```

**JavaScript, Good:**

```javascript
function transfer(amount, src, dst) {
  assert(amount > 0);
  assert(src.balance >= amount);
  src.balance -= amount;
  dst.balance += amount;
}
```

### SAFE603: `blanket_suppression`

**What it flags:** un-scoped suppressions of *other* analysers. Cross-language (all nine registered languages). Disabled by default.

Holzmann's rule 10 ("compile with all warnings enabled and heed every warning") has a modern failure mode: not disabling warnings at the compiler, but silencing an entire analyser from inside the source. SAFE603 flags the *blanket* forms while leaving *scoped* suppressions alone, because a scoped suppression is a deliberate, auditable decision about one rule.

Per language, the blanket forms that fire (and the scoped forms that stay clean):

- **Python** (comments): bare `noqa` (no `: code` list), `type: ignore` with no `[code]` qualifier, `pylint: disable=all`. Scoped (`noqa: E501`, `type: ignore[arg-type]`, `pylint: disable=line-too-long`) is clean.
- **JavaScript / TypeScript** (comments): `eslint-disable` / `eslint-disable-line` / `eslint-disable-next-line` with no rule list, `@ts-nocheck`, `@ts-ignore`. `@ts-expect-error` is clean (it self-polices: it errors when the suppressed error no longer occurs). A rule-listed `eslint-disable no-console` is clean.
- **Java** (annotations): `@SuppressWarnings("all")` and `@SuppressWarnings({..., "all"})`. Scoped (`@SuppressWarnings("unchecked")`) is clean.
- **Rust** (attributes): `#[allow(clippy::all)]`, `#[allow(warnings)]`, and their inner `#![...]` forms. Scoped (`#[allow(dead_code)]`, `#[allow(clippy::too_many_arguments)]`) is clean.
- **Go** (comments): bare `//nolint` (all linters) and bare `//lint:ignore` (recognised only with no space after `//`, golangci's requirement). Scoped (`//nolint:errcheck`, `//lint:ignore SA1000 reason`) is clean.
- **PHP**: the `@` error-suppression operator (`@file_get_contents(...)`) - PHP's headline blanket-suppression hazard - plus blanket `@phpstan-ignore` / `@psalm-suppress all`-style directives. Scoped forms are clean.
- **C / C++** (comments): clang-tidy's bare `// NOLINT` / `// NOLINTNEXTLINE`. Scoped `// NOLINT(bugprone-foo)` is clean.

SAFE603 never flags safelint's own `# nosafe` / `# safelint: ignore` directives, those are policed by SAFE004 (unused suppression). Directive-looking text inside a string literal is not flagged either, the detectors scan comment / annotation / attribute nodes, not string contents.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default, opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |

```toml
[tool.safelint.rules.blanket_suppression]
enabled = true
severity = "warning"
```

## Test coverage rules

These are disabled by default. Enable them in CI to enforce test discipline.

### SAFE701: `test_existence`

**What it flags:** Source files that have no corresponding test file. Cross-language.

The expected test filename pattern is language-aware:

- **Python**, looks for `test_<stem>.py` (e.g. `src/mymodule/foo.py` pairs with `test_foo.py`).
- **JavaScript**, looks for `<stem>.test.<ext>` (Jest convention) or `<stem>.spec.<ext>` (Mocha / Karma convention) across all registered JS extensions (`.js` / `.mjs` / `.cjs`). For example `src/app/foo.js` pairs with `foo.test.js` *or* `foo.spec.js`.

The rule searches under the configured `test_dirs` for any of these patterns. Test files themselves (files under a `test_dirs` entry, or files whose names already match the pattern) are skipped; the rule doesn't ask a test to have its own test.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default, opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `test_dirs` | `["tests"]` | Directories to search for test files |

```toml
[tool.safelint.rules.test_existence]
enabled = true
severity = "warning"
test_dirs = ["tests", "test"]
```

### SAFE702: `test_coupling`

**What it flags:** Source files that were changed without a corresponding change to their test file. Cross-language.

If you modify `src/foo.py`, you must also modify `tests/test_foo.py` in the same commit. For JavaScript, modifying `src/foo.js` requires updating `foo.test.js` or `foo.spec.js`. This enforces the discipline that source changes come with test updates. Same filename patterns as SAFE701. Unlike `SAFE701`, this requires the test file to exist; if it does not, `SAFE701` fires instead.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default, opt-in |
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

### SAFE801: `tainted_sink`

**What it flags:** User-controlled input (function parameters, `input()` calls in Python, `prompt()` / `confirm()` / `getItem()` in JS, etc.) flowing into dangerous functions like `eval`, `exec`, `subprocess` (Python) or `eval` / `Function` / `child_process` (JavaScript) without being sanitized first. Cross-language.

The rule tracks data flow through assignments: if `x = user_data` then `x` is tainted. If `y = x + "_suffix"` then `y` is tainted too. Calling `eval(y)` then triggers a violation. Passing the value through a configured sanitizer (e.g. `escape(x)`) clears the taint.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default, opt-in |
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

The naming says it directly: when ``assume_taint_preserving = true``, the analyser assumes any unknown call preserves the taint of its arguments, the more **conservative** stance, fewer false negatives, more false positives:

- **`true` (default)**, conservative / taint-preserving. An unknown call's result is tainted iff any of its arguments are tainted. ``eval(user_input)`` fires (direct flow). ``eval(wrap(user_input))`` *also* fires (taint flows through the unknown ``wrap``). Cost: false positives when ``wrap`` is in fact safe.
- **`false`**, taint-dropping (less conservative, *weaker* detection). Unknown calls always drop taint. ``eval(user_input)`` still fires (direct flow). ``eval(wrap(user_input))`` does **not** fire, the unknown ``wrap`` resets taint, even if it does in fact pass user input through. Use when your codebase has many internal-only wrappers and you'd rather miss a flow than chase down false positives.

Note the asymmetry: `false` is the *less* conservative setting (fewer reports, more chance of missing real issues), not "stricter". The trade-off is fundamental to intra-procedural analysis, there's no way to know whether ``wrap`` actually preserves the taint without inlining it. Switch modes based on which failure mode hurts more in your codebase.

**Python, Bad:**

```python
def run_query(user_input):
    cursor.execute(user_input)   # SAFE801 - tainted param reaches execute()
```

**Python, Good:**

```python
def run_query(user_input):
    safe = sanitize(user_input)
    cursor.execute(safe)          # sanitizer clears taint - no violation
```

**JavaScript, Bad:**

```javascript
function runQuery(userInput) {
  eval(userInput);                // SAFE801 - tainted param reaches eval()
}

function buildFn(userInput) {
  return new Function(userInput); // SAFE801 - Function constructor is a sink too
}
```

**JavaScript, Good:**

```javascript
function runQuery(userInput) {
  const safe = sanitize(userInput);
  someApi.run(safe);              // sanitizer clears taint - no violation
}
```

### SAFE802: `return_value_ignored`

**What it flags:** Calls to functions whose return value signals success or failure, where the return value is discarded. Cross-language.

Calling `subprocess.run(["rm", "-rf", path])` as a bare statement (not assigning the result) means you never check whether the command succeeded. Same with `file.write()`, it returns the number of bytes written, and silently ignoring it means you may have written nothing.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default, opt-in |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `flagged_calls` | see below | Call names whose return value must not be discarded |

Default `flagged_calls`: `run`, `call`, `check_output`, `write`, `send`, `sendall`, `sendfile`, `seek`, `truncate`, `remove`, `unlink`, `rename`, `replace`, `makedirs`, `mkdir`, `rmdir`

```toml
[tool.safelint.rules.return_value_ignored]
enabled = true
severity = "warning"
flagged_calls = ["run", "write", "send", "remove", "unlink"]
```

**Python, Bad:**

```python
subprocess.run(["deploy.sh"])    # SAFE802 - return value discarded
f.write(data)                    # SAFE802 - bytes written not checked
```

**Python, Good:**

```python
result = subprocess.run(["deploy.sh"])
if result.returncode != 0:
    raise RuntimeError("Deploy failed")
```

**JavaScript, Bad:**

```javascript
fs.writeFile("out.txt", data, cb);   // SAFE802 - the returned Promise is discarded
stream.write(buf);                   // SAFE802 - backpressure signal ignored
```

**JavaScript, Good:**

```javascript
await fs.promises.writeFile("out.txt", data);   // await surfaces failure
```

### SAFE803: `null_dereference`

**What it flags:** Chained attribute access or subscript directly on a call that can return `None` (Python) / `null` or `undefined` (JavaScript), without a guard. Cross-language.

`dict.get()` returns `None` when the key is absent. Calling `.strip()` on the result without checking for `None` first will raise `AttributeError` at runtime. Same with ORM methods like `session.scalar()` or `cursor.fetchone()`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Disabled by default, opt-in |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `nullable_methods` | see below | Method names whose return value may be `None` |

Default `nullable_methods`: `get`, `pop`, `find`, `next`, `first`, `one_or_none`, `scalar`, `scalar_one_or_none`, `fetchone`

```toml
[tool.safelint.rules.null_dereference]
enabled = true
severity = "error"
nullable_methods = ["get", "pop", "find", "fetchone", "first"]
```

**Python, Bad:**

```python
name = config.get("username").strip()   # SAFE803 - .get() can return None
row = cursor.fetchone().value           # SAFE803 - fetchone() can return None
```

**Python, Good:**

```python
username = config.get("username")
name = username.strip() if username is not None else ""
```

**JavaScript, Bad:**

```javascript
const text = document.getElementById("title").textContent;   // SAFE803 - getElementById can return null
const first = users.find(u => u.id === id).name;             // SAFE803 - .find() can return undefined
```

**JavaScript, Good:**

```javascript
// Optional chaining, the modern guard
const text = document.getElementById("title")?.textContent;
const first = users.find(u => u.id === id)?.name;

// Or explicit check (catches both null and undefined via loose !=)
const el = document.getElementById("title");
if (el != null) {
  process(el.textContent);
}
```

## Java + Spring Boot rules

`SAFE9xx` rules are Java-only structural checks for common Spring Boot misuses. All four are disabled by default and enabled together by the `spring-boot` framework preset (`[tool.safelint.java] framework = "spring-boot"`). They do not fire on Python / JavaScript / TypeScript files even if explicitly enabled; rule dispatch is gated on file language.

### SAFE901: `spring_field_injection`

**What it flags:** A class field annotated with `@Autowired` (or the fully-qualified `@org.springframework.beans.factory.annotation.Autowired`). Java only.

Spring's reference documentation recommends constructor injection over field injection: constructor-injected dependencies are immutable (`final`), testable without reflection, fail fast on missing beans at construction time, and surface obvious circular dependencies as compile errors. Field-injected dependencies hide all of those properties.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` (vanilla) / `true` (spring-boot preset) | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```java
@Service
public class OrderService {
    @Autowired
    private InventoryClient inventory;   // SAFE901
}
```

**Good:**

```java
@Service
public class OrderService {
    private final InventoryClient inventory;

    public OrderService(InventoryClient inventory) {
        this.inventory = inventory;
    }
}
```

### SAFE902: `spring_missing_transactional`

**What it flags:** A `@Service` or `@Component` method that performs two or more Spring Data repository writes (`save` / `saveAll` / `saveAndFlush` / `delete` / `deleteAll` / `deleteAllInBatch` / `deleteAllById` / `deleteAllByIdInBatch` / `deleteById` / `update`) without `@Transactional` on the method or the enclosing class. Java only.

Multi-write methods without `@Transactional` run each write in its own short-lived transaction; a failure between writes leaves the database in a partially-updated state. Single-write methods are exempt because the implicit per-statement transaction is sufficient.

**Receiver-name heuristic:** detection is constrained to method invocations whose receiver name (lowercased) contains `repo` / `dao` / `jdbctemplate`, e.g. `userRepo.save(...)`, `productDao.update(...)`, `jdbcTemplate.update(...)`. Without this guard, `call_name()` strips the receiver and unrelated calls like `file.delete()` / `cache.delete()` / `restTemplate.delete(...)` would be counted. Rename a service-managed field if your convention is `userStore` / `userManager` / etc., or add the matching pattern via `[tool.safelint.rules.spring_missing_transactional]` configuration in a future release (currently the pattern set is fixed at the source level).

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` (vanilla) / `true` (spring-boot preset) | Toggle the rule |
| `severity` | `"error"` | `"error"` or `"warning"` |

**Bad:**

```java
@Service
public class OrderService {
    public void placeOrder(Order order) {
        orderRepo.save(order);
        inventoryRepo.update(order.itemId(), -1);   // SAFE902: 2 writes, no @Transactional
    }
}
```

**Good:**

```java
@Service
public class OrderService {
    @Transactional
    public void placeOrder(Order order) {
        orderRepo.save(order);
        inventoryRepo.update(order.itemId(), -1);
    }
}
```

### SAFE903: `spring_unvalidated_input`

**What it flags:** A `@RestController` or `@Controller` method parameter annotated with `@RequestBody` or `@ModelAttribute` that is NOT also annotated with `@Valid` or `@Validated`. Java only.

Without `@Valid` / `@Validated`, Bean Validation constraints declared on the DTO (`@NotNull`, `@Size`, `@Email`, etc.) are silently ignored. Malformed or hostile input reaches the controller body. `@PathVariable` and `@RequestParam` are deliberately NOT covered because they typically bind to primitives or simple strings where bean validation is rarely declared.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` (vanilla) / `true` (spring-boot preset) | Toggle the rule |
| `severity` | `"error"` | `"error"` or `"warning"` |

**Bad:**

```java
@RestController
public class UserController {
    @PostMapping("/users")
    public User create(@RequestBody UserDto dto) { ... }   // SAFE903: no @Valid
}
```

**Good:**

```java
@RestController
public class UserController {
    @PostMapping("/users")
    public User create(@Valid @RequestBody UserDto dto) { ... }
}
```

### SAFE904: `spring_async_checked_exception`

**What it flags:** A method annotated `@Async` that declares a `throws` clause. Java only.

The rule's name and historical framing emphasised checked exceptions, but the implementation flags **any** `throws` clause (checked or unchecked) because distinguishing the two requires class-resolution / type-inference we don't do. The conservative behaviour is justified: Spring's executor swallows whatever the method throws regardless of checked-vs-unchecked, so the `throws` clause is always misleading - it implies the caller can observe the exception when in fact they cannot. Fix by either catching inside the method body or returning a `CompletableFuture` whose failure state carries the exception (`CompletableFuture.failedFuture(ex)`).

If you have a deliberate `throws RuntimeException` on an `@Async` method (rare; the JLS doesn't require it), suppress with `// nosafe: SAFE904` on the method declaration.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` (vanilla) / `true` (spring-boot preset) | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```java
@Service
public class IngestService {
    @Async
    public void process(File f) throws IOException { ... }   // SAFE904
}
```

**Good:**

```java
@Service
public class IngestService {
    @Async
    public CompletableFuture<Void> process(File f) {
        try {
            // ... I/O work
            return CompletableFuture.completedFuture(null);
        } catch (IOException e) {
            return CompletableFuture.failedFuture(e);
        }
    }
}
```

## Rust-only rules

The following 10 rules apply only to Rust source. They cover patterns the cross-language rules don't translate to cleanly (Rust has no try/catch, no `global` keyword, RAII handles resource cleanup), or that are uniquely valuable in Rust idiom (`unsafe` documentation, panic placement, lock poisoning, etc.). All ship disabled by default; opt in via `[tool.safelint.rules.<name>] enabled = true`. See [Rust](../languages/rust.md) for the full language reference including idiomatic fix patterns.

### SAFE110: `needless_mut`

**What it flags:** `let mut x = ...` where `x` is never reassigned, never has `&mut x` taken, and is never used as a method receiver / field-access target / index target. Rust only.

Rust's default-immutable design encourages declaring `mut` only when truly needed. Needless `mut` widens the surface for accidental mutation and obscures which variables are actually meant to change. The rule is conservative - skips when usage is ambiguous (method call, field expression, index expression) to keep false-positive rate low. Mirrors `clippy::needless_mut` for projects without a clippy run. Holzmann rule 6 (smallest scope).

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```rust
let mut x = compute();
println!("{}", x);   // never reassigned - SAFE110
```

**Good:**

```rust
let x = compute();
println!("{}", x);
```

### SAFE112: `unchecked_arithmetic_on_input`

**What it flags:** `+` / `-` / `*` (NOT `/` or `%`) where at least one operand is an `identifier` matching an integer-typed function parameter. Rust only.

Rust's bare `+` / `-` / `*` panic on overflow in debug builds and wrap silently in release builds - the worst of both worlds for production reliability. `checked_*` / `wrapping_*` / `saturating_*` make the choice explicit. `/` and `%` are excluded - division by zero is a separate panic-on-debug hazard not addressed by the `checked_*` family the same way. Static-only detection (parameter type annotations); locally-derived integers aren't tracked - `cargo clippy` covers the type-inference version. Holzmann rule 7 (check return values).

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```rust
pub fn total(price: u32, quantity: u32) -> u32 {
    price * quantity        // silent overflow in release - SAFE112
}
```

**Good:**

```rust
pub fn total(price: u32, quantity: u32) -> Result<u32, &'static str> {
    price.checked_mul(quantity).ok_or("overflow")
}
```

### SAFE204: `panic_macros_outside_tests`

**What it flags:** `panic!` / `todo!` / `unimplemented!` macro invocations in non-test code. Rust only.

Production code should return `Result<_, _>` instead of crashing. Panics in test code (`#[test]` / `#[cfg(test)] mod`) are expected - they're the test framework's failure signal - so test context is exempt. `unreachable!()` is deliberately excluded from defaults - it's idiomatic for impossible-branch markers in `match` arms.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `panic_macros_rust` | `["panic", "todo", "unimplemented"]` | Macro names that count as "panicking". Add `"unreachable"` if you want it flagged. |

**Bad:**

```rust
pub fn parse_config(path: &str) -> Config {
    let raw = std::fs::read_to_string(path).unwrap();
    if raw.is_empty() {
        panic!("config is empty");   // SAFE204
    }
    serde_yaml::from_str(&raw).unwrap()
}
```

**Good:**

```rust
pub fn parse_config(path: &str) -> Result<Config, ConfigError> {
    let raw = std::fs::read_to_string(path)?;
    if raw.is_empty() {
        return Err(ConfigError::Empty);
    }
    serde_yaml::from_str(&raw).map_err(ConfigError::Parse)
}
```

### SAFE205: `lock_poisoning_ignored`

**What it flags:** `mutex.lock().unwrap()` / `rwlock.read().unwrap()` / `.write().unwrap()` / `try_lock().unwrap()` / `try_read().unwrap()` / `try_write().unwrap()` and the `.expect("...")` variants. Rust only.

When a thread panics while holding a `Mutex` / `RwLock` guard, the lock becomes *poisoned*: subsequent acquisitions return `Err(PoisonError)`. `.unwrap()` cascades the panic to every other lock holder, often masking the original failure. Safer alternatives: `match` on `PoisonResult`, `.into_inner()` to recover explicitly, or `parking_lot::Mutex` which has no poison state.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```rust
let guard = mutex.lock().unwrap();   // panics on poison - SAFE205
```

**Good:**

```rust
let guard = mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
```

### SAFE206: `silent_result_discard`

**What it flags:** Empty `Err` arms in `match` (`Err(_) => {}`) and empty `if let Err(_) = ... { }` bodies. Rust only.

The Rust spiritual analogue of `SAFE202 empty_except` - "I caught the error and did literally nothing." Both wildcard (`Err(_)`) and binding (`Err(e)`) forms count; the silent thing is the no-op body. `let _ = result;` and `result.ok();` do NOT fire - those are explicit auditable discards, not silent swallows. `if let Ok(v) = result { ... }` without `else` doesn't fire either (common idiom where the Err case is handled elsewhere).

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```rust
match maybe_save(record) {
    Ok(_) => {},
    Err(_) => {}   // silent swallow - SAFE206
}
```

**Good:**

```rust
match maybe_save(record) {
    Ok(_) => {},
    Err(e) => log::error!("save failed: {:?}", e),
}
```

### SAFE207: `unlogged_error_branch`

**What it flags:** `Err` arms / `if let Err(...)` bodies with non-empty bodies that contain no log call and don't propagate / panic. Rust only.

The Rust spiritual analogue of `SAFE203 logging_on_error` - handling an error without logging it loses the failure context. Recognised log calls: `error!` / `warn!` / `info!` / `debug!` / `trace!` / `log!` / `event!` (log + tracing crates), `eprintln!` / `eprint!` / `println!` / `print!` / `dbg!`. Exempts bodies that contain a `return_expression`, a panic-like macro (`panic!` / `todo!` / `unreachable!` / `unimplemented!`), or a tail-position `Err(...)` re-raise.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```rust
if let Err(e) = save(record) {
    cleanup();   // handled but unlogged - SAFE207
}
```

**Good:**

```rust
if let Err(e) = save(record) {
    log::error!("save failed: {:?}", e);
    cleanup();
}
```

### SAFE208: `result_unwrap_outside_tests`

**What it flags:** Any `.unwrap()` / `.expect()` / `.unwrap_unchecked()` outside test code (`#[test]` / `#[cfg(test)] mod` exempt). Rust only.

The broad Holzmann-rule-7 form: catches bare-variable unwraps (`let r = foo(); r.unwrap();`) and unwrap chains the narrower SAFE205 (lock-specific) / SAFE803 (nullable-method-specific) rules don't cover. With all three enabled, `mutex.lock().unwrap()` fires multiple codes - documented intentional overlap; users pick strictness level by enabling subsets. `unwrap_or` / `unwrap_or_default` / `unwrap_or_else` are NOT flagged - they're explicit-default-on-Err, not silent failures.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```rust
pub fn read_config() -> Config {
    let raw = std::fs::read_to_string("config.toml").unwrap();   // SAFE208
    toml::from_str(&raw).unwrap()                                  // SAFE208
}
```

**Good:**

```rust
pub fn read_config() -> Result<Config, ConfigError> {
    let raw = std::fs::read_to_string("config.toml")?;
    toml::from_str(&raw).map_err(ConfigError::Parse)
}
```

### SAFE306: `dangerous_mem_ops`

**What it flags:** Calls to `std::mem::transmute` / `transmute_copy` / `forget` / `zeroed` / `uninitialized`. Rust only.

All four are footguns: `transmute` reinterprets bits as a different type (use `From` / `TryFrom` / `bytemuck` instead); `forget` skips Drop (use `ManuallyDrop`); `zeroed` constructs an all-zero value of any type (use `MaybeUninit::zeroed` + explicit unsafe read so the hazard is visible at the use site); `uninitialized` was deprecated in 1.39+ in favour of `MaybeUninit::uninit()`.

**Path-qualified detection:** the function must be a `scoped_identifier` whose path contains `"mem"` (so `mem::transmute` after `use std::mem` and `std::mem::transmute` both fire, but a user-defined `my_helpers::transmute` does NOT). Bare `transmute(x)` (no `mem::` prefix) is NOT flagged.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"error"` | `"error"` or `"warning"` |
| `dangerous_mem_ops_rust` | `["transmute", "transmute_copy", "forget", "zeroed", "uninitialized"]` | Names to flag (trailing bareword of the scoped path) |

**Bad:**

```rust
let x: i8 = unsafe { std::mem::transmute::<u8, i8>(255) };   // SAFE306
```

**Good:**

```rust
let x: i8 = i8::try_from(255).unwrap_or(0);
```

### SAFE307: `interior_mutable_static`

**What it flags:** `static` items whose type provides safe interior mutability, and `lazy_static!` declarations. Rust only. Disabled by default.

Holzmann rule 6 (declare data at the smallest possible scope) bans global mutable state. Rust's `static mut` route requires `unsafe` and is therefore already audit-gated by SAFE602 (`undocumented_unsafe`), but the **idiomatic** route, a plain `static` holding a `Mutex` / `RwLock` / `OnceLock` / `Atomic*` / a `lazy_static!` block, is entirely safe code and invisible to SAFE602. SAFE307 closes that gap.

Two shapes fire: a `static` whose declared type contains an interior-mutability wrapper name as a standalone token (qualified paths like `std::sync::Mutex<T>` match too); and a `lazy_static! { ... }` macro invocation, flagged wholesale because the macro's whole purpose is declaring lazily-initialised statics and its body is an opaque token tree (the same limitation SAFE801 has with `sqlx::query!`). `const` items (immutable by construction) and `static mut` (SAFE602's territory) are not flagged. Word-boundary matching keeps `Lazy` from matching a user type like `LazyLoader`.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `interior_mutable_types_rust` | `Mutex`, `RwLock`, `RefCell`, `Cell`, `OnceLock`, `OnceCell`, `Lazy`, `LazyLock`, `LazyCell`, `AtomicBool`, `AtomicI8`..`AtomicI64`, `AtomicIsize`, `AtomicU8`..`AtomicU64`, `AtomicUsize`, `AtomicPtr` | Wrapper type names that mark a static as interior-mutable |

```toml
# pyproject.toml
[tool.safelint.rules.interior_mutable_static]
enabled = true
severity = "warning"
# Narrow or extend the wrapper-type set (replaces the default list):
interior_mutable_types_rust = ["Mutex", "RwLock", "OnceLock", "AtomicUsize"]
```

```toml
# standalone safelint.toml (same keys, no [tool.safelint] prefix)
[rules.interior_mutable_static]
enabled = true
```

**Bad:**

```rust
static CACHE: Mutex<Vec<u8>> = Mutex::new(Vec::new());   // SAFE307
static COUNT: AtomicUsize = AtomicUsize::new(0);          // SAFE307
```

**Good:**

```rust
const MAX_RETRIES: u32 = 5;          // immutable constant, not flagged
// or pass the Mutex<Vec<u8>> explicitly to the consumers that need it
```

### SAFE308: `truncating_as_cast`

**What it flags:** `as u8` / `as i8` / `as u16` / `as i16` / `as u32` / `as i32` / `as u64` / `as i64` / `as f32` casts. Rust only.

Rust's `as` operator silently truncates when the source value doesn't fit in the destination: `1_000_000u32 as u8` returns `64` (low byte), no panic, no error. `TryFrom` / `try_into()` returns `Result<T, TryFromIntError>`, making the failure mode explicit and checked. `isize` / `usize` / `i128` / `u128` / `f64` are NOT flagged as targets (widest types; casts TO them from smaller types don't truncate). Holzmann rule 1 + 7.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `truncating_cast_targets_rust` | `["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "f32"]` | Target type names to flag |

**Bad:**

```rust
let small: u8 = big_value as u8;   // silent truncation - SAFE308
```

**Good:**

```rust
let small: u8 = u8::try_from(big_value).map_err(|_| MyError::OutOfRange)?;
```

### SAFE602: `undocumented_unsafe`

**What it flags:** `unsafe { ... }` blocks lacking a `// SAFETY:` comment (case-insensitive) on a preceding line. Rust only.

The `// SAFETY:` comment convention (also enforced by `clippy::undocumented_unsafe_blocks`) documents why a particular use of `unsafe` is sound - which invariants the surrounding code upholds, why the safety contract of each unsafe operation is met. Without it, future readers (including the original author six months later) can't audit whether the unsafe is still justified.

Both `// SAFETY:` (line comment) and `/* SAFETY: */` (block comment) forms count. Multiple intervening line comments are allowed (the SAFETY line doesn't need to be the immediately-previous sibling, but no non-comment statement may sit between them). `unsafe fn` declarations are NOT covered - they require `/// # Safety` doc comments, a separate convention.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |

**Bad:**

```rust
unsafe {
    std::ptr::write(dst, value);   // SAFE602
}
```

**Good:**

```rust
// SAFETY: dst was allocated and aligned by the caller (see `Buffer::reserve`);
// value is a Copy type so this can't leak Drop.
unsafe {
    std::ptr::write(dst, value);
}
```

## Go-only rules

The following 2 rules apply only to Go source. They cover Go-idiom patterns the cross-language rules don't translate to cleanly (Go has no try/catch, so the swallowed-error and panic-placement hazards take Go-specific shapes). Both ship disabled by default; opt in via `[tool.safelint.rules.<name>] enabled = true`. See [Go](../languages/go.md) for the full language reference including idiomatic fix patterns.

### SAFE209: `empty_error_check`

**What it flags:** an `if err != nil { }` (or `== nil`) whose body is empty or comment-only. Go only.

Go's error handling is explicit: a function returns an `error` and the caller checks it. Writing the check and then leaving the body empty silently swallows the failure, which is worse than not checking at all (it looks handled). This is Go's analogue of Rust's SAFE206 (`silent_result_discard`) and the spirit of Python's SAFE202 (`empty_except`). A comment-only body fires too: the error was acknowledged and still ignored.

The error identifier is configurable; the default matches Go's conventional `err`. The comparison operand order is not assumed (`err != nil` and `nil != err` both match).

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `error_names_go` | `["err"]` | Identifier names treated as the error variable |

```toml
# pyproject.toml
[tool.safelint.rules.empty_error_check]
enabled = true
error_names_go = ["err", "e", "rerr"]
```

```toml
# safelint.toml
[rules.empty_error_check]
enabled = true
error_names_go = ["err", "e", "rerr"]
```

**Bad:**

```go
if err != nil {}   // SAFE209 - the error was checked and dropped
```

**Good:**

```go
if err != nil {
    return fmt.Errorf("read config: %w", err)
}
```

### SAFE211: `panic_calls_outside_tests`

**What it flags:** `panic(...)` calls in non-`_test.go` files. Go only.

Production Go code should return an `error` up the call stack, not unwind it with `panic`. A `panic` in a library forces every caller to recover or crash, defeating Go's explicit-error contract (Holzmann rule 1, simple control flow). Test files (`_test.go`) are exempt - a `panic` there is an acceptable test-failure signal, mirroring how Rust's SAFE204 exempts `#[test]` / `#[cfg(test)]` contexts.

The flagged call set is configurable; add the resolved barewords `Fatal` / `Fatalf` / `Exit` if your project treats `log.Fatal*` / `os.Exit` as panic-equivalent.

| Option | Default | Description |
|---|---|---|
| `enabled` | `false` | Toggle the rule |
| `severity` | `"warning"` | `"error"` or `"warning"` |
| `panic_calls_go` | `["panic"]` | Call names that count as panicking |

```toml
# pyproject.toml
[tool.safelint.rules.panic_calls_outside_tests]
enabled = true
panic_calls_go = ["panic", "Fatal", "Exit"]
```

```toml
# safelint.toml
[rules.panic_calls_outside_tests]
enabled = true
panic_calls_go = ["panic", "Fatal", "Exit"]
```

**Bad:**

```go
func mustParse(s string) Config {
    c, err := parse(s)
    if err != nil {
        panic(err)   // SAFE211
    }
    return c
}
```

**Good:**

```go
func parseConfig(s string) (Config, error) {
    c, err := parse(s)
    if err != nil {
        return Config{}, fmt.Errorf("parse config: %w", err)
    }
    return c, nil
}
```
