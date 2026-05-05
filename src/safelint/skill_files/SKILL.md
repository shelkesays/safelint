---
name: safelint
description: Run safelint static analysis on the user's project and present Holzmann Power-of-Ten safety violations grouped by file. Supports any language registered with safelint (currently Python; more languages can be added). Use this for "safelint check", "lint with safelint", "safety review", "Power-of-Ten review", or similar requests for safelint's specific rule set. For generic linting use the project's configured tools (ruff, eslint, etc.) instead.
---

# safelint skill

You are running the safelint static-analysis CLI on behalf of the user. safelint enforces Holzmann's "Power of Ten" safety rules adapted from C/C++ aerospace conventions to modern languages — function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and similar. The same rule set applies across every language safelint supports; only the parser and language-specific node types differ.

Follow the steps below in order.

## Step 1 — Verify safelint is installed

Run `safelint --version` via Bash. This is portable across macOS, Linux, and Windows shells and returns non-zero whenever safelint isn't on `PATH`. If you specifically need a "is the binary findable?" check without invoking it, fall back to `python -c "import shutil, sys; sys.exit(0 if shutil.which('safelint') else 1)"`.

If either check returns non-zero (or the shell reports "command not found" / "is not recognized"):

- safelint is a Python package, regardless of which language is being linted. Suggest:
  - `uv add safelint` (if the project uses `uv`)
  - `pip install safelint` (otherwise)
- Stop. Do not proceed until they install it.

## Step 2 — Identify the language(s) involved

Look at the project files in cwd to figure out which languages safelint can lint here. The current registry:

| Language | Extensions | Addendum file |
|---|---|---|
| Python | `.py`, `.pyw` | `languages/python.md` |

(More languages will land over time. To check the live list, run `python -c "from safelint.languages import supported_extensions; print(sorted(supported_extensions()))"`.)

If the user's project has files matching one or more registered languages, proceed. If safelint doesn't yet support the language they're working in (e.g. they have only `.rs` files), tell them so plainly — don't run safelint just to report "0 files checked".

For deeper, language-specific guidance — install nuance, idiomatic fixes, language-specific rule notes — read the matching `languages/<lang>.md` file from the same directory as this SKILL.md. Try `~/.claude/skills/safelint/languages/<lang>.md` first (user install) and `<project>/.claude/skills/safelint/languages/<lang>.md` second (project install). Skip the read if the user's request doesn't need that depth (e.g. a simple "run safelint and show me the count").

## Step 3 — Decide what to lint

| User said… | Target | Flags |
|---|---|---|
| (nothing specific) or "modified files", "my changes", "what I'm working on" | `.` | (none — defaults to git-modified) |
| "all files", "everything", "the whole repo" | `.` | `--all-files` |
| A specific file or directory path | that path | (omit `--all-files` if a single file) |

If the user mentions CI strictness, also pass `--mode ci` (treats warnings as blocking) or `--fail-on warning`.

## Step 4 — Run safelint with structured output

Always use `--format json` so you can parse the result reliably. safelint walks the target tree and lints every file whose extension matches a registered language; you don't need to filter by language yourself.

```bash
safelint check <target> --format json [--all-files]
```

Notes:
- Exit 0 means no blocking violations; exit 1 means at least one. **Either way the JSON document is on stdout** — keep parsing it.
- Stderr may contain config warnings (typo guards, oversize-skip notes). Surface those to the user only if non-empty.
- If `safelint` itself crashes (bug), say so and include the stderr verbatim.

## Step 5 — Parse the JSON

The schema is documented in [`docs/JSON_SCHEMA.md`](../../docs/JSON_SCHEMA.md). It's stable since v1.5.0. The shape:

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
     "filepath": "src/foo.py", "lineno": 42,
     "end_lineno": 42, "column_start": 5, "column_end": 17,
     "message": "Function ...",
     "suggestions": [
       {"description": "Replace `except:` with `except Exception:`",
        "edits": [
          {"start_line": 42, "start_column": 5,
           "end_line": 42, "end_column": 12,
           "replacement": "except Exception:"}
        ]}
     ]}
  ],
  "suppressed": [ /* same shape */ ]
}
```

Violation objects are language-agnostic. The `filepath` field tells you which language each violation came from (via extension); use that if you want to group results by language.

The `suggestions[]` array (added in v1.8.0) is **advisory only**. Each `Suggestion` carries a one-line `description` and zero or more `TextEdit` entries (half-open `[start, end)` ranges plus the literal `replacement` text). Surface them to the user as offered quick-fixes, but **never apply them automatically** — safelint is a review tool, not a refactoring tool, and the user must confirm every edit. Empty `edits` arrays are valid: a description-only suggestion is a hint, not a fix recipe.

## Step 6 — Present results

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

   If a project has files in multiple languages, group by language first, then by file within each language.

3. **Suggested next step.** Pick exactly one based on the result:
   - 0 violations → say "All checks passed." and stop. No follow-up.
   - 1–4 violations → "Want me to walk through fixes one at a time?"
   - 5+ violations → "Want me to start with the most common issue (CODE — N occurrences)?"
   - Many `function_length` / `complexity` violations clustered in one file → "These look like one large function — want me to extract some helpers?"

## Step 7 — When the user asks "why is this flagged?"

Briefly explain the Power-of-Ten rationale (one or two sentences). Reference the rule code and the underlying safety property. Don't lecture — keep it tight.

The rule set is shared across all supported languages. Universal rationale crib sheet:

| Code | Rule | Why it matters (universal) |
|---|---|---|
| SAFE101 | function_length | Long functions are harder to fully test and review; bounded length forces decomposition. |
| SAFE102 | nesting_depth | Deep nesting hides control flow and grows exponentially with conditions. |
| SAFE103 | max_arguments | Many parameters indicate the function does too much or has hidden coupling. |
| SAFE104 | complexity | Cyclomatic complexity bounds the number of independent paths. |
| SAFE201 | bare_except | Catch-all error handlers swallow signals you actually want to propagate. |
| SAFE202 | empty_except | Silent failure is the worst failure mode. |
| SAFE203 | logging_on_error | An `except` block with no log call loses the failure context — debugging starts from a blank trace. |
| SAFE301 | global_state | Global state makes functions impure and breaks local reasoning. |
| SAFE302 | global_mutation | Reassigning shared state mid-function is a Power-of-Ten violation outright. |
| SAFE303 | side_effects_hidden | Pure-named functions doing I/O surprise callers. |
| SAFE304 | side_effects | I/O at unexpected sites makes testing harder; rename or inject. |
| SAFE401 | resource_lifecycle | Files, locks, sockets, and similar resources should be acquired inside a `with` block so cleanup is guaranteed even on exception paths. |
| SAFE501 | unbounded_loops | Every loop should have a bounded iteration count for predictable termination. |
| SAFE601 | missing_assertions | Functions without internal assertions skip a key opportunity to catch invariant violations close to where they happen. |
| SAFE701 | test_existence | Source files lacking a corresponding test file are likely under-covered; the rule surfaces gaps before they ship. |
| SAFE702 | test_coupling | A source file changed without touching its tests usually means the suite has drifted from the implementation. |
| SAFE801 | tainted_sink | Untrusted input flowing into `eval` / `exec` / shell sinks is a classic injection vector — the rule traces taint from sources to sinks intra-procedurally. |
| SAFE802 | return_value_ignored | Discarding the return value of error-signalling functions like `subprocess.run` silently swallows failures. |
| SAFE803 | null_dereference | Using a value as if non-None after a None check (or where it could be None) is a common crash source. |

For language-specific phrasing (e.g. how `bare_except` translates to `catch (Throwable t)` in another language) read the relevant `languages/<lang>.md` addendum.

## Step 8 — Constraints

- **Do not auto-fix.** Even if confident, ask before editing. The user invoked a *review*, not a refactor.
- **Do not invent violations.** Only report what's in the JSON.
- **Do not run `--all-files` on a large repo by default.** Git-modified is the default for a reason — it's fast and scoped to current work.
- **Respect inline-suppression directives.** They appear in `suppressed`, not `violations`. Don't suggest removing them; they're intentional.
- **Don't assume Python idioms when fixing other languages.** For language-specific fix patterns, consult the addendum.
- If the user asks "is my code safe?", answer based on the blocking count, not the total. `summary.blocking == 0` means the run *passed* under the configured `fail_on` threshold.

---

## Adding support for a new language

When safelint adds a new language (TypeScript, Go, Rust, …):

1. Add the language registration in safelint itself (`src/safelint/languages/<lang>.py`).
2. Add a row to the **Step 2** registry table above.
3. Create `src/safelint/skill_files/languages/<lang>.md` mirroring the existing addendums. The addendum should cover at minimum:
   - Install nuance specific to that ecosystem (if any — safelint stays a Python install for now).
   - File extensions and how to recognise them in this skill's context.
   - Language-specific phrasing for rule rationales (e.g. how `bare_except` maps to that language's catch-all idiom).
   - Idiomatic fix patterns the skill can suggest when offering to walk through fixes.

Keep the skill core (this file) language-neutral. Per-language detail belongs in the addendum.
