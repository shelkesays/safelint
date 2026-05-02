# safelint Claude Code skill

A Claude Code skill that runs `safelint` against the current project and presents the violations in a reviewable format.

Once installed, ask Claude Code things like:

- "run safelint"
- "lint my changes with safelint"
- "do a Power-of-Ten review on src/api/auth.py"
- "safelint check, all files"

…and the skill takes over: invokes `safelint check ... --format json`, parses the output, groups violations by file, and offers to walk through fixes.

## Install

The skill lives in this repo at `skills/safelint/SKILL.md`. To activate it for your user account:

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/safelint" ~/.claude/skills/safelint
```

(Replace `$(pwd)` with the absolute path to your safelint checkout if you're not running from the repo root.)

Prefer a copy over a symlink? Just `cp -r skills/safelint ~/.claude/skills/`. You'll need to repeat that on each safelint upgrade if you want skill changes to land.

To activate it only inside one project:

```bash
mkdir -p .claude/skills
cp -r /path/to/safelint/skills/safelint .claude/skills/
```

## Requirements

- `safelint` 1.5.0 or later on `PATH` — the skill relies on the `--format json` output and the v1.5.0 JSON schema.
- A Python project with at least one `.py` file (otherwise there's nothing to lint).

## What the skill does

1. Verifies `safelint` is installed (`command -v safelint`).
2. Picks a target based on what you said (modified files / all files / a specific path).
3. Runs `safelint check <target> --format json` and parses the result.
4. Prints a one-line headline (`Found N errors, M warnings across K files`) plus a per-file breakdown.
5. Offers a single concrete next step (walk through fixes, focus on the most common code, etc.).

The skill never auto-fixes — every edit goes through a confirmation step.

## What the skill does NOT do

- It does not replace `ruff` / `ty` / `mypy`. Those handle style and types; safelint enforces a different, narrower set of safety rules. Use both.
- It does not run `safelint --all-files` by default. Git-modified files only, unless you ask.
- It does not invent violations or guess at intent. Everything it reports comes from the JSON output.

## Customising

The skill is just a Markdown file. Edit `SKILL.md` to tune wording, swap the suggested follow-up question, or add project-specific guidance (e.g. "for this repo, always pass `--mode ci`"). Claude Code re-reads the file on each invocation.

## See also

- The main safelint docs: [`README.md`](../../README.md), [`CONFIGURATION.md`](../../CONFIGURATION.md)
- JSON output schema: [`docs/JSON_SCHEMA.md`](../../docs/JSON_SCHEMA.md)
