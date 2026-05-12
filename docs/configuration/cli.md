# CLI flags and commands

These are passed on the command line and are not part of the config file. For TOML keys see [Configuration file](toml.md); for ways to silence a single rule see [Suppression mechanisms](suppression.md).

## Top-level commands and flags

SafeLint's top-level surface mirrors ruff's: every command can be invoked positionally (`safelint check ...`), and every flag has both a short and a long form where conventional. Help and version are intercepted before any command parsing so they always work, even when no subcommand is given.

```text
$ safelint --help
SafeLint: Holzmann-inspired safety lint rules and pre-commit integration for Python, JavaScript, and TypeScript.

Usage: safelint [OPTIONS] <COMMAND>

Commands:
  check    Scan a file or directory for safety violations
  skill    Manage the bundled AI-client skill / project rule (Claude, Cursor, Copilot, Gemini, Windsurf, codex, Continue.dev, Cline, aider, Trae, Antigravity, Zed)
  help     Print this message or the help of the given subcommand
  version  Display SafeLint's version

Options:
  -h, --help     Print help (see a summary with -h)
  -V, --version  Print version

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

ANSI colour is auto-disabled when stdout is not a TTY (piping to a file produces clean text), matching the rest of safelint's output conventions.

## `safelint check` flags

| Flag | Default | What it does |
|---|---|---|
| `--all-files` | off | Scan every supported source file under the target (today: `.py`, `.pyw`, `.js`, `.mjs`, `.cjs`). Default (without this flag) is to check only git-modified files. |
| `--fail-on` | from config | Override the minimum severity that blocks the run: `error` or `warning`. |
| `--mode` | from config | `local` (only errors block) or `ci` (warnings block too). |
| `--config` | auto-discovered | Path to a config file (`pyproject.toml` or `safelint.toml`) or a directory to use as the config search root. |
| `--ignore` | none | Repeatable flag to suppress a rule for this run only, e.g. `--ignore SAFE101 --ignore function_length`. Stacks on top of the `ignore` list in the config file. |
| `--format` | `pretty` | Output format: `pretty` (ruff/ty-style coloured), `json` (stable schema documented in [JSON schema](../json-schema.md)), or `sarif` (SARIF 2.1.0 for GitHub code scanning). |
| `--statistics` | off | After the run, print a per-rule violation-count table (active + suppressed). Pretty mode only. Useful for CI snapshots and finding the most-fired rules. |
| `--no-cache` | off | Disable the per-file lint-result cache. By default safelint memoises rule output keyed on `sha256(source + engine config + filepath)` in `.safelint_cache/` next to your config. |
| `--check-skill-freshness` | off | *Added in 1.9.0.* Before linting, verify each installed AI-client skill (Claude Code at `~/.claude/skills/safelint/`, Cursor at `~/.cursor/rules/safelint.mdc`, project-scoped equivalents) matches the bundled version in the active wheel. Stale installs surface as `safelint: warning: …` lines on stderr. Informational only — doesn't fail the lint. Use `safelint skill status` (also added in 1.9.0; exits 1 if stale) for the dedicated CI-friendly check. |
| `--stdin` | off | Read source from stdin instead of from disk. Designed for editor extensions linting un-saved buffers. Pair with `--stdin-filename`. |
| `--stdin-filename` | (none) | Pseudo-filename for `--stdin` input — drives language detection by extension and is shown as the violation file path. Required when `--stdin` is set. |

**When to use `--all-files`:**

- CI pipelines (clean checkout, no modified files in git terms)
- Running a one-off full audit
- `pre-commit run --all-files` already passes all files directly; the hook mode handles this automatically.

## `safelint` hook mode flags (pre-commit)

Pre-commit passes the staged files as positional arguments automatically. `--fail-on`, `--mode`, and `--ignore` are all supported here.

```yaml
# .pre-commit-config.yaml
- id: safelint
  args: [--fail-on=error]   # or --fail-on=warning for strict CI

# Ignore specific rules in the hook:
- id: safelint
  args: [--fail-on=error, --ignore=SAFE203, --ignore=side_effects]
```

## Skill freshness commands (1.9.0)

After `pip install --upgrade safelint`, the bundled skill files in the wheel update but copy-mode installs at `~/.claude/skills/safelint/` and `~/.cursor/rules/safelint.mdc` stay frozen at whatever version was last installed. Two commands answer "is my installed skill up to date?":

```bash
# Dedicated subcommand — pipe-friendly, exits 1 if any install differs from bundled
safelint skill status

# Or fold the same check into a normal lint run (opt-in stderr warning, doesn't fail the run)
safelint check --check-skill-freshness --all-files .
```

`safelint skill status` walks every registered AI client × both scopes (user / project) and prints one line per detected install showing whether it's *fresh* (matches the bundled version) or *differs from bundled*. Exit code is 0 when everything matches, 1 when anything differs.

A few details worth knowing:

- **Symlink installs** (those created with `safelint skill install --symlink`) always show as fresh, because the installed file is a symlink pointing back at the bundled location inside the wheel. After `pip upgrade safelint`, the upgrade is visible immediately — no `skill update` needed.
- **Copy installs** are content-compared against the bundled file. If they match byte-for-byte, fresh; otherwise, differs.
- **Edge case — a symlink install hand-replaced with an identical copy** is reported as fresh (the freshness check compares content, not install mode). The user-visible behaviour is fine *today* because the content matches, but the next `pip upgrade safelint` won't propagate to that location anymore. If you want to re-establish the live link, run `safelint skill update --symlink --force`.

The canonical CI / upgrade-script idiom is:

```bash
safelint skill status || safelint skill update
```

`safelint check --check-skill-freshness` is the same drift check folded into a normal lint run — emits one `safelint: warning:` line per stale install but doesn't change the lint exit code. Off by default so day-to-day `safelint check` invocations stay fast (no extra FS scan).

A locally-customised install will surface as *differs from bundled*; the diagnostic message explicitly mentions that case so customisers can ignore it. See [Updating, removing, freshness checks](../ai-clients/lifecycle.md) for the full workflow.

## Skill update + remove commands (1.10.0)

Two follow-on commands to round out the install lifecycle:

```bash
safelint skill update                          # idempotent refresh — no-op when fresh
safelint skill update --force                  # re-install every detected install
safelint skill remove                          # delete every detected install
safelint skill remove --symlink                # delete only symlink-shape installs (keep copies)
safelint skill remove --path /unusual/place    # delete one specific location
safelint skill remove --dry-run                # preview without deleting
```

Both commands inherit `--client` and `--project` from `install`, but the meaning of `--client auto` is *different* from install's:

- **`install --client auto`** asks: *"which AI client(s) does this user use?"* — and answers that by scanning the cwd for marker files (`CLAUDE.md`, `.cursor/`, etc.).
- **`update --client auto`** and **`remove --client auto`** ask: *"what's already installed?"* — and answer that by scanning the actual install paths (`~/.claude/skills/safelint/`, etc.).

This distinction matters when the user has marker files but no install yet (only `install` will fire) or has an install but the marker file has been deleted (only `update`/`remove` will fire).

**`update` flag semantics — `--force`:** without `--force`, `update` only re-installs the locations that have actually drifted from the bundle. Running it when everything is fresh is a no-op: it just prints "already fresh" lines and exits 0. That's what makes it safe to run from cron, CI, or pre-commit hooks — calling `update` repeatedly does nothing extra. With `--force`, it re-installs every detected location regardless of drift; useful for reverting a customised install back to the bundled content.

**`update` flag semantics — `--symlink` and shape preservation:** by default, `update` preserves the existing install's shape. A copy install stays copy after refresh; a symlink install stays symlink. To *switch* a copy install to symlink mode, pass `--symlink` explicitly. There's one wrinkle: if the copy install is already fresh, `update` is normally a no-op — so converting copy → symlink in that case requires `update --force --symlink` to force the re-install. Switching the other way (symlink → copy) isn't supported via `update`; do `remove` followed by `install` (without `--symlink`) instead, so the intent is unambiguous.

**`remove` flag semantics:** flags compose orthogonally — the absence of a flag means "no filter", *not* "only the opposite":

| Invocation | What gets removed |
|---|---|
| `remove` (no flags) | Every detected install — copy + symlink, every client, both scopes |
| `remove --symlink` | Only symlink-shape installs (copies survive) |
| `remove --client cursor` | All detected Cursor installs (both shapes, both scopes) |
| `remove --project` | All detected project-scope installs (user-scope survives) |
| `remove --path PATH` | Exactly one location, regardless of every other flag |

In particular, `safelint skill remove` without `--symlink` removes **both** copy and symlink installs — it's not a "remove copies only" command. `--symlink` is a *filter* you can opt into when you want to be selective, not a creation-mode toggle like in `install`.

`remove` only deletes the install location. Bundled files inside `site-packages/` are never touched (`shutil.rmtree` doesn't follow symlinks for deletion, and `unlink` removes the symlink itself, not its bundled target). The worst case for a misfired `remove` is "re-run `install` to get the skill back". See [Updating, removing, freshness checks](../ai-clients/lifecycle.md#removing-an-installed-skill) for the full filesystem-level breakdown.
