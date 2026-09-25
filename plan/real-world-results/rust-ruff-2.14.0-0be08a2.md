# ruff - rust

- safelint: **2.14.0** (`/tmp/pipchk/bin/safelint`)
- project: `/Users/rahulshelke/sources/safelint_tests/ruff` @ `0be08a206f9c3180afd3e93bcc792ed5cb1f4db1`
- preset: `none`
- run: 2026-09-24 20:44 UTC

## all-rules

- files scanned (all languages): 5037
- rust files with findings: 2001
- findings (rust files only): **47650**
- wall time: 50.9s, peak RSS: 139 MB, exit code: 1

| Code | Findings | Share |
|---|---|---|
| SAFE601 | 36925 | 77% |
| SAFE101 | 1806 | 3% |
| SAFE701 | 1564 | 3% |
| SAFE102 | 1486 | 3% |
| SAFE208 | 1234 | 2% |
| SAFE104 | 1218 | 2% |
| SAFE304 | 782 | 1% |
| SAFE105 | 650 | 1% |
| SAFE110 | 519 | 1% |
| SAFE803 | 460 | 0% |
| SAFE204 | 214 | 0% |
| SAFE207 | 211 | 0% |
| SAFE112 | 112 | 0% |
| SAFE308 | 95 | 0% |
| SAFE205 | 68 | 0% |
| SAFE307 | 62 | 0% |
| SAFE801 | 61 | 0% |
| SAFE303 | 53 | 0% |
| SAFE103 | 38 | 0% |
| SAFE802 | 37 | 0% |
| SAFE501 | 30 | 0% |
| SAFE602 | 14 | 0% |
| SAFE206 | 5 | 0% |
| SAFE000 | 3 | 0% |
| SAFE306 | 3 | 0% |

## defaults

- files scanned (all languages): 5037
- rust files with findings: 1108
- findings (rust files only): **6066**
- wall time: 20.5s, peak RSS: 76 MB, exit code: 1

| Code | Findings | Share |
|---|---|---|
| SAFE101 | 1806 | 29% |
| SAFE102 | 1486 | 24% |
| SAFE104 | 1218 | 20% |
| SAFE304 | 782 | 12% |
| SAFE105 | 650 | 10% |
| SAFE303 | 53 | 0% |
| SAFE103 | 38 | 0% |
| SAFE501 | 30 | 0% |
| SAFE000 | 3 | 0% |

## Triage

Done 2026-09-26, scoped to the Ruff linter/formatter crates; `crates/ty_*` is
triaged separately in `rust-ty-2.14.0-0be08a2.md` to avoid double-counting.
Ruff-only: **3226** findings on defaults (of the 6066 whole-repo total).

| Rule | Sampled | TP | FP | Verdict |
|---|---|---|---|---|
| SAFE105 | 24 across 14 crates + scan of all 273 | 20 | 4 | trustworthy, ~8% FP |
| SAFE304 | 8 + scan of all 564 | 2 | 5 | broken - 69% is #171 |
| SAFE303 | 5 | 1 | 3 | noisy - receiver-blind |
| SAFE501 | **11 (all)** | 1 | 10 | broken |
| SAFE102 | 4 + **all 849 replicated** | 4 | 0 | ~9.5% else-if tax |
| SAFE104 | 4 + scan of all 656 | 2 | 0 | 54% is `match` dispatch |
| SAFE101 | 4 | 3 | 0 | trustworthy |
| SAFE208 | 6 | 5 | 1 | 11.3% cargo `tests/` |
| SAFE601 | 2 | 0 | 2 | 74.2% of all-rules output |
| SAFE110 | 3 | 0 | 3 | **77% contradicted by a visible mutation** |
| SAFE801 | **5 (all sampled, security)** | **0** | 5 | broken |

### What only a 2000-file multi-author monorepo showed

Three things ripgrep could not:

1. **New FP mechanisms that need library scale.** Trait-impl delegating to a
   same-name inherent method (9 confirmed, e.g. `impl Stack for Vec { fn pop(&mut self) { self.pop() } }`);
   receiver-blind I/O name matching (`file.status(db)`, `RwLock::read`);
   closure-scoped mutations defeating SAFE110.
2. **Rust's two dominant idioms silently dominate two rules.** Exhaustive
   `match` is 54% of SAFE104 findings; insta snapshot tests are 10% of SAFE601.
3. **Measured rather than anecdotal rates** for every filed defect - #154 at
   9.5%, #160 at 5.1%, #170 at 91%, #171 at 69%, #172 at 11.3% - which is what
   turns "we saw this once" into a fix priority.

### Defects filed from this run

| Issue | Rule | Class |
|---|---|---|
| #174 | SAFE000 | `str![[r#"..."#]]` - macro named after a primitive type fails to parse, file silently skipped |
| #175 | - | a parse failure removes a file from analysis with no summary signal |
| #177 | SAFE601 | `assertion_calls_rust` omits the insta snapshot macros - 557 real tests read as assertion-free |
| #178 | SAFE304/303 | I/O primitives matched by bare method name, receiver ignored |
| #181 | SAFE104 | exhaustive `match` arms dominate the score - 54% of findings |
| #160 | SAFE105 | confirmed 14/273, plus a new trait-impl-delegation variant |
| #172 | SAFE208 | refined: in-file `#[cfg(test)]` works; cargo `tests/` is the gap |

### Harness note

Zero findings landed in `crates/ruff_linter/resources/**` - but only because
those 1819 fixture files are `.py`/`.pyi` and this was a Rust run. A
language-agnostic run would ingest deliberately-malformed Python fixtures. The
exclusion list should grow `**/resources/{test,fixtures}/**` before any Python
project is validated this way.
