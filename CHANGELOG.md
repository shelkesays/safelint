# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

This release contains a breaking library API change (`LintResult.suppressed` type) — the version is being bumped to **2.0.0** when tagged.

### Added
- Standalone `safelint.toml` configuration file (top-level keys, no `[tool.safelint]` wrapper). When both `safelint.toml` and `pyproject.toml` `[tool.safelint]` exist in the same directory, `safelint.toml` wins — matching `ruff.toml` / `pyproject.toml` precedence.
- `examples/sample.safelint.toml` reference covering every supported configuration key.
- Public `safelint.languages.supported_extensions() -> frozenset[str]` for callers that need to know which file extensions have a registered language. Use this instead of importing the private `_REGISTRY`.
- `walk()` in `safelint.languages._node_utils` accepts an optional `skip_types` parameter that prunes subtrees rooted at any matching node type (used by per-function rules to avoid descending into nested `def` / `async def` bodies).

### Changed
- `side_effects` (SAFE304) keyword matching is now case-insensitive on the function name (mirrors what `side_effects_hidden` already did) — `writeLog`, `IOWriter`, etc. are exempted alongside `write_log`.
- `load_config()` now returns a fresh deep copy of the merged config on every call. Mutating the result (e.g. `config["ignore"].append(...)`) no longer corrupts the module-global `DEFAULTS`.
- **Removed** YAML (`.safelint.yaml`) configuration support and the `safelint[yaml]` install extra. Migrate to `[tool.safelint]` in `pyproject.toml` or to a standalone `safelint.toml`.
- CLI summary "All checks passed." is now bold green to match `ruff` / `ty`.
- The "No fixes available …" line is no longer printed on clean runs (with or without suppressions). It only appears when there are active violations a developer might wonder about auto-fixing.
- Suppressed-violation summary now shows a per-code breakdown — e.g. `(2 SAFE501, 1 SAFE304 suppressed)` — instead of a bare `(N suppressed)` count, so it is clear which rules were silenced.
- **Breaking (library API):** `LintResult.suppressed` is now `list[Violation]` (was `int`). Use `len(result.suppressed)` for the count and iterate to inspect codes, rules, file paths, and line numbers of suppressed violations.
- Replaced internal use of Python's `logging` module with a dedicated diagnostics channel that writes formatted single-line messages to stderr (`safelint: warning: …`, `safelint: error: …`). Configuration typos and malformed-TOML errors are now surfaced cleanly instead of leaking through Python's `lastResort` logging handler.
- `walk()` now traverses only `named_children` (skips Tree-sitter's anonymous punctuation/keyword tokens), reducing the number of nodes visited per traversal across every rule and the suppression parser.
- Parse-error violations (`SAFE000`) now include line, column (1-based), and a kind hint such as `missing ':'` or `syntax error`. The lineno on the violation now points at the offending location instead of being hardcoded to 0.
- `MaxArgumentsRule` now counts `*args` and `**kwargs` parameters, each as one argument. Previously they were silently ignored, allowing functions to exceed `max_args` without triggering.
- An empty `[tool.safelint]` section in `pyproject.toml` (or an empty `safelint.toml`) is now treated as a present-but-empty config. Previously the loader fell through to an ancestor directory's config, hiding unintentionally-blank sections.
- Self-development pre-commit hook switched from `repo: https://github.com/shelkesays/safelint @ v1.3.2` to `repo: local`, so contributors run the in-tree code rather than an outdated published release while iterating on safelint itself.

### Fixed
- Per-function rules no longer incorrectly aggregate metrics from nested `def` / `async def` bodies into the enclosing function. Affects `complexity`, `nesting_depth`, `missing_assertions`, `unbounded_loops`, `global_state`, `global_mutation`, `logging_on_error` (a logging call inside a nested helper would have falsely satisfied the rule), and the dataflow `TaintTracker`. Each nested function is scored as its own unit, as the outer-walk loop already intended.
- `state_purity` (`global_state`, `global_mutation`) now also stops at nested class definitions — a `global X` declared inside a nested class body lives in that class's scope, not the enclosing function's.
- `function_length` (SAFE101) reported counts that were off by one (a 60-line function showed `59 lines`). The calculation is now inclusive of the `def` line.
- Dataflow taint tracker now unwraps `keyword_argument` nodes — `eval(code=user_input)` is no longer missed because the tainted value was hidden behind a kwarg wrapper.
- `per_file_ignores` now validates that every entry in each list is a string. Non-string elements (e.g. `["SAFE101", 42]`) are reported with a clear `TypeError` at engine init instead of crashing later on `.upper()`.
- File discovery now does a single `rglob('*')` pass and filters by suffix, instead of one `rglob('*<ext>')` per registered extension. Discovery is now O(number_of_files) rather than O(number_of_extensions * number_of_files). No behaviour change on a single-language registry, but matters as more languages are added.

## [1.3.1] - 2026-04-24

### Added
- `ignore` config key and `--ignore` CLI flag: suppress rules globally by code (`SAFE101`) or name (`function_length`); unknown entries log a warning at startup.
- `per_file_ignores` config key: suppress specific rules for files matching a glob pattern (e.g. `"tests/**" = ["SAFE101", "SAFE103"]`); multiple patterns union their ignore lists.
- `# nosafe: RULE, CODE` inline suppression: codes and rule names can now be mixed in the same comma-separated list on a single `# nosafe:` comment.
- Suppressed violation count (from both `# nosafe` and `per_file_ignores`) reported in the end-of-run summary so suppressions remain auditable.

### Changed
- `SafetyEngine.__init__` extracted into two focused static methods (`_build_active_rules`, `_parse_per_file_ignores`) to keep complexity within bounds.
- Pattern matching for `exclude_paths` and `per_file_ignores` switched from `pathlib.Path.match` to `fnmatch.fnmatchcase(path.as_posix(), pattern)`, fixing incorrect `**` handling on Python ≤ 3.12.
- `--ignore` CLI flag changed from `nargs="+"` to `action="append"` so it can be repeated (`--ignore SAFE101 --ignore SAFE103`).
- CLI summary now shows `(N suppressed)` instead of `(N suppressed via # nosafe)` to cover all suppression mechanisms.

### Fixed
- `per_file_ignores` patterns with `**` (e.g. `tests/**`) now correctly match files in nested subdirectories on Python ≤ 3.12.
- Pre-commit hook no longer shows a success message for files that were silently excluded.

## [1.3.0] - 2026-03-01

### Added
- Initial public release with 16 built-in rules covering function length, nesting depth, cyclomatic complexity, error handling, global state, side effects, resource lifecycle, loop safety, and opt-in dataflow analysis.
- TOML (`pyproject.toml`) and YAML (`.safelint.yaml`) configuration with deep-merge against built-in defaults.
- `# nosafe` inline suppression (bare and with specific codes).
- `exclude_paths` glob patterns to skip directories entirely.
- `fail_fast` execution option.
- Pre-commit hook integration.
- `--mode=ci` and `--fail-on` CLI flags.

[Unreleased]: https://github.com/shelkesays/safelint/compare/v1.3.1...HEAD
[1.3.1]: https://github.com/shelkesays/safelint/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/shelkesays/safelint/releases/tag/v1.3.0
