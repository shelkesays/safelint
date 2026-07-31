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

## Priority 1 - Taint propagation through attribute / subscript / receiver chains  ✅ IMPLEMENTED (2.11.0rc1)

**Status**: done, shipping in 2.11.0. **The spec below was substantially stale**:
an empirical per-language audit (run the SAFE801 rule on `request.<attr>` -> sink
snippets) showed Java, Rust, Go, PHP, and C **already** propagated taint through
attribute / subscript projections, and Java / Rust / Go / PHP **already** checked
the method receiver (via the existing `assume_taint_preserving = true` default).
The real gaps were narrow: **Python** (no attribute/subscript, no receiver),
**JavaScript / TypeScript** (had attribute/subscript, no receiver), and **C++**
(had attribute/subscript, no receiver). Those three were brought up to parity
under the *existing* `assume_taint_preserving` knob - **no new config knob** was
added (the spec's proposed `follow_receiver_taint` flag would have contradicted
the 4 languages that already do receiver-taint unconditionally). Per-language
tests, a Django request-chain -> sink e2e, and docs landed with it. Original spec
retained below for context.

**Type**: cross-language enhancement to the intra-procedural taint trackers (not
a language addition). Do it as **one comprehensive change across all trackers**,
with per-language tests.

**Why it is #1**: it is fully specified and ready to implement, and it is the
change that turns the **already-shipped** v2.9.0 framework presets' (and Spring's,
and the JS-runtime presets') SAFE801 sink extensions into real request-chain
injection detection - the headline value users expect from a "framework preset".
Until it lands, those added sinks are largely inert on idiomatic web-framework
code, and the concrete working value of the presets is only the SAFE905-907
structural rules plus direct-flow sink coverage.

### Problem

Every language's intra-procedural taint tracker (`analysis/dataflow.py` for
Python and the `dataflow_<lang>.py` siblings) drops taint at an **attribute
access**, a **subscript**, and a **method call on a tainted receiver**. Taint is
only carried by:

- a tainted *identifier* (a seeded function parameter, or a variable assigned
  from a tainted expression), and
- a *call* whose callee name is in the `sources` list, or (under
  `assume_taint_preserving`) whose *arguments* are tainted.

It does **not** propagate from a tainted base outward through a projection. So
for `request` seeded tainted:

- `request.GET` (attribute) is treated as clean;
- `request.GET["q"]` (subscript) is clean;
- `request.GET.get("q")` (method call on a tainted receiver) is clean - the
  callee `get` is neither a source nor a sanitiser, and its *argument* `"q"` is
  a constant.

In those frameworks the tainted data almost always arrives **behind an attribute
chain on the request object** (`request.GET["q"]`, `request.data`,
`request.json`, `$request->input('x')`), never as a bare tainted parameter
passed straight to a sink:

```python
# framework = "django", tainted_sink enabled
def view(request):
    q = request.GET.get("q")          # taint lost here
    return Model.objects.raw(q)       # SAFE801 does NOT fire (verified)

def view2(request):
    return Model.objects.raw(request) # SAFE801 DOES fire (direct param - rare)
```

This limitation is **pre-existing and universal**, not introduced by the presets:
the Java Spring preset shares it (its e2e fixture only exercises a *direct*
`@RequestParam`, `jdbc.query("... " + name)`, never `request.getParameter("x")`).
It bites the Python/PHP web presets harder because their idiomatic taint entry
*is* the attribute chain. The v2.9.0 docs were corrected to state the limitation
honestly rather than overclaim injection coverage; this item is the real fix.

### Exact requirement

In each tracker, make taint **sticky through projections of a tainted base**:

1. **Attribute access** (`obj.attr`): propagate taint from the object child.
   In `dataflow.py` this is adding the `attribute` node to
   `_taint_propagating_children` (return its object/first named child).
2. **Subscript** (`obj[k]`): propagate taint from the object child (not the
   index).
3. **Method call on a tainted receiver** (`obj.method(...)`): treat the call
   result as tainted when the *receiver* is tainted, **unless** the callee is in
   `sanitizers`. This is the important and riskiest one - it is what makes
   `request.GET.get("q")` tainted. Extend `_call_tainted` to also test the
   receiver (the object of the callee attribute), not just the callee name and
   the arguments.

Each of the six trackers (`dataflow.py`, `dataflow_javascript.py`,
`dataflow_java.py`, `dataflow_rust.py`, `dataflow_go.py`, plus the PHP path)
needs the language-appropriate node types (`attribute` / `member_expression` /
`field_access` / `field_expression` / `subscript` / `member_access_expression`,
etc.). Probe each grammar; do not assume node names. Keep every walk iterative
(SAFE105 polices safelint's own source).

### Risks and open decisions

- **Broadening taint surfaces new violations on existing users' code** that has
  `tainted_sink` enabled: e.g. `subprocess.run(config.path)` where `config` is a
  tainted parameter now flows to the sink. That may be a true or false positive
  depending on the project. Because it can newly flag previously-clean code,
  decide up front:
  - ship it **on by default** as a MINOR with a loud CHANGELOG note (more
    findings is the point), **or**
  - gate it behind a per-rule config knob (e.g.
    `[tool.safelint.rules.tainted_sink] follow_receiver_taint = true`) defaulting
    off, so adopters opt in. **Recommended**: gate the *method-call-on-tainted-
    receiver* step (item 3, the noisy one) behind the flag, but ship the plain
    attribute/subscript propagation (items 1-2) on by default - those are
    unambiguous projections of tainted data.
- **Sanitisers must still clear.** `escape(request.GET["q"])` etc. must remain
  clean; verify the sanitiser check runs before the receiver-taint check.
- **Cross-language parity.** Land all trackers together with matched tests, or
  the `test_engine.py` per-language expectations and the language docs drift.
- **Add framework e2e coverage** once it works: extend
  `tests/integration/test_framework_presets_e2e.py` with a `request.<attr>` ->
  sink SAFE801 assertion per framework (the suite currently only asserts
  SAFE905/906/907, precisely because the taint path was inert).

---

## Priority 2 - Framework rules `csrf_protection_disabled` + `hardcoded_secret` (9xx fast-follow)  ✅ IMPLEMENTED (2.11.0rc1)

**Status**: done, shipping in 2.11.0 alongside Priority 1. SAFE908
`csrf_protection_disabled` (Django `@csrf_exempt` / Laravel non-empty `$except`)
and SAFE909 `hardcoded_secret` (Django `SECRET_KEY` / Flask `app.secret_key`
literal / Laravel `base64:` `APP_KEY`) landed as `("python","php")`-scoped 9xx
rules, disabled by default and enabled by the presets that scope them (Django +
Laravel for both; Flask also enables SAFE909; FastAPI neither). Per-rule tests,
both-form config docs, language pages, all 14 skill files, and the CHANGELOG
Added entry all landed. Original spec retained below for context.

**Type**: two new framework-specific structural rules (9xx band), enabled by the
existing Python/PHP framework presets. **Deferred from the v2.9.0 first cut** by
owner decision (SAFE905-907 only); "list them as a fast-follow, revisit only if
demand appears." Demand-gated, so below the taint work.

### Exact requirement

- **`csrf_protection_disabled`** - a CSRF guard explicitly turned off:
  Django `@csrf_exempt`, Laravel `VerifyCsrfToken::$except`.
- **`hardcoded_secret`** - a secret key as a source literal: Django `SECRET_KEY`,
  Flask `secret_key`, Laravel `APP_KEY` literals.

Both are real but **more false-positive-prone** (test settings, example configs)
and lower-frequency than SAFE905-907, so they were intentionally left out of the
first cut. Slot each into the **9xx band** (framework-specific only), disabled by
default and enabled by the relevant preset, following the full "Adding a new
rule" checklist in `CLAUDE.md` (registry, defaults, order list, tests both
violation + clean per language, `docs/configuration/rules.md`, the language
pages, and **all 14 client skill files** - the rule drift test enforces the last).
Re-verify the chosen 9xx codes are free with `uv run safelint list-rules` at
implementation time.

---

## Priority 3 - Taint-tracker core overhaul (do 3a + 3b together)

**Type**: architectural enhancement to the taint trackers. Two sub-items,
strategically downstream of Priority 1 (which is now shipped):

- **3a - Property-typed sanitiser framework** (Pydantic as first sanitiser).
  Previously the standalone Priority 3; a v3.x-roadmap item the framework-presets
  work explicitly deferred. **Independently re-flagged by CodeRabbit on PR #133**
  (the `escape()`-clears-`RawSQL` false negative), which corroborates the need.
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
  run *before* the Priority 1 receiver-taint step, so an explicit sanitiser on a
  tainted receiver still clears (for the properties it covers) rather than being
  re-tainted.
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

## Priority 4 - Overlapping file + dir `check` targets drop the changed-files context

**Type**: small correctness fix in the multi-path CLI (`cli.py`), narrow but real.
Surfaced by the high-effort code review of the v2.11.0 branch.

**Problem**: a file target returns `changed_files=None` from
`_resolve_check_targets` (only directory targets in git-modified mode carry the
repo-wide diff). Overlapping targets dedup **most-specific-first**, so a file
reached via both `pkg/` and `pkg/foo.py` keeps the *file* target's result, whose
`changed_files` is `None`. Any rule that needs the repo-wide changed-files
context - notably `test_coupling` (SAFE7xx) - therefore behaves differently
depending on whether the file is *also* named explicitly: `safelint check pkg/`
flags `foo.py` (modified without its test), but `safelint check pkg/ pkg/foo.py`
silently drops that finding.

**Why deferred, not fixed in v2.11.0**: it is pre-existing (shipped with the
2.10.0 multi-path feature), gated to an opt-in rule (`test_coupling`) in an
unusual invocation, and the clean fix touches the target-resolution core
(threading the repo-wide `changed_files` to file / explicit targets too) - which
also changes single-file-run semantics (`check foo.py` would start running
`test_coupling`) and adds a git call per file target. That deserves its own
focused change with tests, not a rushed edit in the taint branch.

**Exact requirement**: make a file's changed-files context independent of how it
is named. Simplest approach: compute the repo-wide changed-files list once per
run (in git-modified mode) and hand it to **every** target's `run(...)`
(directory and file alike), so the deduped result is identical regardless of
overlap. Add a regression test asserting `check pkg/ pkg/foo.py` and
`check pkg/` produce the same `test_coupling` result for `foo.py`.
