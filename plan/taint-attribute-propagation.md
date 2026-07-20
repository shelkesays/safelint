# Taint propagation through attribute / subscript / receiver chains

**Status**: deferred follow-up (surfaced by the v2.9.0 framework-presets code
review). Not a language addition; a cross-language enhancement to the
intra-procedural taint trackers. Do it as one comprehensive change across all
trackers, with per-language tests, once someone picks it up.

## Problem

Every language's intra-procedural taint tracker
(`analysis/dataflow.py` for Python and the `dataflow_<lang>.py` siblings) drops
taint at an **attribute access**, a **subscript**, and a **method call on a
tainted receiver**. Taint is only carried by:

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

### Why it matters (the review finding)

The v2.9.0 Django / Flask / FastAPI / Laravel presets extend the SAFE801
`tainted_sink` sink lists (`RawSQL`, `mark_safe`, `render_template_string`,
`HTMLResponse`, `whereRaw`, ...). But in those frameworks the tainted data
almost always arrives **behind an attribute chain on the request object**
(`request.GET["q"]`, `request.data`, `request.json`, `$request->input('x')`),
never as a bare tainted parameter passed straight to a sink. So the added sinks
are largely **inert on realistic framework code**:

```python
# framework = "django", tainted_sink enabled
def view(request):
    q = request.GET.get("q")          # taint lost here
    return Model.objects.raw(q)       # SAFE801 does NOT fire (verified)

def view2(request):
    return Model.objects.raw(request) # SAFE801 DOES fire (direct param - rare)
```

This limitation is **pre-existing and universal**, not introduced by the
presets: the Java Spring preset shares it (its e2e fixture only exercises a
*direct* `@RequestParam` parameter, `jdbc.query("... " + name)`, never
`request.getParameter("x")`). It bites the Python/PHP web presets harder because
their idiomatic taint entry *is* the attribute chain. The v2.9.0 docs were
corrected to state the limitation honestly rather than overclaim injection
coverage; this spec is the real fix.

## Proposed approach

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

## Risks and open decisions

- **Broadening taint surfaces new violations on existing users' code** that has
  `tainted_sink` enabled: e.g. `subprocess.run(config.path)` where `config` is a
  tainted parameter now flows to the sink. That may be a true positive or a
  false one depending on the project. Because it can newly flag previously-clean
  code, decide up front:
  - ship it **on by default** as a MINOR with a loud CHANGELOG note (more
    findings is the point), **or**
  - gate it behind a per-rule config knob (e.g.
    `[tool.safelint.rules.tainted_sink] follow_receiver_taint = true`) defaulting
    off, so adopters opt in. Recommended: gate the *method-call-on-tainted-
    receiver* step (item 3, the noisy one) behind the flag, but ship the plain
    attribute/subscript propagation (items 1-2) on by default - those are
    unambiguous projections of tainted data.
- **Sanitisers must still clear.** `escape(request.GET["q"])` etc. must remain
  clean; verify the sanitiser check runs before the receiver-taint check.
- **Cross-language parity.** Land all trackers together with matched tests, or
  the `test_engine.py` per-language expectations and the language docs drift.
- **Add framework e2e coverage** once it works: extend
  `tests/integration/test_framework_presets_e2e.py` with a
  `request.<attr>` -> sink SAFE801 assertion per framework (currently the suite
  only asserts SAFE905/906/907, precisely because the taint path was inert).

## Payoff

Turns the framework presets' (and Spring's, and the JS runtime presets') SAFE801
sink extensions into real request-chain injection detection, which is the
headline value users expect from a "framework preset". Until then, the concrete
working value of the presets is the SAFE905-907 structural rules plus the
direct-flow sink coverage.
