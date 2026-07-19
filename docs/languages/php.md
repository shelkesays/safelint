# PHP

SafeLint analyses PHP source for the Holzmann "Power of Ten" safety rules and PHP-language-specific patterns: function shape (length, nesting depth, cyclomatic complexity, argument count), error-handling discipline (empty `catch {}` bodies, unlogged catches), global state (the `global` keyword and `$GLOBALS` writes), resource lifecycle via `try { } finally { }`, loop safety (the `while (true)` / `for (;;)` shapes with numeric-level `break N` resolution), suppression hygiene (the `@` error-suppression operator), and dataflow taint into `eval` / `exec` / `unserialize` / raw-SQL sinks from the web superglobals. PHP is the **7th registered language** and adds no new rule codes: it is the widest *port* of the existing rule set. SafeLint does NOT replace PHP_CodeSniffer / PHPStan / Psalm; it runs alongside them and targets the engineering-discipline patterns those tools leave alone.

## File extensions

- **`.php`**, parsed by `tree-sitter-php`. Picked up by `safelint check` (directory mode, `--all-files` mode, and the pre-commit hook). SafeLint uses the mixed HTML+PHP grammar (`language_php()`) so templated `.php` files parse: HTML outside `<?php ?>` tags arrives as inert `text` nodes that the rules never match, and only the PHP regions inside the tags are analysed.

## Quick start

```bash
pip install 'safelint[php]'         # adds the tree-sitter-php grammar
safelint check src/                # lint a directory (git-modified files by default)
safelint check --all-files .       # lint everything under cwd
safelint check --format json src/  # machine-readable for editors / CI
```

In a project that already uses `uv`, add it as a dev dependency:

```bash
uv add --dev 'safelint[php]'
```

safelint is a Python package, not a Composer package. A `composer.json` is not required; safelint walks the source tree directly and auto-detects by file extension. Run it from the project root. If your PHP project has no Python tool chain, `pipx install 'safelint[php]'` isolates the install.

v2.0.0+ ships every language grammar as an opt-in extra. Plain `pip install safelint` installs only the engine and would skip every `.php` file with an install hint (`safelint: warning: skipping .php files, install with: pip install 'safelint[php]'`) on first run. The exit code is 2 only when EVERY candidate file is skipped (the typical PHP-only project); in a mixed Python + PHP repo, safelint emits the `.php` skip warning and continues linting the supported files normally.

## Suppression directives

PHP supports **line-comment directives only** (`//`): `// nosafe`, `// nosafe: SAFE501`, `// safelint: ignore: SAFE101`. The `#` shell-style and `/* */` block-comment forms are a **documented non-feature** for directives: a `# nosafe` or `/* nosafe */` is parsed as ordinary text and does not suppress anything. Use the `//` form.

## Rules that fire on PHP

**21 rules apply to PHP.** PHP is in scope for 13 cross-language rules (the all-language core), plus a set of rules shared with most other languages, plus the try/catch rules and SAFE301. 2 rules are deliberately skipped, see the next section. Like the other languages' optional rules, every dataflow rule and several state / suppression rules are disabled by default.

### Cross-language rules

| Code | Rule | Notes for PHP |
|---|---|---|
| [SAFE101](../configuration/rules.md#safe101-function_length) | `function_length` | Counts source lines on `function_definition` / `method_declaration` / anonymous functions and arrow functions. Default cap is 60. Closure bodies count toward their own size, not the enclosing function. |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | `nesting_depth` | Counts `if_statement` / `for_statement` / `foreach_statement` / `while_statement` / `do_statement` / `switch_statement` / `try_statement`. Default max 2. Per-arm `case` nodes are not counted; the switch counts once. |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | `max_arguments` | Counts declared parameters. Variadic `...$args` counts as one. Promoted constructor parameters (`public int $x`) count as parameters. Default cap 7. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | `complexity` | Cyclomatic complexity: every `if` / `for` / `foreach` / `while` / `do` / `case` / `catch` adds one; `&&` / `\|\|` (and `and` / `or`) each add one. The `default` case is not counted (it adds no decision). Default cap 10. |
| [SAFE105](../configuration/rules.md#safe105-no_recursion) | `no_recursion` | Flags a `function_definition` calling itself bare (`recurse($n - 1)`) or a `method_declaration` calling itself via `$this->walk(...)` / `self::walk(...)` / `static::walk(...)` inside `walk()`. A call on another object does not fire. Direct self-recursion only (mutual recursion is out of scope). Enabled by default at warning severity. |
| [SAFE301](../configuration/rules.md#safe301-global_state) | `global_state` | **PHP is this rule's first non-Python registration.** PHP has a literal `global` keyword, so SAFE301 fires on a `global $config;` statement inside a function - the direct analogue of Python's `global` declaration. Enabled by default at warning severity. |
| [SAFE302](../configuration/rules.md#safe302-global_mutation) | `global_mutation` | Fires on writes to global state. In PHP that is a write through a `global`-declared name and, additionally, a write to the `$GLOBALS[...]` superglobal (`$GLOBALS['x'] = ...`). Reads are clean; only mutations fire. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | `side_effects_hidden` | Fires when a function with a "pure" name prefix (`get` / `compute` / `is` / `validate` / etc.) contains an I/O call. Default `io_functions_php` covers output (`print_r` / `var_dump` / `printf` / `fwrite`), filesystem (`fopen` / `readfile` / `file_get_contents` / `file_put_contents`), network (`curl_exec` / `mail`), and HTTP side-effects (`header` / `setcookie`). |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | `side_effects` | Fires on any function (not name-signalled for I/O) containing an I/O call. The `io_functions_php` list is kept **identical** to SAFE303 here (not narrowed as for Go) because the PHP primitives are unambiguous global builtins with no method-name overlap. The `io_name_keywords` exemption suppresses functions whose names already signal I/O. |
| [SAFE309](../configuration/rules.md#safe309-dynamic_code_execution) | `dynamic_code_execution` | Structural flag for runtime code evaluation. Default `dynamic_exec_calls_php`: `eval` (a language construct that parses as a call), `assert` (its string form evaluates code), `create_function` (the legacy runtime function builder), and the `call_user_func` / `call_user_func_array` dispatchers. Variable `include` / `require` is SAFE801 (taint) territory, not here. Disabled by default. |
| [SAFE401](../configuration/rules.md#safe401-resource_lifecycle) | `resource_lifecycle` | PHP has no RAII or `with` block, so the safe form is a `try { } finally { }` that closes the handle. Fires on a tracked acquirer (`tracked_functions_php`: `fopen` / `fsockopen` / `popen` / `proc_open` / `curl_init` / `opendir` / `tmpfile`) whose handle is not closed in a `finally`. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | `unbounded_loops` | Flags `while (true)` and `for (;;)` (the empty three-clause header) without an exiting break. **Numeric `break N` levels are resolved**: PHP's `break 2;` exits two enclosing loops / switches at once, so a `break 2` inside a nested loop correctly counts as exiting the outer `while (true)`. Conditioned (`while ($cond)`), `for`, and `foreach` loops are bounded shapes and never fire. |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | `missing_assertions` | Counts assertion calls per function. Default `assertion_calls_php` covers `assert` plus the PHPUnit family (`assertSame` / `assertEquals` / `assertTrue` / `assertNull` / `assertCount` / `assertInstanceOf` / `assertThat` / `expectException` / `fail` etc.). `min_assertions` defaults to 1; set 2 to match the paper. Disabled by default. |
| [SAFE603](../configuration/rules.md#safe603-blanket_suppression) | `blanket_suppression` | The headline PHP target is the **`@` error-suppression operator** (`@file_get_contents(...)`): every use is flagged, since `@` silences the analyser and the runtime alike. Also flags bare `phpcs:ignore` (no sniff named), `@phpstan-ignore-line`, and `@psalm-suppress all`. Scoped forms (`phpcs:ignore Generic.Files.LineLength`, `@phpstan-ignore-next-line specific.error`) are clean. Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | `test_existence` | PHP's convention is the PHPUnit `<ClassName>Test.php` file under `tests/`. SAFE701 looks for that pair; a `*Test.php` file is itself a test and is skipped. Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | `test_coupling` | Same PHPUnit convention: when `Foo.php` changes, its `FooTest.php` under `tests/` must change too. Test files are exempt from the coupling check. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | `tainted_sink` | Models the classic PHP web-taint flow, tracked by `analysis/dataflow_php.py` (iterative worklists). **Sources** (`sources_php`) are the superglobals - reading any key from one (`$_GET['id']`) yields attacker-controlled data: `$_GET` / `$_POST` / `$_REQUEST` / `$_COOKIE` / `$_SERVER` / `$_FILES` / `$_ENV`. **Sinks** (`sinks_php`): `eval` / `exec` / `system` / `shell_exec` / `passthru` / `popen` / `proc_open` (command), `unserialize` (object-injection), `query` / `mysqli_query` / `pg_query` (raw SQL), plus dynamic `include` / `require`. **Sanitizers** (`sanitizers_php`): `intval` / `floatval` (numeric coercion), `escapeshellarg` / `escapeshellcmd` (shell neutralisation), plus the generic `sanitize` / `validate` / `escape` / `quote`. **`htmlspecialchars` is deliberately excluded** - it is HTML-context-only (clears XSS, not SQLi / command injection); add it via config if your sinks are HTML-only. Disabled by default. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | `return_value_ignored` | Fires on a bare call statement whose meaningful return is discarded. Default `flagged_calls_php`: `fwrite` / `fputs` / `fclose`, `unlink` / `rename` / `copy` / `mkdir` / `rmdir`, `file_put_contents`, `mail`, `session_start` - functions whose `false`-on-failure return signals an error you must check. Disabled by default. |
| [SAFE803](../configuration/rules.md#safe803-null_dereference) | `null_dereference` | Fires on a method / property access chained off a call whose name is in `nullable_methods_php` without a null guard. Default set: array-pointer functions (`current` / `next` / `prev` / `end` / `reset`), `DateTime::createFromFormat` (returns `false` on bad input), and ORM finders (`find` / `first`, which return `null` when absent). The **nullsafe operator `?->`** is recognised as the safe form: `$repo->find($id)?->name` does not fire. Disabled by default. |

### Rules not registered for PHP

| Code | Rule | Why skipped for PHP |
|---|---|---|
| [SAFE201](../configuration/rules.md#safe201-bare_except) | `bare_except` | PHP 7+ `catch` always carries a type - `catch (\Throwable $e)` is the typed catch-all, which is auditable rather than a bare-catch hazard. The "swallowed / unlogged catch" spirit is covered by **SAFE202 `empty_except`** and **SAFE203 `logging_on_error`**, the same treatment as Java. |
| [SAFE305](../configuration/rules.md#safe305-wide_scope_declaration) | `wide_scope_declaration` | PHP has no `var` / `let` / `const` declaration-keyword distinction at function scope; a variable simply exists where first assigned. There is no narrow-the-declaration hazard to flag. |

## Key PHP adaptations

A few PHP-vs-other-languages shapes the rule engine contends with, worth knowing when reading violations:

- **Mixed HTML + PHP.** `.php` files routinely interleave HTML and `<?php ?>` blocks. SafeLint parses with the mixed grammar so the HTML arrives as inert `text` nodes the rules never match; only the code inside the PHP tags is analysed. A pure-template file with no PHP logic produces no violations.
- **The `@` operator is the most literal "suppress the analyser" construct.** SAFE603's headline PHP target is `@expr`, which silences both the runtime warning and any analyser. Every `@` use is flagged (Holzmann rule 10).
- **`global` keyword + `$GLOBALS`.** PHP is the first non-Python language to register SAFE301 (`global_state`) because it has a literal `global` keyword. SAFE302 additionally flags `$GLOBALS[...]` superglobal writes.
- **Numeric `break N`.** PHP's `break` takes an optional level: `break 2;` exits two enclosing loops / switches. SAFE501 resolves the level when deciding whether a `while (true)` has an exiting break.
- **The nullsafe operator `?->`.** SAFE803 treats `$x?->y` as the safe dereference form; only an unguarded `->` / `::` off a nullable-returning call fires.
- **PHPUnit `*Test.php` under `tests/`.** SAFE701 / SAFE702 use the `<ClassName>Test.php` convention rather than a sibling file or `_test` suffix.

## Known limitation: case-sensitive function-name matching

PHP function and method names are **case-insensitive at runtime** (`System(...)` calls the same builtin as `system(...)`), but SafeLint matches resolved call names against the configured lists (`sinks_php`, `io_functions_php`, `dynamic_exec_calls_php`, `assertion_calls_php`, ...) **case-sensitively**. The shipped defaults are lowercase, so canonically-cased code (the overwhelming norm, and what IDEs / formatters produce) matches as expected; a deliberately mixed-case spelling like `SYSTEM($_GET['x'])` would currently evade the corresponding rule. Variable names (including the superglobals `$_GET` / `$_POST`) are genuinely case-sensitive in PHP and are matched exactly. If your code base mixes the case of builtin calls, add the alternate spellings to the relevant `_php` config list. (Superglobal *variable* names are unaffected.)

## Configuration

SafeLint config is read from `[tool.safelint]` in `pyproject.toml` (if your PHP project also has one) or from a standalone `safelint.toml` at the project root. Pure-PHP projects typically prefer the standalone form, which drops the `[tool.safelint]` prefix.

### Per-rule TOML overrides

Override any per-language config list with the `_php` suffix. Each example is shown in **both forms**: `[tool.safelint.rules.<rule>]` for `pyproject.toml` and `[rules.<rule>]` for a standalone `safelint.toml`.

**SAFE303 / SAFE304 `side_effects` - `io_functions_php`:**

```toml
# pyproject.toml
[tool.safelint.rules.side_effects]
io_functions_php = ["var_dump", "printf", "fwrite", "file_put_contents"]   # narrower than the default
```

```toml
# safelint.toml
[rules.side_effects]
io_functions_php = ["var_dump", "printf", "fwrite", "file_put_contents"]
```

**SAFE309 `dynamic_code_execution` - `dynamic_exec_calls_php`:**

```toml
# pyproject.toml
[tool.safelint.rules.dynamic_code_execution]
enabled = true
dynamic_exec_calls_php = ["eval", "assert", "create_function", "call_user_func", "call_user_func_array"]
```

```toml
# safelint.toml
[rules.dynamic_code_execution]
enabled = true
dynamic_exec_calls_php = ["eval", "assert", "create_function", "call_user_func", "call_user_func_array"]
```

**SAFE401 `resource_lifecycle` - `tracked_functions_php`:**

```toml
# pyproject.toml
[tool.safelint.rules.resource_lifecycle]
tracked_functions_php = ["fopen", "fsockopen", "popen", "proc_open", "curl_init", "opendir", "tmpfile"]
```

```toml
# safelint.toml
[rules.resource_lifecycle]
tracked_functions_php = ["fopen", "fsockopen", "popen", "proc_open", "curl_init", "opendir", "tmpfile"]
```

**SAFE601 `missing_assertions` - `assertion_calls_php`:**

```toml
# pyproject.toml
[tool.safelint.rules.missing_assertions]
enabled = true
min_assertions = 2
assertion_calls_php = ["assert", "assertSame", "assertEquals", "assertTrue", "assertThat"]
```

```toml
# safelint.toml
[rules.missing_assertions]
enabled = true
min_assertions = 2
assertion_calls_php = ["assert", "assertSame", "assertEquals", "assertTrue", "assertThat"]
```

**SAFE801 `tainted_sink` - `sinks_php` / `sanitizers_php` / `sources_php`:**

```toml
# pyproject.toml
[tool.safelint.rules.tainted_sink]
enabled = true                                                      # dataflow rules are opt-in
sinks_php = ["eval", "exec", "system", "shell_exec", "unserialize", "query", "mysqli_query"]
sources_php = ["$_GET", "$_POST", "$_REQUEST", "$_COOKIE", "$_SERVER", "$_FILES", "$_ENV"]
sanitizers_php = ["intval", "escapeshellarg", "escapeshellcmd", "htmlspecialchars"]  # add htmlspecialchars for HTML-only sinks
```

```toml
# safelint.toml
[rules.tainted_sink]
enabled = true
sinks_php = ["eval", "exec", "system", "shell_exec", "unserialize", "query", "mysqli_query"]
sources_php = ["$_GET", "$_POST", "$_REQUEST", "$_COOKIE", "$_SERVER", "$_FILES", "$_ENV"]
sanitizers_php = ["intval", "escapeshellarg", "escapeshellcmd", "htmlspecialchars"]
```

**SAFE802 `return_value_ignored` - `flagged_calls_php`:**

```toml
# pyproject.toml
[tool.safelint.rules.return_value_ignored]
enabled = true
flagged_calls_php = ["fwrite", "fclose", "unlink", "rename", "file_put_contents", "mail"]
```

```toml
# safelint.toml
[rules.return_value_ignored]
enabled = true
flagged_calls_php = ["fwrite", "fclose", "unlink", "rename", "file_put_contents", "mail"]
```

**SAFE803 `null_dereference` - `nullable_methods_php`:**

```toml
# pyproject.toml
[tool.safelint.rules.null_dereference]
enabled = true
nullable_methods_php = ["current", "next", "end", "reset", "createFromFormat", "find", "first"]
```

```toml
# safelint.toml
[rules.null_dereference]
enabled = true
nullable_methods_php = ["current", "next", "end", "reset", "createFromFormat", "find", "first"]
```

### Enabling the disabled-by-default rules

The dataflow rules (SAFE801 / SAFE802 / SAFE803), SAFE309, SAFE601, and SAFE603 ship disabled by default. Opt-in via TOML (shown here in `pyproject.toml` form; the standalone `safelint.toml` form drops the `tool.safelint.` prefix):

```toml
[tool.safelint.rules.dynamic_code_execution]
enabled = true

[tool.safelint.rules.missing_assertions]
enabled = true

[tool.safelint.rules.blanket_suppression]
enabled = true

[tool.safelint.rules.tainted_sink]
enabled = true

[tool.safelint.rules.return_value_ignored]
enabled = true

[tool.safelint.rules.null_dereference]
enabled = true
```

## Integration with the PHP tool chain

SafeLint runs alongside the standard PHP tool chain; it doesn't replace any of it. Typical wiring:

* **PHP_CodeSniffer** (`phpcs`) handles coding-standard / formatting checks; safelint doesn't lint style.
* **PHPStan** and **Psalm** cover a broad surface of type-level and correctness analysis. SafeLint targets the engineering-discipline patterns (function shape, error-handling discipline, global state, dataflow taint) those tools leave alone or treat differently; use them together, they complement.
* **Pre-commit**: drop into `.pre-commit-config.yaml`:

  ```yaml
  - repo: https://github.com/shelkesays/safelint
    rev: v2.6.0  # or whatever the latest tag is
    hooks:
      - id: safelint
        additional_dependencies: ['safelint[php]']
        # For a polyglot repo with Python + PHP:
        # additional_dependencies: ['safelint[python,php]']
  ```

  Pre-commit routes `.php` files via the `php` filetype tag in `types_or` (pre-commit's `identify` library recognises it).

* **CI**: invoke `safelint check src/ --fail-on warning` (or `--mode ci`) in your build pipeline. Exit code 0 / 1 / 2 maps cleanly to "passed" / "violations found" / "setup error - install hint emitted on stderr".
* **IDE**: any JSON-output-consuming editor plugin (the safelint JSON schema is stable in v2.0.0+) can surface violations inline.

## Framework presets

PHP source is PHP source - the parser and rule logic are framework-agnostic. The rule *defaults* shift with the framework via `[tool.safelint.php] framework = "<name>"`:

| Framework | When to pick it | What changes |
|---|---|---|
| `vanilla` (default) | Plain PHP, framework-free libraries | Stdlib-only defaults (the lists in the rules table above). The `SAFE905-907` framework rules are disabled. |
| `laravel` | Laravel apps | Adds the raw-SQL query-builder methods `whereRaw` / `orderByRaw` / `havingRaw` / `selectRaw` / `unprepared` to the SAFE801 PHP sinks. **Enables `SAFE905-907`**: Eloquent `$guarded = []` mass-assignment (SAFE906), `$request->all()` / `->input(...)` without `validate()` (SAFE907), and a `'debug' => true` config-array entry (SAFE905). |

```toml
# safelint.toml (standalone) - no [tool.safelint] wrapper
[php]
framework = "laravel"

# Or, in pyproject.toml:
[tool.safelint.php]
framework = "laravel"
```

Explicit per-rule TOML config still wins over the preset; `[tool.safelint.rules.tainted_sink] sinks_php = [...]` overrides whatever the preset planted. The default framework is `vanilla`, so existing users with no `[php]` config see no behaviour change. An unknown framework name surfaces a `safelint: warning:` on stderr and falls back to `vanilla`.

`.env` files are not parsed, so SAFE905 detects a debug flag only where it appears in PHP code (a `config([...])` array or a returned config array), not in `APP_DEBUG=true` env entries - a documented limit. Symfony / WordPress presets are not shipped; track them via [GitHub issues](https://github.com/shelkesays/safelint/issues).
