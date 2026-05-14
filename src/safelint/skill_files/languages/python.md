# safelint skill: Python addendum

Language-specific notes for the Python target. Mirrors `src/safelint/languages/python.py` in the safelint source tree. The skill core (`SKILL.md`) handles the universal flow; this file holds Python-specific detail.

## Install nuance

safelint is a Python package and Python support ships in the `[python]` extra in v2.0.0+. The plain `pip install safelint` command installs only the engine and won't lint anything until an extra is added:

```bash
uv add --dev 'safelint[python]'        # uv-based projects
pip install 'safelint[python]'         # everything else
```

After install, `safelint` is on `PATH` (entry point declared in `pyproject.toml`).

For pre-commit integration, add to `.pre-commit-config.yaml`. Note that v2.0.0+ requires `additional_dependencies` even for Python-only projects (the hook env is isolated and needs its own grammar install):

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.0.0rc3  # pin to a release (use the GA tag once v2.0.0 ships)
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[python]']
```

If you forget `additional_dependencies`, safelint exits with code 2 on the first run; pre-commit reports the hook as **Failed** (red), not silently green. The stderr message tells you exactly what to add.

## File extensions

safelint lints `.py` and `.pyw` files in Python projects. The skill doesn't need to filter by extension, `safelint check` walks the project and picks up the registered extensions automatically.

## Language-specific rule phrasing

When the user asks "why is this flagged?", the universal rationale in the SKILL.md crib sheet is correct, but Python phrasing helps:

| Code | Rule | Python-specific notes |
|---|---|---|
| SAFE101 | function_length | Default cap is 60 source lines (configurable via `[tool.safelint.rules.function_length]` `max_lines`). Class methods and module-level functions are both counted; the cap is per-function. |
| SAFE102 | nesting_depth | Counts `if`/`for`/`while`/`with`/`try` blocks. Default max is 2. Comprehension nesting (`[x for x in y for z in w]`) does not count toward the depth; it's a single AST node. |
| SAFE103 | max_arguments | Counts positional, keyword, `*args`, `**kwargs`, and keyword-only arguments. `self`/`cls` are *included* in the count. Default cap is 7. |
| SAFE104 | complexity | Cyclomatic complexity: every `if`/`elif`/`else`/`for`/`while`/`except`/`and`/`or`/ternary adds one. Default cap is 10. |
| SAFE201 | bare_except | Fires on `except:` (no exception type). The Python-specific concern is that bare `except` swallows `KeyboardInterrupt` and `SystemExit`, breaking Ctrl-C and `sys.exit()`. Always use `except Exception:` at minimum. |
| SAFE202 | empty_except | Fires on `except <Type>: pass` and `except <Type>: ...`. Exception handlers should at least log; silent suppression is a Power-of-Ten violation. |
| SAFE301 | global_state | Fires on the `global` keyword inside functions. Python's `global` declaration makes the function depend on module-level state. |
| SAFE302 | global_mutation | Fires when a function declares `global x` *and* writes to `x`. Reading is fine; writing is the Power-of-Ten concern. |
| SAFE303 | side_effects_hidden | Fires when a function with a "pure" name prefix (`get_`, `compute_`, `is_`, `has_`, `validate_`, `parse_`, etc.) calls an I/O primitive (`open`, `print`, `subprocess.run`, etc.). |
| SAFE304 | side_effects | Fires when *any* function calls I/O primitives at unexpected sites, distinct from SAFE303 in that it doesn't require a pure-named caller. Suppress with `# nosafe: SAFE304` for intentional I/O wrappers. |
| SAFE501 | unbounded_loops | Fires on `while True:` without a `break`. Any loop without a clear termination condition triggers this. |

## Idiomatic fix patterns

When offering to walk the user through fixes, use these Python-native patterns:

### SAFE101 (function too long)

Suggest decomposition by **responsibility**: identify cohesive blocks (validation, transformation, I/O, return-shape building) and extract each as a private helper. Avoid splitting purely by line count; that produces helpers no one can name.

```python
# Before: 80 lines
def process_user_data(payload: dict) -> Response:
    # ... 30 lines of validation ...
    # ... 20 lines of transformation ...
    # ... 30 lines of building response ...

# After
def process_user_data(payload: dict) -> Response:
    cleaned = _validate_payload(payload)
    record = _build_record(cleaned)
    return _make_response(record)
```

### SAFE102 (nesting too deep)

Use early returns / guard clauses rather than nested `if`s:

```python
# Before
def f(user):
    if user is not None:
        if user.is_active:
            if user.has_permission("read"):
                return load(user)
    return None

# After
def f(user):
    if user is None:
        return None
    if not user.is_active:
        return None
    if not user.has_permission("read"):
        return None
    return load(user)
```

### SAFE103 (too many arguments)

Group related arguments into a dataclass or `TypedDict`. For instance:

```python
# Before
def render(width, height, dpi, colour, font, font_size, line_height, padding):
    ...

# After
@dataclass
class RenderOptions:
    width: int
    height: int
    dpi: int
    colour: str
    font: str
    font_size: int
    line_height: float
    padding: int

def render(options: RenderOptions):
    ...
```

### SAFE201 (bare except)

Always specify the exception type. Bare `except:` is rarely the right answer.

```python
# Before
try:
    risky()
except:
    handle()

# After: narrow as much as you can
try:
    risky()
except (ValueError, OSError):
    handle()
```

### SAFE301 / SAFE302 (global state)

Convert module-level mutable state into either a class instance or a thread-local context object. If it must stay global, document why and suppress with `# nosafe: SAFE301` *with a comment* explaining the constraint.

### SAFE304 (hidden I/O)

Two patterns work well:

1. **Rename to signal intent.** A function called `print_summary` is exempt; one called `summary` that internally prints isn't. Renaming is often the cheapest fix.
2. **Inject the I/O primitive.** Pass the file handle / logger / printer in as an argument so the function becomes pure modulo its dependencies.

```python
# Before
def render_report(data):
    print(format_report(data))   # SAFE304

# After (option 1: rename)
def print_report(data):
    print(format_report(data))   # name signals intent, suppressed by rule heuristic

# After (option 2: inject)
def render_report(data, write=print):
    write(format_report(data))   # caller controls the I/O primitive
```

## Stdin mode for editor / Claude Code unsaved buffers

If the user is asking about a buffer that isn't saved to disk (e.g. they paste code in chat and ask for a safelint review), use stdin mode:

```bash
echo "<source code>" | safelint --stdin --stdin-filename buffer.py --format json
```

The pseudo-filename drives language detection (so use a `.py` suffix to ensure Python rules fire) and shows up as the violation file path.
