# C support post-release audit - remediation spec

**Status**: not started. **Scheduling (owner decision, 2026-07-02, revised):
this plan runs FIRST and ships as 2.7.1, BEFORE C++ (`plan/03-cpp.md`).**
Rationale: the C++ work widens SAFE106/310/311/312/313 from `("c",)` to
`("c","cpp")` and extends `dataflow_c` into `dataflow_cpp` - exactly the rules
and tracker whose regression guards this plan adds (config-override tests, the
SAFE106 contract lock, the behavioural pin). Those guards must exist before
C++ touches that code, or a C++ refactor could silently regress C behaviour
with nothing to catch it. Closing the C gaps as a self-contained 2.7.1 gives
C++ a fully-closed, fully-guarded baseline.

**Origin**: a full verification audit of the shipped C support (v2.7.0,
2026-07-02) against `plan/02-c.md` (now captured in the shipped docs) and
against Holzmann's "Power of Ten" paper (spinroot.com/gerard/pdf/P10.pdf).
**Audit verdict: the implementation is behaviourally correct** - all 21 C
rules registered exactly as specified, every `_c` config default matches the
spec (one deliberate, documented divergence: `sources_c`), and a 35-case
live battery against paper-shaped C code passed on every intended behaviour.
What remains is documentation debt, stale enumerations, and two test gaps
the original spec asked for. **Nothing in this plan changes rule behaviour.**

**Audience**: the AI coding agent implementing this. Read `plan/README.md`
"Non-negotiables" and "Validation gate" first; they all apply (Indian
English, no em-dashes, safelint must pass itself, drift tests land in the
same commit, config examples in both TOML forms).

---

## Execution protocol (context-resilience; follow exactly)

This spec is the **single source of truth**. Do not rely on conversation
memory, prior summaries, or assumptions about "what the audit meant" - every
required fact (exact stale texts, behavioural invariants, file anchors) is
written down here so no context loss can corrupt the work.

1. **One work package per commit**, in order (WP0 pin, WP1, WP2, WP3, WP4).
   Each commit message names the WP. This makes position recoverable from
   `git log --oneline` alone.
2. **After any context compaction, session restart, or hand-off**: re-read
   this ENTIRE file, then run `git log --oneline development..HEAD` and
   `git status` to re-derive exactly which WP is next. Never resume from
   memory of the plan; resume from the plan.
3. **Verify every anchor before editing.** Each WP quotes the exact current
   text it expects. Before each edit, confirm the quoted text exists
   verbatim (grep for a distinctive fragment). If it does not match - the
   file moved on since 2026-07-02 (e.g. C++ shipped in between) - STOP,
   re-locate the intent by grep, and adapt; never apply a quoted replacement
   onto drifted text, and never guess line numbers (all line numbers in this
   spec are hints from the audit date, not addresses).
4. **Regression locks run at the start and end** (WP0 below). If any lock
   fails at the end, the work introduced a behaviour change; revert the
   offending commit rather than "fixing forward" - this plan has no licence
   to change behaviour.
5. If anything in this spec conflicts with the state of the repository in a
   way the Sequencing section does not anticipate, stop and ask the owner
   rather than improvising.

## WP0 - Behavioural regression locks (run FIRST, commit the script)

Two hard invariants pin "no functionality regression":

**Lock 1 - source-tree invariant.** This plan may only change: `docs/**`,
`plan/**`, `tests/**`, `CHANGELOG.md`, `CONTRIBUTING.md`, `README.md`, and
`src/safelint/skill_files/**` (bundled docs, not code). At the end:

```bash
git diff --name-only development...HEAD -- src/safelint/ | grep -v '^src/safelint/skill_files/'
# MUST print nothing. Any hit = an unauthorised source change; revert it.
```

**Lock 2 - behavioural pin.** Save the script below as
`tests/rules/test_c_power_of_ten_pin.py` (it doubles as a permanent
regression test; that is its value beyond this plan). It distils the audit's
live battery: every C rule's fire AND clean case, including the subtle
behaviours later review rounds fixed. Run it BEFORE any other WP (must be
100% green on the unchanged branch point) and again at the end.

```python
"""Power-of-Ten behavioural pin for C - one fire + one clean case per C rule.

Written by the v2.7.0 post-release audit as a compact regression lock: if a
future refactor changes any C rule's observable behaviour, exactly one of
these named cases flips. Each case is the audit's minimal reproducer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path

_OPT_IN = {"rules": {n: {"enabled": True} for n in (
    "dynamic_allocation", "complex_macro", "conditional_compilation",
    "restricted_pointers", "missing_assertions", "dynamic_code_execution",
    "blanket_suppression", "tainted_sink", "return_value_ignored",
)}}

# (case id, source, code, fires?)
_CASES = [
    ("goto fires SAFE106", "void f(int x){ if(x) goto out; out: return; }", "SAFE106", True),
    ("setjmp fires SAFE106", "int f(void){ jmp_buf b; return setjmp(b); }", "SAFE106", True),
    ("plain flow clean SAFE106", "int f(int x){ return x + 1; }", "SAFE106", False),
    ("direct recursion fires SAFE105", "int fact(int n){ return n < 2 ? 1 : n * fact(n - 1); }", "SAFE105", True),
    ("while(1) bare fires SAFE501", "void f(void){ while(1) { } }", "SAFE501", True),
    ("goto OUT of loop is an exit SAFE501", "void f(int x){ while(1){ if(x) goto done; } done: return; }", "SAFE501", False),
    ("goto WITHIN loop still unbounded SAFE501", "void f(int x){ while(1){ again: if(x) goto again; } }", "SAFE501", True),
    ("malloc fires SAFE310", "void *f(void){ return malloc(8); }", "SAFE310", True),
    ("no allocation clean SAFE310", "int f(int a){ return a; }", "SAFE310", False),
    ("assert satisfies SAFE601", "int f(int x){ assert(x); return 1 / x; }", "SAFE601", False),
    ("file-scope var fires SAFE302", "int counter;\nint f(void){ return counter; }", "SAFE302", True),
    ("const file-scope clean SAFE302", "const int MAX = 5;\nint f(void){ return MAX; }", "SAFE302", False),
    ("extern fwd-ref clean SAFE302", "extern int g;\nint f(void){ return g; }", "SAFE302", False),
    ("initialised extern fires SAFE302", "extern int g = 1;\nint f(void){ return g; }", "SAFE302", True),
    ("pointer-returning prototype clean SAFE302", "char *foo(void);\nchar *g(void){ return foo(); }", "SAFE302", False),
    ("ignored fclose fires SAFE802", "void f(FILE *fp){ fclose(fp); }", "SAFE802", True),
    ("(void) cast discard clean SAFE802", "void f(FILE *fp){ (void)fclose(fp); }", "SAFE802", False),
    ("token paste fires SAFE311", "#define CAT(a, b) a##b\n", "SAFE311", True),
    ("bracket in string literal clean SAFE311", '#define OPEN "["\n', "SAFE311", False),
    ("misordered brackets fire SAFE311", "#define BAD )(\n", "SAFE311", True),
    ("#ifdef fires SAFE312", "#ifdef DEBUG\nint d;\n#endif\n", "SAFE312", True),
    ("include guard exempt SAFE312", "#ifndef H_H\n#define H_H\nint x;\n#endif\n", "SAFE312", False),
    ("double pointer fires SAFE313", "void f(int **pp){ }", "SAFE313", True),
    ("single pointer clean SAFE313", "void f(int *p){ }", "SAFE313", False),
    ("argv->system taint fires SAFE801", 'void f(char **argv){ system(argv[1]); }', "SAFE801", True),
    ("literal argument clean SAFE801", 'void f(void){ system("ls"); }', "SAFE801", False),
    ("printf in pure-named fn fires SAFE303", 'int compute_total(int x){ printf("%d", x); return x; }', "SAFE303", True),
    ("dlopen fires SAFE309", 'void load(void){ void *h = dlopen("lib.so", 1); }', "SAFE309", True),
    ("bare NOLINT fires SAFE603", "int f(void){ return bad(); } // NOLINT\n", "SAFE603", True),
    ("scoped NOLINT clean SAFE603", "int f(void){ return bad(); } // NOLINT(bugprone-foo)\n", "SAFE603", False),
]


@pytest.mark.parametrize(("label", "src", "code", "fires"), _CASES, ids=[c[0] for c in _CASES])
def test_c_power_of_ten_pin(label: str, src: str, code: str, fires: bool, tmp_path: Path) -> None:
    """Each audited C behaviour holds exactly as shipped in v2.7.0."""
    sample = tmp_path / "pin.c"
    sample.write_text(src, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, _OPT_IN))
    codes = {v.code for v in engine.check_file(str(sample)).violations}
    assert (code in codes) is fires
```

Commit this as WP0 with the full validation gate green. If any case fails
at WP0 time, the repository has drifted since the audit - STOP and report;
do not adjust the expectations to match.

## Sequencing (this plan runs FIRST, ships as 2.7.1, then C++)

- Execute every WP exactly as written. This is the intended order: C++ has
  NOT shipped yet, so all counts go to **eight** languages (not nine), and
  every fidelity note in WP1 is C-only (C++ will *extend* them when it
  widens SAFE311/312/313 - that is the C++ plan's job, per its section 0.4).
- WP0 (the behavioural pin) is the load-bearing reason this runs first: it
  and the WP3b config-override tests are the regression guards that must be
  in place before C++ widens SAFE106/310/311/312/313 and the dataflow
  tracker. The C++ plan's section 0.2 assumes these already exist.
- WP4 deletes `plan/02-c.md` (C is fully closed once this plan lands). The
  C++ plan's step-0 hygiene then finds it already gone - that is expected.

## Release mechanics

- This ships as **2.7.1** (a patch: the runtime is behaviourally unchanged;
  the shipped delta is the corrected bundled skill-file docs plus new
  tests). Follow the branch flow (CLAUDE.md "Release workflow"):
  - Branch `feature/c-audit-remediation` off `development`; PR into
    `development`. **NEVER push directly to `main`** - everything reaches
    `main` via PR, no exceptions (including doc-only commits).
  - The `feature -> development` PR bumps `project.version` to **`2.7.1`**
    (a patch needs no RC round unless the owner asks; RC is the X.Y.0-minor
    convention). The later `development -> main` PR keeps it at `2.7.1`.
  - The owner controls release timing and tagging; do not tag. But DO bump
    `project.version` - leaving it at `2.7.0` is the most-missed step.
- `CHANGELOG.md` currently has no `## [Unreleased]` heading (it was renamed
  to `## [2.7.0] - 2026-07-02` at the tag). **Add a fresh `## [Unreleased]`**
  above `## [2.7.0]` and record this work under it (a `### Fixed` for the
  doc/enumeration corrections, `### Added` for the new tests is fine). It
  flips to `## [2.7.1] - <date>` only at the production tag, per
  `feedback_changelog_unreleased_marker` - do not date it yourself.

## Non-goals (do NOT do these)

1. **No behaviour changes to SAFE311 / SAFE313** (recursive-macro detection,
   typedef resolution). WP1 documents these gaps; implementing them is a
   separate future decision.
2. **No node-type literal-to-constant conversions** anywhere you touch
   (`plan/refactor-node-type-constants.md`, after C++, all languages at
   once).
3. **No per-language "enable every rule" engine smoke test** (separately
   scheduled after C AND C++ ship).
4. **Do not touch `sources_c`.** Its trimmed value
   (`["getenv", "fgets", "gets"]`) is a deliberate, review-driven divergence
   from the original spec (out-parameter readers like `scanf` / `read` /
   `recv` would taint the count variable, not the buffer) - documented in
   `src/safelint/core/config.py`, `docs/languages/c.md`, and the skill crib.

---

## WP1 - Power-of-Ten fidelity notes (docs/power-of-ten.md + rules.md)

The page's own contract: gaps are "recorded so they are recognised as
deliberate decisions, not oversights". Two paper sub-clauses SAFE311/SAFE313
do not cover are recorded nowhere; one note went stale when C shipped. Write
each note **C-only** (SAFE311/312/313 are `("c",)` at this point); the C++
work extends them to C++ later per its section 0.4.

### WP1a - Rule 8: recursive macro calls (undocumented gap)

The paper's rule 8 bans token pasting, variadic argument lists, **and
recursive macro calls**. SAFE311 detects the first two (plus the
unbalanced-replacement heuristic) but not recursion between macros.

Wording nuance to preserve: the C preprocessor does NOT re-expand a macro
inside its own expansion (the standard's "painted blue" rule), so *self*-
referential macros are inert; the paper's concern is **mutually recursive**
macro chains, which need a macro-table analysis SafeLint does not do.

1. `docs/power-of-ten.md`, "Deferred and out-of-scope" bulleted list (anchor:
   the existing bullet "**Indirect / mutual recursion** (rule 1)"): add,
   matching the list's voice:

   > - **Recursive macro calls** (rule 8, C): [SAFE311](configuration/rules.md#safe311-complex_macro)
   >   flags token pasting, `__VA_ARGS__`, and unbalanced replacements, but
   >   does not detect mutually recursive macro definitions - that needs a
   >   macro-table analysis. (Direct self-reference is inert in standard C:
   >   the preprocessor never re-expands a macro inside its own expansion.)

2. `docs/configuration/rules.md`, `### SAFE311` section: append one sentence
   to the "What it flags" paragraph: "Mutually recursive macro definitions
   (the paper's third banned construct) are not detected; that needs
   macro-table analysis."

### WP1b - Rule 9: pointer levels hidden in typedefs / macros (undocumented gap)

The paper's rule 9 also bans pointer dereferences "hidden in macro
definitions or inside typedef declarations". SAFE313 is a purely
**syntactic declarator check** with no type resolution, so this passes clean
(verified live in the audit):

```c
typedef int *intp;
void f(intp *pp) { }   /* two real levels; SAFE313 does not fire */
```

1. `docs/power-of-ten.md`, "Deferred and out-of-scope" (anchor: the
   "**Java `static final` interior mutability**" bullet, which has the same
   needs-type-resolution shape): add:

   > - **Typedef- / macro-hidden indirection** (rule 9, C):
   >   [SAFE313](configuration/rules.md#safe313-restricted_pointers) counts
   >   pointer levels syntactically in the declarator, so a level hidden
   >   behind a `typedef` (`typedef int *intp; intp *pp;`) or a macro is
   >   not seen; detecting it needs type resolution SafeLint does not do.
   >   The paper bans exactly this hiding, so paper-strict projects should
   >   also avoid pointer typedefs by convention.

2. `docs/configuration/rules.md`, `### SAFE313` section (anchor: the
   sentence ending "**expressed literally**."): qualify in the same
   paragraph: "The check is syntactic (declarator shape only): a pointer
   level hidden behind a `typedef` or a macro is not counted - the paper's
   no-hidden-dereference clause needs type resolution and is a documented
   gap."

3. `docs/languages/c.md`, SAFE313 row/section: add the same one-line caveat
   so the language page and the rules reference agree.

### WP1c - Rule 7 fidelity note is stale (C has the literal `(void)` cast)

`docs/power-of-ten.md`, "Fidelity notes from the paper", bullet "**Rule 7's
explicit-ignore escape hatch**" ends (anchor text): "Go's blank identifier
is the idiomatic form, so it is the closest of any supported language to the
paper's literal `(void)` cast." Written before C shipped; C's SAFE802
recognises the actual cast
(`tests/rules/test_dataflow_c.py::test_c_void_cast_discard_is_clean_for_safe802`).

Rewrite the ending, e.g.: "... and on C the paper's own `(void)fclose(fp)`
cast is recognised directly by SAFE802 (the cast wraps the call, so it is no
longer a bare expression statement). Among the memory-managed languages,
Go's blank identifier is the closest analogue."

## WP2 - Stale-enumeration sweep

Exact texts as verified 2026-07-02. Target count: **"Eight"** (C is the
eighth language). Prefer count-free phrasings where suggested so the next
language (C++) does not re-stale them.

1. `CONTRIBUTING.md` (~78) and its mirror `docs/contributing/index.md`
   (~82), identical sentence - anchor: "Seven languages are registered
   today (Python, JavaScript, TypeScript, Java, Rust, Go, PHP). Adding a
   new one (C, C++, etc.)". Fix the count + language list, and drop shipped
   languages from the "Adding a new one" examples ("C++, Kotlin, ..." or
   just "C++, etc." pre-C++).
2. Same two files, the contribution-types table row (~39 / ~43) - anchor:
   'A new **language** safelint can lint (e.g. C, C++, PHP)'. Make the
   examples forward-looking (drop C and PHP).
3. `docs/json-schema.md` (~9) - anchor: "All seven supported languages
   (Python, JavaScript, TypeScript, Java, Rust, Go, PHP) produce identical
   violation structures". Update count + list (C produces the same shape;
   that statement stays true).
4. `README.md`, "One hook, every language" (~222-226) - two edits:
   - anchor: "handles Python, JavaScript, TypeScript, Java, Rust, Go, and
     PHP; there's no" - add C.
   - anchor: "sets `types_or: [python, javascript, ts, tsx, java, rust, go,
     php]`" - append `c` so the quoted spec matches the real
     `.pre-commit-hooks.yaml` (which already has `c`). Verified: pre-commit's
     `identify` tags both `.c` AND `.h` with `c`, so no extra header tag is
     needed.
5. `src/safelint/skill_files/README.md` (~3) - anchor: "currently Python,
   JavaScript, TypeScript, Java, Rust, Go, and PHP (mirroring". Add C. The
   "fourteen AI clients" count is correct; leave it.
6. "all-seven core" labels - the 13-rule count is right; the "seven" label
   is stale (those 13 are shared by ALL registered languages). Four spots,
   ONE consistent replacement - use "the 13 all-language core" (count-free,
   future-proof) in all four:
   - `README.md` (~30, the Go row of the language table)
   - `docs/index.md` (~16, the docs mirror of that row)
   - `docs/configuration/rules.md` (~23, the Go paragraph: "the 13
     all-seven core")
   - `docs/languages/php.md` (~34: "the all-seven-languages set")
   NOT stale, leave alone: `docs/power-of-ten.md` "the seven memory-managed
   languages" (C is the eighth language but is not memory-managed, so "seven
   memory-managed" is still correct).
7. **Pre-existing (pre-C) staleness - separate commit, clearly labelled as
   unrelated to the C release:**
   - `src/safelint/skill_files/claude/SKILL.md` (~3) frontmatter - anchor:
     "currently Python, JavaScript, and TypeScript". Long-stale (already
     omitted Java/Rust/Go/PHP). Replace with a count-free phrasing like
     "any language registered with safelint". **First check all 14 client
     files for the same phrasing (`grep -rn "currently Python" src/safelint/skill_files/`)
     and fix every hit in one pass.** `tests/test_skill_install.py` drift
     tests must stay green.
   - `docs/contributing/adding-a-language.md` (~7) - anchor: "Today Python,
     JavaScript, and TypeScript". Same vintage; use the full current list or
     a count-based phrasing.

Post-edit sweep (zero hits expected outside `CHANGELOG.md`, which is
historical and must NOT be edited):

```bash
grep -rn "Seven languages\|seven supported languages\|all-seven\|all seven" \
  README.md CONTRIBUTING.md docs/ src/safelint/skill_files/ | grep -v CHANGELOG
grep -rn "e.g. C, C++" README.md CONTRIBUTING.md docs/
grep -rnE "types_or.*php\]" README.md docs/
grep -rn "currently Python, JavaScript, and TypeScript" docs/ src/
```

## WP3 - Test gaps (the original C spec asked for these)

### WP3a - Engine-level C suite: `tests/core/test_engine_c.py` (new file)

Every other non-Python language has one (`test_engine_go.py`,
`test_engine_javascript.py`, `test_engine_php.py`, ...); C is the only one
missing. **Read `tests/core/test_engine_go.py` first and mirror its
structure and helper style exactly.** Five behaviours, covering BOTH
extensions (C is the first two-extension language):

1. `.c` AND `.h` in `supported_extensions()`.
2. Language resolution: a `.c` file AND a `.h` file resolve to the C
   `LanguageDefinition`.
3. Clean end-to-end run: a valid C file with zero default-rule violations
   (short function, no I/O, no file-scope state, no goto).
4. `SAFE000` on unparseable input (mirror
   `test_engine_emits_safe000_on_unparseable_go`).
5. Directory discovery: a directory with one `.c`, one `.h`, and one
   non-source file discovers exactly the two C files.

### WP3b - Config-override tests for the two C-only rules with list knobs

Fires + clean shipped; the override leg is missing for the two rules that
have knobs. (SAFE311/312/313 expose no per-rule knob; their `enabled`
toggling is already full coverage.) Both knobs already pass through
`_validated_string_list` (verified in the audit:
`src/safelint/rules/c_rules.py` reads `nonlocal_jump_calls_c` and
`allocation_calls_c` through it), so ONLY tests are needed - do not touch
the rule code. Add to `tests/rules/test_c_rules.py` using its existing
`_codes` helper:

1. **SAFE106 `nonlocal_jump_calls_c`** (three cases):
   - Custom list honoured: override to `["my_longjmp_wrapper"]`; a sample
     calling `my_longjmp_wrapper(buf, 1)` fires.
   - Default entries replaced, not merged: same override; a sample calling
     `setjmp(buf)` (and containing NO goto) does not fire.
   - Scope guard: same override; a `goto` sample STILL fires - `goto` is
     structural, not list-driven. This pins the knob's scope so a future
     refactor cannot silently make goto configurable.
2. **SAFE310 `allocation_calls_c`** (two cases):
   - Override to `["my_pool_alloc"]`; `my_pool_alloc(n)` fires.
   - Same override; plain `malloc(8)` does not fire (replaced, not merged).

### WP3c - Lock SAFE106's default-on / warning contract

Default-enabled is currently only proven implicitly. Add one explicit test
(place next to similar per-rule default assertions if any exist - check
`grep -rn "severity" tests/core/ tests/rules/test_c_rules.py` for precedent
first, else put it in `tests/rules/test_c_rules.py`):

```python
def test_safe106_defaults_enabled_at_warning_severity() -> None:
    """SAFE106 ships enabled at warning severity (the C-spec maintainer decision)."""
    cfg = DEFAULTS["rules"]["nonlocal_jumps"]
    assert cfg["enabled"] is True
    assert cfg["severity"] == "warning"
```

This is a contract lock: SAFE106 is the only default-on C-only rule, and
visible-but-non-blocking at `--fail-on=error` is load-bearing for adoption.
Re-tiering it must be a conscious, test-breaking act. (The C++ plan section
0.3 requires this same lock to still hold after it widens the tuple; leaving
it here gives C++ the guard it depends on.)

## WP4 - Plan-directory hygiene

`plan/README.md`'s convention: "remove a spec file once its language ships".
C shipped in v2.7.0 and this 2.7.1 closes its last sub-tasks, so the C spec
is fully done and gets removed here.

1. **Delete `plan/02-c.md`.** Its design decisions live in the shipped docs
   (audit-confirmed); the SAFE106 maintainer-decision rationale
   (enabled/warning, `// nosafe: SAFE106` for sanctioned `goto err` chains)
   is stated in `docs/languages/c.md` - verify that before deleting.
2. **Update `plan/README.md`**: add a "C shipped in v2.7.0 (gaps closed in
   2.7.1)" blockquote next to the Go / PHP ones (8th language, 21 rules =
   16 ports + 5 C-only SAFE106/310-313, decisions in `docs/languages/c.md`
   + skill addendum + shipped code); remove BOTH the C row and this
   remediation row from the priority table; make **C++ the "1 (next)" row**
   with "Depends on: 2.7.1 remediation shipped".
3. **`plan/03-cpp.md`**: confirm its `.h` note references the SHIPPED C
   behaviour (already reworded), and that its section 0 still reads
   correctly now that its assumed guards (pin test, override tests, SAFE106
   lock) are in place - no edit expected, just a read-through.
4. **Delete THIS file** (`plan/c-audit-remediation.md`) in the final commit
   of its own PR - completed plans do not linger (same convention as
   language specs). Its row is removed from `plan/README.md` in step 2.

## Validation gate (all, in order; run per-WP where cheap, always at the end)

```bash
uv run pytest                                  # coverage >= 97, all green
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/ --all-files         # zero blocking violations
uv run mkdocs build --strict                   # WP1/WP2 touch docs; anchors must hold
```

Plus: the WP0 Lock 1 diff check (nothing under `src/safelint/` except
`skill_files/`), the WP2 sweep greps (zero non-CHANGELOG hits), the WP0 pin
test green, and `uv run pytest tests/test_skill_install.py -q` explicitly
after any skill-file edit.

## Acceptance checklist

- [ ] WP0: pin test `tests/rules/test_c_power_of_ten_pin.py` committed,
      green before AND after all other WPs; Lock 1 diff check clean.
- [ ] WP1a: recursive-macro gap in power-of-ten.md Deferred + SAFE311 section.
- [ ] WP1b: typedef-hidden-indirection gap in power-of-ten.md Deferred +
      SAFE313 section + languages/c.md; "expressed literally" qualified.
- [ ] WP1c: rule-7 fidelity note names C's literal `(void)` cast.
- [ ] WP2 items 1-6 applied (to the eight-language state); item 7 in a
      clearly separated commit; all four sweep greps clean.
- [ ] WP3a: `tests/core/test_engine_c.py` - five behaviours incl. `.h`.
- [ ] WP3b: 5 override tests (3 SAFE106 incl. the goto scope guard, 2 SAFE310).
- [ ] WP3c: SAFE106 enabled/warning contract lock.
- [ ] WP4: 02-c.md gone, README table/blockquotes correct, 03-cpp.md
      coherent, THIS file deleted and de-indexed.
- [ ] `## [Unreleased]` present in CHANGELOG.md with this work recorded.
- [ ] `project.version` bumped to `2.7.1` on the `feature -> development` PR.
- [ ] Full validation gate green; PR into `development` (never direct to main).
