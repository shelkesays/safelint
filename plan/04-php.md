# PHP language support - implementation spec

**Status**: not started. Read `plan/README.md` first, then the standing
references. Independent of the C/C++ work; sequenced last per the roadmap.

**Why PHP is a strong fit**: PHP ports MORE of the existing rule set than any
language so far - it has try/catch (2xx ports), a literal `global` keyword
(SAFE301 ports beyond Python for the first time), `eval` (SAFE309's natural
home), superglobals (classic taint territory for SAFE801), a nullsafe
operator `?->` (SAFE803's safe form), and the `@` error-suppression operator
(SAFE603's most literal target in any language).

**Scope**: one comprehensive MINOR release. Grammar `tree-sitter-php` (note:
the package exposes two grammars, `language_php()` for mixed HTML+PHP and
`language_php_only()`; use `language_php()` so real-world templated files
parse - HTML segments arrive as `text` nodes the rules never match).
Extensions `.php`. Line comments `//` (PHP also allows `#` and `/* */`;
the `//` directive convention applies, document `#`-comment directives as
unsupported).

---

## 1. Language module (`src/safelint/languages/php.py`)

- `EXTRA_NAME = "php"`, extra `php = ["tree-sitter-php>=0.23.0"]` + `[all]`.
- `LanguageDefinition(name="php", file_extensions={".php"},
  comment_node_type="comment", comment_prefix="//")`.
- Key node types (verify by probing): `function_definition`,
  `method_declaration`, `anonymous_function_creation_expression`,
  `arrow_function` - FUNCTION_TYPES. `function_call_expression`,
  `member_call_expression`, `scoped_call_expression`,
  `object_creation_expression`. `try_statement`, `catch_clause`,
  `global_declaration` (the `global $x;` statement),
  `error_suppression_expression` (the `@` operator),
  `nullsafe_member_call_expression` (`?->`), `subscript_expression`
  (`$_GET['x']`), `echo_statement`, `if/while/for/foreach/switch/match`.

## 2. Per-rule portability audit

### Ports cleanly

| Rule | PHP shape / notes |
|---|---|
| SAFE101-104 | The four function-shaped nodes; complexity counts `if` / `elseif` / loops / `case` / `match` arms / ternary / `&&` `\|\|` `??`. |
| SAFE105 `no_recursion` | Bare `function_call_expression` name match plus `$this->walk(...)` (member call whose object is `$this`) and `self::walk(...)` / `static::walk(...)` scoped calls. |
| SAFE201 `bare_except` | **Decision: skip** (see skipped table) - PHP catch requires a type since PHP 7; `catch (\Throwable $e)` is typed catch-all already covered by 202/203, same rationale as Java. |
| SAFE202 / SAFE203 | Direct ports: empty catch bodies; logging via call names (`error_log`, PSR-3 `info`/`warning`/`error`/`debug`/`critical`, Monolog methods). Bare `throw $e;` rethrow exempt. |
| SAFE301 `global_state` | **First non-Python registration.** `global_declaration` inside functions is the literal same construct. Port the Python detection shape. Update SAFE301's "Python-only" phrasing everywhere (rules.md, language pages, all 14 client skill tables - drift test checks presence, not the stale wording; the rewording is on you). |
| SAFE302 `global_mutation` | Python shape ports (`global $x;` + write). Add the superglobal write shape: assignments targeting `$GLOBALS[...]` (subscript on `$GLOBALS`) fire too. |
| SAFE303 / SAFE304 | `io_functions_php`: `echo` (statement node, special-case), `print`, `print_r`, `var_dump`, `file_get_contents`, `file_put_contents`, `fopen`, `fwrite`, `curl_exec`, `mail`, `header`. |
| SAFE309 `dynamic_code_execution` | The richest list in the project: `dynamic_exec_calls_php = ["eval", "assert", "create_function", "call_user_func", "call_user_func_array"]` (`eval` is a language construct - check whether it parses as a dedicated node or a call; handle both). Variable includes (`include $path`) are SAFE801 territory, not 309. |
| SAFE401 `resource_lifecycle` | PHP has `try { } finally { }`: port the JS-style detection. `tracked_functions_php`: `fopen`, `curl_init`, `proc_open`, `fsockopen`. |
| SAFE501 | `while (true)` / `for (;;)` without exiting break; PHP `break 2;` (numeric levels) is the labelled-break analogue - a `break` with an integer argument exits that many levels; resolve accordingly. |
| SAFE601 | `assertion_calls_php = ["assert"]` plus PHPUnit `assert*` method names for parity with Java's hybrid list. |
| SAFE603 `blanket_suppression` | Two shapes: bare `// phpcs:ignore` (no sniff list) / `@phpstan-ignore-line` without an identifier, AND the `@` **error-suppression operator** (`error_suppression_expression` node) - PHP's most literal "silence the analyser" construct; flag every use. This is the headline PHP entry for the rule; document prominently. |
| SAFE701 / SAFE702 | PHPUnit convention `FooTest.php` (StudlyCaps), default `test_dirs = ["tests"]`. |
| SAFE801 `tainted_sink` | New `analysis/dataflow_php.py`. The classic web-taint setup. `sources_php`: superglobal reads `$_GET` / `$_POST` / `$_REQUEST` / `$_COOKIE` / `$_SERVER` / `$_FILES` (subscript-expression on these names - a new source *shape*, not just a name list; seed any expression reading them), `file_get_contents("php://input")`. `sinks_php`: `eval`, `exec`, `system`, `shell_exec`, `passthru`, `popen`, `proc_open`, `unserialize`, `query` (mysqli/PDO), `mysqli_query`, `include` / `require` with non-literal arguments. `sanitizers_php`: `intval`, `escapeshellarg`, `escapeshellcmd`, plus the generic set; `htmlspecialchars` deliberately excluded from global sanitizers (HTML-context-only, same rationale as Java's encoder exclusions - copy that doc note). |
| SAFE802 | `flagged_calls_php`: `fwrite`, `fclose`, `unlink`, `rename`, `mkdir`, `file_put_contents`, `mail`, `session_start`. |
| SAFE803 `null_dereference` | `nullable_methods_php` chained-call detection with PHP's safe form: the nullsafe operator `?->` (`nullsafe_member_call_expression`) is recognised as safe, exactly like JS `?.`. Nullable defaults: `array_search`-style functions return `false` not null - keep the list to genuinely null-returning calls (`current`, `prev`, `next` on empty, `DateTime::createFromFormat`-style factories) and document the false-vs-null limitation. |

### Deliberately skipped

| Rule | Rationale |
|---|---|
| SAFE201 | PHP 7+ catch clauses always carry a type; `catch (\Throwable)` is the typed catch-all and SAFE202/203 cover its hazards (Java precedent). |
| SAFE305 | No hoisting / `var` distinction. |

### New PHP-only rules

None proposed for v1 - the ported set is already the largest of any language,
and the `@` operator (PHP's most-wanted lint target) lands inside SAFE603.
Candidates for later, with demand: a `variable_include` rule (include/require
with a non-literal path, structural complement to the SAFE801 sink) and a
`loose_comparison` rule (`==` vs `===`); record both in the language page's
roadmap note rather than shipping heuristics now.

## 3. Framework presets (record the axis, defer the work)

PHP is the most framework-shaped language in the set. Record a future
`[tool.safelint.php] framework` preset axis (config tokens `laravel` / `symfony` / `wordpress`, lowercase like `spring-boot`)
in the language page, following the Part B standard in
`docs/contributing/adding-a-language.md`:

- **Laravel** (`laravel`): adds `DB::raw`, `whereRaw`, `selectRaw` to `sinks_php`;
  `request()` helpers to sources.
- **WordPress** (`wordpress`): `$wpdb->query` sinks, nonce-check structural rules.
- Any structural rules these grow take the **9xx band** (905+ free as of
  v2.4.0; verify), exactly like Spring's SAFE901-904.

Do NOT implement presets in this release; the vanilla defaults above must
stand alone first (the Java release shipped vanilla + spring together, but
PHP's framework surface is larger - one release per the comprehensive-MINOR
policy still means presets are their own follow-up spec).

## 4. Tests

Standard fan-out plus: a mixed HTML+PHP fixture (rules fire inside `<?php`
segments, HTML text is inert), the `@`-operator SAFE603 fires / scoped
`phpcs:ignore sniff` clean pair, superglobal-source taint tests
(`$_GET['x']` into `eval` / into `query`), the `?->` safe-form SAFE803 test,
`break 2;` loop-exit resolution for SAFE501, and SAFE301 ports (mirror the
Python test file). Allow-list buckets updated for every widened tuple
(SAFE301 gains its first second language - a new bucket).

## 5. Documentation and skill files

Shared checklist (plan/README.md), with the PHP-specific content:

- `docs/languages/php.md`: mixed-HTML parsing note, the `@`-operator story,
  superglobal taint model, `?->` safe form, framework-preset roadmap note,
  skipped-rules table, `_php` keys with both TOML forms.
- `docs/power-of-ten.md`: rule 8 note (PHP's `eval`/`include` surface is the
  largest), rule 10 note (the `@` operator as the literal
  suppress-the-analyser construct).
- `rules.md`: scope-table updates (SAFE301's row **drops** the "Python-only" label and gains PHP, consistent with the section-2 instruction);
  remove PHP from "Planned" - **the Planned section then becomes empty or
  gains its next candidates; ask the maintainer which**.
- Skill files: `languages/php.md` addendum, 14 Step-2 rows, README counts,
  reworded SAFE301 rows in all 14 client tables.
- **Scattered enumerations (the Go miss - OUTSIDE the language tables):**
  `docs/configuration/cli.md` (`--all-files` extension list + `--language`
  values), `SECURITY.md` (supported-versions table, `tree-sitter-<lang>`
  grammar list, files-read extension list), `docs/configuration/toml.md`
  (opt-in-rules walkthrough), and `CONTRIBUTING.md` (language count +
  examples).
- CHANGELOG `[Unreleased]`; stale-count **and enumeration** sweep: grep the
  prior language's extension / name (whole-word, `grep -w`, so short names
  like `go` / `c` don't over-match) / `tree-sitter-<lang>` across `docs/`,
  `README.md`, `SECURITY.md`, and `src/safelint/skill_files/` (the wording
  "all-five-languages set" will be long gone by now - sweep whatever the
  current phrasing is).
