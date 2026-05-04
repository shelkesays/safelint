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
  "code": "SAFE101",
  "rule": "function_length",
  "severity": "error",
  "filepath": "src/foo.py",
  "lineno": 42,
  "column_start": 5,
  "column_end": 18,
  "message": "Function \"verify_token\" is 78 lines (max 60)"
}
```

| Field | Type | Notes |
|---|---|---|
| `code` | string | The SAFE-code, e.g. `"SAFE101"`. May be empty for synthetic violations (rare); fall back to `rule` when displaying. |
| `rule` | string | The snake-case rule name, e.g. `"function_length"`. Stable identifier for config (e.g. `[tool.safelint.rules.function_length]`). |
| `severity` | `"error"` \| `"warning"` | The per-rule severity. Compare against `summary.fail_on` to decide blocking. |
| `filepath` | string | Path as the user supplied it to the CLI (typically relative to cwd). Not a URI; not percent-encoded. For SARIF output, use `--format sarif` instead — it normalises to RFC 3986 URIs. |
| `lineno` | int | 1-based line number in the source file. `0` for run-level errors that have no specific location (rare; only `SAFE000` parse errors emit this). |
| `column_start` | int \| null | *Added in 1.7.0.* 1-based column where the offending construct starts. `null` when no Tree-sitter node was available to position against (synthetic file-level violations like `test_existence`). Editors should treat `null` as "underline the whole line". |
| `column_end` | int \| null | *Added in 1.7.0.* 1-based column where the offending construct ends. Half-open: the range is `[column_start, column_end)`. For zero-width markers (parse-error carets), `column_start == column_end`. |
| `message` | string | Human-readable description. May contain quotes and Unicode; safe for direct display. Don't parse — present verbatim. |

### Column ranges

Columns are 1-based to match safelint's 1-based `lineno`. LSP-style consumers that need 0-based columns should subtract 1 themselves. The range is **half-open**: `column_start` is the first character of the construct, `column_end` is one past the last character. This maps cleanly to VSCode's `Range` (`new vscode.Range(line - 1, col_start - 1, line - 1, col_end - 1)`).

Multi-line constructs (e.g. a function spanning lines 10-69) report only the start line in `lineno`; `column_end` refers to the column on the end-line, not the start-line. Most consumers treat this as "underline from `(lineno, column_start)` to end-of-line" since walking to the actual end position requires re-parsing. SARIF output (`--format sarif`) preserves the same semantics in its `region.endLine` / `region.endColumn` fields when available.

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
  message: string;
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
