# Taint-tracker core overhaul (Priority 1: 3a + 3b)

**Status**: in progress on `feature/taint-tracker-overhaul` (off 2.12.1).

This is the self-contained spec for the single Priority-1 backlog item in
[`PENDING.md`](PENDING.md). Read the requirement text there first; this file is
the design + increment plan grounding the implementation. **3a and 3b are done
together** because both rewrite the same call-classification methods in the six
non-C trackers.

Standing references (read before coding): `CLAUDE.md` (hard constraints, the
"Adding a new rule" checklist, the release-branch flow), and the validation gate
at the top of `PENDING.md`. SafeLint must pass itself; all analysis tree-walking
stays iterative (SAFE105 forbids recursion in the codebase).

---

## Goals

- **3a - property-typed sanitisers.** Replace the flat "a sanitiser clears taint
  for every sink" model with a per-property contract: a sanitiser establishes a
  named safety **property** (`sql_escaped`, `html_escaped`, `shell_quoted`,
  `schema_validated`, ...); a sink requires a property; taint clears at that sink
  only when a sanitiser on the path satisfies **that sink's** required property.
  Pydantic's validating constructors establish **schema-validation only**, so
  they no longer blanket-clear string-injection sinks (the `escape()`-clears-
  `RawSQL` class of false negative CodeRabbit flagged on PR #133).
- **3b - single iterative worklist.** Remove the `_is_tainted` -> `_call_tainted`
  -> `_is_tainted` mutual recursion in the six non-C trackers; fold call
  classification into one worklist step that returns `(is_tainted_here,
  children_to_examine)` per node, matching `dataflow_c.py`.

**Non-goal / hard constraint**: no behaviour change for existing configs. The
flat `sanitizers` list must keep clearing taint exactly as today (see
Backward-compatibility below). The property mechanism is **opt-in**.

---

## The property-typed sanitiser model (3a)

Precise rules (from `PENDING.md`, do not weaken):

- A **sanitiser** declares which safety property (or properties) it establishes.
- A **sink** declares which property it requires. A sink with **no** declared
  property keeps today's behaviour: any flat/legacy sanitiser clears it.
- Taint clears for a given sink **only** when a sanitiser on the path satisfies
  **that sink's** required property. Contracts are per sink / context, never a
  single global "cleared" flag.
- Register Pydantic's validating constructors (`Model(...)`, `model_validate`,
  `parse_obj_as`, `TypeAdapter`) as providers of the **schema-validation**
  property **only** - they clear schema-shaped concerns but leave SQL / shell /
  template sinks tainted.
- `model_construct` / `construct` stay **SAFE801 sinks** (they skip validation
  and establish no property); never infer a sanitiser from them.
- **Ordering**: the sanitiser check runs **before** the 2.11.0 receiver-taint
  step, so an explicit sanitiser on a tainted receiver still clears (for the
  properties it covers) rather than being re-tainted.

### Backward-compatibility (must-hold)

- The existing flat `sanitizers` / `sanitizers_<lang>` list migrates into the new
  model as a **universal** provider: a bare sanitiser name clears **any** sink's
  required property (today's meaning). No current config changes meaning.
- Sinks keep working with no property declared (they fall back to "any sanitiser
  clears"). The property contract only tightens a sink once that sink is given a
  required property AND a property-typed sanitiser is configured.

### Config schema (opt-in additions)

> Finalise against the architecture map before writing `config.py`. Draft shape:

- `sanitizer_properties` (bare Python key; `sanitizer_properties_<lang>` per
  language): table mapping sanitiser name -> list of property strings it
  establishes. Example: `escape = ["html_escaped"]`, `Model = ["schema_validated"]`.
- `sink_properties` / `sink_properties_<lang>`: table mapping sink name ->
  required property string. Example: `execute = "sql_escaped"`,
  `render = "html_escaped"`.
- Both validated (unknown-shape guard) via the existing config-validation
  helpers; both default to empty (so the shipped default behaviour is unchanged
  until a user opts in). Ship a documented Pydantic example.

TODO: confirm exact key names and whether properties attach per-sink inline vs.
in a separate table, once the current `sinks`/`sanitizers` plumbing is mapped.

---

## The single-worklist shape (3b)

Target: each of the six non-C trackers gets a `_taint_step(node) ->
(is_tainted_here, children_to_examine)` reducer drained by one worklist in
`_is_tainted`, exactly like `dataflow_c.py`:

- a source node -> `(True, [])`
- a sanitiser call (for the property the current sink requires) -> `(False, [])`
- an unknown call under `assume_taint_preserving = true` -> `(False, <arg /
  receiver nodes as children>)` so the same worklist drains them, never
  re-entering `_is_tainted`
- everything else -> `(False, <taint-propagating children>)`

`dataflow_c.py` is the **reference exemplar** and is **not** rewritten by 3b; it
receives the 3a sanitiser-property change only (its `_classify_call` step).

Behaviour must be preserved exactly on the existing per-language suites; 3b is a
structural refactor, not a detection change. The property check from 3a is what
the worklist step consults to decide the sanitiser `(False, [])` short-circuit.

---

## The load-bearing design decision (from the architecture map)

Today taint is a **plain boolean** independent of the sink: `_is_tainted(node)
-> bool`, and a sanitiser clears **unconditionally** (`if name in
self.sanitizers: return False`). 3a makes clearing depend on **which property
the target sink requires**, so taint becomes "tainted **with respect to** a
required property". Concretely:

- `_is_tainted` gains a `required_property: str | None` argument, threaded down to
  the worklist step so the sanitiser branch can decide per-property.
- `_visit_call` resolves each sink's required property (from `sink_properties`,
  else `None`) and passes it when testing its arguments/receiver for taint.
- **Clearing decision** for a sanitiser call named `S` at a sink requiring `P`:
  - `S` in the flat `sanitizers` list (legacy/universal) -> clears (any `P`).
    [backward-compat: today every sanitiser clears every sink]
  - else `S` in `sanitizer_properties` and (`P is None` or `P` in its property
    set) -> clears. (`P is None` = sink declared no property -> any listed
    sanitiser clears, today's behaviour.)
  - else -> does not clear.
- Default `sanitizer_properties` ships Pydantic constructors (`Model` /
  `model_validate` / `parse_obj_as` / `TypeAdapter`) -> `{schema_validated}`
  only. No shipped SAFE801 sink requires `schema_validated`, so by default they
  clear nothing for injection sinks (correct - a schema-validated string is
  still injectable), and a user who declares a `schema_validated`-requiring sink
  gets them recognised without adding them to the universal flat list.
- The shipped flat lists stay **universal** (so `escape` still clears every sink
  by default): the `escape()`-clears-`RawSQL` tightening is **opt-in** (move
  `escape` into `sanitizer_properties = { escape = ["html_escaped"] }` and give
  the SQL sink `sink_properties = { RawSQL = "sql_escaped" }`). This is what
  keeps "no current config silently changes meaning".

Constructor gains **one** param: `property_contract: PropertyContract | None =
None` (default -> an empty, inert contract). The two maps are bundled into
`analysis/_taint_contract.py::PropertyContract` (frozen dataclass, with
`.clears(name, required_property)` and `.required_for(sink)` helpers) rather than
passed separately - two extra params would push the shared constructor past the
`max_arguments = 7` limit (SAFE103). All seven trackers share the constructor, so
the single-param change is uniform.

**Increment status**: 1 (foundation) + 2 (Python tracker, 3a + 3b) are **done**
on this branch - `PropertyContract`, config keys `sanitizer_properties` /
`sink_properties` (+ validators `_validated_property_map` /
`_validated_string_map`), the Python `dataflow.py` rewrite (single worklist +
property clearing), and the rule wiring in `_python_check`. Pydantic
(`model_validate` / `model_validate_json` / `parse_obj_as`) ships as a
`schema_validated` default (inert for injection sinks). Behaviour preserved on
the existing Python suite; new tracker- and rule-level property tests incl. the
`escape()`-does-not-clear-`RawSQL` end-to-end case. Remaining: the five worklist
trackers (js/java/rust/go/php - each adopts the same `property_contract` param +
worklist), the C tracker (3a only), and the docs/skills/changelog/version fan-out.

## Per-tracker work (from the map)

Seven trackers; six share the Python recursive shape, `dataflow_c.py` is the
worklist exemplar.

- **Python `dataflow.py`**: `_call_tainted` (`:284-316`), sanitiser check at the
  top; `_is_tainted` worklist (`:229-244`). 3a + 3b.
- **JS `dataflow_javascript.py`**: `_call_tainted` (`:317-342`), sanitiser `:329`. 3a + 3b.
- **Java `dataflow_java.py`**: `_call_tainted` (`:382-415`), sanitiser `:402` (adds receiver-as-input). 3a + 3b.
- **Rust `dataflow_rust.py`**: `_call_tainted` (`:325-359`), sanitiser `:340`. 3a + 3b.
- **Go `dataflow_go.py`**: `_call_tainted` (`:260-286`), sanitiser `:271`. 3a + 3b.
- **PHP `dataflow_php.py`**: `_call_tainted` (`:289-313`), sanitiser `:300`. 3a + 3b.
- **C `dataflow_c.py`**: `_classify_call` (`:228-255`), sanitiser at top; already
  worklist-shaped. **3a only** (+ `is_cpp` variant shares it).

All six recursive trackers have the identical skeleton: `if name in sanitizers:
return False` / `if name in sources: return True` / `if not
assume_taint_preserving: return False` / `return any(self._is_tainted(c) for c in
candidates)`. 3b turns the last line into `return False, candidates` drained by
the single worklist (C's shape); 3a replaces the first line with the
property-typed decision.

## Wiring (from the map)

- Config: `DEFAULTS["rules"]["tainted_sink"]` (`config.py:886`). Add
  `sanitizer_properties` (bare + `_<lang>`) and `sink_properties` (bare +
  `_<lang>`), validated. Note Python reads `sinks`/`sanitizers`/`sources` via
  plain `self.config.get(..., self._DEFAULT_*)`; other langs via
  `resolve_lang_config_lookup` + `_validated_string_list`. New keys follow the
  same split. A new validator for the table shape (name -> list) is needed
  alongside `_validated_string_list`.
- Rule `rules/dataflow.py`: only `TaintedSinkRule` (SAFE801) builds trackers.
  Each `_<lang>_check` resolves the new maps and passes them to the constructor
  (`_python_check` `:732-747`; the rest `:757+`). `_DEFAULT_*` class lists
  `:675-702`.

---

## Increment plan

1. **Foundation**: property model + config schema (`config.py` defaults +
   validation) + backward-compat migration of the flat list. No tracker logic
   yet. Unit tests for config resolution + the compat default.
2. **Python tracker** (`dataflow.py`): 3a + 3b together (single worklist +
   property-typed sanitiser clearing, sanitiser-before-receiver ordering).
   Pydantic `schema_validated` default wired. Per-behaviour tests incl. the
   `escape()`-does-not-clear-`RawSQL` case and the existing suite still green.
3. **Remaining five worklist trackers** (js, java, rust, go, php): same
   3a + 3b pattern, one increment each, existing suites preserved.
4. **C tracker** (`dataflow_c.py`): 3a only (sanitiser-property in
   `_classify_call`); it is already in the 3b shape.
5. **Docs + skills + changelog**: `docs/configuration/rules.md` (both TOML
   forms), the language pages, all 14 client skill files + shared addenda if the
   rule phrasing changes, the drift tests, and the `CHANGELOG.md` `[Unreleased]`
   entry. Version bump is MINOR (additive config surface); RC on the
   feature->development PR, production on development->main (owner controls
   timing). Retire this spec + close the two PR #133 tracking threads on ship.

## Validation gate (run all, in order, every increment)

```bash
uv run pytest                                  # coverage gate fail_under = 97
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run ty check src/ scripts/ tests/
uv run safelint check src/ scripts/ tests/ --all-files --fail-on=warning
uv run --extra docs mkdocs build --strict
```
