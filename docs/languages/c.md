# C

C is Holzmann's original "Power of Ten" target language. Several clauses that every other language *adapts away* apply literally to C, so it gains a dedicated set of new language-specific rules: the **five C-family rules** (the "homecoming", shared with C++) express rules 1, 3, 8, and 9 directly. New in v2.7.0.

## File extensions

`.c` and `.h`.

**`.h` ownership:** `.h` headers are linted as **C**. A C++ project that uses `.h` headers gets them linted as C - content sniffing is out of scope, so a header shared between C and C++ is treated as C. [C++](cpp.md) keeps the C++-only header extensions (`.hpp`, `.hxx`, `.hh`). This is a documented limitation.

## Quick start

```bash
pip install 'safelint[c]'        # adds .c, .h
# or
uv add 'safelint[c]'

safelint check src/              # lint a directory
```

The `tree-sitter-c` grammar ships as the opt-in `[c]` extra; the base install bundles no grammars.

## Suppression directives

C uses line-comment directives (`//` form): `// nosafe` (all rules on the line), `// nosafe: SAFE106` (a specific rule), and the file-scope `// safelint: ignore`. Block-comment (`/* */`) directives parse but are not recognised, matching every other language's line-directive-only convention.

## Rules that fire on C

21 rules apply: the 16 cross-language rules plus the 5 new C-family rules (shared with C++).

### Cross-language rules

| Code | Rule | C notes |
|------|------|---------|
| [SAFE101](../configuration/rules.md#safe101-function_length) | function_length | Source lines on `function_definition`. |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | nesting_depth | `if` / `for` / `while` / `do` / `switch`. |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | max_arguments | `parameter_declaration` count; `void` is zero args. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | complexity | `if`/loops/`case`/ternary + `&&` / `||`. |
| [SAFE105](../configuration/rules.md#safe105-no_recursion) | no_recursion | Direct self-recursion. |
| [SAFE302](../configuration/rules.md#safe302-global_mutation) | global_mutation | File-scope mutable `declaration`; `const` / `typedef` / `extern` / prototypes exempt; `static` counts. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | side_effects_hidden | Pure-named function doing C I/O (`io_functions_c`). |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | side_effects | Any non-I/O-named function doing C I/O. |
| [SAFE309](../configuration/rules.md#safe309-dynamic_code_execution) | dynamic_code_execution | `dlopen` / `dlsym`. Disabled by default. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | unbounded_loops | `while (1)` / `while (true)` / `for (;;)`; a `goto` out of the loop counts as an exit. |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | missing_assertions | The `assert(...)` macro. Disabled by default. |
| [SAFE603](../configuration/rules.md#safe603-blanket_suppression) | blanket_suppression | clang-tidy bare `// NOLINT`. Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | test_existence | `<stem>_test.c` / `test_<stem>.c`. Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | test_coupling | Same convention. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | tainted_sink | `argv` / `getenv` / ... into `system` / `strcpy` / ... Disabled by default. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | return_value_ignored | Discarded `fclose` / `fwrite` / ...; `(void)f()` exempt. Disabled by default. |

### C-family rules (the Power-of-Ten homecoming)

| Code | Rule | Holzmann rule | Default | Behaviour |
|------|------|---------------|---------|-----------|
| [SAFE106](../configuration/rules.md#safe106-nonlocal_jumps) | nonlocal_jumps | 1 | **enabled (warning)** | Every `goto` and every `setjmp` / `longjmp` / `sigsetjmp` / `siglongjmp` call. Idiomatic `goto err` surfaces without blocking; annotate with `// nosafe: SAFE106`. |
| [SAFE310](../configuration/rules.md#safe310-dynamic_allocation) | dynamic_allocation | 3 | disabled | Calls to the `malloc` family (`malloc` / `calloc` / `realloc` / `aligned_alloc` / `free` / `strdup`). |
| [SAFE311](../configuration/rules.md#safe311-complex_macro) | complex_macro | 8 | disabled | Function-like macros using `##` or `__VA_ARGS__`, and object-like macros whose replacement is not a balanced syntactic unit. |
| [SAFE312](../configuration/rules.md#safe312-conditional_compilation) | conditional_compilation | 8 | disabled | Every `#if` / `#ifdef` / `#ifndef` beyond the include-guard idiom. |
| [SAFE313](../configuration/rules.md#safe313-restricted_pointers) | restricted_pointers | 9 | disabled | Declarators with more than one pointer level (`int **p`) and function-pointer declarators. |

### Rules not registered for C

| Code | Rule | Why |
|------|------|-----|
| SAFE201 / SAFE202 / SAFE203 | bare_except / empty_except / logging_on_error | C has no try/catch; error discipline is SAFE802's return-code checking. |
| SAFE301 | global_state | No `global` keyword; file-scope state is the SAFE302 port. |
| SAFE305 | wide_scope_declaration | No `var` hoisting distinction. |
| SAFE401 | resource_lifecycle | C cleanup (`goto err`, explicit `fclose` / `free`) needs flow analysis; allocation discipline is SAFE310's job. Documented gap. |
| SAFE803 | null_dereference | Chained deref off a call is rare C style; nullable-return tracking without flow analysis would be noise. Documented gap. |

## Key C adaptations

- `function_definition` is the only function node (no methods / closures). The name nests under `declarator.declarator`.
- `(void)f()` (the explicit-discard cast) wraps the call in a `cast_expression`, so SAFE802 does not fire on it.
- `argv` enters taint analysis via function-parameter seeding; `argv[1]` keeps the taint.
- SAFE313 fires on `char **argv` (a two-level pointer) - intentional for the strict, opt-in rule.
- SAFE313 is a syntactic declarator check: a pointer level hidden behind a `typedef` (`typedef int *intp; intp *pp;`) or a macro is not counted - the paper's no-hidden-dereference clause needs type resolution and is a documented gap.

## Configuration

Every C-specific config key is set in either form. `[tool.safelint.rules.<name>]` for `pyproject.toml`, `[rules.<name>]` for standalone `safelint.toml`.

### Enable the opt-in C rules

```toml
# pyproject.toml
[tool.safelint.rules.dynamic_allocation]
enabled = true

[tool.safelint.rules.restricted_pointers]
enabled = true
```

```toml
# safelint.toml
[rules.dynamic_allocation]
enabled = true

[rules.restricted_pointers]
enabled = true
```

### SAFE106 non-local jump calls

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

### SAFE310 allocation calls

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

### SAFE801 taint sinks / sources / sanitizers

```toml
# pyproject.toml
[tool.safelint.rules.tainted_sink]
enabled = true
sinks_c = ["system", "popen", "execl", "execlp", "execv", "execvp", "sprintf", "strcpy", "strcat", "gets", "memcpy"]
sources_c = ["getenv", "fgets", "gets"]
sanitizers_c = ["sanitize", "validate", "escape"]
```

```toml
# safelint.toml
[rules.tainted_sink]
enabled = true
sinks_c = ["system", "popen", "execl", "execlp", "execv", "execvp", "sprintf", "strcpy", "strcat", "gets", "memcpy"]
sources_c = ["getenv", "fgets", "gets"]
sanitizers_c = ["sanitize", "validate", "escape"]
```
