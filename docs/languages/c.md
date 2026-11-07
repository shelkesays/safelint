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

## Parse coverage: the preprocessor limit

**A quarter to a half of a real C or C++ project's files may not be analysed at all.** safelint parses the source as written; it does not run the preprocessor. Ordinary C that a compiler accepts after `cpp` has run is therefore not always standalone-valid to the parser, the file surfaces a `SAFE000` parse error, and **every other rule is skipped for it**. A clean run on such a project is not the same as a clean project.

Measured on stock defaults against four widely deployed codebases:

| Project | Language | Files scanned | Parse failures | Share |
|---|---|---|---|---|
| [curl](https://github.com/curl/curl) `61a31e0` | C | 1101 | 277 (239 `.c`, 38 `.h`) | **25%** |
| [redis](https://github.com/redis/redis) `b540ca4` | C | 845 | 351 (243 `.c`, 104 `.h`, 4 `.cpp`) | **42%** |
| [fmt](https://github.com/fmtlib/fmt) `4afd0e4` | C++ | 79 | 43 (19 `.cc`, 24 `.h`) | **54%** |
| [leveldb](https://github.com/google/leveldb) `7ee830d` | C++ | 133 | 60 (13 `.cc`, 47 `.h`) | **45%** |

Headers fare worst, which matters most for a header-heavy library: fmt's failures are more `.h` than `.cc`. The figures have been stable since 2.14.3 (identical counts), so they describe the approach rather than a regression in any one release.

### What defeats the parser

Nearly every cause is the preprocessor or a compiler extension, and the code is valid:

```c
// conditional compilation INSIDE an expression
if(ip->maskbits <= 0 ||
#ifdef AF_INET6
   (ip->family == AF_INET6 && ip->maskbits > 128) ||
#endif
   ip->maskbits > 32)

// a function-like macro standing in for parameters
static void timer_cb(EV_P_ struct ev_timer *w, int revents)

// a guarded attribute before a declaration
#if defined(__GNUC__) || defined(__clang__)
__attribute__((format(printf, 2, 3)))
#endif
static int mem_addf(struct mem *mem, const char *format, ...)

// a compiler builtin with non-C argument syntax
if(__builtin_available(macOS 10.12, iOS 5, *)) {}
```

There is a second, smaller cause that only affects `.h` headers in a **C++** project: `.h` lints as C (see the [C++ page](cpp.md#file-extensions)), so C++ syntax in it defeats the C grammar no matter what the preprocessor does. Re-running fmt's 24 failing `.h` headers under the C++ grammar separates the two: 4 parse clean, so the C grammar alone was the problem; the other 20 still fail, so they are genuinely macro or directive shapes. Renaming to `.hpp` / `.hxx` / `.hh` therefore recovers that minority and nothing more.

Because of this the `SAFE000` message on C and C++ names the preprocessor instead of telling you to check your syntax. The hint is per-language, not per-cause: safelint cannot distinguish "valid code the preprocessor would fix" from a genuine typo, so a real syntax error also reads as a possible preprocessor issue. By error kind, roughly three quarters of the failures are a bare `syntax error` and a fifth a `missing ';'` (the macro-as-declarator shape); redis also shows 14 `missing '#endif'`, the conditional-compilation shape proper.

### Working with it

- **Count the `SAFE000` findings before trusting a clean report**, and count them from a full scan: `safelint check . --all-files`, since without `--all-files` the run only covers git-modified files and its count says nothing about the project. They are 10-14% of all default findings on the projects above, so a run with no other violations may still have read only half the tree. A summary line for skipped files is tracked in [#175](https://github.com/shelkesays/safelint/issues/175).
- **Lint preprocessed output** where a build can produce it (`cc -E`). Three things are lost, not just one: line numbers that map back to your source, every inactive branch (whatever the build's own `-D` flags excluded is simply not there), and the directives themselves, which silently retires the opt-in SAFE311 `complex_macro` and SAFE312 `conditional_compilation` rules because the nodes they match no longer exist.
- **`ignore = ["SAFE000"]`** silences the parse errors if the noise outweighs the signal for you. It does not make the files analysable; it only hides the fact that they were skipped. Prefer leaving them visible.

Tracked as [#206](https://github.com/shelkesays/safelint/issues/206), with a preprocessor-tolerant parse pass as the open question.

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
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | missing_assertions | The `assert(...)` macro. *Since 2.16.0* scoped to tests by default (`test_functions_only = true`), which for C means a `<stem>_test.c` / `test_<stem>.c` file or one under `test_dirs`, and a function named for a `test_function_prefixes` entry. A Unity / Check / CMocka `TEST(Suite, Name) { ... }` macro body does **not** parse under `tree-sitter-c` (the file surfaces a `SAFE000` parse error and is dropped from analysis, the class tracked in #206), so no configuration reaches it. The same source compiled as C++ does parse, as a function named `TEST`; see the [C++ page](cpp.md#assertions-safe601). Disabled by default. |
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

Both lists above are **universal**: a name in `sanitizers_c` clears *every* sink. To recognise a
context-specific escaper precisely - one that makes a value safe for a shell sink but not for a
format-string sink - declare it with the opt-in [property-typed sanitiser contract](../configuration/rules.md#property-typed-sanitisers-sanitizer_properties-sink_properties)
instead (2.13.0):

```toml
# safelint.toml
[rules.tainted_sink.sanitizer_properties_c]
shell_quote = ["shell_quoted"]

[rules.tainted_sink.sink_properties_c]
system = "shell_quoted"
```

A property-typed sanitiser clears **only** the sinks that declare a property it establishes, so
`shell_quote` no longer silently vouches for `sprintf`. Keep the name out of the flat
`sanitizers_c` list, which is checked first and would otherwise clear everything regardless.
