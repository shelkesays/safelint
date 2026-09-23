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
  `_node_utils.call_has_arguments`; both-direction regression tests per
  tracker. Also dedups Java's receiver+argument double-report. See CHANGELOG.
- **SAFE908 `csrf_protection_disabled`: `csrf_exempt` keyword-argument value FP**
  ✅ DONE (2.12.1). `@register(handler=csrf_exempt)` (value) no longer fires;
  the guard now excludes a keyword argument on either side, while the real
  decorator forms still fire. See CHANGELOG.
- **Taint-tracker core overhaul (3a property-typed sanitisers + 3b single
  worklist)**  ✅ DONE (2.13.0). Was Priority 1. **3a**: SAFE801 sanitisers now
  declare which safety property they establish (`sanitizer_properties`) and sinks
  which they require (`sink_properties`); a property-typed sanitiser clears a sink
  only when it satisfies that sink's required property, and the clear is
  path-sensitive (survives an intermediate variable and closure capture) via
  property-labelled taint (`tainted` maps each variable to the properties it is
  safe for). Opt-in and backward compatible - both tables ship empty and the flat
  `sanitizers` list stays universal. Fixes the `escape()`-clears-`RawSQL` false
  negative CodeRabbit re-flagged on PR #133. **3b**: the six non-C trackers were
  converted from the `_is_tainted` ↔ `_call_tainted` mutual recursion to the
  single-worklist `_taint_step` / `_classify_call` shape (matching `dataflow_c.py`);
  behaviour-preserving. Property-labelled helpers live in
  `analysis/_taint_contract.py`. Per-language regression tests (assignment + closure
  capture), config docs in both TOML forms. The two PR #133 tracking threads
  (sanitiser-property, recursive-descent) are the anchors for this item. See
  CHANGELOG `[Unreleased]` (Added / Changed).

---

## Open work

**None currently.** The taint-tracker core overhaul - the last open backlog item -
shipped in 2.13.0 (see Shipped above). No language addition is planned (see
[`README.md`](README.md)). When new work is scoped, add a prioritised section here
(and a self-contained spec file for anything large, per the convention).

<!-- Retired specs whose work has shipped are removed on completion; their design
decisions live in the referenced CHANGELOG entries and the shipped code. -->
