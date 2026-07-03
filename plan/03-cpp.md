# C++ language support - implementation spec

**Status**: not started. **Prerequisite satisfied: C shipped in v2.7.0
(2026-07-02).** C++ reuses C's new rule set (SAFE106/310/311/312/313 widen
to C++), shares the grammar family, and inherits the `.h` ownership decision
(already live: `.h` lints as C). Read `plan/README.md` first, then the
standing references, then **section 0 below** - it carries binding
requirements from the C post-release audit and the context-resilience
protocol for the implementing agent.

**Scope**: one comprehensive MINOR release. Grammar `tree-sitter-cpp`,
extensions `.cpp`, `.cxx`, `.cc`, `.hpp`, `.hxx`, `.hh`. Line comments `//`.
`.h` stays registered to C (documented limitation; a C++ project's `.h`
headers lint as C).

**Why C++ is later on the roadmap**: templates, ADL, and the preprocessor make
rule design harder. Keep v1 scope disciplined: port the cross-language set,
widen the C rules, add a small C++-idiom set. Resist template-aware analysis.

---

## 0. Audit-derived requirements (binding; from the C v2.7.0 post-release audit)

The C release was audited against its spec and against the Power of Ten paper
on 2026-07-02. The audit found the C implementation behaviourally correct but
caught repeatable process gaps, which were **closed in the 2.7.1 release
BEFORE this C++ work** (owner-sequenced ahead of C++). That work shipped these
concrete artifacts, which now exist in the tree and are the baseline you build
on (the remediation plan file itself is removed on completion, so this spec
does not depend on it):

- the behavioural pin `tests/rules/test_c_power_of_ten_pin.py`,
- the SAFE106 / SAFE310 config-override tests in `tests/rules/test_c_rules.py`
  (via a config-aware helper `_codes_with_config`),
- the SAFE106 enabled/warning contract lock,
- the engine-level suite `tests/core/test_engine_c.py`,
- the C paper-fidelity notes in `docs/power-of-ten.md`,
- and the eight-language enumeration state across the docs / skill files.

So when you start C++, that C baseline is already fully closed and guarded.
This section tells you how to **build on** that baseline without regressing it
and without repeating the misses. **Every item here is a ship-blocker for the
C++ PR unless marked optional.**

### 0.1 Context-resilience protocol (follow exactly)

- This spec is the **single source of truth**. Work batch by batch (the
  section order below is the batch order), one coherent commit per batch,
  full validation gate before each commit. Position must be recoverable from
  `git log --oneline` alone.
- **After any context compaction, session restart, or hand-off: re-read this
  ENTIRE spec plus `plan/README.md` "Non-negotiables"**, then `git log` /
  `git status` to re-derive the next batch. Never resume from a summary's
  memory of the spec; resume from the spec.
- **Verify every Tree-sitter node type by probing** (plan/README.md has the
  probe snippet) and **verify every quoted anchor text before editing a
  doc** - if the text is not found verbatim, re-locate by grep and adapt;
  never guess.
- If the repository state contradicts this spec in a way it does not
  anticipate, stop and ask the owner rather than improvising.

### 0.2 C behaviour must not regress (the widening risk)

This work widens SAFE106/310/311/312/313 (and possibly the dataflow tracker)
from `("c",)` to `("c", "cpp")`. Widening must be **purely additive**: every
audited C behaviour must be byte-for-byte identical after this PR.

- The behavioural pin test `tests/rules/test_c_power_of_ten_pin.py` already
  exists (shipped in 2.7.1). It is a **representative cross-rule tripwire**
  (not one-per-rule, not exhaustive - the per-rule `tests/rules/test_*_c.py`
  files are the complete coverage), focused on the behaviours most at risk
  from this widening, including the review-hardened subtleties (goto-out-of-loop
  vs goto-within-loop for SAFE501, initialised-`extern` and pointer-returning-
  prototype for SAFE302, `(void)` cast for SAFE802, misordered brackets and
  string-literal brackets for SAFE311, include-guard-first-statement for
  SAFE312, scoped vs bare NOLINT for SAFE603). **It must stay green before,
  during, and after the C++ widening** - if any case flips, the widening
  regressed C behaviour; revert and rework rather than editing the pin. (If,
  unexpectedly, this file is absent - e.g. 2.7.1 did not land first - STOP
  and raise it; do not widen the C rules without this guard.)
- The C tracker (`src/safelint/analysis/dataflow_c.py`) embodies review fixes
  that are easy to lose when extending or copying into
  `src/safelint/analysis/dataflow_cpp.py`: ternary
  (`conditional_expression`) propagation, inline `assignment_expression`
  propagation into sink arguments (RHS always, LHS too for compound
  assignments), compound assignments preserving prior taint, fully
  iterative walks (no recursion, the analysis-module rule), and sanitizer
  calls whose arguments are NOT descended into. Carry all of these over;
  add a C++ test for each.

### 0.3 Ship-time test requirements the C release missed (do not repeat)

1. **Engine-level suite `tests/core/test_engine_cpp.py` in the same PR.**
   `tests/core/test_engine_c.py` now exists (added in 2.7.1); mirror it (and
   `tests/core/test_engine_go.py`): all six extensions in
   `supported_extensions()`, language resolution per extension, a clean
   end-to-end run, `SAFE000` on unparseable input, and directory discovery
   (a dir with `.cpp` + `.hpp` + a non-source file discovers exactly the two).
2. **Config-override tests for EVERY list knob, in the same PR.** The C
   override tests exist now (SAFE106/310) as the pattern to copy. For each
   `_cpp` list this spec introduces (`io_functions_cpp`,
   `dynamic_exec_calls_cpp`, `assertion_calls_cpp`, `sinks_cpp` /
   `sources_cpp` / `sanitizers_cpp`, `flagged_calls_cpp`, and any list on
   SAFE315/316), add BOTH directions: a custom entry fires, and a default
   entry no longer fires under the override (replaced, not merged). Route
   every new list through `_validated_string_list` (the Go-port pitfall).
3. **Decide and test the knob story for the widened C rules.** SAFE106/310
   read `_c`-suffixed keys (`nonlocal_jump_calls_c`, `allocation_calls_c`),
   now covered by C override tests. Decide explicitly: do `.cpp` files honour
   the same `_c` keys, or do they get `_cpp` variants? Document the decision
   on BOTH language pages and test the override path for BOTH languages
   (whichever design you pick, an override must demonstrably affect `.cpp`
   files, and the existing C override tests must still pass unchanged).
4. **Contract locks for default-on rules.** SAFE106 stays
   `enabled = true, severity = "warning"` after widening - assert it
   explicitly against `DEFAULTS` (`assert DEFAULTS["rules"]["nonlocal_jumps"]
   == {"enabled": True, "severity": "warning", ...}`; the 2.7.1 lock test
   `test_safe106_defaults_enabled_at_warning_severity` already exists - keep it
   green). Any
   NEW C++ rule that ships default-on needs the same lock; SAFE315/316 are
   opt-in, so for them the default-disabled smoke assertion (mirror
   `test_c_opt_in_rules_are_silent_by_default` in
   `tests/rules/test_c_rules.py`) is the required lock.

### 0.4 Paper-fidelity notes land in the SAME PR as the behaviour

The C audit found undocumented paper gaps because fidelity notes were treated
as separate from rule work. For C++, every deviation ships with its note in
`docs/power-of-ten.md` in the same PR:

- **Extend the two C gap notes to C++.** They already exist in
  `docs/power-of-ten.md` "Deferred and out-of-scope" (written C-only by
  2.7.1): recursive macro calls (rule 8) and typedef-hidden indirection
  (rule 9). Widen each to mention C++ - notably rule 9's note gains C++
  `using intp = int *;` type aliases as a second hiding form alongside the
  C `typedef`.
- **SAFE313's smart-pointer exemption is itself a paper deviation** - the
  paper's rule 9 bans everything beyond one dereference; exempting
  `unique_ptr` / `shared_ptr` / `weak_ptr` is the modern-C++ concession.
  Record it as a "Fidelity notes from the paper" bullet, not silently.
- **SAFE601's `static_assert` exclusion** (compile-time, does not count
  toward runtime assertion density) - already spec'd below; the note goes in
  rules.md AND the fidelity section.
- **Rule 1 and lambdas**: SAFE105's documented anonymous-function blind spot
  now applies to `lambda_expression` recursion; extend the existing note if
  the wording is Python/JS-specific.

### 0.5 Enumeration sweep (now eight -> nine)

2.7.1 fixed every enumeration to the **eight**-language state (the old
"Seven languages" stragglers in `CONTRIBUTING.md`, `docs/contributing/index.md`,
`docs/json-schema.md`, the "all-seven core" labels, and the README pre-commit
example are all resolved). Your mandatory stale-count/enumeration sweep is
therefore a clean **eight -> nine** step: grep the previous language's
extension / name / `tree-sitter-<lang>` per the `plan/README.md` "Enumerations
cascade" convention, plus re-grep the just-updated spots (they will now read
"eight" / list C, and must gain C++). Do NOT assume the sweep is trivial - C++
adds SIX extensions (`.cpp` / `.cxx` / `.cc` / `.hpp` / `.hxx` / `.hh`), so
every extension list needs all of them. Afterwards prove zero stragglers with
greps for the previous state - e.g. `grep -rn "eight\|all-eight\|... php, c\]"
README.md CONTRIBUTING.md docs/ src/safelint/skill_files/` (adapt to whatever
"eight"-state phrasings 2.7.1 left) - each must now read nine / include C++.

Also: when creating `sources_cpp`, copy the **shipped, trimmed** C
philosophy (return-value sources only: `getenv` / `fgets` / `gets`), NOT the
original C spec's list - `scanf` / `read` / `recv` were removed in review
because out-parameter readers taint the count variable, not the buffer. The
same reasoning applies to any C++ candidate (`std::getline` writes an
out-parameter too; if you want it as a source, that needs the
destination-buffer modelling the tracker does not have - leave it out and
document).

### 0.6 Pre-flight plan hygiene (step 0 of the work)

The 2.7.1 release already deleted `plan/02-c.md` and made C++ the "1 (next)"
row in `plan/README.md`. So step 0 here is lighter: confirm `plan/02-c.md` is
gone (if it somehow survived - 2.7.1 slipped - delete it, verifying the SAFE106
enabled/warning rationale is on `docs/languages/c.md` first), mark this spec
in-progress in `plan/README.md`, and add the C++ RC version bump per the
release flow. On completion, delete this spec and add a "C++ shipped in
2.8.0" blockquote, mirroring the Go / PHP / C entries.

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
| SAFE202 / SAFE203 | Port: empty `catch` bodies; logging recognised via call names (`log`, `error`, `warn`, spdlog/glog method names) in `logging_calls`-style config - `std::cerr << ...` is an operator, not a call, so also match a `<<` chain by its **leftmost operand's resolved stream target**: walk to the leftmost operand of the (possibly nested) `binary_expression`/`<<` and treat it as logging when the target resolves to `cerr` / `clog`, **including the namespace-qualified `std::cerr` / `std::clog`** (a `qualified_identifier`, not a bare `identifier`) and any `using`-introduced alias (`using std::cerr;`). Do NOT match only the bare `cerr` text - idiomatic code writes `std::cerr` - but keep the branch small (a fixed target set, no general type resolution). Re-raise `throw;` (bare rethrow) stays exempt. |
| SAFE302 `global_mutation` | Two declaration-site shapes: file/namespace-scope non-`const` variable declarations (the C shape) AND non-`const` `static` data members in classes (the Java shape). `constexpr` counts as const. |
| SAFE303 / SAFE304 | `io_functions_cpp`: C's list plus `cout`, `cerr` stream usage (operator heuristic above), `getline`, `ifstream`, `ofstream` constructors (via `call_name` on the type). |
| SAFE309 | `dynamic_exec_calls_cpp = ["dlopen", "dlsym", "LoadLibrary", "GetProcAddress"]`. |
| SAFE501 | As C (`while (true)`, `for (;;)`); `goto`-exit resolution carried over. |
| SAFE601 | `assertion_calls_cpp`: `assert` plus gtest's `EXPECT_*` / `ASSERT_*` macro-call names (they parse as `call_expression`). `static_assert` is compile-time and does NOT count toward the runtime-density rule (document). |
| SAFE603 | As C (bare `NOLINT` / `NOLINTNEXTLINE`), plus bare `// clang-format off` is NOT a lint suppression (do not flag). |
| SAFE701 / SAFE702 | `foo_test.cpp` / `test_foo.cpp` / gtest `foo_unittest.cpp` candidates; default `test_dirs = ["tests", "test"]`, document overrides. |
| SAFE801 / SAFE802 | Reuse / extend `src/safelint/analysis/dataflow_c.py` into `src/safelint/analysis/dataflow_cpp.py` (the AST is a superset; a shared module with a language flag is acceptable if it stays under the self-lint caps). Sinks add `system`-equivalents and `popen`; flagged calls add `c_str`-into-system patterns only via the sink list, not new analysis. |
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
  prior language's extension / name (whole-word, `grep -w`, so short names
  like `go` / `c` don't over-match) / `tree-sitter-<lang>` across `docs/`,
  `README.md`, `SECURITY.md`, and `src/safelint/skill_files/`.
