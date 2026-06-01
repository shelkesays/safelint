# safelint skill: Rust addendum

Language-specific notes for the Rust target. Mirrors `src/safelint/languages/rust.py` in the safelint source tree. The skill core (`claude/SKILL.md` for Claude Code, each peer client's own file for other agents) handles the universal flow; this file holds Rust-specific detail.

## Install nuance

safelint is a Python package, not a Cargo crate. The Rust grammar ships in the `[rust]` extra:

```bash
pip install 'safelint[rust]'
# or, in a project that already uses uv:
uv add --dev 'safelint[rust]'
# or, kitchen-sink:
pip install 'safelint[all]'
```

After install, `safelint` is on `PATH`. Run it from the Rust crate / workspace root the same way as for any other language; safelint auto-detects by file extension. A `Cargo.toml` is not required (safelint walks the source tree directly), but using safelint alongside `cargo fmt`, `cargo clippy`, and `cargo test` is the expected workflow.

If you run plain `pip install safelint` (no extra), the first run emits `safelint: warning: skipping .rs files, install with: pip install 'safelint[rust]'`. **Exit code is 2 only when EVERY candidate file is skipped** (typical Rust-only project); in a mixed Python + Rust repo, safelint emits the `.rs` skip warning and continues linting the supported files normally.

For pre-commit integration, set `additional_dependencies`:

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.2.0  # use a recent tag that includes the [rust] extra
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[rust]']
      # For a polyglot repo with Python + Rust:
      # additional_dependencies: ['safelint[python,rust]']
```

## File extensions

safelint lints `.rs` files. The skill doesn't need to filter by extension - `safelint check` walks the project and picks up the registered extensions automatically. There is no separate handling for the crate root (`lib.rs` / `main.rs`), module files (`mod.rs`), or binary entries; they're all `.rs` and treated uniformly.

## Rule count

23 rules apply to Rust: **13 cross-language rules** (SAFE101-104, SAFE303-304, SAFE501, SAFE601, SAFE701-702, SAFE801-803) plus **10 Rust-specific rules** (SAFE110, SAFE112, SAFE204-208, SAFE306, SAFE308, SAFE602). The 6 rules deliberately skipped for Rust (SAFE201, SAFE202, SAFE203, SAFE301, SAFE302, SAFE401) are listed in the "Deliberately skipped" section below.

## Macros vs function calls

The biggest Rust-vs-other-languages shape difference safelint contends with: **Rust I/O entry points are mostly macros** (`println!`, `eprintln!`, `write!`, `writeln!`, `dbg!`), not function calls. The rule engine walks both `call_expression` and `macro_invocation` nodes for SAFE303 / SAFE304, with the same configured `io_functions_rust` list applying to both. Violation messages render macros with the trailing `!` (e.g. `println!`) so you can tell at a glance which form fired.

`format!` and `vec!` are deliberately NOT in any I/O list - they return `String` / `Vec<T>`, no actual I/O.

## Test-context detection

Several Rust rules exempt test code: SAFE204 (`panic_macros_outside_tests`), SAFE208 (`result_unwrap_outside_tests`), and SAFE701 (`test_existence`) all treat inline `#[test]` functions and items inside `#[cfg(test)] mod` blocks as test context. The detection walks parent `function_item` / `mod_item` nodes looking for the relevant attribute as a *preceding sibling* `attribute_item` (tree-sitter-rust attaches attributes that way; `_node_has_test_marker_attribute` does the walk).

Inline test conventions are recognised natively for SAFE701 / SAFE702 - `#[cfg(test)] mod tests { ... }` blocks satisfy "this source file is tested" without an external `tests/<stem>.rs` pair.

## Language-specific rule phrasing

When the user asks "why is this flagged?", the universal rationale in the per-client core is correct, but Rust phrasing helps. The table lists every rule that applies to Rust; rules deliberately skipped (with rationale) are in the next section.

| Code | Rule | Rust-specific notes |
|---|---|---|
| SAFE101 | function_length | Counts source lines on `function_item` / `closure_expression`. Default cap is 60 source lines. Closure bodies count toward their own size, not the enclosing function. |
| SAFE102 | nesting_depth | Counts `if_expression` / `if_let_expression` / `for_expression` / `while_expression` / `while_let_expression` / `loop_expression` / `match_expression`. Default max is 2. `unsafe_block` is NOT counted (visual indentation but not a control-flow branch). |
| SAFE103 | max_arguments | Counts `parameter` and (for closures) bare `identifier` children of `closure_parameters`. `self_parameter` (`self` / `&self` / `&mut self`) is excluded - it's the receiver, analogous to Python's `self`. Default cap is 7. |
| SAFE104 | complexity | Cyclomatic complexity: every `if_expression` / `for_expression` / `while_expression` / `loop_expression` / `match_arm` / `try_expression` (`foo()?`) adds one. `&&` / `\|\|` inside `binary_expression` each add one. Default cap is 10. |
| SAFE110 | needless_mut | *Rust-only.* Fires on `let mut x = ...` where `x` is never reassigned, never has `&mut x` taken, and is never used as a method receiver / field-access target / index target. Conservative: skips ambiguous usages (method call, field expression) to keep false-positive rate low. Mirrors `clippy::needless_mut` for projects without a clippy run. Disabled by default. |
| SAFE112 | unchecked_arithmetic_on_input | *Rust-only.* Fires on `+` / `-` / `*` (NOT `/` or `%`) where at least one operand is an `identifier` matching an integer-typed function parameter. Detection is static-only - looks at parameter type annotations against the `_RUST_INTEGER_PRIMITIVE_TYPES` set (`i8` ... `u128`, `isize`, `usize`). Misses arithmetic on locally-bound integers that derive from parameters; clippy covers the type-inference-aware version. Disabled by default. |
| SAFE204 | panic_macros_outside_tests | *Rust-only.* Fires on `panic!` / `todo!` / `unimplemented!` macro invocations in non-test code. `unreachable!()` is deliberately excluded from the default `panic_macros_rust` set (idiomatic for impossible-branch markers in `match` arms). Test code (`#[test]` / `#[cfg(test)] mod`) is exempt. Disabled by default. |
| SAFE205 | lock_poisoning_ignored | *Rust-only.* Fires on `mutex.lock().unwrap()` / `rwlock.read().unwrap()` / `rwlock.write().unwrap()` / `try_lock().unwrap()` / `try_read().unwrap()` / `try_write().unwrap()` and the `.expect("...")` variants. The hazard: when a thread panics while holding the lock, subsequent acquisitions return `Err(PoisonError)`. `.unwrap()` cascades the panic; the safer form is `match` on `PoisonResult` or `.into_inner()` to recover the guard explicitly. Disabled by default. |
| SAFE206 | silent_result_discard | *Rust-only.* The Rust spiritual analogue of SAFE202 (`empty_except`). Fires on empty `Err` arms in `match` (`Err(_) => {}`) and empty `if let Err(_) = ... { }` bodies. Both wildcard (`Err(_)`) and binding (`Err(e)`) forms count - the silent thing is the no-op body. `let _ = result;` does NOT fire (the underscore makes the discard explicit and auditable). `result.ok();` does NOT fire (explicit conversion to Option). `if let Ok(v) = result { ... }` without `else` does NOT fire (common idiom where the Err case is handled elsewhere). Disabled by default. |
| SAFE207 | unlogged_error_branch | *Rust-only.* The Rust spiritual analogue of SAFE203 (`logging_on_error`). Fires on `Err` arms / `if let Err(...)` bodies with non-empty bodies that contain no log call. Recognised log calls: `error!` / `warn!` / `info!` / `debug!` / `trace!` / `log!` / `event!` (log / tracing crates), `eprintln!` / `eprint!` / `println!` / `print!` / `dbg!` (stderr / stdout writers). Exempts bodies that contain a `return_expression`, a panic-like macro (`panic!` / `todo!` / `unreachable!` / `unimplemented!`), or a tail-position `Err(...)` re-raise. Disabled by default. |
| SAFE208 | result_unwrap_outside_tests | *Rust-only.* Broader Holzmann-rule-7 (`check return values`) form. Fires on any `.unwrap()` / `.expect()` / `.unwrap_unchecked()` outside test code. Catches bare-variable unwraps (`let r = foo(); r.unwrap();`) and unwrap chains that the narrower SAFE205 / SAFE803 rules don't cover. With all three enabled, `mutex.lock().unwrap()` fires multiple codes - documented intentional overlap; users pick strictness level by enabling subsets. `unwrap_or` / `unwrap_or_default` / `unwrap_or_else` are NOT in the set - they're explicit-default-on-Err, not silent failures. Disabled by default. |
| SAFE303 | side_effects_hidden | Fires when a function with a "pure" name prefix (`get_` / `compute_` / `is_` / `has_` / `validate_` / `parse_` / etc.) contains an I/O primitive call or macro. Rust default `io_functions_rust` set covers stdout / stderr macros (`println` / `print` / `eprintln` / `eprint` / `write` / `writeln` / `dbg`), `std::fs` entry points (`read_to_string` / `read_to_end` / `read_dir` / `metadata` / `canonicalize`), `std::io::Read` / `Write` methods (`read` / `read_exact` / `read_line` / `write_all` / `flush`), `std::process::Command` runners (`spawn` / `output` / `status`), and network (`connect` / `bind` / `accept` / `recv` / `recv_from` / `send_to`). Both bare and scoped forms are resolved (`std::println!` matches via trailing-bareword extraction). |
| SAFE304 | side_effects | Fires when any function (not name-signalled for I/O) contains an I/O call or macro. Same `io_functions_rust` vocabulary as SAFE303. The `io_name_keywords` exemption (`log` / `write` / `read` / `save` / `load` / `send` / `fetch` etc.) suppresses functions whose names already signal I/O. Macro names render with the `!` suffix in violation messages. |
| SAFE306 | dangerous_mem_ops | *Rust-only.* Fires on calls to `std::mem::transmute` / `transmute_copy` / `forget` / `zeroed` / `uninitialized`. Path-qualified detection: the function must be a `scoped_identifier` (or `generic_function` wrapping one, for turbofish `mem::transmute::<u8, i8>(0)`) whose path text contains `"mem"`. Bare `transmute(x)` (without `mem::` prefix) is NOT flagged - it's indistinguishable from a user-defined helper of the same name. Disabled by default. |
| SAFE308 | truncating_as_cast | *Rust-only.* Fires on `as u8` / `as i8` / `as u16` / `as i16` / `as u32` / `as i32` / `as u64` / `as i64` / `as f32` casts. The `as` operator silently truncates when the source value doesn't fit; `TryFrom` / `try_into()` is the explicit-failure-mode alternative. `isize` / `usize` / `i128` / `u128` / `f64` are NOT flagged as targets (widest types - casts TO them don't truncate). Configurable via `truncating_cast_targets_rust`. Disabled by default. |
| SAFE501 | unbounded_loops | Fires on `loop { ... }` (Rust's unconditional infinite loop) and `while true { ... }` without an exiting break. Labelled break (`'outer: loop { loop { break 'outer; } }`) is correctly recognised - a break's target label resolves outward, and a labelled break whose target is NOT defined strictly inside the loop counts as exiting. `match` arms inside loops are NOT break-scope boundaries (Rust `break` inside a match arm legally targets the enclosing loop). |
| SAFE601 | missing_assertions | Walks for `macro_invocation` nodes (Rust expresses assertions exclusively through macros). Default `assertion_calls_rust` set covers stdlib (`assert` / `assert_eq` / `assert_ne`), debug-only stdlib (`debug_assert` / `debug_assert_eq` / `debug_assert_ne`), and the proptest crate (`prop_assert` / `prop_assert_eq` / `prop_assert_ne`). `panic!` / `todo!` / `unreachable!` / `unimplemented!` are deliberately NOT recognised as assertions - they're failure-exit markers, not invariant checks (cover them with `assertion_calls_rust` if your project treats them as assertions). |
| SAFE602 | undocumented_unsafe | *Rust-only.* Fires on `unsafe { ... }` blocks lacking a `// SAFETY:` comment (case-insensitive) on a preceding line. Both `// SAFETY:` and `/* SAFETY: */` comment forms count. Multiple intervening line comments are walked through (the SAFETY line doesn't need to be the immediately-previous sibling, but no non-comment statement may sit between them). `unsafe fn` declarations are NOT covered - they require `/// # Safety` doc comments, a separate convention with its own detection shape that may land in a future rule. Mirrors `clippy::undocumented_unsafe_blocks`. Disabled by default. |
| SAFE701 | test_existence | Recognises both Rust test-placement conventions: inline (`#[cfg(test)] mod tests { ... }` or any `#[test]` function inside the file) and external (`tests/<stem>.rs` Cargo integration test, or alternative `tests/<stem>_test.rs`). Inline-test bypass is the headline Rust adaptation - without it, every Rust source with the idiomatic inline tests would fire SAFE701 asking for an external pair the Rust ecosystem doesn't use. |
| SAFE702 | test_coupling | Same shape as SAFE701: inline tests trivially satisfy the rule (editing the source necessarily edits the inline tests). Files identified as test files (under `tests/` or filename ending `_test.rs`) are exempt from the coupling check. |
| SAFE801 | tainted_sink | Vanilla sinks (`sinks_rust`): `Command` / `new` (`Command::new(tainted)`), `arg` / `args` (`cmd.arg(tainted)` / `cmd.args(tainted)`), `query` / `query_as` / `query_scalar` / `execute` / `execute_batch` (raw-SQL across sqlx / diesel / rusqlite / postgres), `Library` (libloading FFI), `open` (filesystem paths). Vanilla sources (`sources_rust`): `var` (`std::env::var`) and `read_to_string` (`std::fs::read_to_string`); call names whose RETURN carries user data. Out-parameter / count-returning calls (`read_line`, `recv`, `recv_from`, `lock`) and bareword-colliding builders (`args` collides with `Command::args`) are intentionally NOT in defaults to keep noise down. Vanilla sanitizers (`sanitizers_rust`): narrow generic-wrapper set (`validate` / `sanitize` / `escape` / `quote`); context-specific encoders are deliberately NOT in the defaults. Macros (`sqlx::query!`) are a documented limitation - they parse as `macro_invocation`, not `call_expression`, and the macro body is a token tree we don't currently decode. |
| SAFE802 | return_value_ignored | Fires on bare expression statements whose call discards a meaningful return. Vanilla `flagged_calls_rust`: `io::Write` (`write` / `write_all` / `write_fmt` / `flush`), `io::Read` (`read` / `read_exact` / `read_to_end` / `read_to_string`), `std::fs` mutators (`remove_file` / `remove_dir` / `remove_dir_all` / `rename` / `copy` / `create_dir` / `create_dir_all` / `set_permissions` / `set_len`), networking (`send` / `send_to`), `Command` runners (`spawn` / `output` / `status`), `Child` lifecycle (`wait` / `wait_with_output` / `try_wait` / `kill`). The Rust idiom for explicit discard is `let _ = expr;` - that does NOT fire SAFE802. |
| SAFE803 | null_dereference | Rust has no `null`; the analogue is unwrapping `Option<T>` / `Result<T, E>`. Fires on `<call>.unwrap()` / `.expect(...)` / `.unwrap_unchecked()` / `.unwrap_err()` / `.expect_err()` when the inner call's name is in `nullable_methods_rust`. Default set covers `Map::get` / `Vec::get` / `slice::get`, `Vec::first` / `last` / `pop`, `Iterator::next` / `nth` / `peek`, `&str::find` / `rfind` / `parse`, `env::var` / `var_os`, `std::fs::read` family, `checked_add` / `sub` / `mul` / `div`. Pass-through wrappers (`parenthesized_expression`, `reference_expression` for `&x`, `try_expression` for `foo()?`) are peeled before the receiver check. Recommended fix surfaced in messages: `if let Some(x) = ...` / `match` / propagate via `?`. |

## Deliberately skipped rules

These rules are NOT registered for Rust because Python / JS-family / Java semantics don't translate cleanly:

| Code | Rule | Why skipped for Rust |
|---|---|---|
| SAFE201 | bare_except | Rust has no try/catch; the panic-recovery primitive is `std::panic::catch_unwind` which has its own auditable shape and isn't a control-flow construct in the same way. No bare-catch hazard exists. |
| SAFE202 | empty_except | Rust has no try/catch. The Rust spirit ("silently swallow an error") is covered by **SAFE206 `silent_result_discard`**, which has its own detection logic for `Err(_) => {}` arms and empty `if let Err(_) = ... { }` bodies. |
| SAFE203 | logging_on_error | Same as SAFE202 - no try/catch in Rust. The spirit ("handle the error without logging") is covered by **SAFE207 `unlogged_error_branch`** with its own detection for `Err` arms / `if let Err` bodies that contain no log call. |
| SAFE301 | global_state | Rust has no `global` keyword. `static mut FOO` is the closest analogue but requires `unsafe { }` to access, so it's already audit-gated via **SAFE602 `undocumented_unsafe`**. |
| SAFE302 | global_mutation | Same as SAFE301 - `static mut` writes are unsafe-gated, covered by SAFE602. |
| SAFE401 | resource_lifecycle | Rust's RAII (Drop trait) makes resource cleanup language-enforced - no `with` block, `try-finally`, or `try-with-resources` analogue is needed because going out of scope guarantees `Drop`. The rule has nothing to add for Rust. |

## Idiomatic fix patterns

When walking the user through fixes, use these Rust-native patterns:

### SAFE101 (function too long)

Decompose by responsibility into private functions in the same module:

```rust
// Before: 80 lines
pub fn place_order(req: OrderRequest) -> Result<Order, Error> {
    // ... validation
    // ... pricing
    // ... persistence
    // ... event publication
}

// After
pub fn place_order(req: OrderRequest) -> Result<Order, Error> {
    let validated = validate(req)?;
    let priced = calculate_pricing(validated)?;
    let saved = persist(priced)?;
    publish_order_created_event(&saved);
    Ok(saved)
}
```

### SAFE102 (nesting too deep)

Use `?` propagation and guard clauses instead of nested `if let`:

```rust
// Before
fn get_user(id: Option<i64>) -> Option<User> {
    if let Some(id) = id {
        if id > 0 {
            if let Some(user) = repo::find_by_id(id) {
                return Some(user);
            }
        }
    }
    None
}

// After
fn get_user(id: Option<i64>) -> Option<User> {
    let id = id?;
    if id <= 0 { return None; }
    repo::find_by_id(id)
}
```

### SAFE103 (too many arguments)

Group related parameters into a struct or builder:

```rust
// Before
pub fn render(width: u32, height: u32, dpi: u32, colour: Colour,
              font: String, font_size: u32, line_height: f32, padding: u32) { ... }

// After
pub struct RenderOptions {
    pub width: u32,
    pub height: u32,
    pub dpi: u32,
    pub colour: Colour,
    pub font: String,
    pub font_size: u32,
    pub line_height: f32,
    pub padding: u32,
}
pub fn render(opts: RenderOptions) { ... }
```

### SAFE110 (needless mut)

Drop the `mut`:

```rust
// Before
let mut x = compute();
println!("{}", x);

// After
let x = compute();
println!("{}", x);
```

If the binding really does mutate but the rule still fires, the mutation is hidden behind an ambiguous shape (method call / field access) - the rule conservatively skips those. Double-check with `cargo clippy` if needed.

### SAFE112 (unchecked arithmetic on input)

Pick the explicit overflow behaviour:

```rust
// Before
pub fn total(price: u32, quantity: u32) -> u32 {
    price * quantity  // SAFE112 - silent overflow in release
}

// After (panic on overflow regardless of build mode)
pub fn total(price: u32, quantity: u32) -> Result<u32, &'static str> {
    price.checked_mul(quantity).ok_or("overflow")
}

// After (intentionally wrap, e.g. for hash-mixing)
pub fn mix(seed: u64, input: u64) -> u64 {
    seed.wrapping_mul(input)
}

// After (saturate at MAX, e.g. for clamped counters)
pub fn add_count(current: u32, increment: u32) -> u32 {
    current.saturating_add(increment)
}
```

### SAFE204 (panic macros outside tests)

Return `Result` and let the caller decide:

```rust
// Before
pub fn parse_config(path: &str) -> Config {
    let raw = std::fs::read_to_string(path).unwrap();
    if raw.is_empty() {
        panic!("config is empty");  // SAFE204
    }
    serde_yaml::from_str(&raw).unwrap()
}

// After
pub fn parse_config(path: &str) -> Result<Config, ConfigError> {
    let raw = std::fs::read_to_string(path)?;
    if raw.is_empty() {
        return Err(ConfigError::Empty);
    }
    serde_yaml::from_str(&raw).map_err(ConfigError::Parse)
}
```

### SAFE205 (lock poisoning ignored)

Match on the `PoisonResult` or call `.into_inner()` to recover the guard regardless of poisoning:

```rust
// Before
let guard = mutex.lock().unwrap();  // panics if poisoned

// After (option 1: recover unconditionally)
let guard = mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner());

// After (option 2: handle poisoning explicitly)
let guard = match mutex.lock() {
    Ok(g) => g,
    Err(poisoned) => {
        log::warn!("mutex was poisoned; recovering");
        poisoned.into_inner()
    }
};
```

For projects that don't need poisoning at all, consider `parking_lot::Mutex` (no poison state by design).

### SAFE206 (silent result discard)

Add at least a log call or explicit propagation:

```rust
// Before
match maybe_save(record) {
    Ok(_) => {},
    Err(_) => {}  // SAFE206
}

// After
match maybe_save(record) {
    Ok(_) => {},
    Err(e) => log::error!("save failed: {:?}", e),
}
```

If the discard is intentional, `let _ = maybe_save(record);` is the auditable form and doesn't fire SAFE206 (or SAFE207).

### SAFE207 (unlogged error branch)

Add a log call or propagate the error:

```rust
// Before
if let Err(e) = save(record) {
    cleanup();  // SAFE207 - no log, no return
}

// After (option 1: log and continue)
if let Err(e) = save(record) {
    log::error!("save failed: {:?}", e);
    cleanup();
}

// After (option 2: propagate)
save(record)?;  // ? operator forwards Err automatically
```

### SAFE208 (result unwrap outside tests)

Replace `.unwrap()` with `?` (if the function returns `Result`), `if let Some(x) =` / `match` (if you want to handle both arms), or `unwrap_or` / `unwrap_or_default` / `unwrap_or_else` (if a sensible default exists):

```rust
// Before
pub fn read_config() -> Config {
    let raw = std::fs::read_to_string("config.toml").unwrap();  // SAFE208
    toml::from_str(&raw).unwrap()  // SAFE208
}

// After
pub fn read_config() -> Result<Config, ConfigError> {
    let raw = std::fs::read_to_string("config.toml")?;
    toml::from_str(&raw).map_err(ConfigError::Parse)
}
```

For test code, the rule auto-exempts inside `#[test]` functions and `#[cfg(test)] mod` blocks - you don't need to refactor your tests.

### SAFE306 (dangerous mem ops)

Use the safer alternative:

```rust
// Before
let x: i8 = unsafe { std::mem::transmute::<u8, i8>(255) };  // SAFE306

// After
let x = i8::from_ne_bytes([255]);   // for byte reinterpretation
let x = i8::try_from(255u8).unwrap_or(0);  // for value conversion with checked failure
```

For `mem::forget`, use `ManuallyDrop` instead - it's typed, has IDE / clippy support, and makes intent explicit. For `mem::zeroed` / `mem::uninitialized`, use `MaybeUninit` which forces an explicit `unsafe { .assume_init() }` at the use site (the hazard becomes visible).

### SAFE308 (truncating as cast)

Use `TryFrom` (returns `Result`) or `try_into()` (postfix sugar):

```rust
// Before
let small: u8 = big_value as u8;  // SAFE308 - silent truncation

// After (option 1: TryFrom)
let small: u8 = u8::try_from(big_value).map_err(|_| MyError::OutOfRange)?;

// After (option 2: try_into in expression position)
let small: u8 = big_value.try_into().map_err(|_| MyError::OutOfRange)?;
```

If the cast is genuinely intentional (e.g. extracting low byte for a hash), `// nosafe: SAFE308` with a one-line justification keeps the cast and documents the intent. Configure via `[tool.safelint.rules.truncating_as_cast] truncating_cast_targets_rust = [...]` to permanently exclude specific target types.

### SAFE602 (undocumented unsafe)

Add a `// SAFETY:` comment:

```rust
// Before
unsafe {
    std::ptr::write(dst, value);
}

// After
// SAFETY: dst was allocated and aligned by the caller (see `Buffer::reserve`);
// value is a Copy type so this can't leak Drop.
unsafe {
    std::ptr::write(dst, value);
}
```

Both `// SAFETY:` (line comment) and `/* SAFETY: */` (block comment) forms work; case-insensitive. Multiple intervening line comments are allowed (e.g. SAFETY comment, then a TODO comment, then the unsafe block - still recognised).

## Integration with Rust tooling

safelint runs alongside the standard Rust tool chain; it doesn't replace any of them. Typical wiring:

* **`cargo fmt`** handles formatting; safelint doesn't lint style.
* **`cargo clippy`** covers a huge surface of idiomatic-Rust lints. safelint and clippy overlap on a few rules (SAFE110 ≈ `clippy::needless_mut`, SAFE602 ≈ `clippy::undocumented_unsafe_blocks`, SAFE205 ≈ partial `clippy::unwrap_used` coverage); the overlap is intentional - clippy isn't enabled by default in many projects and its rule set is broader than the Holzmann-safety focus. Use both; they complement.
* **Pre-commit**: drop into `.pre-commit-config.yaml` as shown in the install section above.
* **CI**: invoke `safelint check src/ tests/ --fail-on warning` (or `--mode ci`) in your build pipeline. Exit code 0 / 1 / 2 maps cleanly to "passed" / "violations found" / "setup error - install hint emitted on stderr".
* **IDE**: any JSON-output-consuming editor plugin (the safelint JSON schema is stable in v2.0.0+) can surface violations inline.

## Stdin mode for editor / Claude Code unsaved buffers

If the user is asking about a buffer that isn't saved to disk (e.g. they paste code in chat and ask for a safelint review), use stdin mode:

```bash
echo "<source code>" | safelint --stdin --stdin-filename buffer.rs --format json
```

The pseudo-filename drives language detection (use a `.rs` suffix to ensure Rust rules fire) and shows up as the violation file path.

## What this addendum does NOT cover

- Frameworks. The four major Rust web frameworks (axum, actix-web, rocket, warp) and async runtimes (tokio, async-std) don't have dedicated SafeLint presets yet. Rule defaults assume vanilla stdlib; framework-specific patterns (e.g. axum's `IntoResponse`, actix's `web::Json` validation) would land in a future preset analogous to the Java `spring-boot` framework knob.
- `unsafe fn` declarations. SAFE602 covers `unsafe { ... }` blocks but not `unsafe fn` items. The latter requires `/// # Safety` doc-comment detection, a separate convention; a future rule may extend this.
- Macros as taint-flow sinks. SAFE801 walks `call_expression` only; `sqlx::query!("SELECT ...")` (compile-time-checked SQL macros) and similar token-tree-based macros aren't currently modelled. Real SQL injection in those forms requires careful raw-string assembly which `safelint check` won't catch.
