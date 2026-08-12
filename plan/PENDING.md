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
- **SAFE601 `missing_assertions`: Python method-call asserts + test-only scoping**
  ✅ DONE (2.12.0). Counts assertion *method calls* (`self.assertEqual`,
  `pytest.raises`) via a configurable `assertion_calls` list (bare Python key),
  in addition to the `assert` keyword; plus `test_functions_only` scoping
  (`test_function_prefixes` + `test_dirs`) so the rule fires only on test-named
  functions in test files. Shared test-file identification extracted to
  `rules/_test_files.py`. See CHANGELOG `[Unreleased]`.
- **SAFE907 `unvalidated_request_input`: configurable validator allowlist**
  ✅ DONE (2.12.0). `request_validators` (Python, bare key) /
  `request_validators_php` lists union with the built-in validation calls, so a
  project validator (`validate_export_request`, ...) clears a read without a
  file-level ignore. See CHANGELOG `[Unreleased]`.
- **`test_coupling` (SAFE702): file-target changed-files context**  ✅ DONE
  (2.12.0). An explicit `check <file>` target now carries the repo-wide diff
  (not just the named file), and the rule gates on the source being in the
  changed set, so overlapping targets (`check pkg/ pkg/foo.py`) reach the same
  verdict as `check pkg/` and a named-but-unmodified file no longer trips
  coupling. This was Priority 4. See CHANGELOG `[Unreleased]`.

---

## Priority 1 - SAFE801 `tainted_sink`: constant-argument false positive on a tainted receiver

**Type**: correctness bugfix to the dataflow trackers (`analysis/dataflow.py`
plus the `dataflow_<lang>.py` siblings). **Surfaced by the high-effort code
review of the 2.12.0 branch (Aug 2026).** Pre-existing since the 2.11.0
receiver-taint work; not introduced by 2.12.0, so it was deferred out of that
release PR and filed here at top priority.

### Problem

The 2.11.0 method-receiver taint step makes a **method call on a tainted
receiver** fire SAFE801 even when **every argument is a constant**, so no
attacker-controlled data actually reaches the sink. The receiver being tainted
is not the same as the sink's *payload* being tainted.

Failure case: `conn = request.get_connection(); conn.execute("SELECT 1")` -
`conn` is tainted (derived from `request`; `_call_tainted` propagates receiver
taint), `execute` is a sink, so `_visit_call`'s receiver branch records a
SAFE801 hit on the receiver even though the query argument is a hard-coded
constant. The same new-hit path exists in `dataflow_go` / `dataflow_rust` /
`dataflow_javascript` / `dataflow_php` (C excludes the receiver step by design).

### Exact requirement

For a sink whose injected payload is an **argument** (SQL string, shell command,
etc.), a tainted receiver with **all-constant arguments** must NOT report - the
receiver alone conveys no user data into the sink. Decide the precise rule:
either require at least one tainted argument for argument-consuming sinks, or
restrict the receiver-only hit to sinks where the receiver itself is the
injected value. Preserve the true positives the 2.11.0 work added
(`tainted.execute(user_input)`, and receiver-as-payload cases). Per-language
tests across all six affected trackers; a regression test for the
constant-argument case.

**Relationship to Priority 3** (taint overhaul): the fix touches the same
`_call_tainted` / receiver classification the overhaul rewrites; if Priority 3
is scheduled soon, fold this in as part of 3a/3b, otherwise land it as a
standalone guard first (it is a live false positive on the opt-in rule).

Bugfix = PATCH (next `2.12.z`).

---

## Priority 2 - SAFE908 `csrf_protection_disabled`: fires on a `csrf_exempt` keyword-argument VALUE

**Type**: correctness bugfix to `csrf_protection_disabled` (SAFE908),
`framework_rules.py` `_python_exempts_csrf`. **Surfaced by the same 2.12.0
review.** Pre-existing since the 2.11.0 SAFE908 work (the 2.11.0 fix handled a
kwarg *named* `csrf_exempt`; this is the kwarg *value* case), so it was out of
scope for the 2.12.0 PR and filed here.

### Problem

`_python_exempts_csrf` excludes `csrf_exempt` only when it is a keyword-argument
**name** (`@foo(csrf_exempt=True)`). When `csrf_exempt` appears as a
keyword-argument **value** - `@register(handler=csrf_exempt)`,
`@configure(default=csrf_exempt)` - it is treated as an applied `csrf_exempt`
decorator, so SAFE908 fires a false positive claiming CSRF was disabled even
though no `@csrf_exempt` decorator was applied.

### Exact requirement

SAFE908 should fire only when `csrf_exempt` is the decorator actually being
applied - the bare form (`@csrf_exempt`), the called form (`@csrf_exempt()`),
or `method_decorator(csrf_exempt)`. Exclude `csrf_exempt` when it is a
keyword-argument value (in addition to the existing kwarg-name exclusion).
Tests: the three real decorator forms still fire; `@register(handler=csrf_exempt)`
and `@foo(csrf_exempt=True)` are both clean.

Bugfix = PATCH (next `2.12.z`).

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

