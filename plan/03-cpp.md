# C++ language support - implementation spec

**Status**: not started. **Hard prerequisite: the C spec (`plan/02-c.md`) must
be shipped first.** C++ reuses C's new rule set (SAFE106/310/311/312/313 widen
to C++), shares the grammar family, and inherits the `.h` ownership decision.
Read `plan/README.md` first, then the standing references.

**Scope**: one comprehensive MINOR release. Grammar `tree-sitter-cpp`,
extensions `.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`. Line comments `//`.
`.h` stays registered to C (documented limitation; a C++ project's `.h`
headers lint as C).

**Why C++ is later on the roadmap**: templates, ADL, and the preprocessor make
rule design harder. Keep v1 scope disciplined: port the cross-language set,
widen the C rules, add a small C++-idiom set. Resist template-aware analysis.

---

## 1. Language module (`src/safelint/languages/cpp.py`)

- `EXTRA_NAME = "cpp"`, extra `cpp = ["tree-sitter-cpp>=0.23.0"]` + `[all]`.
- `LanguageDefinition(name="cpp", file_extensions={".cpp", ".cxx", ".cc",
  ".hpp", ".hxx", ".hh"}, comment_node_type="comment", comment_prefix="//")`.
- Key node types (probe to verify; tree-sitter-cpp is a superset of
  tree-sitter-c): `function_definition` (free functions AND methods - the
  declarator distinguishes), `lambda_expression`, `call_expression`,
  `new_expression`, `delete_expression`, `try_statement`, `catch_clause`,
  `throw_statement`, `class_specifier` / `struct_specifier`,
  `field_declaration`, `template_declaration`, C's `goto_statement` and
  `preproc_*` family, `namespace_definition`.
- `FUNCTION_TYPES = {function_definition, lambda_expression}`. A
  `template_declaration` *wraps* a `function_definition`; the inner node is
  what the walks find, so templates need no special casing (add a test).

## 2. Per-rule portability audit

### Ports cleanly

| Rule | C++ shape / notes |
|---|---|
| SAFE101-104 | As C, plus `lambda_expression` bodies count as their own functions; `catch_clause` adds complexity. |
| SAFE105 `no_recursion` | Bare calls plus `this->walk(...)` qualified self-calls (`field_expression` with `this`). Same shadowing guard as the other languages. |
| SAFE201 `bare_except` | **First registration beyond Python.** `catch (...)` (the literal ellipsis catch-all) is C++'s bare except: it swallows every exception including the ones used for stack-unwind cancellation. The catch parameter shape distinguishes `catch (...)` from typed catches. |
| SAFE202 / SAFE203 | Port: empty `catch` bodies; logging recognised via call names (`log`, `error`, `warn`, spdlog/glog method names) in `logging_calls`-style config - `std::cerr << ...` is an operator, not a call; recognise a `binary_expression`/`<<` whose leftmost operand text is `cerr` or `clog` as logging (C++-specific branch, keep it small). Re-raise `throw;` (bare rethrow) is exempt. |
| SAFE302 `global_mutation` | Two declaration-site shapes: file/namespace-scope non-`const` variable declarations (the C shape) AND non-`const` `static` data members in classes (the Java shape). `constexpr` counts as const. |
| SAFE303 / SAFE304 | `io_functions_cpp`: C's list plus `cout`, `cerr` stream usage (operator heuristic above), `getline`, `ifstream`, `ofstream` constructors (via `call_name` on the type). |
| SAFE309 | `dynamic_exec_calls_cpp = ["dlopen", "dlsym", "LoadLibrary", "GetProcAddress"]`. |
| SAFE501 | As C (`while (true)`, `for (;;)`); `goto`-exit resolution carried over. |
| SAFE601 | `assertion_calls_cpp`: `assert` plus gtest's `EXPECT_*` / `ASSERT_*` macro-call names (they parse as `call_expression`). `static_assert` is compile-time and does NOT count toward the runtime-density rule (document). |
| SAFE603 | As C (bare `NOLINT` / `NOLINTNEXTLINE`), plus bare `// clang-format off` is NOT a lint suppression (do not flag). |
| SAFE701 / SAFE702 | `foo_test.cpp` / `test_foo.cpp` / gtest `foo_unittest.cpp` candidates; default `test_dirs = ["tests", "test"]`, document overrides. |
| SAFE801 / SAFE802 | Reuse / extend `analysis/dataflow_c.py` into `dataflow_cpp.py` (the AST is a superset; a shared module with a language flag is acceptable if it stays under the self-lint caps). Sinks add `system`-equivalents and `popen`; flagged calls add `c_str`-into-system patterns only via the sink list, not new analysis. |
| SAFE106 / SAFE310 / SAFE311 / SAFE312 / SAFE313 (from C) | **Widen the C-only tuples to `("c", "cpp")`.** SAFE310 additionally recognises `new_expression` / `delete_expression` as dynamic allocation in C++. SAFE313 exempts smart-pointer types (`unique_ptr`, `shared_ptr`, `weak_ptr`) from the pointer-level count. |

### Deliberately skipped

| Rule | Rationale |
|---|---|
| SAFE301 | No `global` keyword. |
| SAFE305 | No hoisting. |
| SAFE401 `resource_lifecycle` | RAII makes cleanup language-enforced, same rationale as Rust. Raw `new` / `delete` discipline is SAFE310's (widened) job; the new SAFE315 below covers the idiom gap. |
| SAFE803 | Same as C; nullable tracking needs types. |

### New C++-only rules (verify codes free; opt-in)

| Proposed | Name | Band | Behaviour |
|---|---|---|---|
| SAFE315 | `raw_new_delete` | 3xx | Flags `new_expression` / `delete_expression` outside smart-pointer construction (`make_unique` / `make_shared` are clean by construction and never fire; `new` directly inside a `unique_ptr<T>(new T)` constructor argument still fires - prefer `make_unique`). The modern-C++ ownership rule. Disabled by default. Note the overlap with widened SAFE310: 310 is the Holzmann no-allocation rule (embedded posture), 315 is the idiom rule (ownership posture); enabling both double-reports by design, document like SAFE205/208. |
| SAFE316 | `dangerous_casts` | 3xx (precedent: SAFE306) | Flags `reinterpret_cast` and `const_cast` expressions (named node types). `static_cast` / `dynamic_cast` are clean. Disabled by default. |

## 3. Framework / runtime presets

None in v1. Note Qt / Boost-specific lists as a future `[tool.safelint.cpp]`
axis in the language page, per the Part B preset standard.

## 4. Tests

Standard fan-out plus: a `template_declaration`-wrapped function test for
every FUNCTION_TYPES walker (length / nesting / complexity / recursion), the
`catch (...)` vs typed-catch pair for SAFE201, the `cerr <<` logging
recognition for SAFE203, smart-pointer exemptions for SAFE313/315, and tuple
re-bucketing in `tests/core/test_engine.py` (the five C rules move from a
C-only bucket to a `("c", "cpp")` bucket - add it).

## 5. Documentation and skill files

Shared checklist (plan/README.md), with the C++-specific content:

- `docs/languages/cpp.md`: `.h`-lints-as-C note, the SAFE201 catch-all story
  (first non-Python registration - also update SAFE201's rules.md section and
  the "Python-only" phrasing it carries today), RAII / SAFE401 rationale,
  SAFE310-vs-315 posture table, `_cpp` keys with both TOML forms.
- `docs/languages/c.md`: update the shared-rule tuples note (C rules now
  C + C++).
- `docs/power-of-ten.md`: extend the C literal-rule notes to C++.
- `rules.md`: SAFE315/316 sections; SAFE201's scope row changes from
  "Python-only" to Python + C++; remove C++ from "Planned".
- Skill files: `languages/cpp.md` addendum, 14 Step-2 rows, README counts,
  new rule codes/names in all 14 client tables; **SAFE201's row text in all
  14 clients says "Python-only" today and must be reworded** (drift test only
  checks presence, not accuracy - this one is on you).
- **Scattered enumerations (the Go miss - OUTSIDE the language tables):**
  `docs/configuration/cli.md` (`--all-files` extension list + `--language`
  values), `SECURITY.md` (supported-versions table, `tree-sitter-<lang>`
  grammar list, files-read extension list), `docs/configuration/toml.md`
  (opt-in-rules walkthrough), and `CONTRIBUTING.md` (language count +
  examples). C++ adds several extensions (`.cpp` / `.cxx` / `.cc` / `.hpp` /
  `.hxx` / `.hh`) - every extension list above needs all of them.
- CHANGELOG `[Unreleased]`; stale-count **and enumeration** sweep: grep the
  prior language's extension / name / `tree-sitter-<lang>` across `docs/`,
  `README.md`, `SECURITY.md`, and `src/safelint/skill_files/`.
