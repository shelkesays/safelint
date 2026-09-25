# Real-world validation programme

Running safelint against well-known open-source projects - once with **every
rule for that language enabled**, once with **stock defaults** - and manually
classifying each finding as a true positive, a false positive, or debatable.

## Why this exists

safelint's own test suite proves rules fire on code written to make them fire.
It cannot prove they *stay quiet* on idiomatic code someone else wrote. The
first pass of this programme (2026-09-24, against a mix of private and public
codebases) found fifteen
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

TypeScript, Rust, Go, C and C++ have no presets, so they have language rows only.
That is not an omission in the matrix.

### Not just one project each

A rule tuned until it is quiet on one codebase is overfitted to that codebase.
Each **language** row needs at least two unrelated projects, from different
authors and ideally different domains, and a fix is only accepted when both
stay clean. Framework rows can start with one project, since the preset surface
is much narrower, but a second is preferable before declaring a preset sound.

The goal is not "clean on project X". It is that an arbitrary developer can
enable a rule and trust what it tells them.

## Method

0. The harness is `scripts/validate_real_world.py`. One invocation does steps
   2-6 below for one project and one language, and writes the summary that
   step 7 is done against. Run it with `--help` for the flags; the module
   docstring records the reasoning behind each design choice.
1. Install the published artefact (not the working tree) into an isolated venv,
   so what is validated is what a user would get:
   `uv venv v && uv pip install --python v/bin/python 'safelint[all]==X.Y.Z'`,
   then pass `--safelint v/bin/safelint`.
2. Generate a config enabling every rule that applies to the language, plus the
   preset for framework rows.
3. Run with `--config <dir>` pointing at that config. This matters: config is
   discovered from the **target path**, not the working directory, so a
   `safelint.toml` inside the cloned project will silently override the
   intended one. This caught us on the first pass.
4. Filter results by file extension - `--all-files` on a polyglot repo lints
   every supported language it finds, not just the one under test.
5. Exclude vendored and generated trees before counting anything - see below.
6. Run **twice**: once with every rule enabled, and once with **stock defaults**.
7. Read the reported line for each sampled finding and classify it. Quote the
   code. No verdict without reading the source.
8. For each defect, open a GitHub issue stating **why** it happens (root cause
   in safelint's own source), **what** the fix is, and **how** to verify it.
9. Fix later, in batches, then re-run against *every* project for that language.

### Run stock defaults too, not just every rule

The all-rules run finds the most defects, but it is not what anyone
experiences. Most users run defaults, and the two worst findings of the first
pass - `SAFE105` on Java overloads and `SAFE102` on JavaScript `else if` - fire
on **default config**. Those matter more than anything only visible at maximum
verbosity, and the default-config output is small enough to read in full rather
than sample.

Record both numbers per project. A rule that is noisy only when explicitly
enabled is a tuning problem; a rule that is noisy by default is a bug.

### Exclude vendored and generated code

The first pass wasted a run on this: the candidate Go and C++ "projects" turned
out to be dependency source inside `.venv` directories, so the numbers described
third-party code that no one in the project wrote. Before counting, exclude at
least `node_modules/`, `.venv/`, `venv/`, `vendor/`, `target/`, `dist/`,
`build/`, `third_party/`, `site-packages/` and any generated output the project
declares.

Check the file count against what the project actually ships. If the count looks
too high for the repository, something vendored is being linted.

### Pin the revision

Record the commit SHA cloned for each project. Without it, "we fixed the rule
and re-ran clean" cannot be reproduced - the project moved, and it is impossible
to tell a real fix from upstream churn. Clone with `--depth 1` for speed, but
capture `git rev-parse HEAD` into the results.

### Classification, and how much to sample

- **True positive** - the code genuinely has the property the rule describes,
  whether or not the author cares. `assert`-free production function: true.
- **False positive** - the rule's claim is not true of the code. A `no_recursion`
  hit on an overload; a `null_dereference` hit on `d.get(k, default)`.
- **Debatable** - the claim holds literally but the finding is not actionable,
  usually because the fix is worse than the finding. `with session:` counted as
  nesting; `List.add()`'s discarded boolean.

Debatable is not a way to avoid deciding. If a rule's findings are mostly
debatable, the rule has a tuning problem and that is worth recording as such.

Sample **3-5 findings per rule code**, spread across different files - one file
can have one unusual pattern. Validate **all** findings for any rule with fewer
than ten, and **all** findings from security rules (SAFE8xx, SAFE9xx) regardless
of count: a security rule that is wrong is worse than one that is silent.

### Definition of done, per language

A language row is `triaged` when every rule code in its output has been sampled
and classified, every defect has an issue, and both projects have been run. It
is **not** done when the findings have merely been counted.

A defect issue is closable when the fix is in, the minimal repro is clean, and
**every** project for that language has been re-run - not just the one that
surfaced it. That is the whole point of having two.

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
| TypeScript | Superset frontend | `apache/superset` (`superset-frontend/`) | Large React/TS app; already run, and the source of the styled-components finding | run |
| Java | Commons Lang | `apache/commons-lang` | Vanilla Java, no framework; pure library idioms | todo |
| Java | Guava | `google/guava` | Large, heavily reviewed, different house style | todo |
| Rust | Ruff | `astral-sh/ruff` | Large modern idiomatic Rust; a linter itself. **Includes ty**: the type checker's source is `crates/ty_*` in this monorepo | run (`plan/real-world-results/rust-ruff-2.14.0-0be08a2.md`) |
| Rust | ty | `astral-sh/ruff` subtree `crates/ty_` | The type checker: a recursion-heavy subsystem by partly different authors. Validated with `--include` rather than its own clone - see the note below | run (`plan/real-world-results/rust-ty-2.14.0-0be08a2.md`) |
| Rust | ripgrep | `BurntSushi/ripgrep` | Single author, different domain, classic idiomatic Rust - the unrelated second project the two-project rule requires | run (`plan/real-world-results/rust-ripgrep-2.14.0-3fce3b5.md`) |
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
| python / `fastapi` + `pydantic = true` | FastAPI | `fastapi/fastapi` | todo |
| java / `spring-boot` | Spring PetClinic | `spring-projects/spring-petclinic` | run (`plan/real-world-results/java-spring-petclinic-2.14.0-c7ee170.md`) |
| php / `laravel` | Laravel framework | `laravel/framework` | todo |
| php / `laravel` | FreeScout (application, not framework) | `freescout-help-desk/freescout` | run |
| javascript / `browser` | Chart.js | `chartjs/Chart.js` | todo |
| javascript / `deno` | Deno std | `denoland/std` | todo |
| javascript / `bun` | Elysia | `elysiajs/elysia` | todo |
| javascript / `cloudflare-workers` | Workers templates | `cloudflare/templates` | todo |

Notes on the Rust rows:

* **`astral-sh/ty` has no Rust in it.** The clone is 96 files of docs and
  release config; the type checker's 404 `.rs` files live in the Ruff monorepo
  under `crates/ty_*`. It is validated as a **subtree** of the Ruff clone via
  `--include crates/ty_`, which is why the harness grew that flag.
* **ty is a subset of Ruff, so their numbers overlap.** Ruff's row counts the
  whole monorepo including ty. When triaging, the linter crates and the ty
  crates are sampled separately so nothing is counted twice, and the two are
  treated as one project for the purposes of the two-project rule - same
  repository, same house style. **ripgrep is the genuinely unrelated second
  Rust project**, which is what makes a pattern appearing in both meaningful.

Notes on the runtime rows:

* **`pydantic` rides on the FastAPI row**, as `[python] pydantic = true`
  alongside `framework = "fastapi"`. It is a switch, not a preset - it adds
  `model_construct` / `construct` as SAFE801 sinks and enables SAFE906 - and it
  can be combined with any framework. Running it against `pydantic/pydantic`
  itself would be circular: that is the codebase that *defines* the methods the
  switch treats as sinks. FastAPI is a large, idiomatic *consumer* of pydantic,
  which is what the switch is for.
* **There is no `node` row on purpose.** `node` is the *default* runtime - its
  preset is empty - so a run with `runtime = "node"` is byte-for-byte the same
  as a run with no preset. The JavaScript language rows (Express, Axios) already
  cover it. Listing it here would have counted one run twice and blurred the
  language/framework split this document exists to keep.
* **Elysia** over Hono, Brisa and the rest for `bun`. It is Bun-first by design
  (`Bun.serve`, `Bun.file`), which is what the preset is about. Hono is
  deliberately runtime-agnostic Web Standards code and would barely exercise
  the preset at all - it is the wrong test even though it is the bigger project.
* **`cloudflare/templates`** replaces the earlier `cloudflare/workers-sdk`
  choice. workers-sdk is Wrangler: CLI tooling *about* Workers, written as Node
  code, in a 160MB monorepo. It would have validated the `node` preset while
  claiming to validate `cloudflare-workers`. The templates repo is actual
  worker code - `fetch` handlers, `env` bindings - which is what the preset
  models.
* **Every runtime row except `node` and `browser` will be TypeScript**, because
  the Deno, Bun and Workers ecosystems are TS-dominant. That is fine (the
  runtime preset is set under `[javascript] runtime`, and TS inherits the
  `_javascript` config keys), but it means those rows exercise the TS grammar
  path, not the JS one. The `node` and `browser` rows carry the plain-JavaScript
  coverage.

### What the first pass already covered

Run on 2026-09-24 against safelint **2.14.0rc3**. Three of the five were
public repositories and count toward the bar; the two `run` rows above are the
same clones.

| Project | Language | Public? | Counts? |
|---|---|---|---|
| `spring-projects/spring-petclinic` | Java (`spring-boot`) | yes | yes |
| `freescout-help-desk/freescout` | PHP (`laravel`) | yes | yes |
| `apache/superset` (`superset-frontend/`) | TypeScript | yes | yes - listed as a language row |
| `salessync` | Python | private | no |
| `v4` | JavaScript | private | no |
| `arkstore` | Rust | private | no |

The private three are not reproducible by anyone else, so their findings are
evidence but their runs do not count. Every finding below names the project it
came from so it can be re-checked against a public one.

## Known gaps in this programme

Recorded rather than left implicit, because each is a way the results could
mislead:

- ~~The harness is not in the repository.~~ Closed: `scripts/validate_real_world.py`,
  with a smoke test in `tests/test_validate_real_world.py`. It asks the binary
  under test for its rule registry, so config generation cannot drift from the
  version being validated - the `/tmp` scripts imported from whatever was on
  `sys.path`.
- ~~Results are not stored.~~ Closed: one markdown summary per run is committed
  to `plan/real-world-results/` named `<lang>-<project>-<version>-<sha7>.md`;
  raw JSON sits beside it in `.raw/`, which is ignored. Comparing two summaries
  for the same project across versions is how a regression between releases
  becomes visible.
- ~~No performance record.~~ Closed: every run records wall time and the child
  process's peak RSS. A run that suddenly takes minutes, or a peak RSS that
  jumps, is a finding in its own right.
- **True positives in third-party code are not acted on.** If safelint finds a
  genuine defect in a cloned project, this programme records it as evidence the
  rule works and stops there. Reporting upstream is out of scope - worth
  restating if that ever changes.

## Findings register

Every defect found gets a GitHub issue. All fifteen were found against safelint
**2.14.0rc3**. `Verified` means reproduced from a minimal case, not just
observed in a large codebase. `Found in` is where it first surfaced, so the
claim can be re-checked; a private project there means the finding still needs
confirming on a public one before the issue is worked.

| # | Rule | Defect | Severity | Default-on? | Verified | Found in | Issue |
|---|---|---|---|---|---|---|---|
| 1 | SAFE105 | Java method overload counted as recursion | High | **yes** | yes | spring-petclinic | #153 |
| 2 | SAFE102 | `else if` counted as nesting in JS/TS **and Rust** (fix exists for Python/PHP) | High | **yes** | yes | v4 (private), ripgrep | #154 |
| 3 | SAFE803 | Python `dict.get(k, default)` cannot return None but is flagged | High | no | yes | salessync (private) | #155 |
| 4 | SAFE802 | Python `flagged_calls` defaults are C/POSIX; `mkdir`/`unlink`/etc. return None | High | no | yes | salessync (private) | #156 |
| 5 | SAFE907 | `Validator::make()` unrecognised, so the validation call is flagged as unvalidated | High | preset | yes | freescout | #157 |
| 6 | SAFE801 | PHP `query` sink collides with Eloquent / php-imap; zero-arg receiver branch fires | High | no | agent | freescout | #158 |
| 7 | SAFE203 | Fires on handlers that re-raise; message says "swallowed" | Medium | no | yes | salessync (private) | #159 |
| 8 | SAFE203 | PHP log-method set is hard-coded, misses project logging wrappers | Medium | no | agent | freescout | #159 |
| 9 | SAFE105 | Rust: bare call inside an `impl` method is not a self-call | **High** | **yes** | yes | arkstore (private), ripgrep 8/32 | #160 |
| 10 | SAFE207 | Rust: blind to logging one call hop away in a helper | Medium | no | agent | arkstore (private) | #161 |
| 11 | SAFE908 | Fires on stock Laravel `TrimStrings` / `EncryptCookies` | Medium | preset | agent | freescout | #162 |
| 12 | SAFE601 | `test_functions_only=false` default makes it 56-92% of all output | Tuning | no | yes | all four | #163 |
| 13 | SAFE102 | Python counts `with` / `try` as nesting levels | Tuning | **yes** | agent | salessync (private) | #166 |
| 14 | SAFE101 | JS reports `<anonymous>` for `const Foo = () => {}` | Low | **yes** | agent | v4 (private) | #165 |
| 15 | - | `styled.div<T>` template literals fail to parse (tree-sitter-typescript) | Medium | n/a | yes | superset-frontend | #164 |
| 16 | SAFE501 | Rust `loop {}` exiting via `return` called an infinite loop - 7/7 FP | High | **yes** | yes | ripgrep | #170 |
| 17 | SAFE304 | Rust `write!`/`writeln!` to a `Formatter` or `String` counted as I/O | High | **yes** | yes | ripgrep | #171 |
| 18 | SAFE208 | Rust test context misses cargo `tests/` and parent-file `#[cfg(test)] mod x;` | Medium | no | yes | ripgrep | #172 |
| 19 | SAFE105 | Rust function-local `use` shadowing the enclosing fn name | Medium | **yes** | yes | ripgrep | #173 |

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
