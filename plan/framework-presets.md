# Framework presets: Django, Flask, FastAPI, Pydantic (Python) + Laravel (PHP)

**Type**: framework/runtime presets (Part B of the add-language-support skill),
**not** new languages. Each preset changes rule *defaults* for an existing
language (Python or PHP); none touches parsing or rule logic. Precedents:
`[tool.safelint.java] framework = "spring-boot"` and
`[tool.safelint.javascript] runtime = "..."`.

**Status**: planned, not started. Read this master spec, then
`.claude/skills/add-language-support/SKILL.md` **Part B** and
`docs/contributing/adding-a-language.md` (its framework-preset section) before
writing code. The Spring Boot preset is the exact reference implementation to
mirror (`src/safelint/rules/spring.py`, the `_JAVA_*` machinery in
`core/config.py`, `tests/core/test_java_framework_presets.py`).

---

## 1. Guiding principle: extend, do not duplicate

The owner's hard requirement drives the whole design:

> A framework preset must **not repeat existing functionality**. It extends the
> existing language support to add framework-specific coverage, exactly like the
> Spring preset. If a framework-specific concern applies across frameworks, it
> becomes **one shared rule / code**, never a per-framework duplicate.

This yields a strict decision order for every framework concern. Apply the
**first** option that fits; only fall through when it genuinely cannot express
the concern:

1. **Extend an existing taint list (zero new code).** Most framework risks are
   injection: raw SQL, server-side template injection (SSTI), command
   execution, unsafe deserialisation, open redirect, path traversal. These are
   **sinks** for `SAFE801 tainted_sink`; the request objects are **sources**.
   The preset just replaces the language's `sinks` / `sources` list with the
   vanilla list **plus** the framework additions. No new rule, no new code.
2. **Enable an existing disabled rule.** If a vanilla rule already covers the
   concern and is merely off by default (the dataflow rules, `dynamic_code_execution`),
   the preset flips its `enabled` flag.
3. **Add ONE shared 9xx rule used across frameworks.** Only for structural
   concerns taint cannot model (debug mode on, mass assignment, unvalidated
   request binding). The rule is written **once**, parametrised by preset, and
   listed in the `language` tuple of every language it serves. It is **never**
   split into `django_x` + `laravel_x`.
4. **Add a framework-only 9xx rule.** Last resort, only where a concern is
   unique to a single framework and has no analogue elsewhere. (Spring's four
   rules are here because `@Autowired` / `@Transactional` / `@Async` are
   Spring-only. Across our five targets, almost nothing is this narrow - see §4.)

The consequence: **the bulk of every preset is taint-list extension (option 1),
a handful of `enabled` flips (option 2), and at most three shared new codes
(option 3) covering all five frameworks between them.** That is the opposite of
"a rule per framework".

---

## 2. Config mechanism (mirror the Spring machinery exactly)

Confirmed shape from `core/config.py` (Java at 2113-2335, JS at 1734-2076, wiring
at 2694-2697). Each preset axis is four pieces:

| Piece | Pattern |
|---|---|
| Valid-names frozenset | `_<LANG>_VALID_<AXIS>` (e.g. `_PYTHON_VALID_FRAMEWORKS`) |
| Preset dict | `_<LANG>_<AXIS>_PRESETS`, nested shape mirrors `DEFAULTS["rules"]`, baseline = `{}` |
| Resolver | `_resolve_<lang>_<axis>(cfg)` - validates, warns via `_diagnostics.print_warning`, **never raises**, falls back to the baseline |
| Applier | `_apply_<lang>_<axis>_preset(defaults, name)` - deep-copies each override into the `DEFAULTS` copy |

Wire resolver+applier into `load_config` **before** `deep_merge(defaults_with_preset, cfg)`
so explicit user TOML always beats the preset.

### 2.1 Two axes to add

- **Python framework axis (new)**: `[tool.safelint.python] framework =
  "django" | "flask" | "fastapi" | "vanilla"` (default `"vanilla"`). Mutually
  exclusive - a file is one framework.
- **PHP framework axis (new)**: `[tool.safelint.php] framework = "laravel" |
  "vanilla"` (default `"vanilla"`). An exact clone of the Java axis.

### 2.2 Pydantic is a *composable library*, not a framework value - design decision

Pydantic is used **with** FastAPI, with Django, with Flask, or standalone. It is
therefore **not** a mutually-exclusive `framework` value. Add it as an
independent boolean axis:

```toml
[tool.safelint.python]
framework = "fastapi"   # or django / flask / vanilla
pydantic  = true        # composes with ANY framework (or none)
```

Mechanism: a fourth piece - `_resolve_python_pydantic(cfg)` returning a bool,
and `_apply_python_pydantic_preset(defaults, on)` applied **after** the framework
preset so both stack (framework sinks first, then Pydantic overrides layered on).
This is a small, deliberate extension of the single-named-axis precedent; call it
out in the PR. The `fastapi` framework preset should **not** silently force
`pydantic` on (keep axes orthogonal and predictable); instead the docs recommend
`framework = "fastapi"` + `pydantic = true` together, and the FastAPI section of
the language page says so.

### 2.3 Replace-semantics reminder (the drift-test trap)

The applier assigns list values **wholesale** (`target[key] = deepcopy(value)`),
so every framework `sinks` / `sources` / `nullable_methods` list must
**re-include the entire vanilla list** plus its additions - otherwise selecting a
framework silently drops stdlib coverage. Add a drift test per preset modelled on
`test_spring_boot_preset_overrides_sinks_java`, asserting every vanilla entry
survives. Python's keys are the **bare** `sinks` / `sources` / `sanitizers` /
`nullable_methods` (Python is the default language); PHP's are `sinks_php` /
`sources_php` / `sanitizers_php` / `nullable_methods_php`. (Confirmed vanilla
Python: `sinks = [eval, exec, compile, system, popen, Popen, run, call,
check_output, execute]`, `sources = [input, readline, recv, recvfrom, read]`,
`nullable_methods = []` (empty). Vanilla PHP: `sinks_php = [eval, exec, system,
shell_exec, passthru, popen, proc_open, unserialize, query, mysqli_query,
pg_query]`, `sources_php = [$_GET, $_POST, $_REQUEST, $_COOKIE, $_SERVER,
$_FILES, $_ENV]`, `nullable_methods_php = [find, findOneBy, first, firstWhere]`.)

### 2.4 Key technical risk to resolve FIRST: the Python taint-source shape

The taint tracker matches Python **sources by call name** (`input()`,
`file.read()`), whereas the Django/Flask request surface is largely
**attribute / subscript reads**: `request.GET['id']`, `request.POST`,
`request.args`, `request.json`. PHP already models superglobal **subscript**
sources (`$_GET['id']`), but Python has no attribute/subscript source model
today. This means naively adding `GET` / `POST` / `args` to the Python `sources`
list may **not** taint `request.GET[...]` the way it taints `input()`.

**Resolve this before committing to sink/source lists** - probe
`analysis/dataflow.py` (Python `TaintTracker`) and confirm which shapes it can
treat as a source. Two outcomes:

- If the tracker can be pointed at the `.get()` **call** form
  (`request.args.get(...)`, `request.GET.get(...)`, `request.POST.get(...)`,
  `request.json`), list those call names and document that direct-subscript
  access (`request.GET['id']`) is a known blind spot (advise `.get()`).
- If not, this becomes a **small, shared tracker enhancement** (attribute-source
  support for Python, mirroring PHP's subscript-source handling) that lands
  once and benefits every Python framework - still "extend existing", not a new
  rule. Scope it explicitly in the Django sub-task; do not discover it late.

The **sinks** side has no such issue (sinks are call-name matched, which fits
`.raw()`, `render_template_string(...)`, `DB::raw(...)`), so the injection
coverage in §5 lands cleanly regardless; only the *source* side carries this
risk. Prior art the project already anticipated: `skill_files/languages/php.md`
(~line 173) explicitly notes a `[tool.safelint.php] framework` axis is unbuilt
and would "extend taint sources and take the 9xx band" - this plan realises it.

---

## 3. The shared cross-framework rule catalogue (option 3)

These are the **only** genuinely new rules. Each is written once and serves
multiple frameworks. Codes are the next free 9xx slots (Spring holds
**SAFE901-904**; **re-verify free with `uv run safelint list-rules` at
implementation time** and renumber if taken). All default-disabled; each
preset's `enabled: true` is the gate (no in-rule framework check, exactly like
Spring).

| Code | name | Concern | Serves (preset → language) | Holzmann |
|---|---|---|---|---|
| **SAFE905** | `debug_mode_enabled` | Debug/reload flag hard-enabled in code | django, flask, fastapi (python) + laravel (php) | Rule 10 (production posture) |
| **SAFE906** | `mass_assignment` | Unbounded attribute binding from request data | django, pydantic (python) + laravel (php) | Rule 6 (least data scope) / 7 |
| **SAFE907** | `unvalidated_request_input` | Request body/params consumed without a validation layer | django, flask, fastapi (python) + laravel (php) | Rule 7 (validate parameters) |

**Why exactly these three and not one-per-framework:**

- **`debug_mode_enabled`** detects `DEBUG = True` (Django settings),
  `app.run(debug=True)` / `app.debug = True` (Flask), `uvicorn.run(..., reload=True)`
  in app code (FastAPI), and `config(['app.debug' => true])` / a literal
  `APP_DEBUG` write (Laravel). One rule, one code, four frameworks, **two
  languages**. Splitting it would create four codes for one idea.
- **`mass_assignment`** detects Django `ModelForm.Meta.fields = "__all__"` (or a
  bare `exclude`), Pydantic input models with `model_config = {"extra": "allow"}`
  (or v1 `class Config: extra = "allow"`), and Laravel Eloquent `$guarded = []` /
  `Model::create($request->all())`. Same "bind everything the client sent"
  defect; one rule with per-framework detection branches keyed off the active
  preset.
- **`unvalidated_request_input`** is the **cross-framework generalisation of
  Spring's SAFE903** (`spring_unvalidated_input`, `@RequestBody` without
  `@Valid`). We do **not** rename or widen SAFE903 (invariant: never repurpose an
  existing code; it is Java-only and annotation-shaped). Instead SAFE907 covers
  the non-Java frameworks - a Django view reading `request.POST[...]` straight
  into a model, a Flask route using `request.json` without a schema, a FastAPI
  endpoint taking raw `dict`/`Request` instead of a Pydantic model, a Laravel
  controller using `$request->all()` without a `FormRequest`/`$request->validate()`.
  Crucially SAFE907 is **one shared code across those four frameworks**, not four.

**Considered and deliberately deferred** (keep the new-code set tight; revisit
only if demand appears): `csrf_protection_disabled` (Django `@csrf_exempt`,
Laravel `VerifyCsrfToken::$except`) and `hardcoded_secret` (Django `SECRET_KEY`,
Flask `secret_key`, Laravel `APP_KEY` literals). Both are real but more
false-positive-prone (test settings, example configs) and lower-frequency than
the three above; list them as a fast-follow, not part of the first cut.

**Everything else needs no new code** - it is taint-list extension (§5).

---

## 4. Why almost nothing is a framework-only rule

Unlike Spring (whose `@Autowired`/`@Transactional`/`@Async` rules are genuinely
Spring-only), the injection surface of Django/Flask/FastAPI/Laravel is shared
across the web-framework world and is best modelled by the **existing** taint
engine. After the three shared rules above, no target framework has a structural
concern unique enough to justify a framework-only 9xx code in the first cut. If
one emerges during implementation (e.g. a Django-specific `SECRET_KEY` in
`settings.py`), it slots into 9xx as a single code - but the default assumption
is **taint extension first**.

---

## 5. Per-framework detail

Each framework section gives: (a) the **taint sinks/sources** to add (option 1 -
the bulk), (b) which existing rules to **enable** (option 2), (c) which **shared
9xx rules** apply (option 3), (d) the **Power-of-Ten** mapping, (e) gotchas.
Sink/source names below are *candidates to verify by probing the grammar and the
library APIs at implementation time* - do not hardcode from memory (project
convention).

### 5.1 Django (`framework = "django"`, Python)

**Taint sinks to add to `sinks`** (re-include all vanilla Python sinks + these):
`raw`, `extra`, `RawSQL` (ORM raw SQL), `execute` (cursor), `mark_safe`,
`format_html` (SSTI/XSS when fed user input), `HttpResponse`/`HttpResponseRedirect`/`redirect`
(open redirect / reflected output when the argument is tainted), `FileResponse`/`open`
(path traversal), `call_command` (command exec), `loads` (`django.core.signing`,
`pickle`). **Sources to add to `sources`**: `GET`, `POST`, `COOKIES`, `FILES`,
`META`, `body`, `data` (DRF `request.data`), `query_params`.

**Enable**: `tainted_sink` (SAFE801), `return_value_ignored` (SAFE802),
`null_dereference` (SAFE803), `dynamic_code_execution` (SAFE309) - all currently
opt-in.

**Shared 9xx**: SAFE905 `debug_mode_enabled` (`DEBUG = True`), SAFE906
`mass_assignment` (`ModelForm` `fields = "__all__"`), SAFE907
`unvalidated_request_input` (request data into a model without a `Form`/serializer).

**Power of Ten**:

| # | Holzmann | Django effect |
|---|---|---|
| 1-5 | control flow, loop bounds, alloc, fn size, asserts | Unchanged - views/models are ordinary functions; the structural rules apply as-is. |
| 6 | smallest scope | `global_state` unchanged; `mass_assignment` (SAFE906) sharpens "least data scope" at the model-binding boundary. |
| 7 | check returns / validate params | **Sharpened**: SAFE907 flags request data bound without a validation layer (the Django analogue of Spring `@Valid`). |
| 8 | limit dynamic code | **Sharpened**: SAFE801 gains ORM-raw-SQL + SSTI (`mark_safe`) + `call_command` sinks; SAFE309 on. |
| 9 | pointers | n/a (Python). |
| 10 | heed warnings | **Sharpened**: SAFE905 flags `DEBUG = True`. |

**Gotchas**: `.raw()`/`.extra()` are `attribute`/`call` nodes - SAFE801 matches
by call-name, receiver-blind, so bare `execute`/`extra`/`raw` will also match
unrelated methods; scope by keeping the list conservative (the Spring precedent
excluded `put`/`delete` for exactly this). `settings.py` `DEBUG` is a
module-level assignment - SAFE905 walks assignments, not calls. For SAFE803, the
Python `nullable_methods` list is **empty** by default; a Django preset can add
`first`/`cache.get` (both return `None`), but **not** `QuerySet.get` - it
*raises* `DoesNotExist` rather than returning null, so it is not a nullable
method.

### 5.2 Flask (`framework = "flask"`, Python)

**Sinks to add**: `render_template_string` (SSTI - the headline Flask risk),
`Markup` (XSS), `redirect` (open redirect), `send_file`/`send_from_directory`
(path traversal), `make_response`. **Sources**: `args`, `form`, `values`,
`json`, `data`, `cookies`, `files`, `headers` (all attributes of `flask.request`).

**Enable**: `tainted_sink`, `return_value_ignored`, `null_dereference`,
`dynamic_code_execution`.

**Shared 9xx**: SAFE905 (`app.run(debug=True)` / `app.debug = True` /
`app.config["DEBUG"] = True`), SAFE907 (`request.json`/`request.form` used
without a schema - Flask has no built-in validation, so this is advisory-leaning;
tune severity to `warning`). Flask has **no ORM** and **no mass-assignment
concept**, so SAFE906 does **not** list Flask.

**Power of Ten**: same table shape as Django; the sharpened rows are 7 (SAFE907,
warning), 8 (SAFE801 SSTI via `render_template_string` - the marquee Flask sink),
10 (SAFE905). Rows 1-6/9 unchanged.

**Gotchas**: `render_template_string` vs `render_template` - only the `_string`
form is a sink (the file form is safe); match the exact name. `debug=True` can be
a keyword arg on `app.run(...)` or an attribute assignment - SAFE905 must handle
both shapes.

### 5.3 FastAPI (`framework = "fastapi"`, Python)

**Sinks to add**: SQLAlchemy `text` / `execute` (raw SQL), `HTMLResponse`/`Response`
(`content=` tainted → XSS), Jinja2 `from_string`, `RedirectResponse` (open
redirect), `FileResponse` (path traversal). **Sources**: FastAPI injects request
data through typed parameters, so the taint sources are the parameter binders -
`Query`, `Path`, `Body`, `Form`, `Header`, `Cookie` - plus a raw `Request`
object's `.query_params`/`.path_params`/`.json`/`.body`.

**Enable**: `tainted_sink`, `return_value_ignored`, `null_dereference`,
`dynamic_code_execution`.

**Shared 9xx**: SAFE905 (`uvicorn.run(..., reload=True)` / `debug=True` in app
code), SAFE907 (endpoint taking raw `dict`/`Request`/unannotated body instead of
a Pydantic model - FastAPI's idiomatic validation is a Pydantic parameter, so
its absence is the "unvalidated input" signal). Recommend pairing with
`pydantic = true`.

**Power of Ten**: FastAPI's design *encourages* rule-7 compliance (Pydantic
params validate automatically), so SAFE907 here flags the *opt-out* (raw request
access). Rows 8 (SAFE801 raw-SQL/SSTI) and 10 (SAFE905) as above.

**Gotchas**: FastAPI validation is *type-annotation-driven*; SAFE907 detects the
**absence** of a Pydantic-model-typed parameter on a route handler, which is a
structural check over the decorated function's signature. Keep it conservative
(only flag handlers that *do* read raw request data) to avoid FP on handlers with
no input.

### 5.4 Pydantic (`pydantic = true`, composable - Python)

Pydantic is a **validation library that mostly reduces risk**, so its preset is
deliberately small and mostly overlaps the shared rules:

- **Shared 9xx**: SAFE906 `mass_assignment` - flag input models declaring
  `model_config = ConfigDict(extra="allow")` (v2) or `class Config: extra =
  "allow"` (v1), which lets a client inject arbitrary extra fields.
- **Taint sink**: `model_construct` / `construct` - these **skip validation**,
  so feeding tainted data through them defeats Pydantic's guarantee; add as a
  SAFE801 sink so tainted → `model_construct` is flagged. (`parse_obj_as`/`TypeAdapter`
  are safe.)
- **Future / deferred**: Pydantic is the natural first **sanitiser** for the
  taint tracker - a value that passes through `Model(...)`/`model_validate(...)`
  is validated and could clear taint. The tracker has **no sanitiser framework
  yet** (`config.py` notes it is on the v3.x roadmap). Do **not** build sanitiser
  support here; note it as the motivating use-case for that future work.

**Power of Ten**: Pydantic sharpens **rule 7** (it *is* parameter validation);
SAFE906 covers the one way Pydantic can be misconfigured to *skip* that intent.
No other rows change.

**Gotchas**: v1 vs v2 config shapes differ (`class Config` vs `model_config =
ConfigDict(...)`); SAFE906 must recognise both. Only **input** models matter -
FP risk if it flags internal/response models; keep the check to
`extra="allow"` presence (that is the actual defect regardless of model role).

### 5.5 Laravel (`framework = "laravel"`, PHP)

Exact Java-clone axis on PHP. PHP already has superglobal taint **sources**
(`$_GET`/`$_POST`/... at `config.py:1143`); Laravel adds its request helpers and
Eloquent/Blade sinks.

**Sinks to add to `sinks_php`** (re-include all vanilla PHP sinks + these):
`raw`, `statement`, `whereRaw`, `orderByRaw`, `havingRaw`, `selectRaw` (`DB::`
query builder raw SQL), `unprepared`, `render` (`Blade::render` SSTI),
`unserialize` (already vanilla? verify), `file`/`download` (`response()->file`
path traversal), `to`/`away` (`redirect()->to()` open redirect). **Sources to add
to `sources_php`**: `all`, `input`, `query`, `post`, `get`, `request`, `json`,
`only`, `except` (methods of the Laravel `$request` / `request()` helper).

**Enable**: `tainted_sink`, `return_value_ignored`, `null_dereference`,
`dynamic_code_execution` (PHP `eval` / dynamic). Caveat: `return_value_ignored`
(SAFE802) has **no `flagged_calls_php` default** today - verify whether it fires
on PHP at all before relying on it; if not, either add a `flagged_calls_php`
default (extend, not new rule) or drop SAFE802 from the Laravel enable set.
`nullable_methods_php` already carries `find`/`first`/`firstWhere`, which Eloquent
`Model::find()` / `->first()` return-null semantics match - so SAFE803 needs
little Laravel extension.

**Shared 9xx**: SAFE905 `debug_mode_enabled` (`config(['app.debug' => true])` or
a literal `APP_DEBUG` true in code - note `.env` is not parsed, so this is
code-only), SAFE906 `mass_assignment` (Eloquent `$guarded = []` or
`Model::create($request->all())`), SAFE907 `unvalidated_request_input`
(`$request->all()`/`input()` used without a `FormRequest` type-hint or a
`$request->validate([...])` call in the method).

**Power of Ten**:

| # | Holzmann | Laravel effect |
|---|---|---|
| 1-5 | control flow…asserts | Unchanged (controllers/models are ordinary methods). |
| 6 | smallest scope | `global_state` (PHP `global`/`$GLOBALS`) unchanged; SAFE906 sharpens model-binding scope. |
| 7 | validate params | **Sharpened**: SAFE907 flags `$request->all()` without a `FormRequest`/`validate()`. |
| 8 | limit dynamic code | **Sharpened**: SAFE801 gains `DB::raw`/`whereRaw`/`Blade::render` sinks; SAFE309 on. |
| 9 | pointers | n/a. |
| 10 | heed warnings | **Sharpened**: SAFE905 flags in-code debug enable. |

**Gotchas**: `DB::raw` and Eloquent are static/facade or fluent chains -
call-name matching is receiver-blind, so bare `raw`/`statement` may over-match;
keep the list tight and lean on the `whereRaw`/`orderByRaw` compound names which
are unambiguous. Laravel's real config lives in `.env` / `config/*.php` which
safelint does not treat specially - SAFE905 only catches an in-code debug enable,
document that limit.

---

## 6. Deliverable checklist (per preset, from skill Part B)

For **each** of the two axes (Python framework, PHP framework) and the Pydantic
toggle:

**Config** (`core/config.py`): valid-names frozenset; preset dict(s) mirroring
`DEFAULTS["rules"]`; `_resolve_*` (warn+fallback, never raise); `_apply_*`
(deep-copy); wire into `load_config` before the user `deep_merge`.

**Rules** (the three shared 9xx): `rules/framework_rules.py` (or one file per
rule) subclassing `BaseRule`; `language` tuple lists **every** language the rule
serves (SAFE905 = `("python", "php")`; SAFE906/907 likewise); register in
`ALL_RULES` + `__all__`, add to `DEFAULTS["rules"]` (disabled, severity) and
`DEFAULTS["execution"]["order"]`. Obey safelint's own rules (iterative walks,
`function_length<=60`, `nesting_depth<=2`, `complexity<=10`).

**Tests**: preset-resolution tests per axis (model on
`tests/core/test_java_framework_presets.py`): each override lands, user TOML
beats preset, unknown name warns+falls back, baseline is a no-op, **drift test**
that the full-replace sink/source lists retain every vanilla entry. Per-rule
structural tests (violation + clean) for SAFE905-907, **per framework in the
tuple**. e2e fixtures (`tests/fixtures/django/`, `.../flask/`, `.../fastapi/`,
`.../laravel/` + `tests/integration/test_*_e2e.py`) mirroring
`tests/fixtures/spring_boot/`.

**Docs**: `docs/configuration/toml.md` - a preset section per axis in **BOTH**
forms (`[tool.safelint.python]`/`[python]`, `[tool.safelint.php]`/`[php]`);
`docs/languages/python.md` + `docs/languages/php.md` preset tables;
`docs/configuration/rules.md` sections for SAFE905-907 (both config forms);
`docs/power-of-ten.md` - add the sharpened-row references (SAFE905 under rule 10,
SAFE906 under rule 6/7, SAFE907 under rule 7 alongside Spring SAFE903);
`README.md` / `docs/index.md` language-row mentions.

**Skill files**: the shared addenda `skill_files/languages/python.md` +
`skill_files/languages/php.md` (preset tables); **all 14 client skill files** gain
rows for SAFE905-907 (`tests/test_skill_install.py::test_skill_documents_every_active_rule`
enforces this per client - land in the same commit).

**CHANGELOG**: under `## [Unreleased]` → Added. Additive = **MINOR**.

**Gate** (all must pass): `uv run pytest` (coverage >=97), `ruff check`,
`ruff format --check`, `ty check src/`, `safelint check src/ --all-files`,
`mkdocs build --strict`.

---

## 7. Release sequencing (CONFIRMED: one bundled MINOR)

Additive = **MINOR**, never MAJOR. Decision (owner, confirmed): ship **all five
together in a single MINOR** (e.g. `2.9.0`), per the comprehensive-RC preference.
Concretely:

- Both the `[tool.safelint.python] framework` + `pydantic` axes **and** the
  `[tool.safelint.php] framework` axis land in the one release.
- The three shared rules (SAFE905-907) carry **`("python", "php")`** in their
  `language` tuple **from day one** - no later tuple-widening edit.
- All Python (bare `sinks`/`sources`/`nullable_methods`) **and** PHP
  (`sinks_php`/`sources_php`) list extensions ship at once.

Follow the branch flow: `feature/framework-presets -> development` carries the
**RC** bump (`project.version = "2.9.0rcN"`); the later `development -> main` PR
flips to production `2.9.0`. The version *number* is the owner's call at release
time; do not leave `project.version` at the previous release.

---

## 8. Decisions (confirmed) and implementation-time checks

Confirmed with the owner:

1. **Release**: one bundled MINOR - all five presets + SAFE905-907 together (§7).
2. **Pydantic**: a **composable boolean axis** (`[tool.safelint.python] pydantic
   = true`), independent of and stacking on top of the `framework` axis (§2.2);
   not a `framework` value.
3. **New-rule scope**: **only SAFE905-907** in the first cut
   (`debug_mode_enabled`, `mass_assignment`, `unvalidated_request_input`).
   `csrf_protection_disabled` and `hardcoded_secret` are **deferred** as a
   fast-follow, not part of this release.

Still to settle *during* implementation (not blockers):

4. **SAFE907 severity per framework** - propose `error` where the framework has a
   first-class validation layer whose absence is a real defect (Django forms,
   FastAPI Pydantic, Laravel FormRequest) and `warning` for Flask (no built-in
   validation). Finalise when writing the rule.
5. **Re-verify SAFE905-907 are free** with `uv run safelint list-rules` at
   implementation time; renumber within 9xx if any is taken.
6. **Resolve the Python taint-source shape (§2.4) FIRST** - the one real unknown;
   probe the tracker before finalising the Django/Flask/FastAPI source lists.
