# C++

C++ builds on C. `tree-sitter-cpp` is a superset of `tree-sitter-c`, so the C node types carry over and the five C-family rules (SAFE106 / SAFE310-313) apply to C++. On top of that, C++ gains its `try` / `catch` / `throw` error-handling rules (SAFE201 / SAFE202 / SAFE203) and **two new C++-only idiom rules** (SAFE315 / SAFE316). New in v2.8.0.

## File extensions

`.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`.

**`.h` ownership:** a plain `.h` header is linted as **C**, not C++ - content sniffing is out of scope, so a header shared between C and C++ is treated as C. Use the C++-specific header extensions (`.hpp`, `.hxx`, `.hh`) for C++ header linting. This is a documented limitation shared with the [C page](c.md).

## Quick start

```bash
pip install 'safelint[cpp]'      # adds .cpp, .cxx, .cc, .hpp, .hxx, .hh
# or
uv add 'safelint[cpp]'

safelint check src/              # lint a directory
```

The `tree-sitter-cpp` grammar ships as the opt-in `[cpp]` extra; the base install bundles no grammars.

## Suppression directives

C++ uses line-comment directives (`//` form): `// nosafe` (all rules on the line), `// nosafe: SAFE315` (a specific rule), and the file-scope `// safelint: ignore`. Block-comment (`/* */`) directives parse but are not recognised, matching every other language's line-directive-only convention.

## Rules that fire on C++

26 rules apply: the cross-language ports, the five C-family rules widened to C and C++, the three try/catch rules (SAFE201 / SAFE202 / SAFE203), and the two C++-only idiom rules (SAFE315 / SAFE316).

### C++-only rules

- **[SAFE315 `raw_new_delete`](../configuration/rules.md#safe315-raw_new_delete)** - every `new` / `delete` expression. Prefer `std::make_unique` / `std::make_shared` and RAII. `std::make_unique` contains no `new` expression and never fires; a raw `new` inside a `std::unique_ptr<T>(new T)` argument still fires. Overlaps the widened SAFE310 by design (SAFE310 is the Holzmann no-allocation posture, SAFE315 the modern-ownership posture). Disabled by default.
- **[SAFE316 `dangerous_casts`](../configuration/rules.md#safe316-dangerous_casts)** - `reinterpret_cast` and `const_cast`, which defeat the type / const system. `static_cast` and `dynamic_cast` are compiler-checked and stay clean. The flagged list is configurable via `dangerous_casts_cpp`. Disabled by default.

### C-family rules widened to C++

SAFE106 (`nonlocal_jumps`), SAFE310 (`dynamic_allocation`), SAFE311 (`complex_macro`), SAFE312 (`conditional_compilation`), and SAFE313 (`restricted_pointers`) all apply to C++. Two behaviours differ from plain C:

- **SAFE310** additionally flags C++ `new` / `delete` expressions as dynamic allocation (alongside the configured `malloc`-family calls).
- **SAFE313** naturally exempts smart pointers: `std::unique_ptr<T>` is a class template, not a `pointer_declarator`, so it never trips the raw multi-level-pointer check.

Two of them take `_cpp`-suffixed config lists so a project can diverge its C and C++ knobs: SAFE106 (`nonlocal_jump_calls_cpp`) and SAFE310 (`allocation_calls_cpp`). SAFE311, SAFE312 and SAFE313 have no configurable name list - they match on syntax alone. The try/catch rules below (SAFE201-SAFE203) share the cross-language error-handling options rather than taking `_cpp` keys.

### Error handling (`try` / `catch` / `throw`)

C++ is the first non-Python home for **SAFE201 `bare_except`**: it flags the `catch (...)` catch-all, which swallows every exception with no binding to inspect or re-raise - the same hazard as Python's bare `except:`. A typed `catch (const E& e)` is clean. **SAFE202** fires on empty / comment-only / literal-only catch bodies; **SAFE203** requires a swallowing catch to log. A `std::cerr << ...` stream insertion counts as logging (it is a `<<` operator, not a call, so it is recognised specially), as does an `spdlog::error(...)`-style call; a bare `throw;` or `throw e;` counts as a re-raise.

## Configuration

Every C++ rule reads `_cpp`-suffixed config keys, independent of the C ones. The dataflow rule is the one with the widest surface:

### SAFE801 taint sinks / sources / sanitizers

```toml
# pyproject.toml
[tool.safelint.rules.tainted_sink]
enabled = true
sinks_cpp = ["system", "popen", "execl", "execv", "sprintf", "strcpy", "strcat", "memcpy"]
sources_cpp = ["getenv", "fgets"]
sanitizers_cpp = ["sanitize", "validate", "escape"]
```

```toml
# safelint.toml
[rules.tainted_sink]
enabled = true
sinks_cpp = ["system", "popen", "execl", "execv", "sprintf", "strcpy", "strcat", "memcpy"]
sources_cpp = ["getenv", "fgets"]
sanitizers_cpp = ["sanitize", "validate", "escape"]
```

C++ reuses the C taint tracker's node handling and adds a **method-receiver step** that plain C does not have, so `req->param("q")` stays tainted into a sink.

`sanitizers_cpp` is **universal**: a name there clears *every* sink. To recognise a context-specific escaper precisely, declare it with the opt-in [property-typed sanitiser contract](../configuration/rules.md#property-typed-sanitisers-sanitizer_properties-sink_properties) instead (2.13.0):

```toml
# safelint.toml
[rules.tainted_sink.sanitizer_properties_cpp]
shell_quote = ["shell_quoted"]

[rules.tainted_sink.sink_properties_cpp]
system = "shell_quoted"
```

A property-typed sanitiser clears **only** the sinks that declare a property it establishes, so `shell_quote` no longer silently vouches for `sprintf`. Keep such a name out of the flat `sanitizers_cpp` list, which is checked first and would otherwise clear everything regardless.

## C++ shapes worth knowing

- `function_definition` covers both free functions AND methods; `lambda_expression` is a separate function node. A method name is a `field_identifier` (in-class) or a `qualified_identifier` (`S::m`, out-of-line); a free function's name nests under `declarator.declarator` as in C.
- SAFE105 detects a `this->m()` self-call in addition to a bare recursive call.
- SAFE302 descends into `namespace_definition` bodies, so a namespace-scoped mutable global fires, not just a translation-unit-scope one.
- The named casts (`reinterpret_cast<T>(x)`) are **not** dedicated cast nodes: they parse as a `call_expression` whose `function` is a `template_function`. SAFE316 detects them by that template callee name.
- An **explicitly instantiated template call** carries its `<...>` in the callee node: `execute<int>(x)` is a `template_function` and `db.query<Row>(x)` a `template_method`. Both are unwrapped to the bare name, so a sink configured as `execute` / `query` matches either form. (Before 2.14.0 they resolved to nothing and to the literal `query<Row>`, so templated calls escaped every name-filtered rule.)
- A reference declaration (`const std::string& r = x;`) is a `reference_declarator`, which - unlike `pointer_declarator` - has no `declarator` field; its name is a plain child. Taint binds through it, so `r` carries `x`'s taint.

## Deliberately not registered for C++

| Rule | Rationale |
|---|---|
| SAFE301 `global_state` | No `global` keyword; namespace / file-scope state is the SAFE302 port. |
| SAFE305 `wide_scope_declaration` | No `var` hoisting distinction. |
| SAFE401 `resource_lifecycle` | RAII makes cleanup language-enforced (same rationale as Rust); raw `new` / `delete` discipline is SAFE310 / SAFE315. |
| SAFE803 `null_dereference` | Nullable-return tracking without types would be noise (same as C). |
