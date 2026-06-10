# The Power of Ten, adapted

SafeLint is an adaptation of Gerard Holzmann's ["The Power of Ten - Rules for Developing Safety-Critical Code"](https://spinroot.com/gerard/pdf/P10.pdf) (NASA/JPL, 2006). The original ten rules target C for spacecraft flight software; SafeLint translates their *intent* to Python, JavaScript, TypeScript, Java, and Rust. Some rules map almost directly (bounded function length, assertion density); others have no literal analogue in a garbage-collected or memory-safe language and are adapted, or deliberately left to the compiler.

This page maps each of the ten rules to the SafeLint rules that implement it, and records the rationale wherever a clause is adapted away. For the full per-rule configuration, see the [rules reference](configuration/rules.md); for what fires on each language, see the per-language pages under **Languages**.

## Coverage map

| # | Holzmann rule | SafeLint rules | Notes |
|---|---|---|---|
| 1 | Simple control flow; no `goto`, `setjmp`, or **recursion** | [SAFE102](configuration/rules.md#safe102-nesting_depth) `nesting_depth`, [SAFE104](configuration/rules.md#safe104-complexity) `complexity`, [SAFE105](configuration/rules.md#safe105-no_recursion) `no_recursion` | `goto` / `setjmp` do not exist in the supported languages. SAFE105 enforces the recursion ban (direct self-recursion; mutual recursion is out of scope). |
| 2 | Fixed loop bounds | [SAFE501](configuration/rules.md#safe501-unbounded_loops) `unbounded_loops` | Flags `while True` / `loop {}` without a reachable exit. |
| 3 | No dynamic memory allocation after initialisation | *(adapted away, see below)* | No direct rule; intent partly served by SAFE501 and SAFE401. |
| 4 | Functions no longer than ~60 lines | [SAFE101](configuration/rules.md#safe101-function_length) `function_length`, [SAFE103](configuration/rules.md#safe103-max_arguments) `max_arguments` | Default cap 60 lines / 7 arguments. |
| 5 | At least two assertions per function | [SAFE601](configuration/rules.md#safe601-missing_assertions) `missing_assertions`, [SAFE701](configuration/rules.md#safe701-test_existence) / [SAFE702](configuration/rules.md#safe702-test_coupling) | SAFE601 checks in-function assertions; the test rules check external verification. |
| 6 | Declare data at the smallest possible scope | [SAFE301](configuration/rules.md#safe301-global_state) `global_state`, [SAFE302](configuration/rules.md#safe302-global_mutation) `global_mutation`, [SAFE305](configuration/rules.md#safe305-wide_scope_declaration) `wide_scope_declaration`, [SAFE307](configuration/rules.md#safe307-interior_mutable_static) `interior_mutable_static` | Python `global`; JS/TS `globalThis.*` writes and `var` hoisting; Java non-final `static` fields; Rust interior-mutable statics. |
| 7 | Check every return value; validate parameters | [SAFE802](configuration/rules.md#safe802-return_value_ignored) `return_value_ignored`, [SAFE803](configuration/rules.md#safe803-null_dereference) `null_dereference`, [SAFE205](configuration/rules.md#safe205-lock_poisoning_ignored)–[SAFE208](configuration/rules.md#safe208-result_unwrap_outside_tests) (Rust), [SAFE112](configuration/rules.md#safe112-unchecked_arithmetic_on_input) (Rust), [SAFE903](configuration/rules.md#safe903-spring_unvalidated_input) (Spring) | Return-value checking is broadly covered; parameter validation is covered precisely where it can be (Spring `@Valid`, Rust arithmetic-on-input) rather than via a noisy generic rule. |
| 8 | Limit the preprocessor | [SAFE309](configuration/rules.md#safe309-dynamic_code_execution) `dynamic_code_execution`, [SAFE801](configuration/rules.md#safe801-tainted_sink) `tainted_sink`, [SAFE204](configuration/rules.md#safe204-panic_macros_outside_tests) (Rust) | No C preprocessor exists; the analysability threat is dynamic code execution / reflection (structural via SAFE309, taint-gated via SAFE801). See below for Rust macros. |
| 9 | Restrict pointer use | [SAFE803](configuration/rules.md#safe803-null_dereference) `null_dereference`, [SAFE306](configuration/rules.md#safe306-dangerous_mem_ops) (Rust), [SAFE308](configuration/rules.md#safe308-truncating_as_cast) (Rust), [SAFE602](configuration/rules.md#safe602-undocumented_unsafe) (Rust) | Null/Option dereference across all languages; raw-pointer and transmute hazards on Rust. |
| 10 | All warnings on; heed every warning | [SAFE603](configuration/rules.md#safe603-blanket_suppression) `blanket_suppression`, plus the [engine-internal codes](configuration/rules.md#engine-internal-codes) SAFE000 / SAFE004 | SafeLint runs as the always-on analyser; SAFE603 flags blanket suppressions of *other* analysers; SAFE004 polices SafeLint's own unused suppressions. |

The error-handling rules ([SAFE201](configuration/rules.md#safe201-bare_except)–[SAFE203](configuration/rules.md#safe203-logging_on_error) and their Rust analogues [SAFE206](configuration/rules.md#safe206-silent_result_discard)/[SAFE207](configuration/rules.md#safe207-unlogged_error_branch)) and the hidden-side-effect rules ([SAFE303](configuration/rules.md#safe303-side_effects_hidden)/[SAFE304](configuration/rules.md#safe304-side_effects)) are SafeLint extensions in the *spirit* of the Power of Ten (predictable, reviewable, testable code) rather than direct mappings of a numbered clause.

## Adapted-away clauses

### Rule 3: no dynamic allocation after initialisation

The original rule forbids `malloc`/`free` after start-up so that memory behaviour is statically bounded and there is no allocator non-determinism or use-after-free. SafeLint has no direct rule for this:

- **Python, JavaScript, TypeScript, Java** are garbage-collected. Allocation-site analysis is not a meaningful safety gate in these languages: allocation is pervasive and implicit, and the failure modes the rule targets (fragmentation, allocator latency, leaks-by-forgotten-free) are managed by the runtime. The rule's underlying intent, *predictable memory and termination behaviour*, is partly served by [SAFE501](configuration/rules.md#safe501-unbounded_loops) (bounded loops) and [SAFE401](configuration/rules.md#safe401-resource_lifecycle) (deterministic resource cleanup).
- **Rust** makes allocation explicit but idiomatic; `rustc` and `clippy` own the performance lane, and a blanket "no allocation in a loop" rule would be noisy. An allocation-in-loop rule is a *possible future addition*, deliberately not committed to here.
- **AssemblyScript** (`.as`, parsed via the TypeScript grammar) genuinely has manual memory management and is the one place a rule-3 analysis would be meaningful; it is currently an un-analysed surface and is noted here as a known gap.

### Rule 8: limit the preprocessor

C's `#define` macros generate code the compiler (and any analyser) cannot see until expansion, which is why the original rule restricts them. The supported languages have no C-style preprocessor, so the analysability threat is **runtime code generation and reflection**:

- **Python, JavaScript, TypeScript, Java** are covered structurally by [SAFE309](configuration/rules.md#safe309-dynamic_code_execution) (flag `eval` / `new Function` / `Class.forName` / `Method.invoke` wherever they appear) and dataflow-wise by [SAFE801](configuration/rules.md#safe801-tainted_sink) (flag user input reaching those sinks). The two are complementary and may both fire on one line.
- **Rust**'s true preprocessor analogue is its **macro system**. Macro bodies parse as opaque token trees that SafeLint does not decode (the same documented limitation that makes [SAFE801](configuration/rules.md#safe801-tainted_sink) blind to `sqlx::query!`), so coverage is limited to [SAFE204](configuration/rules.md#safe204-panic_macros_outside_tests) (panic-family macros) and the `lazy_static!` case caught by [SAFE307](configuration/rules.md#safe307-interior_mutable_static). A general macro-as-codegen rule is not offered.

## Deferred and out-of-scope

These are recorded so they are recognised as deliberate decisions, not oversights:

- **Indirect / mutual recursion** (rule 1): SAFE105 covers direct self-recursion only. Detecting `a -> b -> a` cycles needs a call graph and is out of scope for now.
- **Generic parameter validation** (rule 7, second half): a blanket "validate every parameter" rule is unacceptably noisy without type information. The intent is served precisely where it can be: Spring `@Valid` ([SAFE903](configuration/rules.md#safe903-spring_unvalidated_input)) and Rust arithmetic-on-input ([SAFE112](configuration/rules.md#safe112-unchecked_arithmetic_on_input)).
- **Rust allocation-in-loop** (rule 3): a real but niche check, recorded above as a possible future rule.
- **Java `static final` interior mutability** (rule 6): a `static final` field holding a mutable collection is not flagged by [SAFE302](configuration/rules.md#safe302-global_mutation); detecting interior mutability needs type resolution SafeLint does not do.
