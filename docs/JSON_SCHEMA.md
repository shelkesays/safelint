# safelint JSON output schema

`safelint check --format json` and `safelint --stdin --format json` both emit a single JSON document on stdout describing the lint run. This page documents that contract so plugin authors (Claude Code skill, VSCode extension, CI scripts) can rely on a stable shape.

The schema is **stable since v1.5.0**. Additions are non-breaking; field removals or type changes will only happen in a major-version bump (and have not happened to date).

## Top-level shape

```json
{
  "version": "1.5.0",
  "summary": {
    "files_checked": 12,
    "violations": 4,
    "errors": 2,
    "warnings": 2,
    "blocking": 2,
    "fail_on": "error",
    "suppressed": {
      "total": 3,
      "by_code": { "SAFE501": 2, "SAFE304": 1 }
    }
  },
  "violations": [ /* Violation objects */ ],
  "suppressed":  [ /* Violation objects, same shape */ ]
}
```

### `version` *(string)*

The version of safelint that produced the document. Use this for compatibility checks if you depend on field additions from a specific release.

### `summary` *(object)*

Aggregated counts across the whole run. All counts are integers ≥ 0.

| Field | Type | Meaning |
|---|---|---|
| `files_checked` | int | Number of files the engine attempted to lint after exclusions. |
| `violations` | int | Active violations (i.e. `len(top.violations)`). |
| `errors` | int | Count of active violations with `severity == "error"`. |
| `warnings` | int | Count of active violations with `severity == "warning"`. |
| `blocking` | int | Active violations whose severity meets or exceeds the configured `fail_on` threshold. `blocking == 0` ⇔ exit code 0. |
| `fail_on` | `"error"` \| `"warning"` | Effective threshold for this run. |
| `suppressed.total` | int | Count of violations that fired but were suppressed (`# nosafe` or `per_file_ignores`). |
| `suppressed.by_code` | `{code: int}` | Per-code breakdown of suppressed violations. Codes are sorted alphabetically; keys are SAFE-codes (e.g. `"SAFE501"`). |

### `violations` *(array of Violation)*

Active violations — i.e. violations that the user is expected to act on. Order is the engine's natural order: file-by-file in discovery order, rule-by-rule in execution order within each file.

### `suppressed` *(array of Violation)*

Violations that fired but were suppressed. Same shape as `violations`. Useful for showing users "what's being silenced" or for auditing `# nosafe` directives.

## Violation object

```json
{
  "code": "SAFE201",
  "rule": "bare_except",
  "severity": "error",
  "filepath": "src/foo.py",
  "lineno": 4,
  "end_lineno": 5,
  "column_start": 5,
  "column_end": 17,
  "message": "Bare except clause - specify the exception type(s)",
  "suggestions": [
    {
      "description": "Catch ``Exception`` instead of using a bare ``except:``",
      "edits": [
        {"start_line": 4, "start_column": 5, "end_line": 4, "end_column": 12, "replacement": "except Exception:"}
      ]
    }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `code` | string | The SAFE-code, e.g. `"SAFE101"`. May be empty for synthetic violations (rare); fall back to `rule` when displaying. |
| `rule` | string | The snake-case rule name, e.g. `"function_length"`. Stable identifier for config (e.g. `[tool.safelint.rules.function_length]`). |
| `severity` | `"error"` \| `"warning"` | The per-rule severity. Compare against `summary.fail_on` to decide blocking. |
| `filepath` | string | Path as the user supplied it to the CLI (typically relative to cwd). Not a URI; not percent-encoded. For SARIF output, use `--format sarif` instead — it normalises to RFC 3986 URIs. |
| `lineno` | int | 1-based start line. `0` for run-level errors with no specific location (rare; only `SAFE000` parse errors emit this). |
| `end_lineno` | int \| null | *Added in 1.7.0.* 1-based end line. Equal to `lineno` for single-line constructs; greater for multi-line. `null` when no Tree-sitter node was available (synthetic file-level violations). |
| `column_start` | int \| null | *Added in 1.7.0.* 1-based column on `lineno` where the construct starts. `null` when no Tree-sitter node / position was available. `column_start` and `column_end` are always either both set or both `null`. Editors should treat `null` as "underline the whole line". |
| `column_end` | int \| null | *Added in 1.7.0.* 1-based column on `end_lineno` (not `lineno`!) where the construct ends. Half-open: the range is `[column_start, column_end)`. `null` when no Tree-sitter node / position was available (paired with a `null` `column_start`). For zero-width markers (parse-error carets), `column_start == column_end` and `end_lineno == lineno`. |
| `message` | string | Human-readable description. May contain quotes and Unicode; safe for direct display. Don't parse — present verbatim. |
| `suggestions` | Suggestion[] | *Added in 1.10.0.* Zero or more advisory fixes the rule offers. **NEVER apply automatically** — see the "Suggestions are advisory only" section below. Empty array when the rule has no fix to offer. |

### Suggestion object

```json
{
  "description": "Catch ``Exception`` instead of using a bare ``except:``",
  "edits": [
    {"start_line": 4, "start_column": 5, "end_line": 4, "end_column": 12, "replacement": "except Exception:"}
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `description` | string | One-line human-readable label for the suggestion. Suitable as the title of a "Quick Fix" code action. |
| `edits` | TextEdit[] | Zero or more text edits describing the minimal change that would make the rule pass. Empty when the suggestion is informational only (e.g. "extract a helper function" — too ambiguous to render as a single edit). |

### TextEdit object

```json
{"start_line": 4, "start_column": 5, "end_line": 4, "end_column": 12, "replacement": "except Exception:"}
```

| Field | Type | Notes |
|---|---|---|
| `start_line` | int | 1-based start line of the range to replace. |
| `start_column` | int | 1-based start column on `start_line`. |
| `end_line` | int | 1-based end line of the range to replace. |
| `end_column` | int | 1-based end column on `end_line` (exclusive — half-open `[start, end)`). |
| `replacement` | string | The literal text that *would* replace the range. May span multiple lines. |

### Suggestions are advisory only

**SafeLint never auto-applies suggestions.** This is a deliberate design choice — the tool is for *review*, not refactoring. Many of safelint's rules (function decomposition, nesting reduction, side-effect rename) require human judgement on how to restructure; an auto-applied "fix" could make the code pass the rule while not addressing the underlying concern.

Editor / CI integrations:

- **MAY** render suggestions as Quick Fix code actions, hover hints, or "lightbulb" suggestions.
- **MAY** show a preview diff before any change.
- **MUST** require explicit user confirmation before applying any edit.
- **MUST NOT** implement "fix on save", "fix all", or any automation that bypasses confirmation.

The CLI **never** ships a `--fix` flag. The pretty-mode summary line uses the word "suggestions" (not "fixes") to reinforce this. SARIF output uses the spec's native `fixes[]` block — SARIF 2.1.0 itself defines this as advisory; consumers (GitHub code scanning, IDE extensions) already implement confirmation flows.

The contract: a violation's `suggestions` array means "here's what I'd consider doing — your call." Nothing more.

### Range semantics

The four position fields together specify a fully-resolved half-open range, matching LSP / VSCode `Range` and SARIF `region` semantics:

```typescript
// VSCode mapping. Subtract 1 for 0-based, but only after normalising
// every nullable field — naive ``v.column_start - 1`` produces NaN
// when the field is null. Synthetic violations (test_existence,
// missing-file SAFE000) carry null columns / null end_lineno; the
// fallbacks below render them as a whole-line marker on ``lineno``.
const startLine = Math.max(0, v.lineno - 1);
const endLine = Math.max(startLine, (v.end_lineno ?? v.lineno) - 1);
const startCol = v.column_start !== null ? v.column_start - 1 : 0;
const endCol = v.column_end !== null ? v.column_end - 1 : Number.MAX_SAFE_INTEGER;
new vscode.Range(startLine, startCol, endLine, endCol);
```

Earlier 1.7.0 drafts shipped `column_start` / `column_end` without `end_lineno`, which forced editors to assume `column_end` referred to `lineno`. That worked for single-line violations but mis-positioned multi-line ones (function definitions, except clauses, while loops). The 1.7.0 final adds `end_lineno` so the range is unambiguous.

Columns are 1-based to match safelint's 1-based `lineno`. LSP-style consumers that need 0-based columns should subtract 1 themselves.

### SARIF mapping

SARIF output (`--format sarif`) emits `region.startLine`, `region.startColumn`, `region.endColumn` whenever they're present, plus `region.endLine` *only when it differs from* `startLine`. Per the SARIF 2.1.0 spec, an absent `endLine` defaults to `startLine`, so this minimises payload size for the common single-line case while still distinguishing multi-line constructs unambiguously.

### Severities and thresholds

There are two severities today: `"error"` and `"warning"`. The `--fail-on` / config `fail_on` setting decides which severity is *blocking*:

- `fail_on = "error"` (default): only `error` violations block the run.
- `fail_on = "warning"`: both `error` and `warning` violations block.

The `summary.blocking` count tells you the pre-computed answer for the current run — you don't need to re-derive it from severity comparison.

## Codes vs rules

Every rule has both a stable `code` (e.g. `SAFE101`) and a stable `name` (e.g. `function_length`). They form a fixed mapping; safelint will not rename either across major versions. Use `code` for short display, `name` for config keys.

The current full list lives in [`CONFIGURATION.md`](../CONFIGURATION.md).

## Example consumers

### Bash one-liner — count blocking violations

```bash
safelint check . --format json | jq '.summary.blocking'
```

### Python — extract files with errors

```python
import json
import subprocess

result = subprocess.run(
    ["safelint", "check", ".", "--format", "json"],
    capture_output=True, text=True, check=False,
)
doc = json.loads(result.stdout)
files_with_errors = {v["filepath"] for v in doc["violations"] if v["severity"] == "error"}
```

### Node — minimal VSCode-style diagnostics

```typescript
import { spawn } from "node:child_process";

interface Violation {
  code: string;
  rule: string;
  severity: "error" | "warning";
  filepath: string;
  lineno: number;
  // Position fields added in 1.7.0. ``null`` for synthetic violations
  // (test_existence, missing-file SAFE000) where no Tree-sitter node
  // was available to position against.
  end_lineno: number | null;
  column_start: number | null;
  column_end: number | null;
  message: string;
  // Advisory suggestions added in 1.10.0. Empty array when the rule
  // has no fix to offer. Never auto-apply.
  suggestions: Suggestion[];
}

interface Suggestion {
  description: string;
  edits: TextEdit[];
}

interface TextEdit {
  start_line: number;
  start_column: number;
  end_line: number;
  end_column: number;
  replacement: string;
}

interface SafelintOutput {
  version: string;
  summary: { /* ... */ };
  violations: Violation[];
  suppressed: Violation[];
}
```

## Versioning policy

- The top-level keys (`version`, `summary`, `violations`, `suppressed`) are part of the stable contract.
- All Violation fields listed above are part of the stable contract.
- New fields may appear without a major-version bump (your code should ignore unknown keys).
- Field removals or type changes require a major-version bump; the `version` field will reflect the change.

For the SARIF output (`--format sarif`), see the SARIF 2.1.0 spec; safelint emits a minimally conformant subset.
