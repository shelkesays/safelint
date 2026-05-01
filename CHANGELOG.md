# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Standalone `safelint.toml` configuration file (top-level keys, no `[tool.safelint]` wrapper). When both `safelint.toml` and `pyproject.toml` `[tool.safelint]` exist in the same directory, `safelint.toml` wins — matching `ruff.toml` / `pyproject.toml` precedence.
- `examples/sample.safelint.toml` reference covering every supported configuration key.

### Changed
- **Removed** YAML (`.safelint.yaml`) configuration support and the `safelint[yaml]` install extra. Migrate to `[tool.safelint]` in `pyproject.toml` or to a standalone `safelint.toml`.
- CLI summary "All checks passed." is now bold green to match `ruff` / `ty`.
- The "No fixes available …" line is no longer printed on clean runs (with or without suppressions). It only appears when there are active violations a developer might wonder about auto-fixing.
- Suppressed-violation summary now shows a per-code breakdown — e.g. `(2 SAFE501, 1 SAFE304 suppressed)` — instead of a bare `(N suppressed)` count, so it is clear which rules were silenced.
- **Breaking (library API):** `LintResult.suppressed` is now `list[Violation]` (was `int`). Use `len(result.suppressed)` for the count and iterate to inspect codes, rules, file paths, and line numbers of suppressed violations.

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
