---
name: safelint
description: Run safelint static analysis on Python code in the current project and present Holzmann Power-of-Ten safety violations grouped by file. Use this when the user asks to "safelint check", "lint with safelint", "run a safety review", "Power-of-Ten review", or any similar request for safelint's specific Python rule set. For generic linting requests use the project's configured tools (ruff, etc.) instead.
---

# safelint skill

You are running the safelint static-analysis CLI on behalf of the user. safelint enforces Holzmann's "Power of Ten" safety rules adapted for Python — function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and similar.

The user has asked for a safelint check. Follow the steps below.

## Step 1 — Verify safelint is installed

Run `command -v safelint` via Bash. If it returns non-zero (not installed):

- Tell the user safelint isn't on PATH. Suggest one of:
  - `uv add safelint` (if the project uses `uv`)
  - `pip install safelint` (otherwise)
- Stop. Do not proceed until they install it.

## Step 2 — Decide what to lint

Pick a target based on the user's wording:

| User said… | Target | Flags |
|---|---|---|
| (nothing specific) or "modified files", "my changes", "what I'm working on" | `.` | (none — defaults to git-modified) |
| "all files", "everything", "the whole repo" | `.` | `--all-files` |
| A specific file or directory path | that path | (omit `--all-files` if a single file) |

If the user mentions a CI mode or strictness, also pass `--mode ci` (treats warnings as blocking) or `--fail-on warning`.

## Step 3 — Run safelint with structured output

Always use `--format json` so you can parse the result reliably:

```bash
safelint check <target> --format json [--all-files]
```

Notes:
- Exit 0 means no blocking violations; exit 1 means at least one. **Either way the JSON document is on stdout** — keep parsing it.
- Stderr may contain config warnings (typo guards, oversize-skip notes). Surface those to the user only if non-empty.
- If `safelint` itself crashes (bug), say so and include the stderr verbatim.

## Step 4 — Parse the JSON

The schema (stable since v1.5.0):

```json
{
  "version": "1.x.y",
  "summary": {
    "files_checked": N,
    "violations": N,
    "errors": N,
    "warnings": N,
    "blocking": N,
    "fail_on": "error" | "warning",
    "suppressed": {"total": N, "by_code": {"SAFE501": 3, ...}}
  },
  "violations": [
    {"code": "SAFE101", "rule": "function_length", "severity": "error",
     "filepath": "src/foo.py", "lineno": 42, "message": "Function ..."}
  ],
  "suppressed": [ /* same shape */ ]
}
```

## Step 5 — Present results

Order matters — lead with what the user needs first:

1. **One-line headline.** Examples:
   - `Clean run — 12 files checked, no violations.` (if zero)
   - `Clean run — 12 files checked. 3 violations suppressed (2 SAFE501, 1 SAFE304).` (clean but with suppressions)
   - `Found 4 errors and 7 warnings across 5 files (1 suppressed).` (otherwise)

2. **Per-file breakdown** (skip files with zero violations). For each file, list violations one per line:

   ```
   src/api/auth.py
     SAFE101  L42  Function "verify_token" is 78 lines (max 60)              [function_length]
     SAFE102  L51  Nesting depth is 4 (max 2)                                 [nesting_depth]
     SAFE304  L88  Function "_run_pipeline" calls I/O primitive "open" — ...  [side_effects]
   ```

   Pad codes / line numbers / messages so columns line up. Don't emit ANSI colour — the user's terminal already renders it via the `pretty` mode if they want that; the skill output should be plain.

3. **Suggested next step.** Pick exactly one based on the result:
   - 0 violations → say "All checks passed." and stop. No follow-up.
   - 1–4 violations → "Want me to walk through fixes one at a time?"
   - 5+ violations → "Want me to start with the most common issue (CODE — N occurrences)?"
   - Many `function_length` / `complexity` violations clustered in one file → "These look like one large function — want me to extract some helpers?"

## Step 6 — When the user asks "why is this flagged?"

Briefly explain the Power-of-Ten rationale (one or two sentences). Reference the rule code and the underlying safety property. Don't lecture — keep it tight.

Quick reference for the most-fired rules:

| Code | Rule | Why it matters |
|---|---|---|
| SAFE101 | function_length | Long functions are harder to fully test and review; bounded length forces decomposition. |
| SAFE102 | nesting_depth | Deep nesting hides control flow and grows exponentially with conditions. |
| SAFE103 | max_arguments | Many parameters indicate the function does too much or has hidden coupling. |
| SAFE104 | complexity | Cyclomatic complexity bounds the number of independent paths. |
| SAFE201 | bare_except | `except:` swallows `KeyboardInterrupt`/`SystemExit` and masks real bugs. |
| SAFE202 | empty_except | Silent failure is the worst failure mode. |
| SAFE301 | global_state | Globals make functions impure and break local reasoning. |
| SAFE302 | global_mutation | Reassigning a global mid-function is a Power-of-Ten violation outright. |
| SAFE303 | side_effects_hidden | Pure-named functions doing I/O surprise callers. |
| SAFE304 | side_effects | I/O at unexpected sites makes testing harder; rename or inject. |
| SAFE501 | unbounded_loops | Every loop should have a bounded iteration count for predictable termination. |

## Step 7 — Constraints

- **Do not auto-fix.** Even if confident, ask before editing. The user invoked a *review*, not a refactor.
- **Do not invent violations.** Only report what's in the JSON.
- **Do not run `--all-files` on a large repo by default.** Git-modified is the default for a reason — it's fast and scoped to current work.
- **Respect `# nosafe` directives.** They appear in `suppressed`, not `violations`. Don't suggest removing them; they're intentional.
- If the user asks "is my code safe?", answer based on the blocking count, not the total. `summary.blocking == 0` means the run *passed* under the configured `fail_on` threshold.
