# Go

SafeLint analyses Go source for the Holzmann "Power of Ten" safety rules and Go-language-specific patterns: function shape (length, nesting depth, cyclomatic complexity, argument count), error-handling discipline (ignored `error` returns, empty `if err != nil {}` bodies, `panic` outside tests), loop safety (the bare `for {}` while-true shape), package-level shared state, resource lifecycle via `defer x.Close()`, and dataflow taint into `os/exec` / `database/sql` / `plugin` sinks. Go support landed in **v2.5.0**, with a rule scope deliberately narrowed to Go idioms. SafeLint does NOT replace `gofmt` / `go vet` / `golangci-lint`; it runs alongside them and targets the engineering-discipline patterns those tools leave alone.

## File extensions

- **`.go`**, parsed by `tree-sitter-go`. Picked up by `safelint check` (directory mode, `--all-files` mode, and the pre-commit hook). Sibling `_test.go` files are linted too, but a few rules treat them specially: SAFE701 / SAFE702 recognise `foo_test.go` as the test pair for `foo.go` (and never ask a `_test.go` file to have its own test), and SAFE211 only fires on `panic(...)` in non-`_test.go` files.

## Quick start

```bash
pip install 'safelint[go]'         # adds the tree-sitter-go grammar
safelint check .                   # lint a directory (git-modified files by default)
safelint check --all-files .       # lint everything under cwd
safelint check --format json .     # machine-readable for editors / CI
```

In a project that already uses `uv`, add it as a dev dependency:

```bash
uv add --dev 'safelint[go]'
```

safelint is a Python package, not a Go module. A `go.mod` is not required; safelint walks the source tree directly and auto-detects by file extension. Run it from the module / repository root. If your Go project has no Python tool chain, `pipx install 'safelint[go]'` isolates the install.

v2.0.0+ ships every language grammar as an opt-in extra. Plain `pip install safelint` installs only the engine and would skip every `.go` file with an install hint (`safelint: warning: skipping .go files, install with: pip install 'safelint[go]'`) on first run. The exit code is 2 only when EVERY candidate file is skipped (the typical Go-only project); in a mixed Python + Go repo, safelint emits the `.go` skip warning and continues linting the supported files normally.

## Rules that fire on Go

Go is in scope for 19 cross-language rules plus 2 Go-only rules. 7 cross-language rules are deliberately skipped, see the next section. Like the other languages' optional rules, every dataflow rule and both Go-only rules are disabled by default.

### Cross-language rules

| Code | Rule | Notes for Go |
|---|---|---|
| [SAFE101](../configuration/rules.md#safe101-function_length) | `function_length` | Counts source lines on `function_declaration` / `method_declaration` / `func_literal`. Default cap is 60. Closure bodies count toward their own size, not the enclosing function. |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | `nesting_depth` | Counts `if_statement` / `for_statement` / `expression_switch_statement` / `type_switch_statement` / `select_statement`. Default max 2. Per-arm `case` nodes are not counted; the switch / select counts once. |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | `max_arguments` | Counts parameter *names*: `a, b int` is two parameters from one declaration. `args ...T` (variadic) counts as one. The method receiver is on a separate field and is NOT counted (Go's `self` analogue). Default cap 7. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | `complexity` | Cyclomatic complexity: every `if` / `for` / `expression_case` / `type_case` / `communication_case` adds one; `&&` / `\|\|` inside `binary_expression` each add one. The `default` case is not counted (it adds no decision). Default cap 10. |
| [SAFE105](../configuration/rules.md#safe105-no_recursion) | `no_recursion` | Flags a `function_declaration` calling itself bare (`recurse(n-1)`) or a `method_declaration` calling itself receiver-qualified (`s.Walk(...)` inside `func (s *Svc) Walk()`). A bare same-named call inside a method denotes a package function, not the method, and does not fire. Direct self-recursion only (mutual recursion is out of scope). Enabled by default at warning severity. |
| [SAFE302](../configuration/rules.md#safe302-global_mutation) | `global_mutation` | Declaration-site detection (like Java): fires on every package-level `var`, including sentinel errors (`var ErrNF = errors.New(...)`). `const` declarations and block-scoped `var` / `:=` inside functions are clean. Severity `error` and enabled by default, so Go projects see it out of the box. Suppress sentinels you treat as immutable via a per-file ignore or `// nosafe`. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | `side_effects_hidden` | Fires when a function with a "pure" name prefix (`get` / `compute` / `is` / `validate` / etc.) contains an I/O call. Default `io_functions_go`: `Print` / `Println` / `Printf` / `Fprintf` (fmt), `Open` / `Create` / `ReadFile` / `WriteFile` (os), `Get` / `Post` / `Do` (net/http), `Dial` / `Listen` (net), `Exec` / `Query` (database/sql). `call_name` strips the package, so `fmt.Println` matches `Println`. |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | `side_effects` | Fires when any function not name-signalled for I/O contains an I/O call. Uses a deliberately narrower `io_functions_go` subset than SAFE303 (the ambiguous-as-method-name `Get` / `Post` / `Do` / `Exec` / `Query` are dropped to cut false positives). The `io_name_keywords` exemption suppresses functions whose names already signal I/O. |
| [SAFE309](../configuration/rules.md#safe309-dynamic_code_execution) | `dynamic_code_execution` | Go has no `eval`; the analysability threat is reflection and plugin loading. Default `dynamic_exec_calls_go`: `Call` / `CallSlice` / `MethodByName` (reflect), `Open` / `Lookup` (plugin). Matching is by bare name, so `Open` also matches `os.Open`; narrow the list if noisy. Disabled by default. |
| [SAFE401](../configuration/rules.md#safe401-resource_lifecycle) | `resource_lifecycle` | Go has no RAII, so the safe form is a `defer <var>.Close()` in the same function body. Fires on a tracked acquirer (`tracked_functions_go`: `Open` / `Create` / `Dial` / `Listen`) whose handle is not deferred-closed. A bare-expression acquirer (no assignment) always fires - there is no handle to close. A `defer` routed through a wrapping closure is a documented blind spot. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | `unbounded_loops` | Go's only loop keyword is `for`. The bare `for {}` (no condition, no three-clause header, no `range`) is Go's `while true`; SAFE501 flags it when it has no exiting break. Labelled break (`outer: for { for { break outer } }`) is correctly resolved: a `break outer` exits the labelled loop (and any loop it passes through). Conditioned (`for cond {}`), three-clause (`for i := 0; ...`), and `for range` loops are bounded shapes and never fire. |
| [SAFE603](../configuration/rules.md#safe603-blanket_suppression) | `blanket_suppression` | Flags blanket golangci / staticcheck directives (Holzmann rule 10): bare `//nolint` (all linters) and bare `//lint:ignore` (no checks). Scoped forms (`//nolint:errcheck`, `//lint:ignore SA1000 reason`) are clean. The directives are recognised only with no space after `//` (golangci's requirement), so a prose `// nolint here` comment is not flagged. Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | `test_existence` | Go's test convention is the sibling `<stem>_test.go` *in the same directory* as the source file, not a `tests/` directory. SAFE701 looks for that sibling; a `_test.go` file is itself a test and is skipped. The sibling convention is the headline Go adaptation. Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | `test_coupling` | Same sibling convention: when `foo.go` changes, its sibling `foo_test.go` must change too. Test files are exempt from the coupling check. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | `tainted_sink` | Parameters seeded as tainted on function entry, tracked by `analysis/dataflow_go.py` (iterative worklists). Default vanilla sinks (`sinks_go`): `Command` / `CommandContext` (os/exec), `Query` / `QueryRow` / `Exec` (database/sql raw SQL), `Open` (plugin). Vanilla sources (`sources_go`): `Getenv` (os), `FormValue` / `PostFormValue` / `FormFile` (net/http request). Sanitizers (`sanitizers_go`): narrow generic set (`sanitize` / `validate` / `escape` / `quote`). Collision rule: selector matching is name-only (no type info), so a name that is both a sink and a source resolves as the sink (`Query` is kept as a sink and dropped from sources). `os.Args` and `Header.Get` are omitted from default sources (non-call / collision-prone); add them via config if needed. Disabled by default. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | `return_value_ignored` | The flagship Go rule: ignoring `error` returns. Fires on a bare call statement whose `error` return is discarded. Default `flagged_calls_go`: `Write` / `Close` (io), `Remove` / `RemoveAll` / `Rename` / `Mkdir` / `MkdirAll` / `Chmod` / `Chown` / `Setenv` / `Truncate` (os), `Commit` / `Rollback` (database/sql). The explicit discards `_ = f()` and `x, _ := f()` are assignments, not expression statements, so they never fire - they are Go's auditable `(void)`-cast analogue. Disabled by default. |

### Go-only rules

| Code | Rule | Notes |
|---|---|---|
| [SAFE209](../configuration/rules.md) | `empty_error_check` | Flags `if err != nil { }` (or `== nil`) with an empty or comment-only body - the error was checked and then silently swallowed. The condition shape matched is a binary `!=` / `==` comparison where one operand's identifier text is `err` (configurable via `error_names_go`, default `["err"]`) and the other is `nil`. Go analogue of Rust's SAFE206 `silent_result_discard`. Disabled by default. |
| [SAFE211](../configuration/rules.md) | `panic_calls_outside_tests` | Flags `panic(...)` calls in non-`_test.go` files; production paths should return an `error`, not unwind the stack. Configurable via `panic_calls_go` (default `["panic"]`; add resolved barewords like `Fatal` / `Exit` if you treat those as panic-equivalent). Go analogue of Rust's SAFE204 `panic_macros_outside_tests`. Disabled by default. |

### Rules not registered for Go

| Code | Rule | Why skipped for Go |
|---|---|---|
| [SAFE201](../configuration/rules.md#safe201-bare_except) | `bare_except` | Go has no try/catch. No bare-catch hazard exists. |
| [SAFE202](../configuration/rules.md#safe202-empty_except) | `empty_except` | Go has no try/catch. The spirit ("silently swallow an error") is covered by **SAFE209 `empty_error_check`** (empty `if err != nil {}` bodies) plus **SAFE802** (discarded `error` returns). |
| [SAFE203](../configuration/rules.md#safe203-logging_on_error) | `logging_on_error` | Same as SAFE202 - Go has no catch blocks. Unlogged-error handling is partially covered by SAFE209 / SAFE802. |
| [SAFE301](../configuration/rules.md#safe301-global_state) | `global_state` | Go has no `global` keyword; package-level shared state is covered by the **SAFE302 `global_mutation`** port (declaration-site detection on package `var`). |
| [SAFE305](../configuration/rules.md#safe305-wide_scope_declaration) | `wide_scope_declaration` | Go has no `var` hoisting; `:=` is block-scoped, so there is no narrow-the-scope hazard to flag. |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | `missing_assertions` | Go has no production assertion idiom (no `assert` keyword or stdlib macro; testify is test-only). Registering a heuristic would be noisy; revisit if demand appears. |
| [SAFE803](../configuration/rules.md#safe803-null_dereference) | `null_dereference` | Go has no chained-nullable idiom to anchor on - nil-pointer analysis needs type information, and map reads return zero values rather than nil. Documented gap. |

## Key Go adaptations

A few Go-vs-other-languages shapes the rule engine contends with, worth knowing when reading violations:

- **One loop keyword.** Go's only loop is `for`. The bare `for {}` (no condition, no three-clause header, no `range`) is Go's `while true`; SAFE501 flags it when it has no exiting break. Conditioned, three-clause, and `for range` loops are bounded shapes and never fire.
- **Sibling test files.** Go's test convention is `foo_test.go` *in the same directory* as `foo.go`, not a `tests/` directory. SAFE701 / SAFE702 look for the sibling, and a `_test.go` file is itself recognised as a test (never asked to have its own test).
- **Explicit error discard.** `_ = f()` and `x, _ := f()` are Go's auditable "I am intentionally ignoring this" form (the `(void)`-cast analogue). SAFE802 only fires on a *bare* call statement (`f.Write(b)`) whose error return is silently dropped; the blank-identifier forms never fire.
- **Receiver as `self`.** A method's receiver name is user-chosen (`func (s *Svc) Walk()`). SAFE105 treats an `s.Walk(...)` call inside `Walk` as self-recursion, matching the receiver identifier rather than a fixed `self` / `this`.
- **Package-level `var` is shared state.** SAFE302 fires at the declaration site on every package-level `var`, including sentinel errors (`var ErrX = errors.New(...)`); `const` and block-scoped `var` / `:=` are clean.
- **`defer x.Close()` is the resource form.** Go has no RAII, so SAFE401 looks for a `defer <var>.Close()` in the same function body as the acquirer rather than a `with` block or try-with-resources.

## Configuration

SafeLint config is read from `[tool.safelint]` in `pyproject.toml` (if your Go project also has one) or from a standalone `safelint.toml` at the project root. Pure-Go projects typically prefer the standalone form, which drops the `[tool.safelint]` prefix.

### Per-rule TOML overrides

Override any per-language config list with the `_go` suffix. Each example is shown in **both forms**: `[tool.safelint.rules.<rule>]` for `pyproject.toml` and `[rules.<rule>]` for a standalone `safelint.toml`.

**SAFE304 `side_effects` - `io_functions_go`:**

```toml
# pyproject.toml
[tool.safelint.rules.side_effects]
io_functions_go = ["Println", "Printf", "WriteFile", "Open"]   # narrower than the default
```

```toml
# safelint.toml
[rules.side_effects]
io_functions_go = ["Println", "Printf", "WriteFile", "Open"]
```

**SAFE401 `resource_lifecycle` - `tracked_functions_go`:**

```toml
# pyproject.toml
[tool.safelint.rules.resource_lifecycle]
tracked_functions_go = ["Open", "Create", "Dial", "Listen"]
```

```toml
# safelint.toml
[rules.resource_lifecycle]
tracked_functions_go = ["Open", "Create", "Dial", "Listen"]
```

**SAFE801 `tainted_sink` - `sinks_go` / `sources_go` / `sanitizers_go`:**

```toml
# pyproject.toml
[tool.safelint.rules.tainted_sink]
enabled = true                                              # dataflow rules are opt-in
sinks_go = ["Command", "CommandContext", "Query", "Exec"]   # shell + raw SQL
sources_go = ["Getenv", "FormValue", "PostFormValue"]
sanitizers_go = ["sanitize", "validate", "escape", "quote"]
```

```toml
# safelint.toml
[rules.tainted_sink]
enabled = true
sinks_go = ["Command", "CommandContext", "Query", "Exec"]
sources_go = ["Getenv", "FormValue", "PostFormValue"]
sanitizers_go = ["sanitize", "validate", "escape", "quote"]
```

**SAFE802 `return_value_ignored` - `flagged_calls_go`:**

```toml
# pyproject.toml
[tool.safelint.rules.return_value_ignored]
enabled = true
flagged_calls_go = ["Write", "Close", "Remove", "Commit", "Rollback"]
```

```toml
# safelint.toml
[rules.return_value_ignored]
enabled = true
flagged_calls_go = ["Write", "Close", "Remove", "Commit", "Rollback"]
```

**SAFE209 `empty_error_check` - `error_names_go`:**

```toml
# pyproject.toml
[tool.safelint.rules.empty_error_check]
enabled = true
error_names_go = ["err", "e"]   # also treat a `e != nil` check as an error check
```

```toml
# safelint.toml
[rules.empty_error_check]
enabled = true
error_names_go = ["err", "e"]
```

**SAFE211 `panic_calls_outside_tests` - `panic_calls_go`:**

```toml
# pyproject.toml
[tool.safelint.rules.panic_calls_outside_tests]
enabled = true
panic_calls_go = ["panic", "Fatal", "Exit"]   # treat log.Fatal / os.Exit as panic-equivalent
```

```toml
# safelint.toml
[rules.panic_calls_outside_tests]
enabled = true
panic_calls_go = ["panic", "Fatal", "Exit"]
```

**SAFE309 `dynamic_code_execution` - `dynamic_exec_calls_go`:**

```toml
# pyproject.toml
[tool.safelint.rules.dynamic_code_execution]
enabled = true
dynamic_exec_calls_go = ["Call", "CallSlice", "MethodByName", "Lookup"]   # drop the os.Open-colliding Open
```

```toml
# safelint.toml
[rules.dynamic_code_execution]
enabled = true
dynamic_exec_calls_go = ["Call", "CallSlice", "MethodByName", "Lookup"]
```

### Enabling the disabled-by-default rules

Both Go-only rules and every dataflow rule ship disabled by default. Opt-in via TOML (shown here in `pyproject.toml` form; the standalone `safelint.toml` form drops the `tool.safelint.` prefix):

```toml
[tool.safelint.rules.empty_error_check]
enabled = true

[tool.safelint.rules.panic_calls_outside_tests]
enabled = true

[tool.safelint.rules.tainted_sink]
enabled = true

[tool.safelint.rules.return_value_ignored]
enabled = true

[tool.safelint.rules.dynamic_code_execution]
enabled = true
```

## Integration with the Go tool chain

SafeLint runs alongside the standard Go tool chain; it doesn't replace any of it. Typical wiring:

* **`gofmt`** handles formatting; safelint doesn't lint style.
* **`go vet`** and **`golangci-lint`** cover a broad surface of correctness and idiomatic-Go lints. SafeLint targets the engineering-discipline patterns (function shape, error-handling discipline, package-level state, dataflow taint) those tools leave alone; use them together, they complement.
* **Pre-commit**: drop into `.pre-commit-config.yaml`:

  ```yaml
  - repo: https://github.com/shelkesays/safelint
    rev: v2.5.0  # or whatever the latest tag is
    hooks:
      - id: safelint
        additional_dependencies: ['safelint[go]']
        # For a polyglot repo with Python + Go:
        # additional_dependencies: ['safelint[python,go]']
  ```

  Pre-commit routes `.go` files via the `go` filetype tag in `types_or` (pre-commit's `identify` library recognises it).

* **CI**: invoke `safelint check . --fail-on warning` (or `--mode ci`) in your build pipeline. Exit code 0 / 1 / 2 maps cleanly to "passed" / "violations found" / "setup error - install hint emitted on stderr".
* **IDE**: any JSON-output-consuming editor plugin (the safelint JSON schema is stable in v2.0.0+) can surface violations inline.

## Future: framework presets

Go has no framework preset in this release. A future `[tool.safelint.go] framework` axis (gin / echo / chi) would extend `sources_go` with framework request accessors (`c.Param` / `c.Query` / `c.PostForm`), analogous to the Java `spring-boot` framework knob and the JS runtime presets. Any Gin / Echo / chi structural rules would take the 9xx framework-specific band. Track via [GitHub issues](https://github.com/shelkesays/safelint/issues).
