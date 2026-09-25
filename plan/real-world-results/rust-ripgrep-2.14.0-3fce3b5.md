# ripgrep - rust

- safelint: **2.14.0** (`/tmp/pipchk/bin/safelint`)
- project: `/Users/rahulshelke/sources/safelint_tests/ripgrep` @ `3fce3b5bb0236da2df6d99672afb8a719642eca7`
- preset: `none`
- run: 2026-09-24 20:43 UTC

## all-rules

- files scanned (all languages): 110
- rust files with findings: 106
- findings (rust files only): **3664**
- wall time: 3.2s, peak RSS: 47 MB, exit code: 1

| Code | Findings | Share |
|---|---|---|
| SAFE601 | 2900 | 79% |
| SAFE208 | 125 | 3% |
| SAFE102 | 83 | 2% |
| SAFE304 | 83 | 2% |
| SAFE104 | 72 | 1% |
| SAFE701 | 62 | 1% |
| SAFE110 | 57 | 1% |
| SAFE101 | 51 | 1% |
| SAFE308 | 47 | 1% |
| SAFE803 | 46 | 1% |
| SAFE207 | 34 | 0% |
| SAFE105 | 32 | 0% |
| SAFE204 | 19 | 0% |
| SAFE801 | 14 | 0% |
| SAFE307 | 10 | 0% |
| SAFE501 | 7 | 0% |
| SAFE112 | 5 | 0% |
| SAFE205 | 5 | 0% |
| SAFE303 | 4 | 0% |
| SAFE602 | 4 | 0% |
| SAFE802 | 2 | 0% |
| SAFE206 | 1 | 0% |
| SAFE603 | 1 | 0% |

## defaults

- files scanned (all languages): 110
- rust files with findings: 57
- findings (rust files only): **332**
- wall time: 1.3s, peak RSS: 46 MB, exit code: 1

| Code | Findings | Share |
|---|---|---|
| SAFE102 | 83 | 25% |
| SAFE304 | 83 | 25% |
| SAFE104 | 72 | 21% |
| SAFE101 | 51 | 15% |
| SAFE105 | 32 | 9% |
| SAFE501 | 7 | 2% |
| SAFE303 | 4 | 1% |

## Triage

Done 2026-09-26 against the defaults run first, since that is what every user gets.
Every verdict below was reached by reading the reported line.

| Rule | Total | Sampled | TP | FP | Debatable | Verdict |
|---|---|---|---|---|---|---|
| SAFE105 no_recursion | 32 | **32 (all)** | 23 | **9** | 0 | noisy - 28% FP |
| SAFE501 unbounded_loops | 7 | **7 (all)** | 0 | **7** | 0 | **broken for Rust** |
| SAFE304 side_effects | 83 | 6 | 2 | 2 | 2 | noisy - ~36% is `write!` |
| SAFE101 function_length | 51 | 4 | 4 | 0 | 0 | trustworthy |
| SAFE102 nesting_depth | 83 | 4 | 4 | 0 | 0 | trustworthy, `else if` caveat |
| SAFE104 complexity | 72 | 4 | 4 | 0 | 0 | trustworthy |
| SAFE208 unwrap (all-rules) | 125 | 6 | 2 | 2 | 2 | 21% test-code leakage |
| SAFE601 (all-rules) | 2900 | 2 | 2 | 0 | 0 | 79% of output; see #163 |

### SAFE105: 23 genuine / 8 issue #160 / 1 new

The 23 true positives are regex-AST, HIR and glob-token tree walks where
recursion is the idiom - true by the rule's definition, but the rule does not
fit the domain.

The 8 false positives are all #160: a bare call inside an `impl`/`trait` method
resolving to a different free function or import. `crates/core/search.rs:347`
and `:349` call the free `fn search_path` from the method of the same name;
`crates/matcher/src/lib.rs:450` calls the imported `interpolate`;
`crates/printer/src/standard.rs:1524` and `:1587` call `crate::util` imports;
`crates/regex/src/config.rs:264` calls `non_matching::non_matching_bytes`.

The 1 remaining is a new class, now #173: `crates/ignore/src/walk.rs:2217`,
where a function-local `use std::os::unix::fs::symlink;` shadows the enclosing
`fn symlink` and the call resolves to std.

### Defects filed from this run

| Issue | Rule | Class |
|---|---|---|
| #170 | SAFE501 | `loop {}` exiting via `return` reported as infinite - 7/7 FP |
| #171 | SAFE304 | `write!`/`writeln!` to a `Formatter` or `String` counted as I/O |
| #172 | SAFE208 | test context misses cargo `tests/` and parent-file `#[cfg(test)] mod x;` |
| #173 | SAFE105 | function-local `use` shadowing the enclosing fn name |
| #154 | SAFE102 | `else if` inflation - confirmed in Rust, extending the JS/TS issue |
| #160 | SAFE105 | bare call in `impl` - confirmed, 8/32 here |
| #163 | SAFE601 | `test_functions_only=false` default - confirmed, 79% of output |

### Is any of this ripgrep-specific?

No. Every false-positive class is a grammar-shape mechanism - a bare
`identifier` callee, a macro matched by name, `loop` without a
`break_expression`, a file-local `#[cfg(test)]` lookup, `else_clause >
if_expression` - that any idiomatic Rust crate will trigger. The #160 pattern
reproduced here at 8/32 with a single author, on a codebase unrelated to Ruff,
which is what the rule source predicts.
