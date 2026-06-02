---
name: safelint
description: Run safelint static analysis on the user's project and present Holzmann Power-of-Ten safety violations grouped by file. Supports any language registered with safelint (currently Python, JavaScript, and TypeScript including TSX / AssemblyScript; more languages can be added). Use this for "safelint check", "lint with safelint", "safety review", "Power-of-Ten review", or similar requests for safelint's specific rule set. For generic linting use the project's configured tools (ruff, eslint, etc.) instead.
---

# safelint skill

You are running the safelint static-analysis CLI on behalf of the user. safelint enforces Holzmann's "Power of Ten" safety rules adapted from C/C++ aerospace conventions to modern languages: function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and similar. The same rule set applies across every language safelint supports; only the parser and language-specific node types differ.

Follow the steps below in order.

## Step 1: Verify safelint is installed

Run `safelint --version` via Bash. This is portable across macOS, Linux, and Windows shells and returns non-zero whenever safelint isn't on `PATH`. If you specifically need a "is the binary findable?" check without invoking it, fall back to `python -c "import shutil, sys; sys.exit(0 if shutil.which('safelint') else 1)"`.

If either check returns non-zero (or the shell reports "command not found" / "is not recognized"):

- safelint is a Python package regardless of the language being linted, but **v2.0.0+ ships language grammars as opt-in extras**, so the install command needs a `[<lang>]` suffix matching the project's language(s). Glance at the file extensions in the project tree, then suggest the right one:

  | Project contains | Install command |
  |---|---|
  | `.py` / `.pyw` | `uv add 'safelint[python]'` or `pip install 'safelint[python]'` |
  | `.js` / `.mjs` / `.cjs` | `uv add 'safelint[javascript]'` or `pip install 'safelint[javascript]'` |
  | `.ts` / `.tsx` / `.as` | `uv add 'safelint[typescript]'` or `pip install 'safelint[typescript]'` (bundles JS grammar too) |
  | `.java` | `uv add 'safelint[java]'` or `pip install 'safelint[java]'` (Spring Boot via `[tool.safelint.java] framework = "spring-boot"`, see `languages/java.md`) |
  | `.rs` | `uv add 'safelint[rust]'` or `pip install 'safelint[rust]'` (Rust-specific rules and Holzmann-inspired additions; see `languages/rust.md`) |
  | Multiple languages | Compose, e.g. `pip install 'safelint[python,javascript]'` |
  | Unsure / kitchen-sink | `pip install 'safelint[all]'` (covers every supported language) |

  Plain `pip install safelint` (no extra) installs only the engine and is rarely what the user wants. On first run safelint emits an install hint pointing them at the right extra and exits with code 2.
- If safelint is already installed but exits non-zero with `safelint: error: no files linted …` on stderr, the grammar extra is missing. That error fires in **every** output mode (JSON / SARIF included) and is the reliable signal. Pretty-mode runs additionally print one `safelint: warning: skipping .X files …` line per missing grammar as context; JSON / SARIF runs, and hook-mode runs where every file is skipped, suppress that warning. Re-install with the right `[<lang>]` extra and retry.
- After running `safelint skill install`, safelint also auto-detects the project's language(s) and emits a final `safelint: warning: Detected source files for N language(s) ... Run: pip install 'safelint[<a,b>]'` line if any grammars are missing. The composed install command in that line is the one-shot fix for multi-language projects; run it as-is.
- For pre-commit users: the same extra must go into `additional_dependencies` in `.pre-commit-config.yaml`, e.g. `additional_dependencies: ['safelint[python]']`. Without it, the pre-commit hook also exits 2 and is reported as Failed (red), so there's no silent-pass.
- Stop. Do not proceed until they install the right extra.

## Step 2: Identify the language(s) involved

Look at the project files in cwd to figure out which languages safelint can lint here. The current registry:

| Language | Extensions | Addendum file |
|---|---|---|
| Python | `.py`, `.pyw` | `languages/python.md` |
| JavaScript (Node) | `.js`, `.mjs`, `.cjs` | `languages/javascript.md` |
| TypeScript (also AssemblyScript) | `.ts`, `.tsx`, `.as` | `languages/typescript.md` |
| Java (vanilla and Spring Boot) | `.java` | `languages/java.md` |
| Rust | `.rs` | `languages/rust.md` |

(More languages will land over time. To check the live list, run `python -c "from safelint.languages import supported_extensions; print(sorted(supported_extensions()))"`.)

If the user's project has files matching one or more registered languages, proceed. If safelint doesn't yet support the language they're working in (e.g. they have only `.go` files), tell them so plainly; don't run safelint just to report "0 files checked".

For deeper, language-specific guidance (install nuance, idiomatic fixes, language-specific rule notes), read the matching `languages/<lang>.md` file from the bundled skill directory. Locate it with `safelint skill path` (prints the on-disk root); the addendums sit at `<that path>/languages/<lang>.md`. Skip the read if the user's request doesn't need that depth (e.g. a simple "run safelint and show me the count").

## Step 3: Decide what to lint

| User said… | Target | Flags |
|---|---|---|
| (nothing specific) or "modified files", "my changes", "what I'm working on" | `.` | (none; defaults to git-modified) |
| "all files", "everything", "the whole repo" | `.` | `--all-files` |
| A specific file or directory path | that path | (omit `--all-files` if a single file) |

If the user mentions CI strictness, also pass `--mode ci` (treats warnings as blocking) or `--fail-on warning`.

## Step 4: Run safelint with structured output

Always use `--format json` so you can parse the result reliably. safelint walks the target tree and lints every file whose extension matches a registered language; you don't need to filter by language yourself.

```bash
safelint check <target> --format json [--all-files]
```

Notes:
- **Exit 0** = no blocking violations; **exit 1** = at least one blocking violation. The JSON document is on stdout in both cases; keep parsing it.
- **Exit 2** = setup error: safelint linted zero files because every candidate's grammar isn't installed (silent-failure guard). The stderr will name the extra to install (e.g. `add 'safelint[typescript]' to additional_dependencies …` under pre-commit, or `install with: pip install 'safelint[typescript]'` direct). The JSON on stdout will look clean (zero violations), so **do not report this as "lint clean"**; surface the stderr install hint to the user.
- Stderr may contain config warnings (typo guards, oversize-skip notes). Surface those to the user only if non-empty.
- If `safelint` itself crashes (bug), say so and include the stderr verbatim.

## Step 5: Parse the JSON

The schema is documented in [`docs/json-schema.md`](https://github.com/shelkesays/safelint/blob/main/docs/json-schema.md) inside the safelint repo. Its *shape* has been stable since v1.5.0; the rule set has expanded as new languages landed (Java in v2.1.0, Rust in v2.2.0), but the field structure of each violation / summary entry is unchanged. The shape:

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
    {"code": "SAFE201", "rule": "bare_except", "severity": "error",
     "filepath": "src/foo.py", "lineno": 42,
     "end_lineno": 42, "column_start": 5, "column_end": 12,
     "message": "Bare ``except:`` clause - specify the exception type to handle",
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

The `suggestions[]` array (added in v1.8.0) is **advisory only**. Each `Suggestion` carries a one-line `description` and zero or more `TextEdit` entries (half-open `[start, end)` ranges plus the literal `replacement` text). Surface them to the user as offered quick-fixes, but **never apply them automatically**. safelint is a review tool, not a refactoring tool, and the user must confirm every edit. Empty `edits` arrays are valid: a description-only suggestion is a hint, not a fix recipe.

## Step 6: Present results

Order matters: lead with what the user needs first.

1. **One-line headline.** Examples:
   - `Clean run: 12 files checked, no violations.` (if zero)
   - `Clean run: 12 files checked. 3 violations suppressed (2 SAFE501, 1 SAFE304).` (clean but with suppressions)
   - `Found 4 errors and 7 warnings across 5 files (1 suppressed).` (otherwise)

2. **Per-file breakdown** (skip files with zero violations). For each file, list violations one per line:

   ```
   src/api/auth.py
     SAFE101  L42  Function "verify_token" is 78 lines (max 60)              [function_length]
     SAFE102  L51  Nesting depth is 4 (max 2)                                 [nesting_depth]
     SAFE304  L88  Function "_run_pipeline" calls I/O primitive "open" - ...  [side_effects]
   ```

   Pad codes / line numbers / messages so columns line up. Don't emit ANSI colour; the user's terminal already renders it via the `pretty` mode if they want that, so the skill output should be plain.

   If a project has files in multiple languages, group by language first, then by file within each language.

3. **Suggested next step.** Pick exactly one based on the result:
   - 0 violations → say "All checks passed." and stop. No follow-up.
   - 1–4 violations → "Want me to walk through fixes one at a time?"
   - 5+ violations → "Want me to start with the most common issue (CODE, N occurrences)?"
   - Many `function_length` / `complexity` violations clustered in one file → "These look like one large function. Want me to extract some helpers?"

## Step 7: When the user asks "why is this flagged?"

Briefly explain the Power-of-Ten rationale (one or two sentences). Reference the rule code and the underlying safety property. Don't lecture; keep it tight.

The rule set is shared across all supported languages. Universal rationale crib sheet:

| Code | Rule | Why it matters (universal) |
|---|---|---|
| SAFE101 | function_length | Long functions are harder to fully test and review; bounded length forces decomposition. |
| SAFE102 | nesting_depth | Deep nesting hides control flow and grows exponentially with conditions. |
| SAFE103 | max_arguments | Many parameters indicate the function does too much or has hidden coupling. |
| SAFE104 | complexity | Cyclomatic complexity bounds the number of independent paths. |
| SAFE110 | needless_mut | *Rust-only.* `let mut x = ...` where `x` is never reassigned, never has `&mut` taken, and is never used as a method receiver / field-access target. Holzmann rule 6 (smallest scope). |
| SAFE112 | unchecked_arithmetic_on_input | *Rust-only.* `+` / `-` / `*` on integer-typed function parameters can overflow silently in release. Use `checked_*` / `wrapping_*` / `saturating_*` to make the choice explicit. Holzmann rule 7. |
| SAFE201 | bare_except | Catch-all error handlers swallow signals you actually want to propagate. |
| SAFE202 | empty_except | Silent failure is the worst failure mode. |
| SAFE203 | logging_on_error | An `except` block with no log call loses the failure context, so debugging starts from a blank trace. |
| SAFE204 | panic_macros_outside_tests | *Rust-only.* `panic!()` / `todo!()` / `unimplemented!()` in non-test code crash on error; production paths should return `Result<_, _>` instead. Test code (`#[test]` / `#[cfg(test)]`) is excluded. |
| SAFE205 | lock_poisoning_ignored | *Rust-only.* `mutex.lock().unwrap()` / `rwlock.read().unwrap()` / `.write().unwrap()` silently swallow lock poisoning. Match on `PoisonError` or call `.into_inner()` to recover explicitly. |
| SAFE206 | silent_result_discard | *Rust-only.* Empty `Err` arms (`Err(_) => {}`) and empty `if let Err(_) = ... {}` bodies silently swallow errors. Spiritual analogue of SAFE202 (empty_except) for Rust's `Result`/`Option` idioms. `let _ = result;` is the explicit auditable discard and is NOT flagged. |
| SAFE207 | unlogged_error_branch | *Rust-only.* `Err` arms / `if let Err(...)` bodies that handle the error but neither log it nor propagate it. Exempts bodies containing `return`, `panic!` / `todo!` / `unreachable!` / `unimplemented!`, or a tail `Err(...)` re-raise. Spiritual analogue of SAFE203 (logging_on_error). |
| SAFE208 | result_unwrap_outside_tests | *Rust-only.* `.unwrap()` / `.expect()` / `.unwrap_unchecked()` outside test code. Broader than SAFE205 (lock-specific) and SAFE803 (nullable-method-specific). Holzmann rule 7 (check return values). |
| SAFE301 | global_state | Global state makes functions impure and breaks local reasoning. |
| SAFE302 | global_mutation | Reassigning shared state mid-function is a Power-of-Ten violation outright. |
| SAFE303 | side_effects_hidden | Pure-named functions doing I/O surprise callers. |
| SAFE304 | side_effects | I/O at unexpected sites makes testing harder; rename or inject. |
| SAFE305 | wide_scope_declaration | JS-family (JavaScript and TypeScript): `var` is function-scoped (hoisted across blocks); `let` / `const` are block-scoped. The rule fires on every `var` declaration; the fix is mechanical (replace with `let` if reassigned, `const` otherwise). TypeScript inherits the same scoping behaviour. No Python equivalent. |
| SAFE306 | dangerous_mem_ops | *Rust-only.* Calls to `std::mem::transmute` / `forget` / `zeroed` / `uninitialized` are footguns. Use `From` / `TryFrom` / `bytemuck` for casts, `ManuallyDrop` for explicit drop control, `MaybeUninit` for uninitialised memory. |
| SAFE308 | truncating_as_cast | *Rust-only.* `as u8` / `as u16` / `as u32` / `as i32` / `as f32` casts silently truncate. Use `u8::try_from(x)` / `u16::try_from(x)` etc. for a checked conversion. Holzmann rule 1 + 7. |
| SAFE401 | resource_lifecycle | Files, locks, sockets, and similar resources should be acquired inside a `with` block so cleanup is guaranteed even on exception paths. |
| SAFE501 | unbounded_loops | Every loop should have a bounded iteration count for predictable termination. |
| SAFE601 | missing_assertions | Functions without internal assertions skip a key opportunity to catch invariant violations close to where they happen. |
| SAFE602 | undocumented_unsafe | *Rust-only.* `unsafe { ... }` blocks must carry a `// SAFETY:` comment (case-insensitive) on a preceding line documenting why the unsafe is sound. Mirrors `clippy::undocumented_unsafe_blocks`. |
| SAFE701 | test_existence | Source files lacking a corresponding test file are likely under-covered; the rule surfaces gaps before they ship. |
| SAFE702 | test_coupling | A source file changed without touching its tests usually means the suite has drifted from the implementation. |
| SAFE801 | tainted_sink | Untrusted input flowing into `eval` / `exec` / shell sinks is a classic injection vector; the rule traces taint from sources to sinks intra-procedurally. |
| SAFE802 | return_value_ignored | Discarding the return value of error-signalling functions like `subprocess.run` silently swallows failures. |
| SAFE803 | null_dereference | Using a value as if non-None after a None check (or where it could be None) is a common crash source. |
| SAFE901 | spring_field_injection | *Java + Spring Boot only.* `@Autowired` on a field; Spring's own docs recommend constructor injection (immutable, testable, fail-fast on missing deps). Enabled by `[tool.safelint.java] framework = "spring-boot"`. |
| SAFE902 | spring_missing_transactional | *Java + Spring Boot only.* Service-layer method does multiple repository writes (`save` / `delete` / etc.) without `@Transactional`; partial writes leak on failure. |
| SAFE903 | spring_unvalidated_input | *Java + Spring Boot only.* Controller method parameter uses `@RequestBody` / `@ModelAttribute` without `@Valid` / `@Validated`; bean validation must run on deserialised request bodies. Complements SAFE801 structurally. |
| SAFE904 | spring_async_checked_exception | *Java + Spring Boot only.* `@Async` method declares a `throws` clause; Spring runs `@Async` on a separate thread and swallows exceptions, the caller never sees them. Catch inside the body or return `CompletableFuture.failedFuture(...)`. |

For language-specific phrasing (e.g. how `bare_except` translates to `catch (Throwable t)` in another language) read the relevant `languages/<lang>.md` addendum; locate it via `safelint skill path`.

## Step 8: Constraints

- **Do not auto-fix.** Even if confident, ask before editing. The user invoked a *review*, not a refactor.
- **Do not invent violations.** Only report what's in the JSON.
- **Do not run `--all-files` on a large repo by default.** Git-modified is the default for a reason: it's fast and scoped to current work.
- **Respect inline-suppression directives.** They appear in `suppressed`, not `violations`. Don't suggest removing them; they're intentional.
- **Don't assume Python idioms when fixing other languages.** For language-specific fix patterns, consult the addendum.
- If the user asks "is my code safe?", answer based on the blocking count **combined with the exit code**: `summary.blocking == 0` AND exit 0 means the run *passed* under the configured `fail_on` threshold; `summary.blocking == 0` AND exit 2 means zero files were actually linted (silent-failure guard fired), which is **not** the same as passing. Surface the stderr install hint instead of declaring the code safe.

---

## Adding support for a new language

When safelint adds a new language (TypeScript, Go, Rust, …):

1. Add the language registration in safelint itself (`src/safelint/languages/<lang>.py`).
2. Add a row to the **Step 2** registry table above.
3. Create `src/safelint/skill_files/languages/<lang>.md` mirroring the existing addendums. The addendum should cover at minimum:
   - Install nuance specific to that ecosystem (if any; safelint stays a Python install for now).
   - File extensions and how to recognise them in this skill's context.
   - Language-specific phrasing for rule rationales (e.g. how `bare_except` maps to that language's catch-all idiom).
   - Idiomatic fix patterns the skill can suggest when offering to walk through fixes.

Keep the skill core (this file) language-neutral. Per-language detail belongs in the addendum.
