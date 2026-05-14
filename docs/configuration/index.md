# Configuration

SafeLint is configured in three places, in roughly increasing order of permanence:

1. **The CLI**, `safelint check --fail-on=warning --ignore SAFE801`. One-off overrides, CI knobs, hook flags. See [CLI flags and commands](cli.md).
2. **In your source files**, `# nosafe` on a line, `# safelint: ignore` at the top of a file. The escape hatch when a violation is intentional. See [Suppression mechanisms](suppression.md).
3. **A TOML config**, `[tool.safelint]` in `pyproject.toml` or a standalone `safelint.toml`. Project-wide policy: thresholds, per-rule options, glob-scoped ignores. See [Configuration file](toml.md).

Per-rule options (`max_lines`, `max_depth`, dataflow `sinks`, …) and what each rule actually flags live on the [Rules reference](rules.md).

## At a glance

```toml
# pyproject.toml: every key is optional; defaults match the section below.
[tool.safelint]
mode = "local"                            # "local" → fail on errors only; "ci" → fail on warnings too
fail_on = "error"                         # overrides mode if both are set
# Append project-specific dirs on top of the built-in vendor-dir
# defaults (.venv/, venv/, node_modules/, build/, dist/, __pycache__/,
# .pytest_cache/, .ruff_cache/, .mypy_cache/, .tox/, .nox/, htmlcov/,
# site-packages/). Prefer this over ``exclude_paths`` (which replaces
# defaults entirely: see the Configuration file reference).
extend_exclude_paths = ["migrations/**"]
ignore = ["SAFE203"]

[tool.safelint.per_file_ignores]
"tests/**" = ["SAFE101", "SAFE103"]

[tool.safelint.rules.function_length]
max_lines = 80
```

The same keys at the top level (without the `[tool.safelint]` wrapper) work in a standalone `safelint.toml`. When both files are present, `safelint.toml` wins.

## How to choose a suppression mechanism

Pick the narrowest scope that matches your intent:

| Want to silence … | Use |
|---|---|
| One specific line | [`# nosafe`](suppression.md#inline-nosafe) |
| One whole file (auto-generated, vendor, fixture) | [`# safelint: ignore`](suppression.md#file-level-safelint-ignore) |
| Files matching a glob pattern (e.g. all tests) | [`per_file_ignores` in TOML](toml.md#per-file-ignore-list) |
| The rule everywhere in the project | [`ignore` in TOML](toml.md#global-ignore-list) or `--ignore` on the CLI |

All four compose: the broader scopes still apply on top of the narrower ones.

## Where to go next

- **[CLI flags and commands](cli.md)**, every `safelint` and `safelint skill` command, with examples.
- **[Suppression mechanisms](suppression.md)**, `# nosafe`, `# safelint: ignore`, the end-of-run summary, and stderr diagnostics.
- **[Configuration file](toml.md)**, top-level keys, ignore lists, per-file ignores, severity model, adoption path.
- **[Rules reference](rules.md)**: every rule, what it flags, its TOML options.
