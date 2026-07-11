# safelint skill: C addendum

C is Holzmann's original "Power of Ten" target language, so several clauses every other language *adapts away* apply literally here. C ports the 16 cross-language rules and adds **five new C-family rules** (the "homecoming", shared with C++) that express those clauses directly.

## Install nuance

```bash
pip install 'safelint[c]'        # adds .c, .h
# or, in a project that already uses uv:
uv add 'safelint[c]'
# or, kitchen-sink:
pip install 'safelint[all]'
```

C ships its grammar (`tree-sitter-c`) as the opt-in `[c]` extra; the base install has no grammars.

For pre-commit integration you normally only need to add the grammar extra via `additional_dependencies`; the published hook already scopes itself to `.c` / `.h` files (its `types_or` carries the `c` filetype tag, so no `types_or` line is needed unless you override it):

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.7.0  # C support requires v2.7.0+
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[c]']
```

`--language c` filters `safelint list-rules` to the C rule set.

## File extensions

`.c` and `.h`. **`.h` ownership:** `.h` headers are linted as **C**. A C++ project that uses `.h` headers gets them linted as C (content sniffing is out of scope); C++ keeps the C++-only header extensions (`.hpp` etc.). This is a documented limitation.

## Rule count

21 rules apply to C: the 16 cross-language ports plus the 5 new C-family rules (SAFE106 / SAFE310-313, shared with C++). Comments use `//` (line-directive form): `// nosafe`, `// nosafe: SAFE106`, `// safelint: ignore`.

## C shapes worth knowing

- `function_definition` is the only function node (no methods, closures, or lambdas) - the simplest function model of any language. The function name nests under `declarator.declarator` (no `name` field).
- File-scope mutable `declaration`s are shared state (SAFE302); `const` and prototypes / `typedef` / `extern` are exempt; `static` file-scope variables still count.
- `(void)f()` (an explicit-discard cast) wraps the call in a `cast_expression`, so SAFE802 correctly does NOT fire on it.
- `argv` enters taint analysis through function-parameter seeding; `argv[1]` keeps the taint.

## Language-specific rule phrasing

| Code | Rule | C-specific notes |
|---|---|---|
| SAFE101 | function_length | Source lines on `function_definition`. Default cap 60. |
| SAFE102 | nesting_depth | Counts `if` / `for` / `while` / `do` / `switch`. Default max 2. `goto` labels are flat, not nesting. |
| SAFE103 | max_arguments | Counts `parameter_declaration` nodes (under `function_declarator.parameters`). `int f(void)` is zero args. Default cap 7. |
| SAFE104 | complexity | Every `if` / `for` / `while` / `do` / `case` / ternary adds one; `&&` / `\|\|` each add one. Default cap 10. |
| SAFE105 | no_recursion | Flags a `function_definition` calling its own name directly. Name resolved from `declarator.declarator`. Enabled by default at warning severity. |
| SAFE106 | nonlocal_jumps | *C / C++ (rule 1, literal).* Every `goto` and every `setjmp` / `longjmp` / `sigsetjmp` / `siglongjmp` call. **Enabled at warning severity** (idiomatic `goto err` cleanup surfaces without blocking `--fail-on=error`); annotate sanctioned cleanups with `// nosafe: SAFE106`. Configurable via `nonlocal_jump_calls_c` (C uses its own key; C++ reads `nonlocal_jump_calls_cpp`). |
| SAFE302 | global_mutation | File-scope mutable `declaration` (a translation-unit-shared binding). `const` / prototypes / `typedef` / `extern` exempt; `static` counts. |
| SAFE303 | side_effects_hidden | A pure-named function (`get` / `compute` / ...) containing a C I/O call. Default `io_functions_c`: `printf` / `fprintf` / `puts` / `putchar` / `fopen` / `fread` / `fwrite` / `fgets` / `scanf` / `getchar` / `read` / `write` / `recv` / `send` / `system`. |
| SAFE304 | side_effects | Any non-I/O-named function containing a C I/O call (same `io_functions_c`). |
| SAFE309 | dynamic_code_execution | C has no `eval`; the dynamic surface is the dynamic linker. Default `dynamic_exec_calls_c`: `dlopen` / `dlsym`. Disabled by default. |
| SAFE310 | dynamic_allocation | *C / C++ (rule 3, literal).* Calls to the `malloc` family. Default `allocation_calls_c`: `malloc` / `calloc` / `realloc` / `aligned_alloc` / `free` / `strdup` (C++ reads `allocation_calls_cpp` and additionally flags `new` / `delete` expressions structurally). Disabled by default (embedded / safety-critical opt-in). |
| SAFE311 | complex_macro | *C / C++ (rule 8).* Function-like macros using `##` token paste or `__VA_ARGS__`, and object-like macros whose replacement is not a balanced syntactic unit. Disabled by default. |
| SAFE312 | conditional_compilation | *C / C++ (rule 8).* Every `#if` / `#ifdef` / `#ifndef` beyond the `#ifndef X` + `#define X` include-guard idiom - each doubles the build configurations to test. Disabled by default. |
| SAFE313 | restricted_pointers | *C / C++ (rule 9, literal).* Declarators with more than one pointer level (`int **p`) and function-pointer declarators (`void (*fp)(int)`). Disabled by default. Note: `char **argv` fires too (it is a two-level pointer) - that is intentional for the strict rule. |
| SAFE501 | unbounded_loops | `while (1)` / `while (true)` / `for (;;)` without an exiting break. C has no labelled break; a `goto` out of the loop counts as an exit. |
| SAFE601 | missing_assertions | The literal `assert(...)` macro from `<assert.h>`. Configurable via `assertion_calls_c` (add `ck_assert` / `TEST_ASSERT` for unit-test frameworks). Disabled by default. |
| SAFE603 | blanket_suppression | clang-tidy's bare `// NOLINT` / `// NOLINTNEXTLINE` (all checks). Scoped `// NOLINT(bugprone-foo)` is clean. Disabled by default. |
| SAFE701 | test_existence | Looks for `<stem>_test.c` / `test_<stem>.c` under `test_dirs` (default `tests`). C conventions vary (Unity / Check / CMocka); usually override `test_dirs`. Disabled by default. |
| SAFE702 | test_coupling | Same `<stem>_test.c` / `test_<stem>.c` convention. Disabled by default. |
| SAFE801 | tainted_sink | Sinks (`sinks_c`): `system` / `popen` / `execl` family / `sprintf` / `strcpy` / `strcat` / `gets` / `memcpy`. Sources (`sources_c`): `getenv` / `fgets` / `gets` (return-value sources only; plus `argv` via parameter seeding). Out-parameter readers (`scanf` / `read` / `recv`) are excluded until the tracker taints destination buffers. Sanitizers (`sanitizers_c`): narrow generic set. Disabled by default. |
| SAFE802 | return_value_ignored | A bare flagged call whose return is discarded. Default `flagged_calls_c`: `fclose` / `fwrite` / `fread` / `remove` / `rename` / `fflush` / `setvbuf` / `snprintf`. `(void)f()` is exempt. Disabled by default. |

## Deliberately skipped rules

| Code | Rule | Why skipped for C |
|---|---|---|
| SAFE201 / SAFE202 / SAFE203 | bare_except / empty_except / logging_on_error | C has no try/catch. Error-handling discipline is SAFE802's return-code checking. |
| SAFE301 | global_state | No `global` keyword; file-scope state is the SAFE302 port. |
| SAFE305 | wide_scope_declaration | No `var` hoisting distinction. |
| SAFE401 | resource_lifecycle | C cleanup idioms (`goto err` chains, explicit `fclose` / `free`) need flow analysis the rule does not do; allocation discipline is SAFE310's job. Documented gap. |
| SAFE803 | null_dereference | Chained deref off a call (`*fopen(...)`) is rare C style; nullable-return tracking without flow analysis would be noise. Documented gap. |

## Idiomatic fix patterns

### SAFE106 (`goto` / `setjmp`)
The paper bans `goto`, but `goto err` cleanup is pervasive. SAFE106 ships **enabled at warning severity** so it surfaces without blocking. For a sanctioned cleanup chain, annotate the line: `goto err; // nosafe: SAFE106`. Prefer structured cleanup (a single-exit helper, or a small state machine) where practical.

### SAFE310 (dynamic allocation)
Rule 3 wants all allocation up front. Pre-allocate fixed-size pools / arenas at init and hand out slots, rather than `malloc`/`free` in the steady state. Enable per-project for embedded / safety-critical code.

### SAFE313 (pointer levels)
Collapse `int **p` to a single level with an explicit struct or an out-parameter wrapper; replace function pointers with a tagged dispatch where the safety bar requires it. Disabled by default - opt in for the strictest profiles.
