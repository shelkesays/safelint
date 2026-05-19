# safelint skill: JavaScript addendum

Language-specific notes for the JavaScript (Node) target. Mirrors `src/safelint/languages/javascript.py` in the safelint source tree. The skill core (`claude/SKILL.md` for Claude Code, each peer client's own file for other agents) handles the universal flow; this file holds JavaScript-specific detail.

## Install nuance

safelint is a Python package, not an npm package. v2.0.0+ ships the JavaScript grammar in the `[javascript]` extra, so the install needs that suffix or safelint won't have a JS parser:

```bash
pip install 'safelint[javascript]'
# or, in a project that already uses uv:
uv add --dev 'safelint[javascript]'
# or, for a TS project that also has .js files (vite/eslint/jest configs):
pip install 'safelint[typescript]'   # bundles tree-sitter-javascript automatically
```

After install, `safelint` is on `PATH`. Run it from the JavaScript project's root the same way as for a Python project, it auto-detects the language by file extension.

If you run plain `pip install safelint` (no extra) by mistake, the first run emits `safelint: warning: skipping .js files, install with: pip install 'safelint[javascript]'` and exits with code 2. Re-install with the extra and retry.

For pre-commit integration, the published hook accepts JavaScript via the `javascript` filetype tag in `types_or`:

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.1.0rc1  # pin to a release (use a recent tag; v2.1.0rc1 also unlocks the Java extra if you later add .java files)
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[javascript]']
```

## File extensions

safelint lints `.js`, `.mjs`, and `.cjs` files in JavaScript / Node projects. TypeScript (`.ts` / `.tsx` / `.as` / AssemblyScript) is also fully supported but lives in a separate language module, see the [TypeScript skill addendum](typescript.md) for TS-specific notes. JSX (`.jsx`) is not yet registered (would land as part of JavaScript when added). The skill doesn't need to filter by extension, `safelint check` walks the project and picks up the registered extensions automatically.

## Runtime presets

JavaScript source is the same regardless of where it runs, but the *APIs* it interacts with are runtime-specific. ``[tool.safelint.javascript] runtime = "<name>"`` selects which API surface to assume when the rule defaults are picked. Five presets ship today:

| Runtime | When to pick it | What changes |
|---|---|---|
| `node` (default) | Backend Node.js apps; CLIs; serverless functions running on Node-compatible runtimes | Node `fs` / `child_process` / `process` / streams. The values you see in the rule descriptions above. |
| `browser` | Browser-side JS, ES module bundles, anything running in a `<script>` or via a bundler targeting browsers | Web APIs only. DOM lookups (`getElementById` / `querySelector`) for SAFE803; observers + workers + WebSocket for SAFE401; `localStorage` / `setItem` for SAFE304; `globalThis` / `window` / `self` / `document` for SAFE302. Drops Node `fs` / `child_process` / `process` entirely. |
| `deno` | Deno scripts and Deno Deploy applications | `Deno.*` API surface. ``Deno.open`` / ``Deno.connect`` / ``Deno.listen`` for SAFE401; ``Deno.run`` / ``Deno.Command`` for SAFE801; ``Deno`` added to global namespaces; `process` and `window` dropped. |
| `cloudflare-workers` | Cloudflare Workers (V8 isolates), also a reasonable starting point for other Web-API-only edge runtimes | KV / R2 / Durable Object methods (``put`` / ``delete`` / ``get`` for SAFE802 and SAFE803), ``Request`` body methods (``json`` / ``formData`` / ``arrayBuffer``) as taint sources, minimal global-namespace list. No `fs` surface (Workers has none). |
| `bun` | Bun runtime | Node defaults plus Bun-specific extras (``Bun.serve`` / ``Bun.spawn``). Most things behave identically to the Node preset. |

Configure via TOML:

```toml
[tool.safelint.javascript]
runtime = "browser"   # or "deno" / "cloudflare-workers" / "bun" / "node"
```

User-explicit ``_javascript`` config keys (e.g. ``[tool.safelint.rules.tainted_sink] sinks_javascript = [...]``) still win over the preset, the preset only changes the *default* list, not your overrides.

Unknown runtime names surface a ``safelint: warning:`` line on stderr and fall back to ``"node"``. The validation list lives in ``safelint.core.config._JS_VALID_RUNTIMES``; adding a new preset is a one-dict-entry change in the same module.

**Pure WebAssembly (`.wat` / `.wasm`)** and **AssemblyScript** are out of scope for this language registration; they're separate Tree-sitter grammars and would land as their own ``LanguageDefinition`` registrations.

## Suppression directive form

Line-style only, `// nosafe`, `// nosafe: SAFE101`, `// safelint: ignore`, `// safelint: ignore: SAFE101`. Block-style directives (`/* nosafe */`) are *not* recognised in this release; if a line has both code and a violation, prefer a trailing line comment.

```js
result = eval(userInput);  // nosafe: SAFE801
```

## Rules ported to JavaScript

18 of safelint's 24 user-facing rules lint JavaScript: the 16 cross-language rules (Python / JS / TS / Java) plus SAFE302 (`global_mutation`, Python / JS / TS only, not ported to Java yet) plus SAFE305 (`wide_scope_declaration`, JavaScript-family only). The table below names them and notes any JS-specific behaviour the agent should be aware of when explaining a violation. Rules not listed here remain Python-only (SAFE201, SAFE301) or Java + Spring Boot only (SAFE901-904), see *Rules that stay Python-only* below.

| Code | Rule | JavaScript-specific notes |
|---|---|---|
| SAFE101 | function_length | Default cap is 60 source lines (configurable via `[tool.safelint.rules.function_length]` `max_lines`). Counts function declarations, function expressions, arrow functions, generator functions, and class methods uniformly. `count_mode = "statements"` is Python-only, JS files use `lines` (default) or `logical_lines`. |
| SAFE102 | nesting_depth | Counts `if` / `for` / `for…in` / `while` / `do…while` / `switch` / `try` blocks. Default max is 2. Optional chaining (`?.`) does not count toward depth; it's a single AST node. |
| SAFE103 | max_arguments | Counts named parameters, default-value parameters (`b = 5`), rest parameters (`...args`), and destructured parameters (`{a, b}` / `[x, y]` each count as one). Default cap is 7. Unlike Python, there is no `self` / `cls` skip, every parameter counts. |
| SAFE104 | complexity | Cyclomatic complexity, every `if` / `else if` / `for` / `while` / `case` / `catch` / ternary adds one, plus `&&` / `||` / `??` short-circuit operators. Arithmetic / comparison `binary_expression` nodes (`+`, `>`, etc.) explicitly do NOT count. Default cap is 10. |
| SAFE202 | empty_except | Fires on `catch (e) {}` (truly empty), `catch {}` (ES2019 optional binding form), `catch (e) { ; }` (single empty statement), `catch (e) { 0; }` / `catch (e) { null; }` / `catch (e) { "TODO"; }` (single literal statement). Template strings with `${...}` substitution are NOT treated as no-ops. |
| SAFE203 | logging_on_error | Catch blocks must call a logging method or rethrow. Recognises `console.log` / `console.error` / `console.warn` / `console.info` / `console.debug` / `console.trace`, plus generic `logger.*`, `pino.*`, `bunyan.*` (anything where `call_name` resolves to one of `log` / `info` / `warn` / `error` / `debug` / `trace`). `throw e;` (single-identifier throw of the caught binding) is treated as a re-raise and exempt; `throw new Error(...)` constructs a new error and still requires logging. |
| SAFE303 | side_effects_hidden | Pure-named function (matches a configured `pure_prefixes` list) calling an I/O primitive. JS default I/O list: `log`, `error`, `warn`, `info`, `debug`, `fetch`, `readFile`, `writeFile`, `readFileSync`, `writeFileSync`, `open`. Per-language config key: `io_functions_javascript`. |
| SAFE302 | global_mutation | Function-body assignments to a configured global namespace fire the rule. Default namespaces: `globalThis`, `window`, `global`, `self`, `process`. Walks the receiver chain leftward, `process.env.NODE_ENV = '...'` resolves to `process` and fires. Reading a global (`return globalThis.env;`) does NOT fire, only writes do. Top-level (module-scope) assignments do NOT fire either; that's module setup, not the bug the rule guards against. Per-language config: `global_namespaces_javascript`. |
| SAFE304 | side_effects | Any function (not name-signalled for I/O) calling an I/O primitive. Same JS default list as SAFE303. The `io_name_keywords` exemption (e.g. `logEvent`, `writeData`, `fetchUser`) works the same way as Python: substring match against the lowercased function name. |
| SAFE305 | wide_scope_declaration | JavaScript `var` is function-scoped (hoisted across blocks); `let` / `const` are block-scoped. The rule fires on every `var` declaration; the fix is mechanical (replace with `let` if reassigned, `const` otherwise). JavaScript-only, no Python equivalent. |
| SAFE401 | resource_lifecycle | A call to a configured acquirer name fires unless wrapped in a `try { ... } finally { ... }` somewhere up the AST ancestor chain. Default JS acquirers: `createReadStream`, `createWriteStream`, `openSync`, `createServer`, `createConnection`, `connect`, `createWorker`. **Heuristic only:** the rule doesn't verify that the `finally` block actually closes the resource, only that *some* finally exists. Catches the most common "I created a stream and didn't think about cleanup at all" leak. The newer `using` declarations (Stage 3 / Node 22+) aren't yet recognised; for now, wrap the call inside `try / finally`. Per-language config: `tracked_functions_javascript`. |
| SAFE501 | unbounded_loops | `while (true)` without a `break` fires the same as Python `while True:`. The "non-comparison condition" heuristic is *Python-only*, JS idioms like `while (queue.length)` / `while (token = stream.next())` / `while (cursor)` are entirely valid and bounded; firing on every non-comparison would flood with false positives. Break-scope boundaries: `for_statement`, `for_in_statement`, `while_statement`, `do_statement`, `switch_statement`, plus all function types. |
| SAFE601 | missing_assertions | JS has no built-in `assert` keyword, the rule walks for *calls* to a configured set of assertion function names. Default set covers Node's `assert` module helpers (`assert`, `ok`, `equal`, `strictEqual`, `deepEqual`, `deepStrictEqual`, `notEqual`, `notStrictEqual`, `rejects`, `throws`, `doesNotThrow`, `doesNotReject`, `fail`, `ifError`, `match`), `console.assert`, plus test framework entry points (`expect` for Jest / Chai / Vitest, `should` for Should.js). Disabled by default like in Python, opt in with `[tool.safelint.rules.missing_assertions]` `enabled = true`. |
| SAFE701 | test_existence | JS source pairs with any of `<stem>.test.{js,mjs,cjs}` (Jest convention) or `<stem>.spec.{js,mjs,cjs}` (Mocha / Karma convention) under `test_dirs` (default `["tests"]`). The "expected" filename in violation messages surfaces the Jest-style `.test.<source-extension>` form as the canonical suggestion. |
| SAFE702 | test_coupling | Same filename patterns as SAFE701. Coupling is satisfied when *any* candidate test filename for the source file appears in the changed-files set, `foo.test.js` *or* `foo.spec.js` both count. |
| SAFE801 | tainted_sink | Intra-procedural taint analysis. Function parameters seed the tainted set (including destructured names: `function f({userInput})` taints `userInput`; `function f([first, ...rest])` taints both). Taint propagates through `const` / `let` / `var` declarations, `assignment_expression`, `augmented_assignment_expression` (`+=`), template strings (`\`prefix ${tainted}\``), array / object literals, spread, and member / subscript access on tainted receivers. JS default sinks: `eval`, `Function` (constructor), `execScript`, `exec`, `execSync`, `spawn`, `spawnSync`, `setTimeout`, `setInterval`. JS default sanitizers: `escape`, `sanitize`, `encodeURIComponent`, `encodeURI`, `DOMPurify`. JS default sources: `prompt`, `readline`, `stdin`, `input`. Per-language config keys: `sinks_javascript` / `sanitizers_javascript` / `sources_javascript`. |
| SAFE802 | return_value_ignored | Bare calls (an `expression_statement` whose first child is a call) to a configured set of return-value-significant functions. JS default `flagged_calls_javascript`: Node fs / stream / process methods whose return value or returned promise carries success/failure info, `write`, `writeFile`, `writeFileSync`, `unlink`, `unlinkSync`, `rename`, `renameSync`, `mkdir`, `mkdirSync`, `rmdir`, `rmdirSync`, `rm`, `rmSync`, `send`, `sendall`, `exec`, `execSync`, `spawn`, `spawnSync`. **Common gotcha:** an unhandled rejected promise (e.g. `fs.writeFile(...)` returning a Promise that gets dropped) silently swallows errors, capturing the result with `await` or `.then()` resolves the violation. |
| SAFE803 | null_dereference | Chained `.field` / `[idx]` access on a call returning `null` / `undefined`. **Optional chaining is the safe form**: `arr.find(...)?.name` is null-safe and is NOT flagged. JS default `nullable_methods_javascript`: Array (`find`, `pop`, `shift`), Map (`get`), DOM (`getElementById`, `querySelector`, `closest`), RegExp (`exec`, `match`). |

### Rules that stay Python-only

The following rules don't apply to JavaScript and stay registered for Python only, they will not fire on `.js` / `.mjs` / `.cjs` files.

| Code | Rule | Why JS-only-skipped |
|---|---|---|
| SAFE201 | bare_except | Python `except:` (no exception type) silently catches `KeyboardInterrupt` and `SystemExit`. JavaScript `try/catch` always catches every throw type by language design (no typed exception filtering); the Python-specific process-signal hazard doesn't exist. SAFE202 (empty catch) and SAFE203 (catch must log) cover the related JS concerns. |
| SAFE301 | global_state | Python `global` keyword has no clean JS equivalent. The Python rule fires on the *declaration* `global x` regardless of whether a write follows; JavaScript has no read-only-global declaration form, so SAFE301 would always be a strict subset of SAFE302 on JS. JS users get the same protection from SAFE302 alone. |

## Idiomatic fix patterns

When offering to walk the user through fixes, use these JavaScript-native patterns:

### SAFE101 (function too long)

Suggest decomposition by **responsibility**: extract cohesive blocks (validation, transformation, I/O, response shaping) into separate functions. Avoid splitting purely by line count.

```javascript
// Before, 80 lines
function processUserData(payload) {
  // ... 30 lines of validation ...
  // ... 20 lines of transformation ...
  // ... 30 lines of response building ...
}

// After
function processUserData(payload) {
  const cleaned = validatePayload(payload);
  const record = buildRecord(cleaned);
  return makeResponse(record);
}
```

### SAFE102 (nesting too deep)

Use early returns / guard clauses rather than nested `if`s:

```javascript
// Before
function f(user) {
  if (user !== null) {
    if (user.isActive) {
      if (user.hasPermission("read")) {
        return load(user);
      }
    }
  }
  return null;
}

// After
function f(user) {
  if (user === null) return null;
  if (!user.isActive) return null;
  if (!user.hasPermission("read")) return null;
  return load(user);
}
```

### SAFE103 (too many arguments)

Group related arguments into a single options object. This is the standard JavaScript convention:

```javascript
// Before
function render(width, height, dpi, colour, font, fontSize, lineHeight, padding) {
  // ...
}

// After
function render({ width, height, dpi, colour, font, fontSize, lineHeight, padding }) {
  // ...
}
```

### SAFE202 (empty catch)

Always do *something* in a catch, log, rethrow, or recover. Empty catches are the JavaScript equivalent of swallowing exceptions in Python.

```javascript
// Before
try {
  riskyCall();
} catch (e) {}

// After, log and decide
try {
  riskyCall();
} catch (e) {
  console.error('riskyCall failed:', e);
  // ...handle or rethrow as appropriate
}
```

### SAFE203 (logging on error)

Every catch that swallows an error must log it. `console.error` is the minimum; structured loggers (`pino`, `winston`, `bunyan`) are preferred in production.

```javascript
// Before
try {
  await fetchUser(id);
} catch (e) {
  state.failed = true;
}

// After
try {
  await fetchUser(id);
} catch (e) {
  logger.error({ err: e, userId: id }, 'fetchUser failed');
  state.failed = true;
}
```

### SAFE304 (hidden I/O)

Two patterns work well, mirroring the Python guidance:

1. **Rename to signal intent.** A function called `printSummary` is exempt; one called `summary` that internally calls `console.log` isn't.
2. **Inject the I/O primitive.** Pass the logger / writer / fetcher in as an argument so the function becomes pure modulo its dependencies.

```javascript
// Before
function renderReport(data) {
  console.log(formatReport(data));   // SAFE304
}

// After (option 1: rename)
function printReport(data) {
  console.log(formatReport(data));   // name signals intent
}

// After (option 2: inject)
function renderReport(data, write = console.log) {
  write(formatReport(data));
}
```

### SAFE501 (unbounded loop)

If a `while (true)` is genuinely needed (e.g. an event loop, a server's accept loop), make sure there is at least one `break` path inside. If the loop is meant to terminate on a condition, write the condition explicitly.

```javascript
// Before
while (true) {
  doWork();
}

// After
while (true) {
  const item = queue.shift();
  if (item === undefined) break;   // explicit termination
  doWork(item);
}
```

### SAFE601 (missing assertions)

If your project uses Node's built-in `assert` module, the rule recognises every helper out of the box. For test-framework code, `expect(...)` (Jest, Chai, Vitest) is also recognised. The fix is usually to add a guard / sanity check at the function's entry:

```javascript
// Before
function process(items) {
  return items.map(transform);
}

// After
function process(items) {
  assert(Array.isArray(items), 'items must be an array');
  return items.map(transform);
}
```

### SAFE801 (tainted sink): JavaScript-specific

The biggest hidden-flow trap in JS is template-string interpolation:

```javascript
// Before, userInput taints the template, then taint reaches eval
function run(userInput) {
  const code = `result = ${userInput};`;
  eval(code);   // SAFE801
}

// After, sanitize / use a safer execution model
function run(userInput) {
  const safe = sanitize(userInput);
  eval(`result = ${safe};`);   // OK if ``sanitize`` is in the configured list
  // …or refactor: avoid eval entirely; parse + interpret instead.
}
```

For DOM-XSS contexts, `DOMPurify(userInput)` is recognised as a sanitizer by default.

### SAFE802 (return value ignored)

The Node fs / promise APIs are the most common offenders, a discarded promise from `fs.writeFile` will never throw on failure unless awaited or `.catch`-ed:

```javascript
// Before
fs.writeFile('out.txt', data);   // SAFE802, promise discarded

// After
await fs.writeFile('out.txt', data);

// Or, in a callback context, explicitly handle the result
fs.writeFile('out.txt', data, (err) => {
  if (err) logger.error({ err }, 'write failed');
});
```

### SAFE302 (global mutation)

Module-level mutable state should be encapsulated, not written from inside arbitrary functions:

```javascript
// Before
function setupCache() {
  globalThis.cache = new Map();   // SAFE302
  process.env.READY = 'true';     // SAFE302
}

// After, pass state in / return state
function buildCache() {
  return new Map();
}

// Caller decides where to put it; configuration lives in dedicated config
// loading code, not scattered across functions.
const cache = buildCache();
```

### SAFE401 (resource lifecycle)

The Node-canonical fix is `try { ... } finally { ... }`. The newer `using` declarations are also acceptable (and recognised in a future safelint release).

```javascript
// Before
function readData(path) {
  const stream = fs.createReadStream(path);   // SAFE401
  return processStream(stream);
}

// After (option 1: try/finally)
function readData(path) {
  let stream;
  try {
    stream = fs.createReadStream(path);
    return processStream(stream);
  } finally {
    if (stream) stream.close();
  }
}

// After (option 2: ``using``, Stage 3 / Node 22+)
async function readData(path) {
  using stream = fs.createReadStream(path);   // auto-cleaned up at scope exit
  return await processStream(stream);
}
```

### SAFE803 (null dereference)

JS's optional chaining is the cleanest fix:

```javascript
// Before
const name = users.find(u => u.id === userId).name;   // SAFE803

// After, optional chaining + default
const name = users.find(u => u.id === userId)?.name ?? '<unknown>';

// Or, explicit guard
const user = users.find(u => u.id === userId);
if (user === undefined) {
  return '<unknown>';
}
const name = user.name;
```

## Stdin mode for editor / Claude Code unsaved buffers

If the user is asking about a buffer that isn't saved to disk (e.g. they paste JS code in chat and ask for a safelint review), use stdin mode with a `.js` (or `.mjs` / `.cjs`) pseudo-filename so language detection picks JavaScript:

```bash
echo "<source code>" | safelint --stdin --stdin-filename buffer.js --format json
```

The pseudo-filename drives language detection, drop the `.js` and detection falls back to whatever the default is (today: Python).
