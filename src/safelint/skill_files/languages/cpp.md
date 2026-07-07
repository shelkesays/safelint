# safelint skill: C++ addendum

C++ builds on C. tree-sitter-cpp is a superset of tree-sitter-c, so the C node types carry over and the five C-family rules (SAFE106 / SAFE310-313) apply to C++. On top of that, C++ gains its `try` / `catch` / `throw` error-handling rules (SAFE201 / SAFE202 / SAFE203), and **two new C++-only idiom rules** (SAFE315 / SAFE316).

## Install nuance

```bash
pip install 'safelint[cpp]'      # adds .cpp, .cxx, .cc, .hpp, .hxx, .hh
# or, in a project that already uses uv:
uv add 'safelint[cpp]'
# or, kitchen-sink:
pip install 'safelint[all]'
```

C++ ships its grammar (`tree-sitter-cpp`) as the opt-in `[cpp]` extra; the base install has no grammars.

## File extensions

`.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`. **`.h` ownership:** a plain `.h` header is linted as **C**, not C++ (content sniffing is out of scope). A C++ project whose headers use `.h` gets them linted as C; use the C++-specific header extensions (`.hpp` / `.hxx` / `.hh`) for C++ header linting. This is a documented limitation shared with the C page.

## Rule count

26 rules apply to C++: the cross-language ports, the five C-family rules widened to `("c", "cpp")`, the three try/catch rules, and the two C++-only idiom rules (SAFE315 / SAFE316). Comments use `//` (line-directive form): `// nosafe`, `// nosafe: SAFE315`, `// safelint: ignore`.

## C++ shapes worth knowing

- `function_definition` covers both free functions AND methods; `lambda_expression` is a separate function node. A method name is a `field_identifier` (in-class) or a `qualified_identifier` (`S::m` out-of-line); a free function's name nests under `declarator.declarator` as in C.
- SAFE105 detects a `this->m()` self-call (a `field_expression` callee) and a namespace-qualified `ns::f()` (a `qualified_identifier` callee) in addition to a bare-name recursive call.
- SAFE302 descends into `namespace_definition` and `extern "C"` (`linkage_specification`) bodies, and into `class_specifier` / `struct_specifier` bodies to reach `static` data members - all translation-unit-scoped mutable state.
- The named casts (`reinterpret_cast<T>(x)`) are **not** dedicated cast nodes: they parse as a `call_expression` whose `function` is a `template_function`. SAFE316 detects them by that template callee name.
- `std::cerr << ...` stream logging is a `<<` binary expression, not a call, so SAFE203 recognises it via a dedicated leftmost-operand scan (`cerr` / `clog` / `cout`, qualified or unqualified) in addition to `call_name`-matched log calls (`spdlog::error`, `logger.error`).
- Smart pointers (`std::unique_ptr<T>`) are class templates, not `pointer_declarator`s, so SAFE313 never fires on them.

## Language-specific rule phrasing

| Code | Rule | C++-specific notes |
|---|---|---|
| SAFE101 | function_length | Source lines on `function_definition` / `lambda_expression`. Default cap 60. |
| SAFE102 | nesting_depth | Counts `if` / `for` (classic and range-based `for (auto x : v)`) / `while` / `do` / `switch` / `try`. Default max 2. |
| SAFE103 | max_arguments | Counts `parameter_declaration` nodes on both `function_definition` and `lambda_expression` (a lambda's params nest under `abstract_function_declarator`). `int f()` / `int f(void)` is zero args. Default cap 7. |
| SAFE104 | complexity | Every `if` / `for` (classic and range-based) / `while` / `do` / `case` / `catch` / ternary adds one; `&&` / `\|\|` each add one. Default cap 10. |
| SAFE105 | no_recursion | Flags a function calling its own name directly, including a method's `this->m()` and a namespace-qualified `ns::f()`. Enabled by default at warning severity. **Known limitation:** the check is name-based, so a call to a *different overload* of the same name (`log(int)` calling `log(const char*)`) is reported as recursion - distinguishing overloads needs type resolution safelint does not do. Annotate a genuine non-recursive overload call with `// nosafe: SAFE105`. |
| SAFE106 | nonlocal_jumps | *C / C++.* Every `goto` and every `setjmp` / `longjmp` family call. **Enabled at warning severity**; annotate a sanctioned `goto err` with `// nosafe: SAFE106`. Configurable via `nonlocal_jump_calls_cpp`. |
| SAFE201 | bare_except | C++'s first non-Python home. Flags the `catch (...)` catch-all (swallows every exception with no binding to inspect or re-raise). A typed `catch (const E& e)` is clean. |
| SAFE202 | empty_except | An empty / comment-only / literal-only `catch` body. |
| SAFE203 | logging_on_error | A `catch` that swallows without logging. `std::cerr << ...` stream insertion, `spdlog::error(...)`-style calls, `perror(...)`, and `fprintf(stderr, ...)` all count as logging; a bare `throw;` / `throw e;` counts as a re-raise. |
| SAFE302 | global_mutation | File-scope, namespace-scope, `extern "C"`-block, and `static` class/struct data members (all translation-unit-scoped). Non-static fields are per-instance and exempt; `const` / `constexpr` exempt; prototypes / `typedef` / `extern` forward refs exempt. |
| SAFE303 | side_effects_hidden | A pure-named function containing a C-family I/O call (`io_functions_cpp`, mirrors C's list). `std::cout << ...` stream I/O is operator-based and not call-matchable - a documented non-catch. |
| SAFE304 | side_effects | Any non-I/O-named function containing a C-family I/O call (same `io_functions_cpp`). |
| SAFE309 | dynamic_code_execution | The dynamic-linker surface: default `dynamic_exec_calls_cpp` `dlopen` / `dlsym`. Disabled by default. |
| SAFE310 | dynamic_allocation | *C / C++.* The `malloc` family (`allocation_calls_cpp`) plus C++ `new` / `delete` expressions (flagged structurally). Disabled by default. Overlaps SAFE315 by design. |
| SAFE311 | complex_macro | *C / C++.* Token-paste / `__VA_ARGS__` / unbalanced object-like macros. Disabled by default. |
| SAFE312 | conditional_compilation | *C / C++.* Every `#if` / `#ifdef` / `#ifndef` beyond the include-guard idiom. Disabled by default. |
| SAFE313 | restricted_pointers | *C / C++.* More than one raw pointer level (`int **p`) and function-pointer declarators. Smart pointers (`std::unique_ptr<T>`) are exempt (they are class templates). Disabled by default. |
| SAFE315 | raw_new_delete | *C++-only (3xx).* Every `new` / `delete` expression - prefer `std::make_unique` / `std::make_shared` and RAII. `make_unique` never fires; a raw `new` inside `unique_ptr<T>(new T)` still fires. Overlaps SAFE310 by design. Disabled by default. |
| SAFE316 | dangerous_casts | *C++-only (3xx).* `reinterpret_cast` / `const_cast` (type / const-unsafe). `static_cast` / `dynamic_cast` are compiler-checked and stay clean. Configurable via `dangerous_casts_cpp`. Disabled by default. |
| SAFE501 | unbounded_loops | `while (true)` / `while (1)` / `for (;;)` without an exiting break. A `break` inside a nested lambda does not count as exiting the outer loop. |
| SAFE601 | missing_assertions | The literal `assert(...)` macro from `<cassert>`. Configurable via `assertion_calls_cpp` (add GoogleTest `ASSERT_TRUE` / Catch2 `REQUIRE`). Disabled by default. |
| SAFE603 | blanket_suppression | clang-tidy's bare `// NOLINT` / `// NOLINTNEXTLINE`. Scoped `// NOLINT(check)` is clean. Disabled by default. |
| SAFE701 | test_existence | Looks for `<stem>_test.cpp` / `test_<stem>.cpp` under `test_dirs` (GoogleTest / Catch2 conventions). Disabled by default. |
| SAFE702 | test_coupling | Same `<stem>_test.cpp` / `test_<stem>.cpp` convention. Disabled by default. |
| SAFE801 | tainted_sink | Reuses the C taint tracker; reference parameters (`const std::string& s`) seed taint. Sinks / sources / sanitizers via `sinks_cpp` / `sources_cpp` / `sanitizers_cpp` (mirror C). Disabled by default. |
| SAFE802 | return_value_ignored | A bare flagged call whose return is discarded. Default `flagged_calls_cpp` mirrors C. Disabled by default. |

## Deliberately skipped rules

| Code | Rule | Why skipped for C++ |
|---|---|---|
| SAFE301 | global_state | No `global` keyword; namespace / file-scope state is the SAFE302 port. |
| SAFE305 | wide_scope_declaration | No `var` hoisting distinction. |
| SAFE401 | resource_lifecycle | RAII makes cleanup language-enforced (same rationale as Rust); raw `new` / `delete` discipline is SAFE310 / SAFE315. Documented gap. |
| SAFE803 | null_dereference | Nullable-return tracking without types would be noise (same as C). Documented gap. |

## Idiomatic fix patterns

### SAFE315 (`new` / `delete`)
Replace `T* p = new T(...); ... delete p;` with `auto p = std::make_unique<T>(...)` (or `make_shared` for shared ownership); the owner releases automatically and cannot be leaked on an early return or exception. Enable per-project for a modern-ownership posture.

### SAFE316 (`reinterpret_cast` / `const_cast`)
Prefer `static_cast` / `dynamic_cast` (compiler-checked). A `reinterpret_cast` usually signals a design that should use a `union`, `std::bit_cast`, or a typed wrapper; a `const_cast` usually signals a `const`-correctness bug at the interface. Extend / narrow the list via `dangerous_casts_cpp`.
