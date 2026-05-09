# safelint skill — JavaScript addendum

Language-specific notes for the JavaScript (Node) target. Mirrors `src/safelint/languages/javascript.py` in the safelint source tree. The skill core (`SKILL.md`) handles the universal flow; this file holds JavaScript-specific detail.

## Install nuance

safelint is a Python package, not an npm package. Install it the same way you would for a Python project — even when linting JavaScript:

```bash
pip install safelint
# or, in a project that already uses uv:
uv add --dev safelint
```

After install, `safelint` is on `PATH`. Run it from the JavaScript project's root the same way as for a Python project — it auto-detects the language by file extension.

For pre-commit integration, the published hook accepts JavaScript via the `javascript` filetype tag in `types_or`:

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v1.13.0
  hooks:
    - id: safelint
```

## File extensions

safelint lints `.js`, `.mjs`, and `.cjs` files in JavaScript / Node projects. JSX (`.jsx`) and TypeScript (`.ts`, `.tsx`) are *not* registered today — JSX may be added later as part of JavaScript; TypeScript is a separate language addition. The skill doesn't need to filter by extension — `safelint check` walks the project and picks up the registered extensions automatically.

## Suppression directive form

Line-style only — `// nosafe`, `// nosafe: SAFE101`, `// safelint: ignore`, `// safelint: ignore: SAFE101`. Block-style directives (`/* nosafe */`) are *not* recognised in this release; if a line has both code and a violation, prefer a trailing line comment.

```js
result = eval(userInput);  // nosafe: SAFE801
```

## Language-specific rule phrasing

When the user asks "why is this flagged?", the universal rationale in the SKILL.md crib sheet is correct, but JavaScript phrasing helps. Note that not every Python rule has a JavaScript counterpart yet — the table below covers the rules ported in v1.13.x. Rules not listed here remain Python-only.

| Code | Rule | JavaScript-specific notes |
|---|---|---|
| SAFE101 | function_length | Default cap is 60 source lines (configurable via `[tool.safelint.rules.function_length]` `max_lines`). Counts function declarations, function expressions, arrow functions, generator functions, and class methods uniformly. |
| SAFE102 | nesting_depth | Counts `if` / `for` / `for…in` / `while` / `do…while` / `switch` / `try` blocks. Default max is 2. Optional chaining (`?.`) does not count toward depth — it's a single AST node. |
| SAFE103 | max_arguments | Counts named parameters, rest parameters (`...args`), and destructured parameters. Default cap is 7. |
| SAFE104 | complexity | Cyclomatic complexity — every `if` / `else if` / `for` / `while` / `case` / `catch` / `&&` / `||` / `??` / ternary adds one. Default cap is 10. |

## Idiomatic fix patterns

When offering to walk the user through fixes, use these JavaScript-native patterns:

### SAFE101 (function too long)

Suggest decomposition by **responsibility**: extract cohesive blocks (validation, transformation, I/O, response shaping) into separate functions. Avoid splitting purely by line count.

```javascript
// Before — 80 lines
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

## Stdin mode for editor / Claude Code unsaved buffers

If the user is asking about a buffer that isn't saved to disk (e.g. they paste JS code in chat and ask for a safelint review), use stdin mode with a `.js` (or `.mjs` / `.cjs`) pseudo-filename so language detection picks JavaScript:

```bash
echo "<source code>" | safelint --stdin --stdin-filename buffer.js --format json
```

The pseudo-filename drives language detection — drop the `.js` and detection falls back to whatever the default is (today: Python).
