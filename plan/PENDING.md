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

## Priority 1 - Taint propagation through attribute / subscript / receiver chains

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

## Priority 2 - Framework rules `csrf_protection_disabled` + `hardcoded_secret` (9xx fast-follow)

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

## Priority 3 - Sanitiser framework for the taint tracker (Pydantic as first sanitiser)

**Type**: architectural enhancement to the taint trackers. Previously noted as a
**v3.x roadmap** item; the framework-presets work explicitly deferred it ("do
**not** build sanitiser support here"). Largest of the three and strategically
downstream of Priority 1, so last.

### Exact requirement

The trackers have **no sanitiser-clears-taint framework** beyond the flat
`sanitizers` name list. The motivating use case: a value that passes through a
validating boundary should **clear** taint. Pydantic is the natural first such
sanitiser - a value through `Model(...)` / `model_validate()` is validated, so
tainted data flowing through it could be considered clean (`parse_obj_as` /
`TypeAdapter` are safe too; `model_construct` / `construct` deliberately are
**not** - they skip validation and are already SAFE801 *sinks*). Build a general
sanitiser mechanism (not a Pydantic special-case), then register Pydantic's
validating constructors as its first consumers. Design it to compose cleanly with
the Priority 1 receiver-taint step (the sanitiser check must run *before* the
receiver-taint check, per Priority 1's risk note).
