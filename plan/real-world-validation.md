# Real-world validation programme

Running safelint against well-known open-source projects, with **every rule for
that language enabled**, and manually validating each finding as a true
positive, a false positive, or noise.

## Why this exists

safelint's own test suite proves rules fire on code written to make them fire.
It cannot prove they *stay quiet* on idiomatic code someone else wrote. The
first pass of this programme (2026-09-24, against private codebases) found ten
defects that the full suite - 2228 tests, 97% coverage - does not catch, because
every one of them is a rule being wrong about a language idiom rather than wrong
about its own logic.

Two rules were firing on **default settings**: `SAFE105` on Java method
overloads, and `SAFE102` on every JavaScript `else if` chain.

## Two axes: language idioms and framework presets

A finding can come from the language rules or from a framework preset, and
mixing them makes it impossible to tell which. So the matrix has two kinds of
row:

* **Language rows** - a project with no framework preset applied. Validates the
  cross-language and language-specific rules against plain idiomatic code.
* **Framework rows** - a project that actually uses the framework, run with
  that preset enabled. Validates the 9xx rules and the preset's sink/source
  additions.

Presets that exist today, each of which needs its own row:

| Language | Presets |
|---|---|
| Python | `django`, `flask`, `fastapi` (+ the independent `pydantic` switch) |
| JavaScript | `node`, `browser`, `deno`, `bun`, `cloudflare-workers` |
| Java | `spring-boot` |
| PHP | `laravel` |

### Not just one project each

A rule tuned until it is quiet on one codebase is overfitted to that codebase.
Each **language** row needs at least two unrelated projects, from different
authors and ideally different domains, and a fix is only accepted when both
stay clean. Framework rows can start with one project, since the preset surface
is much narrower, but a second is preferable before declaring a preset sound.

The goal is not "clean on project X". It is that an arbitrary developer can
enable a rule and trust what it tells them.

## Method

1. Install the published artefact (not the working tree) into an isolated venv,
   so what is validated is what a user would get.
2. Generate a config enabling every rule that applies to the language, plus the
   preset for framework rows.
3. Run with `--config <dir>` pointing at that config. This matters: config is
   discovered from the **target path**, not the working directory, so a
   `safelint.toml` inside the cloned project will silently override the
   intended one. This caught us on the first pass.
4. Filter results by file extension - `--all-files` on a polyglot repo lints
   every supported language it finds, not just the one under test.
5. Read the reported line for each sampled finding and classify it. Quote the
   code. No verdict without reading the source.
6. For each defect, open a GitHub issue stating **why** it happens (root cause
   in safelint's own source), **what** the fix is, and **how** to verify it.
7. Fix later, in batches, then re-run against *every* project for that language.

## Project matrix

Clones live in **`/Users/rahulshelke/sources/safelint_tests/`**, deliberately
separate from personal work so the validation corpus is never confused with
actual projects and can be wiped and re-cloned at will. Status: `todo`,
`cloned`, `run`, `triaged`.

### Language rows (no preset)

| Language | Project | Repository | Why this one | Status |
|---|---|---|---|---|
| Python | Requests | `psf/requests` | The most-copied Python idiom source there is; small, pure library | todo |
| Python | Rich | `Textualize/rich` | Modern typed Python, very different style from Requests | todo |
| JavaScript | Express | `expressjs/express` | Canonical Node service code, callback-heavy | todo |
| JavaScript | Axios | `axios/axios` | Promise/async idioms, dual browser+node target | todo |
| TypeScript | Vue core | `vuejs/core` | Large idiomatic TS without styled-components | todo |
| TypeScript | Zod | `colinhacks/zod` | Type-level heavy TS; very different shape from Vue | todo |
| Java | Commons Lang | `apache/commons-lang` | Vanilla Java, no framework; pure library idioms | todo |
| Java | Guava | `google/guava` | Large, heavily reviewed, different house style | todo |
| Rust | Ruff | `astral-sh/ruff` | Large modern idiomatic Rust; a linter itself | todo |
| Rust | ty | `astral-sh/ty` | Same authors, different shape; type checker | todo |
| Go | Cobra | `spf13/cobra` | CLI library; no web framework involved | todo |
| Go | fzf | `junegunn/fzf` | Application rather than library; concurrency-heavy | todo |
| PHP | Guzzle | `guzzle/guzzle` | Widely used PHP with no framework preset | todo |
| PHP | Monolog | `Seldaek/monolog` | Different domain; exercises SAFE203 logging rules honestly | todo |
| C | curl | `curl/curl` | Security-critical C, heavily audited, idiomatic | todo |
| C | Redis | `redis/redis` | Different C style; allocation and string-handling heavy | todo |
| C++ | fmt | `fmtlib/fmt` | Modern C++, template-heavy, widely vendored | todo |
| C++ | LevelDB | `google/leveldb` | Classic OO C++; RAII and pointer discipline | todo |

### Framework / runtime rows (preset enabled)

| Preset | Project | Repository | Status |
|---|---|---|---|
| python / `django` | Django | `django/django` | todo |
| python / `flask` | Flask | `pallets/flask` | todo |
| python / `fastapi` | FastAPI | `tiangolo/fastapi` | todo |
| python / `pydantic` | Pydantic | `pydantic/pydantic` | todo |
| java / `spring-boot` | Spring PetClinic | `spring-projects/spring-petclinic` | run |
| php / `laravel` | Laravel framework | `laravel/framework` | todo |
| php / `laravel` | FreeScout (application, not framework) | `freescout-help-desk/freescout` | run |
| javascript / `node` | Express | `expressjs/express` | todo |
| javascript / `browser` | Chart.js | `chartjs/Chart.js` | todo |
| javascript / `deno` | Deno std | `denoland/std` | todo |
| javascript / `bun` | - | needs a candidate | todo |
| javascript / `cloudflare-workers` | workers-sdk | `cloudflare/workers-sdk` | todo |

Already run against private codebases in the first pass. These are not
reproducible by anyone else, so they do not count toward the bar, but their
findings are recorded below: `salessync` (Python), `v4` (JavaScript),
`arkstore` (Rust), `superset-frontend` (TypeScript), `freescout` (PHP).

## Findings register

Every defect found gets a GitHub issue. `Verified` means reproduced from a
minimal case, not just observed in a large codebase.

| # | Rule | Defect | Severity | Default-on? | Verified | Issue |
|---|---|---|---|---|---|---|
| 1 | SAFE105 | Java method overload counted as recursion | High | **yes** | yes | #153 |
| 2 | SAFE102 | JS/TS `else if` counted as nesting (fix exists for Python/PHP) | High | **yes** | yes | #154 |
| 3 | SAFE803 | Python `dict.get(k, default)` cannot return None but is flagged | High | no | yes | #155 |
| 4 | SAFE802 | Python `flagged_calls` defaults are C/POSIX; `mkdir`/`unlink`/etc. return None | High | no | yes | #156 |
| 5 | SAFE907 | `Validator::make()` unrecognised, so the validation call is flagged as unvalidated | High | preset | yes | #157 |
| 6 | SAFE801 | PHP `query` sink collides with Eloquent / php-imap; zero-arg receiver branch fires | High | no | agent | #158 |
| 7 | SAFE203 | Fires on handlers that re-raise; message says "swallowed" | Medium | no | yes | #159 |
| 8 | SAFE203 | PHP log-method set is hard-coded, misses project logging wrappers | Medium | no | agent | #159 |
| 9 | SAFE105 | Rust: bare call inside an `impl` method is not a self-call | Medium | **yes** | agent | #160 |
| 10 | SAFE207 | Rust: blind to logging one call hop away in a helper | Medium | no | agent | #161 |
| 11 | SAFE908 | Fires on stock Laravel `TrimStrings` / `EncryptCookies` | Medium | preset | agent | #162 |
| 12 | SAFE601 | `test_functions_only=false` default makes it 56-92% of all output | Tuning | no | yes | #163 |
| 13 | SAFE102 | Python counts `with` / `try` as nesting levels | Tuning | yes | agent | #166 |
| 14 | SAFE101 | JS reports `<anonymous>` for `const Foo = () => {}` | Low | yes | agent | #165 |
| 15 | - | `styled.div<T>` template literals fail to parse (tree-sitter-typescript) | Medium | n/a | yes | #164 |

## Cross-cutting root cause

Most of the above are one problem wearing different hats: **safelint matches
call and member names as barewords, with no type information.** Tree-sitter
gives syntax, not semantics, so `query` matches Eloquent's query builder and
php-imap's folder search equally; `add` matches `BigDecimal.add` and
`List.add`; `get` matches `Map.get` and `RequestEntity.get`.

That is inherent to the parsing strategy and cannot be fixed generally. What
*can* be fixed, case by case:

- Drop names whose collision rate is high and whose true-positive rate is low
  (`query` as a bare PHP sink; `mkdir` in Python's `flagged_calls`).
- Use available syntactic evidence before reporting: argument count
  (`dict.get(k, default)`), arity (`getPet(name, false)` is a different
  function), enclosing construct (a bare call inside a Rust `impl`).
- Make hard-coded sets configurable (`SAFE203`'s log-method names).

Issue bodies should say which of these applies, because it determines whether
the fix is a default change, a logic change, or a new config key.
