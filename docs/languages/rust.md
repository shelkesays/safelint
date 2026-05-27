# Rust

SafeLint analyses Rust source for the Holzmann "Power of Ten" safety rules and Rust-language-specific patterns: function length, nesting depth, cyclomatic complexity, error-handling discipline (`Result` / `Option` patterns, panic placement, lock poisoning), `unsafe` block documentation, and dataflow taint. Rust support landed in **v2.2.0**. SafeLint does NOT replace `cargo clippy` / `cargo fmt` / `cargo test`, it runs alongside them and covers a narrower set focused on Holzmann safety + Rust-idiom-specific patterns; clippy's surface is much broader and complementary.

## File extensions

- **`.rs`**, parsed by `tree-sitter-rust`. Picked up by `safelint check` (directory mode, `--all-files` mode, and the pre-commit hook). Crate root files (`lib.rs` / `main.rs`), module files (`mod.rs`), binary entries, integration-test files under `tests/`, and example files under `examples/` are all treated uniformly as Rust source.

## Quick start

```bash
pip install 'safelint[rust]'      # adds the tree-sitter-rust grammar
safelint check src/                # lint a directory (git-modified files by default)
safelint check --all-files .       # lint everything under cwd
safelint check --format json src/  # machine-readable for editors / CI
```

If your Rust project doesn't already have a Python tool chain, `pipx install 'safelint[rust]'` isolates the install. A `Cargo.toml` is not required; safelint walks source files directly.

v2.0.0+ ships every language grammar as an opt-in extra. Plain `pip install safelint` installs only the engine and would skip every `.rs` file with an install hint on first run.

## Rules that fire on Rust

**27 rules apply to Rust**: 17 cross-language rules + 10 Rust-only rules. 6 cross-language rules are deliberately skipped, see the next section.

### Cross-language rules

| Code | Rule | Notes for Rust |
|---|---|---|
| [SAFE101](../configuration/rules.md#safe101-function_length) | `function_length` | Counts source lines on `function_item` / `closure_expression`. Default cap is 60. Closure bodies count toward their own size, not the enclosing function. |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | `nesting_depth` | Counts `if_expression` / `if_let_expression` / `for_expression` / `while_expression` / `while_let_expression` / `loop_expression` / `match_expression`. Default max 2. `unsafe_block` adds visual indent but is NOT counted (no control-flow branch; documented separately by SAFE602). |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | `max_arguments` | Counts `parameter` and (for closures) bare `identifier` children of `closure_parameters`. `self_parameter` (`self` / `&self` / `&mut self`) is excluded - it's the receiver, analogous to Python's `self`. Default cap 7. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | `complexity` | Cyclomatic complexity: every `if_expression` / `for_expression` / `while_expression` / `loop_expression` / `match_arm` / `try_expression` (`foo()?`) adds one. `&&` / `\|\|` inside `binary_expression` each add one. Default cap 10. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | `side_effects_hidden` | Fires when a function with a "pure" name prefix (`get_` / `compute_` / `is_` / `has_` / `validate_` / `parse_` / etc.) contains an I/O primitive call or macro. **Rust's I/O entry points are mostly macros** (`println!` / `eprintln!` / `write!` / `writeln!` / `dbg!`), so the rule walks `macro_invocation` alongside `call_expression`. Default `io_functions_rust` covers stdout/stderr macros (`println` / `print` / `eprintln` / `eprint` / `write` / `writeln` / `dbg`), `std::fs` entry points (`read_to_string` / `read_to_end` / `read_dir` / `metadata` / `canonicalize`), `std::io::Read` / `Write` methods (`read` / `read_exact` / `read_line` / `write_all` / `flush`), `std::process::Command` runners (`spawn` / `output` / `status`), and network primitives (`connect` / `bind` / `accept` / `recv` / `recv_from` / `send_to`). Both bare and scoped forms resolve via trailing-bareword extraction. Macro names render with the `!` suffix in violation messages. |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | `side_effects` | Fires on any function (not name-signalled for I/O) containing an I/O call or macro. Same `io_functions_rust` vocabulary as SAFE303. The `io_name_keywords` exemption (`log` / `write` / `read` / `save` / `load` / `send` / `fetch` etc.) suppresses functions whose names already signal I/O. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | `unbounded_loops` | Fires on `loop { }` (Rust's unconditional infinite loop) and `while true { }` without an exiting break. **Labelled break** (`'outer: loop { loop { break 'outer; } }`) is correctly recognised: a labelled break's target resolves outward, and a break whose target is NOT defined strictly inside the loop counts as exiting. **`match` arms inside loops are NOT break-scope boundaries** in Rust (a `break` inside a match arm legally targets the enclosing loop). |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | `missing_assertions` | Walks `macro_invocation` nodes - Rust expresses assertions exclusively through macros. Default `assertion_calls_rust` covers stdlib (`assert` / `assert_eq` / `assert_ne`), debug-only stdlib (`debug_assert` / `debug_assert_eq` / `debug_assert_ne`), and proptest (`prop_assert` / `prop_assert_eq` / `prop_assert_ne`). `panic!` / `todo!` / `unreachable!` / `unimplemented!` are deliberately NOT recognised as assertions, they're failure-exit markers, not invariant checks. Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | `test_existence` | **Recognises both Rust test conventions:** inline (`#[cfg(test)] mod tests { ... }` or any `#[test]` function in the file) and external (`tests/<stem>.rs` Cargo integration tests, or alternative `tests/<stem>_test.rs`). The inline-test bypass is the headline Rust adaptation, without it, every Rust source with the idiomatic inline tests would fire SAFE701 asking for an external pair the Rust ecosystem doesn't use. Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | `test_coupling` | Same shape as SAFE701: inline tests trivially satisfy the rule (editing the source necessarily edits the inline tests). Files identified as test files (under `tests/` or filename ending `_test.rs`) are exempt. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | `tainted_sink` | Method parameters seeded as tainted on function entry. Default vanilla sinks (`sinks_rust`): `Command` / `new` (`Command::new(tainted)`), `arg` / `args` (`cmd.arg(tainted)`), `query` / `query_as` / `query_scalar` / `execute` / `execute_batch` (raw-SQL across sqlx / diesel / rusqlite / postgres), `Library` (libloading FFI), `open` (filesystem paths). Vanilla sources (`sources_rust`): `var` / `args` (env), `read_line` / `read_to_string` / `lock` (stdin), `recv` / `recv_from` (sockets). Vanilla sanitizers (`sanitizers_rust`): narrow generic-wrapper set (`validate` / `sanitize` / `escape` / `quote`); context-specific encoders deliberately NOT in defaults (same trade-off as Java - shared sanitizer set across sink categories). **Macro-based sinks** (`sqlx::query!`) are a documented limitation - they parse as `macro_invocation`, not `call_expression`, and the macro body is a token tree we don't currently decode. Disabled by default. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | `return_value_ignored` | Fires on bare expression statements whose call discards a meaningful return. Default `flagged_calls_rust`: `io::Write` (`write` / `write_all` / `write_fmt` / `flush`), `io::Read` (`read` / `read_exact` / `read_to_end` / `read_to_string`), `std::fs` mutators (`remove_file` / `remove_dir` / `remove_dir_all` / `rename` / `copy` / `create_dir` / `create_dir_all` / `set_permissions` / `set_len`), networking (`send` / `send_to`), `Command` runners (`spawn` / `output` / `status`), `Child` lifecycle (`wait` / `wait_with_output` / `try_wait` / `kill`). The Rust idiom for explicit discard is `let _ = expr;` - that does NOT fire SAFE802. Disabled by default. |
| [SAFE803](../configuration/rules.md#safe803-null_dereference) | `null_dereference` | Rust has no `null`; the analogue is unwrapping `Option<T>` / `Result<T, E>`. Fires on `<call>.unwrap()` / `.expect(...)` / `.unwrap_unchecked()` / `.unwrap_err()` / `.expect_err()` when the inner call's name is in `nullable_methods_rust`. Default set covers `Map::get` / `Vec::get` / `slice::get`, `Vec::first` / `last` / `pop`, `Iterator::next` / `nth` / `peek`, `&str::find` / `rfind` / `parse`, `env::var` / `var_os`, `std::fs::read` family, `checked_add` / `sub` / `mul` / `div`. Pass-through wrappers (`parenthesized_expression`, `reference_expression`, `try_expression` `foo()?`) are peeled before the receiver check. Recommended fix surfaced in messages: `if let Some(x) = ...` / `match` / propagate via `?`. Disabled by default. |

### Rust-only rules

| Code | Rule | Notes |
|---|---|---|
| [SAFE110](../configuration/rules.md#safe110-needless_mut) | `needless_mut` | **Holzmann rule 6 (smallest scope).** Fires on `let mut x = ...` where `x` is never reassigned, never has `&mut x` taken, and is never used as a method receiver / field-access target / index target. Conservative: skips ambiguous usages (method call, field expression) to keep false-positive rate low. Mirrors `clippy::needless_mut`. Disabled by default. |
| [SAFE112](../configuration/rules.md#safe112-unchecked_arithmetic_on_input) | `unchecked_arithmetic_on_input` | **Holzmann rule 7 (check return values).** Fires on `+` / `-` / `*` (NOT `/` or `%`) where at least one operand is an `identifier` matching an integer-typed function parameter. Detection is static-only - looks at parameter type annotations against `_RUST_INTEGER_PRIMITIVE_TYPES` (`i8`..`u128`, `isize`, `usize`). Misses arithmetic on locally-bound integers that derive from parameters; `cargo clippy` covers the type-inference-aware version. Disabled by default. |
| [SAFE204](../configuration/rules.md#safe204-panic_macros_outside_tests) | `panic_macros_outside_tests` | Fires on `panic!` / `todo!` / `unimplemented!` macro invocations in non-test code. `unreachable!()` is deliberately excluded from the default `panic_macros_rust` set (idiomatic for impossible-branch markers in `match` arms). Test code (`#[test]` or `#[cfg(test)] mod`) is exempt. Disabled by default. |
| [SAFE205](../configuration/rules.md#safe205-lock_poisoning_ignored) | `lock_poisoning_ignored` | Fires on `mutex.lock().unwrap()` / `rwlock.read().unwrap()` / `rwlock.write().unwrap()` / `try_lock().unwrap()` / `try_read().unwrap()` / `try_write().unwrap()` and the `.expect("...")` variants. The hazard: when a thread panics while holding the lock, subsequent acquisitions return `Err(PoisonError)`. `.unwrap()` cascades the panic; the safer form is `match` on `PoisonResult` or `.into_inner()` to recover the guard explicitly. Disabled by default. |
| [SAFE206](../configuration/rules.md#safe206-silent_result_discard) | `silent_result_discard` | The Rust spiritual analogue of SAFE202 (`empty_except`). Fires on empty `Err` arms in `match` (`Err(_) => {}`) and empty `if let Err(_) = ... { }` bodies. Both wildcard (`Err(_)`) and binding (`Err(e)`) forms count - the silent thing is the no-op body. **`let _ = result;` does NOT fire** (the underscore makes the discard explicit and auditable). **`result.ok();` does NOT fire** (explicit conversion to Option). **`if let Ok(v) = result { ... }` without else does NOT fire** (common idiom where the Err case is handled elsewhere). Disabled by default. |
| [SAFE207](../configuration/rules.md#safe207-unlogged_error_branch) | `unlogged_error_branch` | The Rust spiritual analogue of SAFE203 (`logging_on_error`). Fires on `Err` arms / `if let Err(...)` bodies with non-empty bodies that contain no log call. Recognised log calls: `error!` / `warn!` / `info!` / `debug!` / `trace!` / `log!` / `event!` (log / tracing crates), `eprintln!` / `eprint!` / `println!` / `print!` / `dbg!` (stderr / stdout writers). Exempts bodies that contain a `return_expression`, a panic-like macro (`panic!` / `todo!` / `unreachable!` / `unimplemented!`), or a tail-position `Err(...)` re-raise. Disabled by default. |
| [SAFE208](../configuration/rules.md#safe208-result_unwrap_outside_tests) | `result_unwrap_outside_tests` | **Holzmann rule 7 (check return values).** Broader form: any `.unwrap()` / `.expect()` / `.unwrap_unchecked()` outside test code. Catches bare-variable unwraps (`let r = foo(); r.unwrap();`) and unwrap chains that the narrower SAFE205 / SAFE803 rules don't cover. With all three enabled, `mutex.lock().unwrap()` fires multiple codes - documented intentional overlap; users pick strictness level by enabling subsets. `unwrap_or` / `unwrap_or_default` / `unwrap_or_else` are NOT in the set - they're explicit-default-on-Err, not silent failures. Disabled by default. |
| [SAFE306](../configuration/rules.md#safe306-dangerous_mem_ops) | `dangerous_mem_ops` | Fires on calls to `std::mem::transmute` / `transmute_copy` / `forget` / `zeroed` / `uninitialized`. **Path-qualified detection:** the function must be a `scoped_identifier` (or `generic_function` wrapping one, for turbofish `mem::transmute::<u8, i8>(0)`) whose path text contains `"mem"`. Bare `transmute(x)` (without `mem::` prefix) is NOT flagged - it's indistinguishable from a user-defined helper of the same name. Disabled by default. |
| [SAFE308](../configuration/rules.md#safe308-truncating_as_cast) | `truncating_as_cast` | **Holzmann rule 1 + 7 (well-defined operations + checked conversions).** Fires on `as u8` / `as i8` / `as u16` / `as i16` / `as u32` / `as i32` / `as u64` / `as i64` / `as f32` casts. The `as` operator silently truncates when the source value doesn't fit; `TryFrom` / `try_into()` is the explicit-failure-mode alternative. `isize` / `usize` / `i128` / `u128` / `f64` are NOT flagged as targets (widest types - casts TO them don't truncate). Configurable via `truncating_cast_targets_rust`. Disabled by default. |
| [SAFE602](../configuration/rules.md#safe602-undocumented_unsafe) | `undocumented_unsafe` | Fires on `unsafe { ... }` blocks lacking a `// SAFETY:` comment (case-insensitive) on a preceding line. Both `// SAFETY:` and `/* SAFETY: */` comment forms count. Multiple intervening line comments are walked through (the SAFETY line doesn't need to be the immediately-previous sibling, but no non-comment statement may sit between them). **`unsafe fn` declarations are NOT covered** - they require `/// # Safety` doc comments, a separate convention. Mirrors `clippy::undocumented_unsafe_blocks`. Disabled by default. |

### Rules deliberately skipped for Rust

| Code | Rule | Why skipped for Rust |
|---|---|---|
| [SAFE201](../configuration/rules.md#safe201-bare_except) | `bare_except` | Rust has no try/catch. The panic-recovery primitive is `std::panic::catch_unwind` which has its own auditable shape, no bare-catch hazard. |
| [SAFE202](../configuration/rules.md#safe202-empty_except) | `empty_except` | Rust has no try/catch. The spirit ("silently swallow an error") is covered by **SAFE206 `silent_result_discard`**, which has its own detection logic for `Err(_) => {}` arms and empty `if let Err(_) = ... { }` bodies. |
| [SAFE203](../configuration/rules.md#safe203-logging_on_error) | `logging_on_error` | Same as SAFE202 - no try/catch in Rust. The spirit ("handle the error without logging") is covered by **SAFE207 `unlogged_error_branch`** with its own detection for `Err` arms / `if let Err` bodies that contain no log call. |
| [SAFE301](../configuration/rules.md#safe301-global_state) | `global_state` | Rust has no `global` keyword. `static mut FOO` is the closest analogue but requires `unsafe { }` to access, so it's already audit-gated via **SAFE602 `undocumented_unsafe`**. |
| [SAFE302](../configuration/rules.md#safe302-global_mutation) | `global_mutation` | Same as SAFE301 - `static mut` writes are unsafe-gated, covered by SAFE602. |
| [SAFE401](../configuration/rules.md#safe401-resource_lifecycle) | `resource_lifecycle` | Rust's RAII (Drop trait) makes resource cleanup language-enforced - no `with` block, `try-finally`, or `try-with-resources` analogue is needed because going out of scope guarantees `Drop`. The rule has nothing to add for Rust. |

## Configuration

SafeLint config is read from `[tool.safelint]` in `pyproject.toml` (if your Rust project also has one, e.g. for `maturin` / `pyo3` projects) or from a standalone `safelint.toml` at the project root. Pure-Rust projects typically prefer the standalone form (without the `[tool.safelint]` prefix).

### Per-rule TOML overrides

Standard pattern: override any per-language config list with the `_rust` suffix:

```toml
[tool.safelint.rules.side_effects_hidden]
io_functions_rust = ["println", "print", "eprintln", "write_all"]   # narrower than the default

[tool.safelint.rules.tainted_sink]
enabled = true                          # dataflow rules are opt-in
sinks_rust = ["Command", "new", "arg", "query", "execute"]  # focused on shell + raw SQL

[tool.safelint.rules.dangerous_mem_ops]
enabled = true
dangerous_mem_ops_rust = ["transmute", "forget"]            # drop the rarer zeroed / uninitialized

[tool.safelint.rules.panic_macros_outside_tests]
enabled = true
panic_macros_rust = ["panic", "todo", "unimplemented", "unreachable"]   # add unreachable to defaults

[tool.safelint.rules.truncating_as_cast]
enabled = true
truncating_cast_targets_rust = ["i32", "u8"]   # only flag these target types
```

### Enabling the disabled-by-default Rust-only rules

All 10 Rust-only rules ship disabled by default. Opt-in via TOML:

```toml
[tool.safelint.rules.needless_mut]
enabled = true

[tool.safelint.rules.unchecked_arithmetic_on_input]
enabled = true

[tool.safelint.rules.panic_macros_outside_tests]
enabled = true

[tool.safelint.rules.lock_poisoning_ignored]
enabled = true

[tool.safelint.rules.silent_result_discard]
enabled = true

[tool.safelint.rules.unlogged_error_branch]
enabled = true

[tool.safelint.rules.result_unwrap_outside_tests]
enabled = true

[tool.safelint.rules.dangerous_mem_ops]
enabled = true

[tool.safelint.rules.truncating_as_cast]
enabled = true

[tool.safelint.rules.undocumented_unsafe]
enabled = true
```

## Integration with Rust tool chain

SafeLint runs alongside the standard Rust tool chain; it doesn't replace any of them. Typical wiring:

* **`cargo fmt`** handles formatting; safelint doesn't lint style.
* **`cargo clippy`** covers a huge surface of idiomatic-Rust lints. SafeLint and clippy overlap on a few rules (SAFE110 ~ `clippy::needless_mut`, SAFE602 ~ `clippy::undocumented_unsafe_blocks`, SAFE205 ~ partial `clippy::unwrap_used` coverage); the overlap is intentional - clippy isn't enabled by default in many projects and its rule set is broader than the Holzmann-safety focus. Use both; they complement.
* **Pre-commit**: drop into `.pre-commit-config.yaml`:

  ```yaml
  - repo: https://github.com/shelkesays/safelint
    rev: v2.2.0  # or whatever the latest tag is
    hooks:
      - id: safelint
        additional_dependencies: ['safelint[rust]']
  ```

  Pre-commit routes `.rs` files via the `rust` filetype tag in `types_or` (pre-commit's `identify` library recognises it).

* **CI**: invoke `safelint check src/ tests/ --fail-on warning` (or `--mode ci`) in your build pipeline. Exit code 0 / 1 / 2 maps cleanly to "passed" / "violations found" / "setup error - install hint emitted on stderr".
* **IDE**: any JSON-output-consuming editor plugin (the safelint JSON schema is stable in v2.0.0+) can surface violations inline.

## Holzmann mapping

For reference, here's how the 27 Rust-applicable rules map to Holzmann's Power of Ten:

| # | Holzmann rule | Rust coverage |
|---|---|---|
| 1 | Simple control flow | SAFE102, SAFE104, SAFE308 (well-defined casts) |
| 2 | Fixed loop bounds | SAFE501 |
| 3 | No dynamic alloc post-init | (out of safelint's static-analysis scope) |
| 4 | Short functions | SAFE101 |
| 5 | Assertion density | SAFE601 |
| 6 | Smallest scope | SAFE110 |
| 7 | Check return values & params | SAFE802, SAFE205, SAFE206, SAFE207, SAFE208, SAFE112, SAFE308 |
| 8 | Limited preprocessor | (n/a for Rust; macros are auditable via SAFE204) |
| 9 | Limit dereferencing | SAFE803 |
| 10 | Pedantic compiler warnings | (compiler concern; use `cargo clippy -- -W clippy::all`) |

Rules 3, 8, and 10 are inherently outside safelint's static-analysis remit; the other seven Holzmann rules have direct safelint coverage for Rust.

## Limitations

Documented gaps in the Rust port; users should be aware these patterns aren't caught by the current rule set:

* **Framework presets.** axum / actix-web / rocket / warp (web frameworks) and tokio / async-std (async runtimes) don't have dedicated SafeLint presets yet. Rule defaults assume vanilla stdlib; framework-specific patterns (axum's `IntoResponse`, actix's `web::Json` validation) would land in a future preset analogous to the Java `spring-boot` framework knob. Track via [GitHub issues](https://github.com/shelkesays/safelint/issues).
* **`unsafe fn` declarations.** SAFE602 covers `unsafe { ... }` blocks but not `unsafe fn` items. The latter requires `/// # Safety` doc-comment detection, a separate convention; a future rule may extend this.
* **Macro-based taint-flow sinks.** SAFE801 walks `call_expression` only; `sqlx::query!("SELECT ...")` (compile-time-checked SQL macros) and similar token-tree-based macros aren't currently modelled. Real SQL injection in those forms requires careful raw-string assembly which the current rule set won't catch. Use `sqlx::query` (the function form) with parameter binding for safelint coverage.
* **Type-inference-dependent rules.** SAFE112 sees parameter annotations but doesn't track locally-bound types; arithmetic on a local that derives from a parameter won't fire. `cargo clippy` covers the full-type-inference version (`clippy::arithmetic_side_effects`).
