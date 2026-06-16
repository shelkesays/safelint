# safelint skill: Go addendum

Language-specific notes for the Go target. Mirrors `src/safelint/languages/go.py` in the safelint source tree. The skill core (`claude/SKILL.md` for Claude Code, each peer client's own file for other agents) handles the universal flow; this file holds Go-specific detail.

## Install nuance

safelint is a Python package, not a Go module. The Go grammar ships in the `[go]` extra:

```bash
pip install 'safelint[go]'
# or, in a project that already uses uv:
uv add --dev 'safelint[go]'
# or, kitchen-sink:
pip install 'safelint[all]'
```

After install, `safelint` is on `PATH`. Run it from the Go module / repository root the same way as for any other language; safelint auto-detects by file extension. A `go.mod` is not required (safelint walks the source tree directly), but using safelint alongside `gofmt`, `go vet`, and `golangci-lint` is the expected workflow - safelint targets the engineering-discipline patterns those tools leave alone.

If you run plain `pip install safelint` (no extra), the first run emits `safelint: warning: skipping .go files, install with: pip install 'safelint[go]'`. **Exit code is 2 only when EVERY candidate file is skipped** (typical Go-only project); in a mixed Python + Go repo, safelint emits the `.go` skip warning and continues linting the supported files normally.

For pre-commit integration, set `additional_dependencies`:

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.5.0  # use a recent tag that includes the [go] extra
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[go]']
      # For a polyglot repo with Python + Go:
      # additional_dependencies: ['safelint[python,go]']
```

## File extensions

safelint lints `.go` files. The skill doesn't need to filter by extension - `safelint check` walks the project and picks up `.go` automatically. Test files (`_test.go`) are linted too, but a few rules treat them specially (see "Test conventions" below).

## Rule count

Go is in scope for the cross-language rules (SAFE101-105, SAFE302, SAFE303-304, SAFE309, SAFE401, SAFE501, SAFE603, SAFE701-702, SAFE801-802) plus two Go-specific rules: **SAFE209 `empty_error_check`** and **SAFE211 `panic_calls_outside_tests`**. The rules deliberately skipped for Go (SAFE201, SAFE202, SAFE203, SAFE301, SAFE305, SAFE601, SAFE803) are listed in the "Deliberately skipped" section below. Like the other languages' optional rules, every Go-only rule and every dataflow rule is disabled by default.

## Go shapes worth knowing

A few Go-vs-other-languages differences the rule engine contends with:

- **One loop keyword.** Go's only loop is `for`. The bare `for {}` (no condition, no three-clause header, no `range`) is Go's `while true`; SAFE501 flags it when it has no exiting break. Conditioned (`for cond {}`), three-clause (`for i := 0; ...`), and `for range` loops are bounded shapes and never fire.
- **Sibling test files.** Go's test convention is `foo_test.go` *in the same directory* as `foo.go`, not a `tests/` directory. SAFE701 / SAFE702 look for the sibling, and a `_test.go` file is itself recognised as a test (never asked to have its own test).
- **Explicit error discard.** `_ = f()` and `x, _ := f()` are Go's auditable "I am intentionally ignoring this" form (the `(void)`-cast analogue). SAFE802 only fires on a *bare* call statement (`f.Write(b)`) whose error return is silently dropped; the blank-identifier forms never fire.
- **Receiver as `self`.** A method's receiver name is user-chosen (`func (s *Svc) Walk()`). SAFE105 treats a `s.Walk(...)` call inside `Walk` as self-recursion, matching the receiver identifier rather than a fixed `self` / `this`.
- **Package-level `var` is shared state.** SAFE302 fires at the declaration site on every package-level `var` (including sentinel errors `var ErrX = errors.New(...)`); `const` and block-scoped `var` / `:=` are clean.

## Language-specific rule phrasing

When the user asks "why is this flagged?", the universal rationale in the per-client core is correct, but Go phrasing helps. The table lists every rule that applies to Go; rules deliberately skipped (with rationale) are in the next section.

| Code | Rule | Go-specific notes |
|---|---|---|
| SAFE101 | function_length | Counts source lines on `function_declaration` / `method_declaration` / `func_literal`. Default cap is 60 source lines. Closure bodies count toward their own size, not the enclosing function. |
| SAFE102 | nesting_depth | Counts `if_statement` / `for_statement` / `expression_switch_statement` / `type_switch_statement` / `select_statement`. Default max is 2. Per-arm case nodes are not counted - the switch / select counts once. |
| SAFE103 | max_arguments | Counts parameter *names*: `a, b int` is two parameters from one declaration. `args ...T` (variadic) counts as one. The method receiver is on a separate field and is NOT counted (Go's `self` analogue). Default cap is 7. |
| SAFE104 | complexity | Cyclomatic complexity: every `if` / `for` / `expression_case` / `type_case` / `communication_case` adds one; `&&` / `\|\|` inside `binary_expression` each add one. The `default` case is not counted (it adds no decision). Default cap is 10. |
| SAFE105 | no_recursion | Flags a `function_declaration` calling itself bare (`recurse(n-1)`) or a `method_declaration` calling itself receiver-qualified (`s.Walk(...)` inside `func (s *Svc) Walk()`). A bare same-named call inside a method denotes a package function, not the method, and does not fire. Direct self-recursion only. Enabled by default at warning severity. |
| SAFE209 | empty_error_check | *Go-only.* Flags `if err != nil { }` (or `== nil`) with an empty or comment-only body - the error was checked and then silently swallowed. The error identifier is configurable via `error_names_go` (default `["err"]`). Go analogue of Rust's SAFE206. Disabled by default. |
| SAFE211 | panic_calls_outside_tests | *Go-only.* Flags `panic(...)` calls in non-`_test.go` files; production paths should return an `error`, not unwind the stack. Configurable via `panic_calls_go` (default `["panic"]`; add resolved barewords like `Fatal` / `Exit` if you treat those as panic-equivalent). Go analogue of Rust's SAFE204. Disabled by default. |
| SAFE302 | global_mutation | Declaration-site detection (like Java): fires on every package-level `var`, including sentinel errors (`var ErrNF = errors.New(...)`). `const` declarations and block-scoped `var` / `:=` inside functions are clean. Suppress sentinels with a per-file ignore or `//nosafe` if you treat them as immutable. |
| SAFE303 | side_effects_hidden | Fires when a function with a "pure" name prefix (`get` / `compute` / `is` / `validate` / etc.) contains an I/O call. Default `io_functions_go`: `Print` / `Println` / `Printf` / `Fprintf` (fmt), `Open` / `Create` / `ReadFile` / `WriteFile` (os), `Get` / `Post` / `Do` (net/http), `Dial` / `Listen` (net), `Exec` / `Query` (database/sql). `call_name` strips the package, so `fmt.Println` matches `Println`. |
| SAFE304 | side_effects | Fires when any function not name-signalled for I/O contains an I/O call. Uses a deliberately narrower `io_functions_go` subset than SAFE303 (the ambiguous-as-method-name `Get` / `Post` / `Do` / `Exec` / `Query` are dropped to cut false positives). |
| SAFE309 | dynamic_code_execution | Structural detection of reflection / plugin loading (Go's rule-8 analogue; Go has no `eval`). Default `dynamic_exec_calls_go`: `Call` / `CallSlice` / `MethodByName` (reflect), `Open` / `Lookup` (plugin). Matching is by bare name, so `Open` also matches `os.Open` - narrow the list if noisy. Disabled by default. |
| SAFE401 | resource_lifecycle | Go has no RAII, so the safe form is a `defer <var>.Close()` in the same function body. Fires on a tracked acquirer (`tracked_functions_go`: `Open` / `Create` / `Dial` / `Listen`) whose handle is not deferred-closed. A bare-expression acquirer (no assignment) always fires - there is no handle to close. A `defer` routed through a wrapping closure is a documented blind spot. |
| SAFE501 | unbounded_loops | Fires on a bare `for {}` (Go's unconditional infinite loop) with no exiting break. Labelled break (`outer: for { for { break outer } }`) is correctly resolved - a `break outer` exits the labelled loop (and any loop it passes through). Bounded `for` forms never fire. |
| SAFE603 | blanket_suppression | Flags blanket golangci / staticcheck directives (Holzmann rule 10): bare `//nolint` (all linters) and bare `//lint:ignore` (no checks). Scoped forms (`//nolint:errcheck`, `//lint:ignore SA1000 reason`) are clean. The directives are recognised only with no space after `//` (golangci's requirement), so a prose `// nolint here` comment is not flagged. Disabled by default. |
| SAFE701 | test_existence | Looks for the sibling `<stem>_test.go` in the source file's own directory (Go has no `tests/` idiom). A `_test.go` file is itself a test and is skipped. |
| SAFE702 | test_coupling | Same sibling convention: when `foo.go` changes, its sibling `foo_test.go` must change too. Test files are exempt from the coupling check. |
| SAFE801 | tainted_sink | Vanilla sinks (`sinks_go`): `Command` / `CommandContext` (os/exec), `Query` / `QueryRow` / `Exec` (database/sql raw SQL), `Open` (plugin). Vanilla sources (`sources_go`): `Getenv` (os), `FormValue` / `PostFormValue` / `FormFile` (net/http request). Sanitizers (`sanitizers_go`): narrow generic set (`sanitize` / `validate` / `escape` / `quote`). Collision rule: a name that is both a sink and a source resolves as the sink (`Query` is kept as a sink, dropped from sources). `os.Args` and `Header.Get` are omitted from default sources (non-call / collision-prone) - add via config if needed. |
| SAFE802 | return_value_ignored | Fires on a bare call statement whose `error` return is discarded. Default `flagged_calls_go`: `Write` / `Close` (io), `Remove` / `RemoveAll` / `Rename` / `Mkdir` / `MkdirAll` / `Chmod` / `Chown` / `Setenv` / `Truncate` (os), `Commit` / `Rollback` (database/sql). The explicit discards `_ = f()` and `x, _ := f()` are assignments, not expression statements, so they never fire. |

## Deliberately skipped rules

These rules are NOT registered for Go because Python / JS-family / Java semantics don't translate cleanly:

| Code | Rule | Why skipped for Go |
|---|---|---|
| SAFE201 | bare_except | Go has no try/catch. No bare-catch hazard exists. |
| SAFE202 | empty_except | Go has no try/catch. The spirit ("silently swallow an error") is covered by **SAFE209 `empty_error_check`** (empty `if err != nil {}` bodies) plus SAFE802 (discarded error returns). |
| SAFE203 | logging_on_error | Same as SAFE202 - no catch blocks. Unlogged-error handling is partially covered by SAFE209 / SAFE802. |
| SAFE301 | global_state | Go has no `global` keyword; package-level shared state is covered by the **SAFE302** port (declaration-site on package `var`). |
| SAFE305 | wide_scope_declaration | Go has no `var` hoisting; `:=` is block-scoped, so there is no narrow-the-scope hazard to flag. |
| SAFE601 | missing_assertions | Go has no production assertion idiom (no `assert` keyword or stdlib macro; testify is test-only). Registering a heuristic would be noisy; revisit if demand appears. |
| SAFE803 | null_dereference | Go has no chained-nullable idiom to anchor on - nil-pointer analysis needs type information, and map reads return zero values rather than nil. Documented gap. |

## Idiomatic fix patterns

When walking the user through fixes, use these Go-native patterns:

### SAFE401 (resource not closed)

Pair the acquirer with `defer Close()` on the next line:

```go
// Before: leak
f, err := os.Open(path)
if err != nil {
    return err
}
use(f)

// After
f, err := os.Open(path)
if err != nil {
    return err
}
defer f.Close()
use(f)
```

### SAFE209 (empty error check)

Handle, wrap, or return the error instead of swallowing it:

```go
// Before
if err != nil {}

// After
if err != nil {
    return fmt.Errorf("read config: %w", err)
}
```

### SAFE802 (discarded error)

Either handle the error or make the discard explicit:

```go
// Before: silently drops the write error
f.Write(buf)

// After: handle it
if _, err := f.Write(buf); err != nil {
    return err
}

// Or, if the discard is genuinely intentional, make it auditable
_, _ = f.Write(buf)
```

### SAFE211 (panic in production)

Return an error up the call stack instead of panicking:

```go
// Before
func mustParse(s string) Config {
    c, err := parse(s)
    if err != nil {
        panic(err)
    }
    return c
}

// After
func parseConfig(s string) (Config, error) {
    c, err := parse(s)
    if err != nil {
        return Config{}, fmt.Errorf("parse config: %w", err)
    }
    return c, nil
}
```

## Future: framework / runtime presets

Go has no framework preset in this release. A future `[tool.safelint.go] framework` axis (gin / echo / chi) would extend `sources_go` with framework request accessors (`c.Param` / `c.Query` / `c.PostForm`); any framework-specific structural rules would take the 9xx band.
