# Refactor: rule node-type constants to module-access instead of aliased imports

**Type**: cross-language refactor (NOT a language addition). Pure maintainability
change - **no behaviour change**. Follow-up to
[[refactor-node-type-constants]] (which shipped in v2.8.2).

**Status**: not started. **Run only after v2.8.2 has shipped** - it re-touches
the exact files that refactor just changed, so doing it on a stable released
base keeps the diff clean and the review focused.

---

## Why

The node-constant refactor made every rule import each node-type constant with a
per-language alias:

```python
from safelint.languages.cpp import IF_STATEMENT as _CPP_IF_STATEMENT
from safelint.languages.cpp import FOR_STATEMENT as _CPP_FOR_STATEMENT
...  # 78 such lines in complexity.py / dataflow.py
```

and references them bare at use sites (`node.type == _CPP_IF_STATEMENT`). That is
**~700 aliased-import lines** and **~1,767 use-site references** across the rule
and analysis files. The aliasing is the verbose part - not the constants
themselves.

The owner's design instinct was to group the constants (a `Namespace.CONSTANT`
feel) rather than have them scattered. In Python the **module is already that
namespace**, so the idiomatic way to get `Namespace.CONSTANT` - and to delete the
alias soup - is **module-access**, not a wrapper class:

```python
from safelint.languages import cpp as _cpp
...  node.type == _cpp.IF_STATEMENT
```

One import per language per file (~9 max) replaces ~70, and the language is
explicit at every call site. **The language modules do NOT change** - the
constants stay module-level (that is idiomatic Python; cf. `token`, `stat`,
`socket`, `re`). This refactor only changes how the rules *access* them.

A bare "constants class" (`class CppNodes: IF_STATEMENT = ...`) was considered
and rejected: it repeats the language name (`cpp.CppNodes.IF_STATEMENT`), a
class of only string attributes is non-idiomatic in Python, and it buys nothing
over module-access. `enum.StrEnum` was also considered and rejected for plain
node-type tags (Enum machinery, subtle frozenset/config/snapshot interactions,
name still redundant with the module).

## Scope

Convert the aliased-import references to module-access in:

- `src/safelint/rules/*.py` (all rule files that import per-language node-type
  constants - complexity, dataflow, loop_safety, error_handling, nesting_depth,
  state_purity, resource_lifecycle, max_arguments, rust_rules, no_recursion,
  side_effects, dynamic_code_execution, function_length, documentation,
  blanket_suppression, spring, c_rules, cpp_rules, go_rules, test_coverage,
  _rust_test_attribute).
- `src/safelint/analysis/*.py` (dataflow + dataflow_<lang>).
- `src/safelint/languages/_node_utils.py`.

Out of scope: the `languages/<lang>.py` modules keep their module-level constants
unchanged. `EXTRA_NAME`, the `FUNCTION_TYPES` / `CALL_TYPES` aggregates, and any
other imported name convert the same way (`_cpp.EXTRA_NAME`, `_cpp.FUNCTION_TYPES`).

## Design decisions to settle at implementation time

1. **Module-alias name.** `languages/__init__.py` already uses `_cpp_mod` /
   `_c_mod`. That is verbose at ~1,767 call sites. Recommend a shorter private
   alias per language - `_cpp`, `_js`, `_ts`, `_java`, `_rust`, `_go`, `_php`,
   `_c`, `_py` - and align `__init__` to match, OR keep `_<lang>_mod` for
   consistency. Pick one and apply uniformly.
2. **Python constants.** Some rules import Python constants bare (`IF_STATEMENT`,
   not `_PY_IF_STATEMENT`). Decide whether Python also moves to module-access
   (`_py.IF_STATEMENT`) for uniformity, or stays bare. Uniform is cleaner but
   touches more lines.

## Mechanics (scriptable, same shape as the node-constant refactor)

Per file: collect the `(lang, CONST)` set that the file's aliases reference,
replace the ~N aliased-import lines with one `from safelint.languages import
<lang> as _<lang>` per language used, then rewrite each `_<PFX>_<CONST>` ->
`_<lang>.<CONST>`. Run `ruff check --fix --select I,F401` to drop the old
imports and sort, then `ruff format`.

## Non-negotiables

- **No behaviour change.** The resolved values are identical - a frozenset that
  held `_CPP_IF_STATEMENT` (== "if_statement") now holds `_cpp.IF_STATEMENT`
  (== "if_statement"). The existing rule test suites must pass **unchanged**.
- **safelint must pass itself** (`uv run safelint check src/ --all-files`),
  coverage stays >= 97%.
- Indian English, no em-dashes (comment touch-ups only).

## Validation gate

```bash
uv run pytest                                  # unchanged expectations
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/ --all-files
uv run mkdocs build --strict
```

Plus the behaviour-preservation harness from the node-constant refactor:
`scratchpad/snapshot_tables.py` dumped with `PYTHONHASHSEED=0`, diffed against a
baseline captured from the pre-refactor tree. **Watch the diff for removals /
value changes only** - the rule modules will legitimately lose their
`_<PFX>_<CONST>` *string* attributes (now reached through the module object,
which the harness skips), so expect a shrink in scalar keys; the collection
(frozenset / dict / tuple) values must be byte-identical.

## Release

Pure refactor = **PATCH**, behaviour-neutral, no version bump owed beyond that
(owner's call on timing). Own PR, after v2.8.2. Do NOT bundle with a feature.
