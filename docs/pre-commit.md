# Pre-commit integration

SafeLint ships a [pre-commit](https://pre-commit.com/) hook so it runs automatically on every `git commit`, before code lands in your history. The hook is the recommended way to wire SafeLint into a project alongside `ruff`, `ty`, `eslint`, and friends: each tool runs in its own isolated environment, gets the staged files passed in, and blocks the commit if anything fails.

The hook is *the same binary* `safelint` you'd invoke from the command line, just driven by pre-commit's argument-passing and exit-code conventions. Everything you can configure via `pyproject.toml` / `safelint.toml` (rules, suppressions, per-file ignores, language-specific options) applies to hook runs identically; the hook is not a separate code path.

## Quick start

Add this block to your `.pre-commit-config.yaml`. Pick the `additional_dependencies` line that matches the language(s) your repo contains:

```yaml
repos:
  - repo: https://github.com/shelkesays/safelint
    rev: v2.1.0  # replace with the latest release tag (Java support requires v2.1.0 or later)
    hooks:
      - id: safelint
        # Required in v2.0.0+. Pick whichever extras match your project's languages:
        additional_dependencies: ['safelint[python]']               # Python-only repo
        # additional_dependencies: ['safelint[javascript]']         # JS-only repo
        # additional_dependencies: ['safelint[typescript]']         # TypeScript repo (bundles JS too)
        # additional_dependencies: ['safelint[java]']     # Java repo, RC pin until v2.1.0 GA (Spring Boot via [tool.safelint.java] framework = "spring-boot")
        # additional_dependencies: ['safelint[python,javascript]']  # mixed monorepo
        # additional_dependencies: ['safelint[all]']      # every supported language, RC pin until v2.1.0 GA so [all] actually includes Java

        args: [--fail-on=error]   # default; use --fail-on=warning for stricter CI
        files: ^src/              # optional, scope to a directory
```

Then install the hooks:

```bash
pre-commit install
```

SafeLint now runs on every `git commit` and blocks the commit if it finds blocking violations.

## What the `additional_dependencies` line does

v2.0.0+ ships every language grammar as an opt-in PEP 621 extra (`[python]`, `[javascript]`, `[typescript]`, `[java]`, `[all]`). Plain `pip install safelint` installs only the engine, no grammars. The same applies to the hook: pre-commit creates an isolated virtualenv per hook revision and installs only what you list in `additional_dependencies`.

`safelint[python]` pulls `tree-sitter-python`. `safelint[javascript]` pulls `tree-sitter-javascript`. `safelint[typescript]` pulls both `tree-sitter-javascript` and `tree-sitter-typescript` (TypeScript projects almost always have `.js` files too: vite / webpack / jest configs, generated declaration shims). `safelint[java]` pulls `tree-sitter-java` and unlocks the optional Spring Boot framework preset configured via `[tool.safelint.java] framework = "spring-boot"`. `safelint[all]` is the kitchen-sink that pulls every supported grammar (`tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-java`) in one go.

You can compose extras: `['safelint[python,javascript]']` for a Python+JS monorepo is exactly the same as listing both individually, just one fewer string. New languages will get their own extras and be folded into `[all]` as they land.

## One hook, every language

The same `id: safelint` handles Python, JavaScript, TypeScript, and Java. There is no `safelint-python` / `safelint-javascript` / `safelint-typescript` / `safelint-java` split. The published hook spec sets:

```yaml
types_or: [python, javascript, ts, tsx, java]
```

so pre-commit's [`identify`](https://github.com/pre-commit/identify) library routes the right files to the hook automatically. SafeLint's engine then dispatches each file to its language-specific rule implementations based on the extension, the file-type tag pre-commit attached is just the routing key.

Every CLI flag (`--fail-on`, `--mode`, `--ignore`, `--format`, `--statistics`) and every TOML option behaves identically across languages. The only per-project knob is which `additional_dependencies` extra you list.

### AssemblyScript: override `types_or`

`.as` files (AssemblyScript) are TypeScript-grammar lintable but pre-commit's `identify` library has no `as` filetype tag. They only carry the generic `text` / `file` tags. Adding `files: \.as$` alone is *not* enough: pre-commit ANDs `types_or` with `files`, so the manifest's `types_or` still excludes the file.

To lint `.as` via the published hook, override `types_or` with a permissive tag `.as` files actually carry, and use `files` to scope the match:

```yaml
- id: safelint
  additional_dependencies: ['safelint[typescript]']
  types_or: [text]              # permissive tag .as files actually carry
  files: \.(ts|tsx|as)$         # restrict to TS-family extensions
```

`types_or: []` does **not** work: pre-commit treats an empty tag list as "no tag matches", not "filter disabled".

## What happens if you forget the extra

The `additional_dependencies` line is genuinely required in v2.0.0+, including for Python projects (which used to work without it in 1.x). Forgetting it doesn't silently pass: SafeLint exits with code **2**, which pre-commit reports as **Failed** (red).

When *every* passed file is skipped for a missing grammar (the usual "forgot the extra" case), the hook prints a single error line with the exact fix:

```text
safelint: error: no files linted, every file pre-commit passed had a grammar that
isn't installed, add 'safelint[python]' to additional_dependencies in your
.pre-commit-config.yaml
```

In a *mixed* run, where some files lint successfully and others are skipped, SafeLint additionally prints one `safelint: warning: skipping .X files …` line per missing grammar as actionable context for the skipped subset. The all-skipped case omits that warning because the error above already carries the same install hint.

See [Exit codes](configuration/cli.md#exit-codes) for the full table of what each exit code means.

## `--fail-on` and `--mode`: lenient vs strict

Two flags govern whether warning-severity violations block the hook:

| Flag | Default | Behaviour |
|---|---|---|
| `--fail-on=error` | (default) | Only `error`-severity violations block. Warnings print to stdout but don't fail the hook. |
| `--fail-on=warning` | | Errors AND warnings block. Strictest setting. |
| `--mode=local` | (default) | Same as `--fail-on=error`. The mode flag is a shorthand that also defaults other behaviours appropriately for interactive use. |
| `--mode=ci` | | Same as `--fail-on=warning`. The mode flag also tunes behaviours suitable for CI environments. |

Precedence: explicit `--fail-on` > explicit `--mode` > built-in default. The published hook ships with `args: [--fail-on=error]` to match the local-dev expectation; flip to `--fail-on=warning` in a CI-specific config (e.g. a separate `.pre-commit-config.ci.yaml`) if you want stricter gating on shared infra.

See [CLI flags and commands](configuration/cli.md) for the full flag reference.

## How files get to the hook

By default, pre-commit passes the staged files. So `git commit` triggers SafeLint on the subset of files in that commit, not the whole repo. This is intentional: pre-commit hooks should be fast on a commit-by-commit basis.

For a full-repo lint:

```bash
pre-commit run safelint --all-files
```

This runs the hook against every file in the repo, useful for the initial pre-commit setup or to backfill compliance after a config change.

### `require_serial: true` (issue [#52](https://github.com/shelkesays/safelint/issues/52))

The published hook manifest sets `require_serial: true`. Without it, pre-commit runs the hook in parallel batches across files, producing one `Found N errors ... (M SAFE### suppressed)` summary block per batch with partial counts. `require_serial: true` collapses execution into one process so the summary aggregates correctly across the whole run.

**Downstream impact:** anyone consuming the published `repo: https://github.com/shelkesays/safelint` hook now sees serialised execution (no inter-batch parallelism). SafeLint is fast per-file (Tree-sitter parse plus rule walks), so this is a non-issue in practice. On very large repos that exceed the OS argv limit, pre-commit may still split into sequential invocations, but each batch's summary is then internally consistent.

## Config files inside the repo

SafeLint reads configuration from (in priority order, highest first):

1. A standalone `safelint.toml` at any parent directory (top-level keys, no wrapper)
2. A `[tool.safelint]` section in `pyproject.toml` at any parent directory
3. Built-in defaults

The hook respects this lookup the same way the CLI does: drop your config wherever it makes sense for your project layout and the hook picks it up.

See [Configuration file](configuration/toml.md) for the schema and [Rules reference](configuration/rules.md) for the per-rule options.

## Suppressions still work

Every suppression mechanism the CLI honours works identically under the hook:

- **Inline `# nosafe`** comments suppress one or more rules on a single line.
- **In-file `# safelint: ignore`** directives suppress rules for the whole file.
- **`[tool.safelint.per_file_ignores]`** globs suppress rules for matched paths.
- **Global `ignore`** lists suppress rules project-wide.

The suppression breakdown surfaces in the hook's per-run summary the same way it does interactively. See [Suppression mechanisms](configuration/suppression.md) for the full model.

## Troubleshooting

### "InstallEnvironmentError: pre-commit failed"

Usually means pre-commit couldn't install one of the `additional_dependencies` entries at all: for example, the requirement string is malformed, the package name / version is wrong, or dependency resolution / download failed. Verify the requirement syntax is valid and that any SafeLint extras use supported names such as `[python]`, `[javascript]`, `[typescript]`, `[java]`, `[python,javascript]`, or `[all]`. A typoed extra name (e.g. `safelint[pythno]`) does *not* fail the install, pip emits a `WARNING: safelint X.Y.Z does not provide the extra 'pythno'` and continues, so the hook env still builds and the typo only shows up at runtime as the missing-grammar / silent-failure case below.

### Hook runs but lints nothing

Either pre-commit isn't passing files (check `types_or` matches your file extensions, or use `--all-files` to test) or the silent-failure guard is firing because the needed grammar wasn't installed (for example, you forgot the extra or typoed an extra name, both of which leave SafeLint installed but without the matching tree-sitter grammar). See ["What happens if you forget the extra"](#what-happens-if-you-forget-the-extra) above for the error message and the fix.

### Hook is slow on the first run

pre-commit creates an isolated virtualenv per `rev:` and installs `safelint` plus its grammar(s) on first invocation. Subsequent commits reuse the cached env. Bump the `rev:` pin and the first commit after the bump re-installs.

### CI reports "passed" but I see errors locally

You're probably hitting the `--fail-on=error` default. Errors are blocking but warnings aren't (severity is per-rule, see [Rules reference](configuration/rules.md)). Set `args: [--fail-on=warning]` in your CI pre-commit config to gate on warnings too.

### `.as` files aren't being linted

See [AssemblyScript: override `types_or`](#assemblyscript-override-types_or) above. The default `types_or` list doesn't include `.as`; you need to override it.

## See also

- **[CLI flags and commands](configuration/cli.md)** for the full flag reference, exit codes, and machine-readable output formats.
- **[Configuration file](configuration/toml.md)** for the TOML schema and per-rule options.
- **[Suppression mechanisms](configuration/suppression.md)** for inline `# nosafe`, in-file `# safelint: ignore`, glob-based `per_file_ignores`, and global `ignore`.
- **[Rules reference](configuration/rules.md)** for every rule's code, severity, and configurable knobs.
