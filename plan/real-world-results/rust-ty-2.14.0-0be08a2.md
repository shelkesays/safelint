# ty - rust

- safelint: **2.14.0** (`/tmp/pipchk/bin/safelint`)
- project: `/Users/rahulshelke/sources/safelint_tests/ruff` @ `0be08a206f9c3180afd3e93bcc792ed5cb1f4db1`, subtree `crates/ty_`
- preset: `none`
- run: 2026-09-25 22:16 UTC

## all-rules

- files scanned (all languages): 5037
- rust files with findings: 381
- findings (rust files only): **22066**
- wall time: 51.3s, peak RSS: 138 MB, exit code: 1

| Code | Findings | Share |
|---|---|---|
| SAFE601 | 17978 | 81% |
| SAFE101 | 955 | 4% |
| SAFE102 | 631 | 2% |
| SAFE104 | 553 | 2% |
| SAFE208 | 423 | 1% |
| SAFE105 | 377 | 1% |
| SAFE110 | 285 | 1% |
| SAFE701 | 238 | 1% |
| SAFE304 | 152 | 0% |
| SAFE207 | 145 | 0% |
| SAFE803 | 134 | 0% |
| SAFE204 | 51 | 0% |
| SAFE308 | 29 | 0% |
| SAFE112 | 23 | 0% |
| SAFE501 | 19 | 0% |
| SAFE205 | 15 | 0% |
| SAFE307 | 13 | 0% |
| SAFE802 | 13 | 0% |
| SAFE103 | 11 | 0% |
| SAFE303 | 8 | 0% |
| SAFE602 | 6 | 0% |
| SAFE801 | 4 | 0% |
| SAFE206 | 3 | 0% |

## defaults

- files scanned (all languages): 5037
- rust files with findings: 263
- findings (rust files only): **2706**
- wall time: 20.5s, peak RSS: 75 MB, exit code: 1

| Code | Findings | Share |
|---|---|---|
| SAFE101 | 955 | 35% |
| SAFE102 | 631 | 23% |
| SAFE104 | 553 | 20% |
| SAFE105 | 377 | 13% |
| SAFE304 | 152 | 5% |
| SAFE501 | 19 | 0% |
| SAFE103 | 11 | 0% |
| SAFE303 | 8 | 0% |

## Triage

Done 2026-09-26. Two rules validated exhaustively; SAFE102 and SAFE104 had their
arithmetic independently reimplemented and reproduced on every finding.

| Rule | Total | Sampled | TP | FP | Verdict |
|---|---|---|---|---|---|
| SAFE501 | 19 | **19 (all)** | **0** | **19** | broken |
| SAFE105 | 377 | **377 (scripted + 22 read)** | 339 | 38 | sound but mistuned |
| SAFE304 | 152 | 6 + scripted | 1 | ~100 are #171 | broken for Rust |
| SAFE102 | 631 | 4 + **all 631 replicated** | 507 | **74** | ~12% else-if tax |
| SAFE104 | 553 | 4 + **all 553 replicated** | 553 | 0 | arithmetic exact, wrong metric |
| SAFE101 | 955 | 4 | 4 | 0 | correct, unactionable |
| SAFE110 | 285 | 3 + scripted | 203 | **82** | **compile-breaking advice** |
| SAFE208 | 423 | 6 + scripted | 351 | 72 | cargo `tests/` gap |
| SAFE801 | 4 | **4 (all, security)** | 1 | 3 | broken |
| SAFE601 | 17978 | 2 | 2 | 0 | 81.5% of output |

**SAFE501: 0 of 19.** Combined with ripgrep's 0 of 7, that is **0 true positives
in 26 findings across two unrelated projects**. Every one exits via `return`.

**SAFE104 arithmetic reproduced on 553/553.** `match_arm` alone is 50% of all
counted decision points; 135 findings (24%) are over threshold *only* because of
exhaustive matches.

### Defects filed from this run

| Issue | Rule | Class |
|---|---|---|
| #176 | SAFE110 | reassignment inside a closure missed - the suggested fix does not compile (E0594) |
| #179 | SAFE501 | blind inside macro token trees: three literal `break;` in `crossbeam::select!` unseen |
| #180 | SAFE801 | bare callee matching - a closure parameter named `query` reported as injection |
| #181 | SAFE104 | exhaustive `match` arms dominate the score |
| #170 | SAFE501 | confirmed 19/19 |
| #160 | SAFE105 | confirmed 35/377 |
| #171 | SAFE304 | confirmed ~100/152 |
| #172 | SAFE208 | confirmed 72/423, and extends to SAFE204 (45%) and SAFE802 (46%) |
| #173 | SAFE105 | `let`-closure shadow variant added |

### Does a type checker stress these rules differently?

Yes, in both directions. ty makes SAFE105 look *better* than ripgrep did (90% vs
72% genuine, because deliberate type-graph recursion really is everywhere) while
making SAFE104, SAFE601 and SAFE102 look far worse. But the two genuinely new
defects it exposed - macro-token-tree blindness and closure-captured `mut` - come
from `crossbeam::select!` and closure capture, which any async or iterator-heavy
Rust project hits just as hard. They are rule bugs, not domain artefacts.
