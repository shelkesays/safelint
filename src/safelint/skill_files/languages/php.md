# safelint skill: PHP addendum

Language-specific notes for the PHP target. Mirrors `src/safelint/languages/php.py` in the safelint source tree. The skill core (`claude/SKILL.md` for Claude Code, each peer client's own file for other agents) handles the universal flow; this file holds PHP-specific detail.

## Install nuance

safelint is a Python package, not a Composer package. The PHP grammar ships in the `[php]` extra:

```bash
pip install 'safelint[php]'
# or, in a project that already uses uv:
uv add --dev 'safelint[php]'
# or, kitchen-sink:
pip install 'safelint[all]'
```

After install, `safelint` is on `PATH`. Run it from the PHP project / repository root the same way as for any other language; safelint auto-detects by file extension. A `composer.json` is not required (safelint walks the source tree directly), but using safelint alongside `php-cs-fixer`, `phpcs`, and `phpstan` / `psalm` is the expected workflow - safelint targets the engineering-discipline patterns those tools leave alone.

If you run plain `pip install safelint` (no extra), the first run emits `safelint: warning: skipping .php files, install with: pip install 'safelint[php]'`. **Exit code is 2 only when EVERY candidate file is skipped** (typical PHP-only project); in a mixed Python + PHP repo, safelint emits the `.php` skip warning and continues linting the supported files normally.

For pre-commit integration, set `additional_dependencies`:

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.5.0  # use a recent tag that includes the [php] extra
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[php]']
      # For a polyglot repo with Python + PHP:
      # additional_dependencies: ['safelint[python,php]']
```

## File extensions

safelint lints `.php` files. The skill doesn't need to filter by extension - `safelint check` walks the project and picks up `.php` automatically. PHPUnit test files (`<ClassName>Test.php`) are linted too, but a few rules treat them specially (see "Test conventions" below).

## Rule count

PHP is in scope for 21 rules: the cross-language structural and dataflow rules (SAFE101-105, SAFE202, SAFE203, SAFE301-304, SAFE309, SAFE401, SAFE501, SAFE601, SAFE603, SAFE701-702, SAFE801-803). The two rules deliberately skipped for PHP (SAFE201, SAFE305) are listed in the "Deliberately skipped" section below. PHP adds **no** new rule codes. Like the other languages' optional rules, every dataflow rule (SAFE801-803) is disabled by default, as are the other opt-in rules (SAFE309, SAFE601, SAFE603).

## PHP shapes worth knowing

A few PHP-vs-other-languages differences the rule engine contends with:

- **The `global` keyword.** PHP is the first non-Python language with a real `global` statement. SAFE301 fires on `global $x;` inside a function body - it pulls module-level shared state into local scope, breaking local reasoning. This is the rule's first non-Python home.
- **Superglobals are the taint source.** `$_GET`, `$_POST`, `$_REQUEST`, `$_COOKIE`, `$_SERVER`, `$_FILES`, and `$_ENV` are PHP's ambient untrusted input. SAFE801 seeds taint from them and traces into `eval` / `exec` / `system` / `shell_exec` / `passthru` / `->query(...)` / `unserialize` / `include` / `require` sinks.
- **The `@` error-suppression operator.** Prefixing an expression with `@` (e.g. `@file_get_contents(...)`) silences any warning or error it raises - PHP's headline blanket-suppression hazard. SAFE603 flags it (Holzmann rule 10).
- **`$GLOBALS` superglobal writes.** SAFE302 flags writes to `$GLOBALS[...]` as global mutation, alongside the universal reassignment patterns.
- **PHPUnit test convention.** PHP's test convention is a sibling `<ClassName>Test.php` (PHPUnit), not a `tests/` directory layout the rule needs to special-case. SAFE701 / SAFE702 use that `Test.php` suffix convention.

## Language-specific rule phrasing

When the user asks "why is this flagged?", the universal rationale in the per-client core is correct, but PHP phrasing helps. The table lists every rule that applies to PHP; rules deliberately skipped (with rationale) are in the next section.

| Code | Rule | PHP-specific notes |
|---|---|---|
| SAFE101 | function_length | Counts source lines on `function_definition` / `method_declaration` / closures (`anonymous_function` / arrow `fn`). Default cap is 60 source lines. Closure bodies count toward their own size, not the enclosing function. |
| SAFE102 | nesting_depth | Counts `if_statement` / `for_statement` / `foreach_statement` / `while_statement` / `do_statement` / `switch_statement` / `try_statement`. Default max is 2. Per-arm `case` nodes are not counted - the switch counts once. |
| SAFE103 | max_arguments | Counts declared parameters in the `formal_parameters` list. A variadic `...$args` counts as one. Default cap is 7. |
| SAFE104 | complexity | Cyclomatic complexity: every `if` / `elseif` / `for` / `foreach` / `while` / `case` / `catch` adds one; `&&` / `\|\|` / `and` / `or` / `??` each add one. The `default` case is not counted. Default cap is 10. |
| SAFE105 | no_recursion | Flags a function calling itself bare (`recurse($n - 1)`) or a method calling itself receiver-qualified (`$this->walk(...)` inside `walk`). Direct self-recursion only; indirect / mutual recursion is out of scope. Enabled by default at warning severity. |
| SAFE202 | empty_except | Flags a `catch` block with an empty (or comment-only) body - the exception was caught and then silently swallowed. PHP's `catch (\Exception $e) {}` is the catch-all-and-drop hazard. |
| SAFE203 | logging_on_error | Flags a `catch` block that neither logs nor re-throws, losing the failure context. Re-throw (`throw $e;`) and recognised log calls exempt the block. |
| SAFE301 | global_state | *PHP's first non-Python home.* Fires on the `global $x;` statement inside a function body - it reaches out to module-level state and defeats local reasoning. Pass the value in as a parameter instead. |
| SAFE302 | global_mutation | Reassigning shared state. PHP additionally flags writes to the `$GLOBALS[...]` superglobal (`$GLOBALS['cfg'] = ...`) on top of the universal patterns. |
| SAFE303 | side_effects_hidden | Fires when a function with a "pure" name prefix (`get` / `compute` / `is` / `validate` / etc.) contains an I/O call (`echo` / `print` / `file_get_contents` / `fwrite` / `curl_exec` / `->query` / etc.). |
| SAFE304 | side_effects | Fires when any function not name-signalled for I/O contains an I/O call. Uses a deliberately narrower I/O list than SAFE303. |
| SAFE309 | dynamic_code_execution | Structural detection of dynamic execution (Holzmann rule 8): `eval` / `create_function` / `call_user_func` / `call_user_func_array` and variable-variable / variable-function call shapes. Complements SAFE801 (taint-gated) - both may fire on one line. Disabled by default. |
| SAFE401 | resource_lifecycle | PHP has no `with` block, so the safe form pairs an acquirer with a `try`/`finally` that closes the handle. Fires on a tracked acquirer (`fopen` / `curl_init` / `fsockopen` / `proc_open` / etc.) whose handle is not closed on every path. A bare-expression acquirer (no assignment) always fires - there is no handle to close. |
| SAFE501 | unbounded_loops | Fires on a `while (true)` / `for (;;)` with no exiting break. PHP's numeric `break N;` (break out of N enclosing loops) is correctly resolved - a `break 2;` exits the loop two levels out. Bounded `for` / `foreach` forms never fire. |
| SAFE601 | missing_assertions | Functions without an internal `assert(...)` skip a chance to catch invariant violations close to the source. PHP's `assert()` is the production assertion idiom. Disabled by default. |
| SAFE603 | blanket_suppression | *Headline: the `@` error-suppression operator.* Flags `@`-prefixed expressions (`@file_get_contents(...)`), which silence any warning / error the expression raises (Holzmann rule 10). Also flags blanket phpstan / psalm `@phpstan-ignore` / `@psalm-suppress all`-style directives. Scoped forms are clean. Disabled by default. |
| SAFE701 | test_existence | Looks for the sibling PHPUnit `<ClassName>Test.php` (PHP's convention). A `*Test.php` file is itself a test and is skipped. |
| SAFE702 | test_coupling | Same `Test.php` convention: when `Foo.php` changes, its `FooTest.php` must change too. Test files are exempt from the coupling check. |
| SAFE801 | tainted_sink | Sources: the superglobals `$_GET` / `$_POST` / `$_REQUEST` / `$_COOKIE` / `$_SERVER` / `$_FILES` / `$_ENV`. Sinks: `eval` / `exec` / `system` / `shell_exec` / `passthru` / `proc_open`, `->query(...)` (raw SQL), `unserialize`, `include` / `require` (and the `_once` forms). Default sanitizers (clear taint): `intval` / `floatval` / `escapeshellarg` / `escapeshellcmd` plus the generic `sanitize` / `validate` / `escape` / `quote`. `htmlspecialchars` is deliberately NOT a default sanitizer (it is HTML-context-only and does not neutralise SQL / shell metacharacters); add it via `sanitizers_php` only when your sinks are HTML-output. |
| SAFE802 | return_value_ignored | Fires on a bare call statement whose error-signalling return is discarded (e.g. `fwrite($h, $buf);` with the byte-count return dropped). |
| SAFE803 | null_dereference | Treats PHP's nullsafe operator `?->` as the safe form. Using a value with `->` after a `=== null` / `!== null` check (or where it could be null) is the flagged crash source; rewrite as `?->` or guard the access. Disabled by default. |

## Deliberately skipped rules

These rules are NOT registered for PHP because Python / JS-family semantics don't translate cleanly:

| Code | Rule | Why skipped for PHP |
|---|---|---|
| SAFE201 | bare_except | PHP's `catch` always names a type (`catch (\Throwable $e)`); there is no bare `catch {}` syntax. The "caught and swallowed" hazard is covered by **SAFE202 `empty_except`** (empty catch bodies) and SAFE203 (unlogged catch). |
| SAFE305 | wide_scope_declaration | PHP has no `var`-style hoisting; variables spring into scope at first assignment and there is no block-vs-function scoping split to narrow. No `let` / `const` analogue to recommend. |

## Idiomatic fix patterns

When walking the user through fixes, use these PHP-native patterns:

### SAFE401 (resource not closed)

PHP has no `with`; pair the acquirer with a `try`/`finally` that closes the handle on every path:

```php
// Before: leaks $h on the exception path
$h = fopen($path, 'r');
$data = process($h);   // may throw
fclose($h);

// After
$h = fopen($path, 'r');
try {
    $data = process($h);
} finally {
    fclose($h);
}
```

### SAFE301 (global keyword)

Pass the dependency in instead of reaching for `global`:

```php
// Before
function render() {
    global $config;
    return $config->theme;
}

// After
function render(Config $config): string {
    return $config->theme;
}
```

### SAFE603 (error-suppression operator)

Drop the `@` and handle the failure explicitly:

```php
// Before: silently swallows any warning
$data = @file_get_contents($path);

// After
$data = file_get_contents($path);
if ($data === false) {
    throw new RuntimeException("read failed: {$path}");
}
```

### SAFE801 (tainted superglobal reaching a sink)

Sanitise the untrusted input before it reaches the sink:

```php
// Before: $_GET flows straight into a shell
system('convert ' . $_GET['file']);

// After: escape it
system('convert ' . escapeshellarg($_GET['file']));

// Or, for SQL, use a prepared statement instead of ->query
$stmt = $pdo->prepare('SELECT * FROM users WHERE id = ?');
$stmt->execute([(int) $_GET['id']]);
```

### SAFE803 (possible null dereference)

Use the nullsafe operator `?->` or guard the access:

```php
// Before
$name = $user->getProfile()->name;  // getProfile() may return null

// After
$name = $user->getProfile()?->name;
```

## Framework presets

PHP source is PHP source - the parser and rule logic are framework-agnostic. The *defaults* shift with the framework via `[tool.safelint.php] framework = "<name>"`:

| Framework | When to pick it | What changes |
| --- | --- | --- |
| `vanilla` (default) | Plain PHP, libraries, no framework | Stdlib-only defaults. SAFE9xx framework rules stay disabled. Existing v2.6.0+ users see no change. |
| `laravel` | Laravel apps | Adds the raw-SQL query-builder methods `whereRaw` / `orderByRaw` / `havingRaw` / `selectRaw` / `unprepared` to the SAFE801 PHP sinks. Enables SAFE905-907 (Eloquent `$guarded = []` mass-assignment, `$request->all()` unvalidated input, `'debug' => true` in config). |

```toml
# pyproject.toml
[tool.safelint.php]
framework = "laravel"
```

```toml
# standalone safelint.toml
[php]
framework = "laravel"
```

The preset merges *before* your explicit TOML, so `[tool.safelint.rules.tainted_sink] sinks_php = [...]` still wins. An unknown framework name warns on stderr and falls back to `vanilla`.
