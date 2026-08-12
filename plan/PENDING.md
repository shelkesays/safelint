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
- **SAFE801 `tainted_sink`: constant-argument receiver false positive**  ✅ DONE
  (2.12.1). A tainted receiver reaching an argument-payload sink no longer
  reports when all arguments are constant (`conn.execute("SELECT 1")`); the
  receiver is the payload only when the call has no arguments. Fixed across all
  seven trackers (Python/JS-TS/Java/Rust/Go/PHP + the C++ path in
  `dataflow_c.py`; C stays excluded) via the shared
  `_node_utils.call_has_named_arguments`; both-direction regression tests per
  tracker. Also dedups Java's receiver+argument double-report. See CHANGELOG.
- **SAFE908 `csrf_protection_disabled`: `csrf_exempt` keyword-argument value FP**
  ✅ DONE (2.12.1). `@register(handler=csrf_exempt)` (value) no longer fires;
  the guard now excludes a keyword argument on either side, while the real
  decorator forms still fire. See CHANGELOG.

---

## Priority 1 - Taint-tracker core overhaul (do 3a + 3b together)

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

