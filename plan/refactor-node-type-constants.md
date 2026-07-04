# Refactor: per-language node-type tables to imported constants

**Type**: cross-language refactor (NOT a language addition). Pure
maintainability change - **no behaviour change**.

**Status**: not started. **Scheduled after C and C++ ship** (so the language
set is stable and the sweep is done once, not re-done per language addition).

**Sequencing**: C has shipped (`plan/02-c.md` removed on completion); run this
only once `plan/03-cpp.md` (C++) is also complete and its spec removed. Doing
it earlier would mean re-touching the same tables for every subsequent
language; doing it once at the end is the single-pass win.

---

## Why

Each per-language rule in `src/safelint/rules/` keeps its node-type / operator sets in
per-language tables (e.g. `_BRANCHING_TYPES_BY_LANG`, `_DEPTH_NODE_TYPES_BY_LANG`,
`_CALL_TYPES_BY_LANG`, `_WHILE_STATEMENT_BY_LANG`). Today **every language's row
in those tables uses raw Tree-sitter string literals** (`"if_statement"`,
`"call_expression"`, `"boolean"`, ...), not the constants the language modules
export. CLAUDE.md's "rules should import these constants instead of hardcoding
magic strings" guidance is currently honoured only at the *outer* rule dispatch
(which imports `FUNCTION_TYPES` etc.), not inside these tables.

Bot reviewers (CodeRabbit) repeatedly flag the PHP rows as "magic strings", but
the PHP rows were deliberately left as literals to stay **consistent with the
other six languages in the same dict** - converting only PHP would produce a
mixed style that is worse than uniform literals. The correct fix is to convert
**all languages at once**, which is what this plan covers.

This was deferred out of the PHP PR (#75) precisely because it is a
cross-language sweep, not a PHP-specific change.

## Scope

Convert the raw node-type / operator string literals in the per-language tables
and per-language branches of `src/safelint/rules/` to constants imported from
the matching `src/safelint/languages/<lang>.py` module, for **all** registered
languages (by the time this runs: Python, JavaScript, TypeScript, Java, Rust,
Go, PHP, C, C++).

Known touch-points (audit at execution time - the set will have grown with
C/C++):

- `complexity.py` - `_*_BRANCHING_TYPES`, `_*_BRANCHING_BINARY_OPS`.
- `nesting_depth.py` - `_DEPTH_NODE_TYPES_BY_LANG`.
- `max_arguments.py` - `_*_COUNTED_PARAM_TYPES` and the `_count_<lang>_args`
  helpers.
- `no_recursion.py` - `_CALL_TYPES_BY_LANG`, the per-language self-call
  predicates.
- `loop_safety.py` - `_WHILE_STATEMENT_BY_LANG`, `_INFINITE_LOOP_STATEMENT_BY_LANG`,
  `_BREAK_STATEMENT_BY_LANG`, `_TRUE_LITERAL_BY_LANG`, `_BREAK_LABEL_TYPE_BY_LANG`,
  the break-scope-boundary sets.
- `error_handling.py` - `_CATCH_CLAUSE_TYPES_BY_LANG`,
  `_NOOP_STATEMENT_TYPES_BY_LANG`, `_LITERAL_EXPR_TYPES_BY_LANG`,
  `_RERAISE_STATEMENT_TYPES_BY_LANG`, the per-language re-raise / binding
  helpers.
- `state_purity.py` - the per-language assignment / global helpers.
- `side_effects.py`, `dynamic_code_execution.py`, `resource_lifecycle.py`,
  `blanket_suppression.py` - the per-language call-node / directive checks.
- `src/safelint/rules/dataflow.py` and `src/safelint/analysis/dataflow_<lang>.py`
  - the per-language param / call / propagation node-type literals.
- `src/safelint/languages/_node_utils.py` - `CALL_TYPES`, `_CALL_NAME_DISPATCH`
  keys, the per-language `call_name` helpers.

## Prerequisite

Audit each `src/safelint/languages/<lang>.py` module first: some node types referenced in the
rule tables are **not yet exported** as constants (operators like `"&&"` /
`"||"`, the `"comment"` / `"boolean"` literals, switch-arm node types, etc.).
Add the missing constants to the language modules before the rule-side sweep, so
every literal has a constant to import. Keep the constant names consistent with
the existing ones in each module.

## Non-negotiables

- **All languages in one pass.** Do NOT convert a subset (that recreates the
  inconsistency this plan exists to remove).
- **No behaviour change.** This is a literal-to-constant substitution only; the
  resolved string values must be identical. The existing rule test suites must
  pass **unchanged** (do not edit test expectations).
- **safelint must pass itself** (`uv run safelint check src/ --all-files`),
  coverage stays >= 97%.
- Indian English, no em-dashes (docstring / comment touch-ups only).

## Validation gate

```bash
uv run pytest                                  # unchanged expectations must pass
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/ --all-files
uv run mkdocs build --strict
```

A useful extra check: before/after, dump each table's *resolved* values and
diff them - they must be identical (proves the refactor is behaviour-preserving).
