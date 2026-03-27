# SafeLint

SafeLint is a Python code safety checker. It reads your Python files and flags patterns that commonly cause bugs, crashes, or hard-to-debug problems — things like functions that are too long, deeply nested `if` statements, silent error handling, and unchecked inputs flowing into dangerous calls.

It works as a standalone command-line tool and as a [pre-commit](https://pre-commit.com) hook so it runs automatically before every commit.

---

## Installation

```bash
pip install safelint
```

To also support YAML config files (`.safelint.yaml`):

```bash
pip install "safelint[yaml]"
```

---

## Usage

**Check a directory:**

```bash
safelint check src/
```

**Check specific files** (pre-commit style):

```bash
safelint src/mymodule.py src/utils.py
```

**Fail on warnings too** (useful in CI):

```bash
safelint check src/ --fail-on=warning
```

**Run in CI mode** (warnings become blocking):

```bash
safelint check src/ --mode=ci
```

---

## Pre-commit integration

Add this to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/shelkesays/safelint
    rev: v0.3.0  # replace with a real tag or commit SHA until a release is tagged
    hooks:
      - id: safelint
```

Then install the hooks:

```bash
pre-commit install
```

SafeLint will now run on every `git commit` and block the commit if it finds errors.

**Override the default args** if you want to change which severity level blocks commits:

```yaml
repos:
  - repo: https://github.com/shelkesays/safelint
    rev: v0.3.0  # replace with a real tag or commit SHA until a release is tagged
    hooks:
      - id: safelint
        args: [--fail-on=warning]  # block on warnings too (recommended for CI)
        files: ^src/               # limit to your source directory
```

---

## What it checks

| Rule | What it flags |
|---|---|
| `function_length` | Functions longer than 60 lines |
| `nesting_depth` | Control flow nested more than 2 levels deep |
| `max_arguments` | Functions with more than 7 parameters |
| `complexity` | Functions with high cyclomatic complexity |
| `bare_except` | `except:` with no exception type |
| `empty_except` | `except` blocks that do nothing (`pass`) |
| `logging_on_error` | Except blocks that swallow errors silently |
| `global_state` | Use of the `global` keyword inside functions |
| `global_mutation` | Writing to global variables inside functions |
| `unbounded_loops` | `while True` loops with no `break` |
| `side_effects_hidden` | Pure-looking functions that secretly do I/O |
| `side_effects` | Functions that call `print`, `open`, etc. without signalling intent |
| `resource_lifecycle` | Files or connections opened outside a `with` block |

**Dataflow rules** (opt-in, disabled by default):

| Rule | What it flags |
|---|---|
| `tainted_sink` | User input flowing into `eval`, `exec`, `subprocess`, etc. without sanitization |
| `return_value_ignored` | Discarding the return value of calls like `subprocess.run` or `file.write` |
| `null_dereference` | Chaining methods directly on calls that can return `None`, e.g. `d.get("key").strip()` |

---

## Configuration

SafeLint is configured via your `pyproject.toml` under `[tool.safelint]`, or via a `.safelint.yaml` file. See [CONFIGURATION.md](CONFIGURATION.md) for all available options.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run the linter on itself
safelint check src/
```

---

## Background

SafeLint is based on **"The Power of Ten — Rules for Developing Safety Critical Code"** by Gerard J. Holzmann (NASA/JPL). The paper was written for C, but the ideas translate directly to Python.

The ten rules from the paper, and how SafeLint maps them:

| # | Original rule (C) | SafeLint equivalent |
|---|---|---|
| 1 | Simple control flow — no `goto`, no recursion | `nesting_depth`, `complexity` |
| 2 | All loops must have a fixed upper bound | `unbounded_loops` |
| 3 | No heap memory allocation after init | — (not applicable to Python) |
| 4 | Functions fit on one printed page (~60 lines) | `function_length` |
| 5 | Minimum two assertions per function | `missing_assertions` |
| 6 | Declare variables at the smallest scope | — (Python handles this) |
| 7 | Check return values of all non-void functions | `return_value_ignored` |
| 8 | Limit preprocessor use | — (not applicable to Python) |
| 9 | Restrict pointer use to one dereference | `null_dereference` |
| 10 | Compile with all warnings enabled; use static analysis | safelint itself |

The original paper is available at: https://spinroot.com/gerard/pdf/P10.pdf
