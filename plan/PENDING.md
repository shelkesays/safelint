# Pending work (single backlog, priority order)

**This is the one consolidated backlog for safelint.** Every open item lives
here, highest priority first. When an item is picked up, land it as its own
comprehensive change following the standing references (read these first):

- `docs/contributing/adding-a-language.md` - the tracked human walkthrough,
  including its "Adding a framework / runtime preset" section.
- `.claude/skills/add-language-support/SKILL.md` - the enforcement checklist
  (Parts A, B, C).
- `CLAUDE.md` - hard constraints, commands, the "Adding a new rule" checklist,
  and the release-branch flow (the version bump is the most-missed step).

The non-negotiables digest, the Tree-sitter probing convention, the Go-port
pitfalls, and the validation gate that used to live in `plan/README.md` all
still apply - see that file (retained) for the full text. **Do not trust counts
written below; re-verify rule codes with `uv run safelint list-rules` and run
the stale-count / enumeration sweep at implementation time.**

Validation gate for every item here (run all, in order):

```bash
uv run pytest                                  # coverage gate fail_under = 97
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run ty check src/ scripts/
uv run safelint check src/ scripts/ tests/ --all-files --fail-on=warning  # zero blocking
uv run mkdocs build --strict                   # broken anchors fail the build
```

---

## Shipped (no longer pending)

- **Taint propagation through attribute / subscript / receiver chains**  ✅ DONE
  (2.11.0). Cross-language taint-projection parity. An empirical per-language
  audit showed Java/Rust/Go/PHP/C already propagated through attribute /
  subscript projections and Java/Rust/Go/PHP already followed the method
  receiver (via the existing `assume_taint_preserving = true` default); the real
  gaps were Python (all three steps), JS/TS and C++ (receiver step only). Closed
  under the *existing* knob - no new config flag. Per-language tests + a Django
  request-chain -> sink e2e + docs landed. See CHANGELOG `[2.11.0]` "Changed".
- **Framework rules `csrf_protection_disabled` + `hardcoded_secret`**  ✅ DONE
  (2.11.0). SAFE908 (Django `@csrf_exempt` / Laravel non-empty `$except`) and
  SAFE909 (Django `SECRET_KEY` / Flask `app.secret_key` literal / Laravel
  `base64:` `APP_KEY`) landed as `("python","php")` 9xx rules, disabled by
  default and enabled by the presets that scope them. Per-rule tests, both-form
  config docs, language pages, all 14 skill files, CHANGELOG. Post-release
  false-positive fixes (a kwarg *named* `csrf_exempt`; an empty prefixed literal
  `r""` / `f""`) also shipped in 2.11.0. See CHANGELOG `[2.11.0]`.

---

## Priority 1 - SAFE601 `missing_assertions`: recognise Python method-call asserts

**Type**: config + rule enhancement to `missing_assertions` (SAFE601), Python
detector. **Surfaced by the optimus-secure-fdn Django config review** (Aug 2026):
a real project had to blanket-ignore SAFE601 across its whole audit app because
the rule flagged ~281 of ~300 functions - all noise. Prioritised **above the
taint overhaul** by owner decision: it removes a systemic false-positive class
that forces blanket ignores in every Python unittest / Django codebase (a
headline safelint audience), and it is small and self-contained.

### Problem

On Python, SAFE601 only recognises the `assert` **keyword**. unittest /
Django `TestCase` tests assert via **method calls** (`self.assertEqual(...)`,
`self.assertTrue(...)`, `self.assertRaises(...)`), which the rule cannot see, so
every unittest-style test reads as assertion-less. Every *other* language already
has an `assertion_calls_<lang>` config list (JS / Java / Rust / PHP / C / C++);
**Python has none** - only the bare-keyword path. So the only recourse is a
file-wide ignore, which also hides genuinely under-asserted production code.

### Exact requirement

- Add a Python assertion-call list to `DEFAULTS["rules"]["missing_assertions"]`.
  Match the Python-uses-bare-key convention the other rules follow (Python =
  bare key, others suffixed) - check the sibling rules before picking
  `assertion_calls` vs `assertion_calls_python`. Seed it with the unittest /
  pytest surface: `assertEqual, assertNotEqual, assertTrue, assertFalse,
  assertIs, assertIsNot, assertIsNone, assertIsNotNone, assertIn, assertNotIn,
  assertRaises, assertRaisesRegex, assertWarns, assertAlmostEqual, assertGreater,
  assertGreaterEqual, assertLess, assertLessEqual, assertListEqual,
  assertDictEqual, assertSetEqual, assertCountEqual, assertRegex, assertItemsEqual,
  fail` plus pytest's `raises` / `warns` where the receiver is detectable.
- The Python detector must count a matching **method call** (resolve via
  `call_name`, so `self.assertEqual(...)` and `pytest.raises(...)` both match) as
  an assertion, in addition to the `assert` keyword it already counts. Keep the
  walk iterative (SAFE105) and skip nested function defs (the standard
  per-function-metric pattern).
- Follow the "Adding a new rule" config discipline for the new key: validate via
  `_validated_string_list`, document in **both TOML forms** in
  `docs/configuration/rules.md`, update the Python language page / skill-file
  crib if they enumerate the rule's config surface.
- Tests: a unittest-style test whose only assertions are `self.assertEqual(...)`
  is no longer flagged; a genuinely assertion-less test still fires; the bare
  `assert` keyword path is unchanged; a mistyped scalar for the new list warns
  (typo guard) rather than silently disabling matching.

Additive = MINOR.

---

## Priority 2 - SAFE907 `unvalidated_request_input`: a validator / allowlist knob

**Type**: rule enhancement to `unvalidated_request_input` (SAFE907), Python + PHP.
**Also surfaced by the optimus-secure-fdn review**: SAFE907 has **no config knob
at all**, so a project that validates request input with hand-rolled functions
(`validate_export_request()`, an allowlist filter builder) can only silence it
with a **file-level ignore** - which then hides any genuinely-unvalidated read
elsewhere in that file. Same false-positive-forces-blanket-ignore problem as
Priority 1, hence paired with it ahead of the taint overhaul.

### Problem

SAFE907 fires on reading request input (`request.GET` / `request.POST` /
`request.body`; PHP superglobals) and recognises only schema libraries as
validation. Real Django / Laravel apps validate through project-specific
functions the rule cannot see, so the accurate-and-strict posture users want is
impossible without disabling the rule for whole files.

### Exact requirement

Give the rule a precision lever, one of:

- **(a) Minimal, standalone**: a configurable list of **validator call names**
  (e.g. `validators` / `request_validators_python` / `_php`); a request read that
  flows through a named validator in the same scope no longer fires. Matches the
  exact-call-name mechanism `tainted_sink.sanitizers` already uses. Validate via
  `_validated_string_list`; both-TOML-form docs; tests (validated read clean,
  unvalidated read still fires, unknown name warns).
- **(b) Principled, ties into Priority 3**: integrate SAFE907 with the
  property-typed sanitiser framework (P3/3a) - a validator registered as a
  sanitiser establishing a `schema_validated` / `allowlisted` property clears the
  "unvalidated input" concern but NOT injection sinks. Prefer (b) if it can ride
  on 3a; sequence it as part of / immediately after that work. (a) is independent
  and can land first if 907 is wanted before the overhaul.

Additive = MINOR.

---

## Priority 3 - Taint-tracker core overhaul (do 3a + 3b together)

**Type**: architectural enhancement to the taint trackers. Two sub-items,
strategically downstream of the shipped 2.11.0 taint-projection parity work:

- **3a - Property-typed sanitiser framework** (Pydantic as first sanitiser).
  A v3.x-roadmap item the framework-presets work explicitly deferred.
  **Independently re-flagged by CodeRabbit on PR #133** (the `escape()`-clears-
  `RawSQL` false negative), which corroborates the need.
- **3b - Convert the trackers to a single iterative worklist** (eliminate the
  `_is_tainted` -> `_call_tainted` -> `_is_tainted` mutual recursion). Raised by
  CodeRabbit on PR #133 (`dataflow_javascript.py`). See "3b" below.

**Which trackers each item touches** - there are **seven** trackers: `dataflow.py`
(Python) plus the **six** `dataflow_<lang>.py` siblings (c, go, java, javascript,
php, rust):

- **3a** rewrites the sanitiser-clearing logic in **all seven** - the
  `_call_tainted` classification in the six non-C trackers, and the
  `_classify_call` step in `dataflow_c.py`.
- **3b** rewrites only the **six non-C trackers** (Python + go/java/javascript/
  php/rust) to remove the mutual recursion. `dataflow_c.py` is **excluded**: it is
  **already** in the target shape - its `_taint_step` reduces each worklist node
  to `(is_tainted_here, children)` and its `_classify_call` returns argument /
  receiver nodes as children rather than re-entering `_is_tainted` - so it is the
  **reference exemplar** for 3b, not something 3b changes.

So the **single-pass requirement applies to the six non-C trackers**, which both
items rewrite; `dataflow_c.py` is touched by **3a only** (its `_classify_call`
sanitiser step). Largest item in this backlog. The two PR #133 review threads
(sanitiser-property, recursive-descent) are left **open** as the tracking anchors
for 3a / 3b.

### 3a - Exact requirement

The trackers have **no sanitiser-clears-taint framework** beyond the flat
`sanitizers` name list, which clears taint unconditionally for every sink.

**Do not model validation as universal sanitisation.** Passing attacker-
controlled data through a validating boundary establishes only the *specific*
safety property that validation enforces - it does **not** make the value safe
for every sink. Pydantic is the clearest example: `Model(...)` /
`model_validate()` enforce **type / schema** (so they legitimately clear the
mass-assignment and type-confusion concerns), but a Pydantic-validated `str` is
still fully injectable into a SQL / shell / template sink. Treating "went through
`Model(...)`" as blanket taint-clearing would therefore create **false
negatives**, silently suppressing real injection findings.

The requirement is a **property-typed sanitiser mechanism**, not a flat clear:

- A sanitiser declares **which safety property it establishes** (e.g.
  `sql_escaped`, `html_escaped`, `shell_quoted`, `schema_validated`), and each
  sink declares **which property it requires**. Taint is cleared for a given sink
  only when a sanitiser on the path satisfies **that sink's** required property;
  otherwise the flow stays tainted. Contracts are **per sink / context**, never
  global.
- Register Pydantic's validating constructors (`Model(...)` /
  `model_validate()` / `parse_obj_as` / `TypeAdapter`) as providers of the
  **schema-validation** property only - so they clear taint for schema-shaped
  concerns but leave string-injection sinks tainted.
- `model_construct` / `construct` stay **SAFE801 sinks** (they skip validation
  and establish no property); a sanitiser must never be inferred from them.
- Preserve **sanitiser-before-receiver-taint ordering**: the sanitiser check must
  run *before* the shipped 2.11.0 receiver-taint step, so an explicit sanitiser
  on a tainted receiver still clears (for the properties it covers) rather than
  being re-tainted.
- Migrate the existing flat `sanitizers` list into this model as a compatibility
  default (a bare name clears the sink's required property for backward
  compatibility) so no current config silently changes meaning.

### 3b - Convert the trackers to a single iterative worklist

**Problem**: in `dataflow.py` and the `dataflow_<lang>.py` siblings (all except
`dataflow_c.py`), `_is_tainted` is an iterative worklist, but it calls
`_node_directly_tainted` -> `_call_tainted`, and `_call_tainted` re-enters
`_is_tainted` for every argument **and** (since the v2.11.0 receiver work) every
method receiver. That is a mutual recursion whose depth grows with call /
method-chain nesting (`f(g(h(...)))`, `a().b().c()...`). It is pre-existing (the
argument path always did this) and stays within safelint's own SAFE105 (which
polices *direct* self-recursion; this is mutual), but it violates the project
guideline that **all tree-walking in the analysis modules must be iterative
worklists, never recursive**, and a pathologically deep input could grow the
Python stack.

**Exact requirement**: `dataflow_c.py` already models the correct shape - its
`_taint_step(node) -> (is_tainted_here, children_to_examine)` reduces each
worklist node without re-entering `_is_tainted`; sources return `(True, [])`,
sanitisers `(False, [])`, and unknown calls return their argument / receiver
nodes as children for the *same* worklist to drain. Refactor the other six
trackers to that single-worklist model: fold the `_call_tainted` classification
into the worklist step so a call's arguments and receiver are pushed as children
rather than recursed into. Behaviour must be preserved exactly (same sink hits on
the existing per-language test suites); this is a structural refactor, not a
detection change. Do it in the **same pass** as 3a, since 3a also rewrites the
sanitiser handling inside these same methods (a sanitiser must short-circuit the
worklist step with `(False, [])`, matching `dataflow_c.py`).

---

## Priority 4 - file / overlapping `check` targets: changed-files context

**Type**: small correctness fix in the multi-path CLI (`cli.py`), narrow but real.
Originally surfaced by the high-effort code review of the v2.11.0 branch, and
re-raised by Copilot on PR #135.

**Update (2.11.0)**: the *standalone* half was fixed - `safelint check <file>`
now returns the named file as its own changed set (commit `2d55abd`,
"fix(cli): `check <file>` is diff-aware like `safelint <file>`"), so a single
named file runs `test_coupling` consistently with the pre-commit `safelint
<file>` invocation. The **overlapping-targets** half is still open, and the fix
**flipped its direction**: because a file target now carries a *single-file*
changed set (just that file), not the repo-wide diff, an overlapping run can now
**false-positive**.

**Remaining problem**: overlapping targets dedup **most-specific-first**, so a
file reached via both `pkg/` and `pkg/foo.py` keeps the *file* target's result,
whose changed set is `[foo.py]` alone. `test_coupling` then fires on `foo.py`
even when the user *did* update `pkg/foo.py`'s test in the same commit (the test
is in the repo-wide diff but not in the single-file set), whereas `safelint check
pkg/` alone stays quiet. Verified: with both `pkg/foo.py` and `tests/test_foo.py`
modified, `check pkg/` exits 0 (clean) but `check pkg/ pkg/foo.py` exits 1
(fires). Pre-2.11.0 the divergence was the opposite - the file target was inert,
so the finding was silently **dropped**; now it is spuriously **added**.

**The design decision this needs (do not skip):** the 2.11.0 standalone fix and
the overlap fix pull in different directions. Making standalone `check <file>`
behave like the pre-commit hook means "the named file *is* the change set"
(`changed_files = [foo.py]`); making overlap consistent means "the run has one
repo-wide change set, regardless of how a file is named" (`changed_files =
repo-wide diff`). Pick one coherent model. **Recommended end-state**: compute
the repo-wide changed-files list once per run (git-modified mode) and hand it to
**every** target's `run(...)` as `changed_files`, keeping the named file(s) as
`files`. That makes the deduped result identical regardless of overlap AND is
strictly more correct (a named-but-unmodified file stops tripping `test_coupling`
because it is genuinely not in the diff). Note this **supersedes the 2.11.0
`[foo.py]`-as-changed-set choice**: standalone `check foo.py` on an *unmodified*
file would then no longer fire `test_coupling` (correct - it wasn't changed),
diverging from the positional `safelint foo.py` hook contract, which is
acceptable because `check` is git-aware while the hook asserts "these are my
staged files". Update the 2.11.0 unit tests
(`test_resolve_check_targets_file_target_is_its_own_changed_set`) accordingly.

**Why still deferred**: gated to an opt-in rule (`test_coupling`) in an unusual
overlapping invocation; the clean fix touches target-resolution core and adds a
git call for file targets.

**Exact requirement**: make a file's changed-files context independent of how it
is named, per the recommended end-state above. Add a regression test asserting
`check pkg/ pkg/foo.py` and `check pkg/` produce the same `test_coupling` result
for `foo.py` - both clean when the test was updated in the same diff, both firing
when it was not.
