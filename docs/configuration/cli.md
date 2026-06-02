# CLI flags and commands

Reference for every command and flag safelint exposes. For TOML keys see [Configuration file](toml.md); for ways to silence a single rule see [Suppression mechanisms](suppression.md).

## Top-level surface

SafeLint's CLI mirrors ruff's: every command can be invoked positionally (`safelint check ...`), help and version are intercepted before any command parsing so they always work even with no subcommand, and ANSI colour auto-disables when stdout is not a TTY.

```text
$ safelint --help
SafeLint: Holzmann-inspired safety lint rules and pre-commit integration for Python, JavaScript, and TypeScript.

Usage: safelint [OPTIONS] <COMMAND>

Commands:
  check       Scan a file or directory for safety violations
  skill       Manage the bundled AI-client skill / project rule (Claude, Cursor, Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed, Warp)
  list-rules  Print the rule catalogue (filter by --language, render as text / json / markdown / sarif)
  help        Print this message or the help of the given subcommand
  version     Display SafeLint's version

Options:
  -h, --help     Print help (see a summary with -h)
  -V, --version  Print version
  --list-rules   Alias for the list-rules subcommand

Global options:
  --fail-on <LEVEL>        Minimum severity that blocks the run: error | warning
  --mode <MODE>            Execution mode: local (only errors block) | ci (warnings block too)
  --ignore <CODE>          Repeatable; suppress a rule for this run
  --format <FORMAT>        Output format: pretty (default) | json | sarif
  --statistics             Print a per-rule violation count summary
  --no-cache               Disable the per-file lint-result cache
  --stdin                  Read source from stdin (editor mode)
  --stdin-filename <PATH>  Pseudo-filename for stdin input
```

Equivalent invocations:

| Goal | Forms |
|---|---|
| Top-level help | `safelint help`, `safelint --help`, `safelint -h` |
| Subcommand help | `safelint help check`, `safelint check --help` |
| Version | `safelint version`, `safelint --version`, `safelint -V` |
| Rule catalogue | `safelint list-rules`, `safelint --list-rules` |

## `safelint check`

The primary linting command. Scans a file or directory and emits violations.

```bash
safelint check src/                  # lint git-modified files under src/
safelint check src/ --all-files      # lint every supported source file under src/
safelint check src/app.py            # lint a single file
safelint check . --format=json       # machine-readable output for editors / CI
```

| Flag | Default | What it does |
|---|---|---|
| `--all-files` | off | Scan every supported source file under the target (`.py`, `.pyw`, `.js`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.as`, `.java`, `.rs`). Default (without this flag) is to check only git-modified files. |
| `--fail-on` | from config | Override the minimum severity that blocks the run: `error` or `warning`. |
| `--mode` | from config | `local` (only errors block) or `ci` (warnings block too). |
| `--config` | auto-discovered | Path to a config file (`pyproject.toml` or `safelint.toml`) or a directory to use as the config search root. |
| `--ignore` | none | Repeatable flag to suppress a rule for this run only, e.g. `--ignore SAFE101 --ignore function_length`. Stacks on top of the `ignore` list in the config file. |
| `--format` | `pretty` | Output format: `pretty` (ruff/ty-style coloured), `json` (stable schema documented in [JSON schema](../json-schema.md)), or `sarif` (SARIF 2.1.0 for GitHub code scanning). |
| `--statistics` | off | After the run, print a per-rule violation-count table (active + suppressed). Pretty mode only. Useful for CI snapshots and finding the most-fired rules. |
| `--no-cache` | off | Disable the per-file lint-result cache. By default safelint memoises rule output keyed on `sha256(source + engine config + filepath)` in `.safelint_cache/` next to your config. |
| `--check-skill-freshness` | off | *Added in 1.9.0.* Before linting, verify each installed AI-client skill matches the bundled version. Stale installs surface as `safelint: warning:` lines on stderr. Informational only, doesn't fail the lint. See [`safelint skill status`](#safelint-skill-status) for the dedicated CI-friendly check. |
| `--stdin` | off | Read source from stdin instead of from disk. See [`safelint --stdin`](#safelint-stdin-editor-mode) for the editor-mode workflow. |
| `--stdin-filename` | (none) | Pseudo-filename for `--stdin` input; drives language detection and shows up as the violation file path. Required when `--stdin` is set. |

**When to use `--all-files`:** CI pipelines (clean checkout, no modified files in git terms), one-off full audits. `pre-commit run --all-files` already passes all files directly, the hook mode handles this automatically.

## `safelint list-rules`

*Added in 2.2.0.* Prints the rule catalogue so AI agents, CI dashboards, and docs-generation pipelines can introspect what safelint will check without grepping skill files. The `--list-rules` form (as a top-level flag) is an alias for the subcommand; the two are interchangeable. Categories are derived from the leading digit of each `SAFExxx` code (1xx function shape, 2xx error handling, 3xx side effects / state, 4xx resource lifecycle, 5xx loop safety, 6xx documentation, 7xx test coverage, 8xx dataflow, 9xx framework-specific).

```bash
safelint list-rules                                       # text table, all rules
safelint list-rules --language=rust                        # rust + cross-language subset
safelint list-rules --enabled-only --language=python       # python's active default surface
safelint list-rules --format=json | jq '.rules | length'   # programmatic count
safelint list-rules --format=markdown > docs/rules.md      # docs regeneration
safelint list-rules --format=sarif                         # GitHub Code Scanning catalogue feed
safelint --list-rules --language=java                      # flag-alias form (same effect)
```

| Flag | Default | What it does |
|---|---|---|
| `--language <LANG>` | (no filter) | Restrict to one language: `python`, `javascript`, `typescript`, `java`, `rust`. Filters by the rule's `language` tuple, so cross-language rules show under any of their languages. |
| `--format <FMT>` | `text` | `text` (aligned table grouped by category band), `json` (versioned document with `code`, `name`, `severity`, `default_enabled`, `languages`, `category`, `description`), `markdown` (one table per category band), or `sarif` (SARIF 2.1.0 catalogue document with rules under `runs[0].tool.driver.rules[]`). |
| `--enabled-only` | off | Drop rules that are off by default. Useful for "what fires out of the box?" views. |

Exit codes: `0` on success, `2` when the filter combination matches zero rules (so a typo in a CI script like `--language=pythn` doesn't silently produce an empty document).

## `safelint skill install`

Install the bundled AI-client skill into the detected client(s) at the chosen scope. Auto-detect scans for marker files in cwd (project scope) or home (user scope) and installs into every matching client.

```bash
safelint skill install                              # auto-detect, project-first then home
safelint skill install --project                    # auto-detect, project scope only
safelint skill install --client cursor              # explicit client, user scope
safelint skill install --client claude --project    # explicit client + scope
safelint skill install --symlink                    # symlink to bundled file (auto-updates on pip upgrade)
safelint skill install --force                      # replace existing install
```

| Flag | Default | What it does |
|---|---|---|
| `--client <NAME>` | `auto` | One of `auto`, `claude`, `cursor`, `copilot`, `gemini`, `windsurf`, `codex`, `continue`, `cline`, `aider`, `trae`, `antigravity`, `zed`, `warp`. With `auto`, safelint detects which client(s) you use from marker files and installs into all of them. |
| `--project` | off | Force project-scope install (`<cwd>/.<client>/...`). With `--client auto`, also restricts detection to cwd. |
| `--symlink` | off | Symlink to the bundled file instead of copying. `pip upgrade safelint` then auto-updates the skill. Requires symlink support (POSIX, or Windows developer mode). |
| `--force` | off | Replace any existing skill / rule at the target location. |

**Project-scope-only clients:** specs with no user-scope file (currently just **Warp**) refuse `--client warp` without `--project` and exit 1 with a clear error. See the [Warp page](../ai-clients/clients/warp.md) for the contract.

**OpenCode (`.opencode/`) projects:** auto-detected via the codex spec; AGENTS.md is auto-created when absent so OpenCode receives the safelint section. See [codex's OpenCode subsection](../ai-clients/clients/codex.md#opencode-auto-detection) for the full lifecycle.

## `safelint skill status`

*Added in 1.9.0.* Compares every detected installed skill against the bundled version. Pipe-friendly: exits 1 if anything differs, 0 when everything is fresh. The canonical CI / upgrade-script idiom is `safelint skill status || safelint skill update`.

```bash
safelint skill status                              # check every detected install
```

`safelint skill status` walks every registered AI client and both scopes (user / project) and prints one line per detected install showing whether it's *fresh* (matches the bundled version) or *differs from bundled*.

A few details:

- **Symlink installs** (created with `safelint skill install --symlink`) always show as fresh, the installed file is a symlink pointing back at the bundled location inside the wheel. After `pip upgrade safelint`, the upgrade is visible immediately; no `skill update` needed.
- **Copy installs** are content-compared against the bundled file. Match byte-for-byte → fresh; otherwise → differs.
- **Edge case, a symlink hand-replaced with an identical copy** reports as fresh (the freshness check compares content, not install mode). User-visible behaviour is fine *today* because content matches, but the next `pip upgrade safelint` won't propagate to that location. Re-establish the link with `safelint skill update --symlink --force`.
- **Locally-customised installs** show as *differs from bundled*; the diagnostic message explicitly mentions that case so customisers can ignore it.

Folded into a normal lint run: `safelint check --check-skill-freshness --all-files .` emits the same drift check as one `safelint: warning:` line per stale install but doesn't change the lint exit code. Off by default so day-to-day `safelint check` invocations stay fast (no extra FS scan).

## `safelint skill update`

*Added in 1.10.0.* Refresh installed skills whose content has drifted from the bundled wheel. Idempotent: no-op when fresh, so safe to run from cron / CI / pre-commit hooks.

```bash
safelint skill update                          # idempotent refresh, no-op when fresh
safelint skill update --force                  # re-install every detected install
safelint skill update --symlink --force        # convert a copy install to symlink mode
```

| Flag | Default | What it does |
|---|---|---|
| `--client <NAME>` | `auto` | With `auto`, scans the actual install paths (not marker files) for "what's already installed?". This is the key difference from `install --client auto`, see below. |
| `--project` | off | Restrict to project-scope installs. |
| `--symlink` | off | Re-create the install in symlink mode (only meaningful when switching a copy install to symlink, which requires `--force` since `update` is a no-op when content is already fresh). |
| `--force` | off | Refresh every matching install regardless of drift status. Useful for reverting customisations to the bundled content. |

**`update --client auto` vs `install --client auto`:** the two interpretations of "auto" differ deliberately. `install --client auto` asks *"which AI client(s) does this user use?"* and answers via marker-file detection. `update --client auto` asks *"what's already installed?"* and answers by scanning install paths. The distinction matters when the user has marker files but no install yet (only `install` will fire) or has an install but the marker file has been deleted (only `update` / `remove` will fire).

**Shape preservation:** by default, `update` preserves the existing install's shape. A copy install stays copy after refresh; a symlink install stays symlink. To *switch* a copy install to symlink mode, pass `--symlink` explicitly. If the copy install is already fresh, `update` is a no-op, so the conversion in that case requires `update --force --symlink`. Switching the other way (symlink → copy) isn't supported via `update`; do `remove` followed by `install` (without `--symlink`) instead, so the intent is unambiguous.

## `safelint skill remove`

*Added in 1.10.0.* Delete detected installed skills. Flag-driven filters compose orthogonally.

```bash
safelint skill remove                          # delete every detected install
safelint skill remove --client cursor          # only Cursor installs (both shapes, both scopes)
safelint skill remove --project                # only project-scope installs (user-scope survives)
safelint skill remove --symlink                # only symlink-shape installs (copies survive)
safelint skill remove --path /unusual/place    # one specific location, bypasses every other flag
safelint skill remove --dry-run                # preview without deleting
```

| Flag | Default | What it does |
|---|---|---|
| `--client <NAME>` | `auto` | Filter by client name (auto-detects from install paths, same as `update`). |
| `--project` | off | Restrict to project-scope installs. |
| `--symlink` | off | Filter to symlink-shape installs only, copy installs survive. Composable with `--client` / `--project`. |
| `--path <PATH>` | (none) | Remove one specific install location, overrides every other flag including auto-detect. |
| `--dry-run` | off | Preview what would be removed without deleting anything. |

**Filter semantics:** flags compose orthogonally; absence of a flag means "no filter", *not* "only the opposite":

| Invocation | What gets removed |
|---|---|
| `remove` (no flags) | Every detected install, copy + symlink, every client, both scopes |
| `remove --symlink` | Only symlink-shape installs (copies survive) |
| `remove --client cursor` | All detected Cursor installs (both shapes, both scopes) |
| `remove --project` | All detected project-scope installs (user-scope survives) |
| `remove --path PATH` | Exactly one location, regardless of every other flag |

In particular, `safelint skill remove` without `--symlink` removes **both** copy and symlink installs; it's not a "remove copies only" command. `--symlink` is a *filter* you can opt into when you want to be selective, not a creation-mode toggle like in `install`.

**Safety:** `remove` only deletes the install location. Bundled files inside `site-packages/` are never touched (`shutil.rmtree` doesn't follow symlinks for deletion, and `unlink` removes the symlink itself, not its bundled target). The worst case for a misfired `remove` is "re-run `install` to get the skill back". See [Updating, removing, freshness checks](../ai-clients/lifecycle.md#removing-an-installed-skill) for the full filesystem-level breakdown.

## `safelint skill path`

Print the on-disk location of bundled skill / rule files. Useful for debugging or for editor integrations that need to read the bundled content directly.

```bash
safelint skill path                       # prints the bundle ROOT directory (parent of every per-client subdir)
safelint skill path --client claude       # prints the bundled Claude SKILL.md path
safelint skill path --client warp         # prints the bundled WARP.md path
```

| Flag | Default | What it does |
|---|---|---|
| `--client <NAME>` | (none) | Print that client's bundled artefact file. Without it, prints the bundle root directory containing every per-client subdir and the shared `languages/<lang>.md` addendums. |

Doesn't write or modify anything; pure introspection.

## `safelint --stdin` (editor mode)

Read source from stdin and lint it as if it were the file named by `--stdin-filename`. Designed for editor extensions linting un-saved buffers without round-tripping through a temp file.

```bash
echo "x = 1" | safelint --stdin --stdin-filename=buffer.py
cat foo.ts | safelint --stdin --stdin-filename=foo.ts --format=json
```

| Flag | Default | What it does |
|---|---|---|
| `--stdin` | off | Read source from stdin instead of disk. The pseudo-filename from `--stdin-filename` drives language detection by extension and shows up as the violation file path. |
| `--stdin-filename <PATH>` | `<stdin>.py` | Pseudo-filename for the stdin buffer. Required in practice (the default falls back to a Python extension); set it to the real file path so language detection and `exclude_paths` matching behave the same as a disk-backed lint. |

**Cache behaviour:** stdin mode unconditionally bypasses the on-disk cache. Every keystroke in an editor produces a slightly different buffer (cache miss every time anyway), and writing to `.safelint_cache/` per keystroke would just churn the project tree. `--no-cache` is therefore irrelevant here.

`--fail-on` / `--mode` / `--ignore` / `--format` all work in stdin mode and follow the same semantics as `safelint check`.

## `safelint version` and `safelint help`

Informational commands; trivial but listed for completeness.

```bash
safelint version          # prints "safelint X.Y.Z" and exits 0
safelint --version
safelint -V

safelint help             # top-level help (the ruff-style usage block above)
safelint help check       # equivalent to `safelint check --help`
safelint help list-rules  # equivalent to `safelint list-rules --help`
safelint help skill       # equivalent to `safelint skill --help`
safelint --help
safelint -h
```

Both are intercepted before any subcommand routing, so they always work even when no subcommand is given and even when global flags (e.g. `--format json`) are interleaved.

## Hook mode (`safelint <files>`)

Pre-commit invokes safelint with the staged file paths as positional arguments. No subcommand involved; safelint detects the hook-mode shape (positional args that don't start with a known subcommand) and treats them as files to lint. `--fail-on`, `--mode`, and `--ignore` are all supported.

```yaml
# .pre-commit-config.yaml
- id: safelint
  args: [--fail-on=error]   # or --fail-on=warning for strict CI

# Ignore specific rules in the hook:
- id: safelint
  args: [--fail-on=error, --ignore=SAFE203, --ignore=side_effects]
```

Pre-commit hooks pass every staged file regardless of extension; safelint filters internally to the supported source extensions before linting. Files with unsupported extensions are silently skipped (the silent-failure guard at exit code 2 catches the case where *every* passed file was unsupported, see below).

## Exit codes

SafeLint's exit code tells CI / pre-commit how the run finished:

| Code | Meaning |
|------|---------|
| `0` | Clean run, no blocking violations (suppressed violations don't count). |
| `1` | One or more blocking violations found (severity ≥ `--fail-on`). |
| `2` | **Silent-failure guard.** Fires in *every* output mode (pretty / JSON / SARIF) so a CI pipeline can't silently report clean. Three distinct triggers, see below for the exact stderr message each emits. |

### Exit code 2: silent-failure triggers

All three triggers print a `safelint: error:` line to stderr before exiting; pre-commit treats exit 2 as a hook *Failed* (red), not Passed. Fix by installing the matching grammar extra (`pip install 'safelint[python]'` etc.) or, for pre-commit users, adding `additional_dependencies: ['safelint[<lang>]']` to your `.pre-commit-config.yaml`.

| Trigger | Path | Stderr message |
|---|---|---|
| **Directory mode** (`safelint check src/ --all-files`) discovers files but none get linted because every grammar is missing | `_check_exit_code` after `_run_check`'s lint pass | `safelint: error: no files linted, every supported file was skipped because its grammar package isn't installed, install with: pip install 'safelint[<lang>]'` |
| **Git-modified mode** (default `safelint check src/`), user modified files but every one was dropped by the supported-extensions filter | `_handle_no_targets` in the no-targets short-circuit | `safelint: error: no files linted, every git-modified source file has a grammar that isn't installed, install with: pip install 'safelint[<lang>]'` |
| **Hook mode** (pre-commit invokes `safelint <files>`), every passed file has an extension whose grammar isn't installed | `_guard_hook_silent_failure` before the engine runs | `safelint: error: no files linted, every file pre-commit passed had a grammar that isn't installed, add 'safelint[<lang>]' to additional_dependencies in your .pre-commit-config.yaml` |

Each error embeds the install hint for the missing extras so the failure is self-explanatory even when no prior warnings were printed (e.g. the no-targets short-circuit, or any machine-output run). The hint phrasing flips between `install with: pip install 'safelint[<lang>]'` (direct CLI) and `add 'safelint[<lang>]' to additional_dependencies in your .pre-commit-config.yaml` (pre-commit, detected via `PRE_COMMIT=1`).

**Per-extension stderr warnings** (one line per missing grammar, listing the affected extensions) are emitted **only in pretty (human) CLI output and in the pre-commit hook flow**. Machine-readable modes, `--format json` and `--format sarif`, deliberately suppress those warnings so stderr stays parseable for CI / editor pipelines; the embedded install hint inside the `safelint: error:` line above is the only signal you get there.
