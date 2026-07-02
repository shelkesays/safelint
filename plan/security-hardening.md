# Security hardening plan (internal audit, 2026-06-25)

**Type**: defensive-security hardening backlog (not a feature). Authorised
internal audit of safelint's own codebase.

**Status**: original findings H1-H6 all remediated (PRs #81-#84, #86); see the
[Findings](#findings) checklist. A follow-up full-repo SOC re-scan on
2026-07-02 (after the C release) recorded new items under
[Follow-up audit](#follow-up-audit-2026-07-02-full-repo-soc-re-scan) below;
those are the open remediation backlog.

## Scope and method

A SPOC-led read-only audit of safelint's filesystem / subprocess / config
surface, calibrated against the documented threat model in `SECURITY.md`
(safelint parses but never executes the linted code, makes no network
requests, opens no sockets). These modules were deep-read because they are the
places that touch the dangerous surface:

- `src/safelint/_skill_install.py` - file writes, symlinks, `shutil.rmtree`,
  `Path.unlink` (the `skill install / remove / status / path` command).
- `src/safelint/cli.py` + `src/safelint/core/engine.py` +
  `src/safelint/core/runner.py` - the only `subprocess` use (shelling to `git`
  for changed-file detection) and file discovery.
- `src/safelint/core/config.py` + `src/safelint/core/_cache.py` +
  `src/safelint/core/_validators.py` - TOML config loading, the
  config-discovery parent walk, `per_file_ignores` globs, and the on-disk
  result cache.
- `src/safelint/rules/test_coverage.py` - the `test_dirs` config value is the
  one config field that reaches the filesystem (`rglob`), so this rule is part
  of the audited surface (see H3).

## Headline

- **No HIGH or MEDIUM findings.** No `eval` / `exec` / `subprocess` of user
  code or config; no `pickle` / `marshal` / `yaml.load` (the cache uses JSON
  deliberately). The git subprocess is list-form with a fixed literal
  subcommand + flags and no interpolated / attacker-influenced argv element
  (no injection; see "Verified clean"). File discovery does not descend into symlinked
  *directories* (`os.walk(followlinks=False)`); a symlinked *file* that
  resolves to a regular file is still read, but reading it only lints it, and
  parse errors report just a token kind + coordinates, never file contents
  (no read-leak primitive). The
  `--client` / auto-detect / `AGENTS.md`-symlink-refusal / `--path` tail-match
  guards described in the README are present and largely sound.
- **The recent PHP language addition introduced no new security surface.** The
  PHP code is pure Tree-sitter tree-walking (parsing, taint tracking) - no
  file I/O, no subprocess, no deserialisation. Nothing below was added by the
  PHP work; these are pre-existing LOW / defence-in-depth items.

## Findings

All findings are LOW / hardening; none are exploitable in the default
no-flag flow. Remediation checklist (detailed write-ups follow):

- [x] H1 - `skill remove --path` symlinked-ancestor containment (done - PR #82)
- [x] H2 - install write TOCTOU symlink race (exclusive `"xb"` create) (done - PR #82)
- [x] H3 - `test_dirs` config glob containment vs project root (done - PR #81)
- [x] H4 - cache tmp write via `mkstemp` (`O_EXCL` + unguessable name) (done - PR #83)
- [x] H5 - `_maybe_seed_secondary_for_opencode` dangling-symlink `touch()` guard (done - PR #83)
- [x] H6 - prefer `pathlib.Path` over `os.path`/`os` where a safe equivalent exists (done - PR #84)
- [ ] H7 - `_install_secondary` / `_remove_secondary` `AGENTS.md` merge write is still check-then-act (the H2 TOCTOU class, unhardened on this path) (open; from the 2026-07-02 re-scan)
- [ ] H8 - `_remove_path` validates the resolved parent shape but deletes the unresolved path (ancestor-swap race) (open; residual, same class as H1)
- [ ] H9 - GitHub Actions pinned to mutable refs; the OIDC-privileged `publish.yml` uses a moving branch ref (`pypa/gh-action-pypi-publish@release/v1`) (open; CI/CD supply-chain hardening)

### H1 - `skill remove --path` validates the path tail lexically; a symlinked ancestor can escape

- **Severity**: LOW. **Location**: `src/safelint/_skill_install.py`
  (`_path_looks_like_safelint_install` ~L1641, `_remove_path` ~L1672,
  `_remove_existing` ~L700).
- **What**: the `--path` guard only checks that the trailing path components
  equal a registered `install_relpath` (e.g. `.cursor/rules/safelint.mdc`). It
  never `resolve()`s the path or confirms containment, so the tail match is
  satisfiable while a **symlinked parent directory** points elsewhere (e.g.
  `~/proj/.cursor/rules` -> `/victim/important`). `_remove_existing` then
  unlinks / `rmtree`s inside the redirected location.
- **Preconditions / why LOW**: requires the victim to invoke `remove --path`
  against an attacker-influenced location, and `--path` is the documented
  "unusual location" opt-in escape hatch where the user already takes
  responsibility. Not reachable in the default no-flag flow.
- **Fix**: containment, NOT a blanket symlink-ancestor rejection. `--path` is
  *designed* to accept unusual real parent directories when the tail matches -
  `tests/test_skill_install.py::test_remove_path_accepts_unusual_parent_with_known_install_shape`
  documents this, and a legitimately symlinked parent (e.g. `~/projects` ->
  `/mnt/work/projects`) must still work, so `any(p.is_symlink() for p in
  path.parents)` would over-reject. Instead, only guard against a symlink
  *redirecting the delete to a different real tree*: `realpath` the path's
  parent and confirm the leaf being removed still ends with the matched
  install tail under that resolved parent, and keep `_remove_existing`'s
  existing terminal-symlink handling (it unlinks the link, not its target).
  Given this is an opt-in, user-named escape hatch, treating the residual
  ancestor-symlink case as accepted-and-documented risk is also defensible.
- **Fixed (PR #82)**: added `_resolved_install_shape_ok`, which re-runs the
  tail match on `path.parent.resolve(strict=False) / path.name`. `_remove_path`
  now requires both the lexical and the resolved match. `Path.resolve(strict=False)`
  does not raise on a missing path, and it rewrites only the symlinked prefix - a real unusual parent (or a platform prefix
  symlink like macOS's `/var` -> `/private/var`) leaves the install tail
  intact and still passes. It *can* raise `RuntimeError` on an ancestor symlink
  loop (per the docs; platform-dependent), so the resolve is wrapped and a
  resolution failure is treated as a non-match (refused) - though in practice
  `_remove_path`'s `exists()` / `is_symlink()` pre-check already short-circuits
  loop/missing paths before this runs (a review-found robustness fix, PR #86).
  The leaf name is appended verbatim so
  `_remove_existing`'s terminal-symlink handling is preserved. Tests:
  `test_remove_path_refuses_symlinked_ancestor_redirect` (redirect blocked)
  and `test_remove_path_accepts_shape_preserving_symlinked_parent` (dotfile
  symlink still works, no over-rejection).

### H2 - install write is check-then-act (TOCTOU symlink race)

- **Severity**: LOW. **Location**: `src/safelint/_skill_install.py`
  (`_install_one` ~L1061, `_install_copy` ~L776 `shutil.copyfile`,
  `_install_symlink` ~L765 `symlink_to`).
- **What**: `_install_one` checks `target.exists() / is_symlink()`, then later
  `shutil.copyfile` / `symlink_to`. An attacker who can write the install
  parent directory could win the window and have the copy follow a swapped
  symlink to an arbitrary victim-writable file. This is the install-flow
  symlink race `SECURITY.md` explicitly lists as in-scope.
- **Preconditions / why LOW**: needs existing write access to the install
  parent (`.claude/skills/safelint/` etc.) AND winning a tight race; the
  payload written is fixed bundled skill text, not attacker-chosen.
- **Fix**: on POSIX, open the destination with
  `os.open(..., O_CREAT | O_EXCL | O_NOFOLLOW)` for the copy (write via the
  fd) and create symlinks without a prior check-then-act window, rather than
  relying on a preceding `exists()` check. **`os.O_NOFOLLOW` is POSIX-only**
  (it does not exist on Windows, which safelint supports), so guard the flag
  behind a `hasattr(os, "O_NOFOLLOW")` / platform check; on Windows fall back
  to `O_CREAT | O_EXCL` (creation fails if the name already exists, closing
  the predictable-target race) plus an `is_symlink()` check immediately before
  the write. The remediation's tests should cover both code paths.
- **Fixed (PR #82)**: `_install_copy` now writes through a new
  `_write_new_file_exclusive` helper using `Path.open("xb")` (exclusive
  create). POSIX makes `O_CREAT | O_EXCL` fail on a symlink too (`EEXIST`,
  regardless of the link target), so this covers the planted-symlink case
  without an explicit `O_NOFOLLOW` / `os.open` (simpler, and keeps the helper
  inside pathlib); Windows gets the same exclusive-create guarantee. The
  helper name carries "write" so SAFE304 reads it as I/O-by-intent, and the
  `with` keeps SAFE401 happy. Tests: `test_install_copy_refuses_symlink_planted_at_target`
  (symlink at target -> `FileExistsError`, victim untouched) and
  `test_install_copy_writes_fresh_file_content` (happy path).

### H3 - `test_dirs` config globs outside the project root (read/stat only)

- **Severity**: LOW. **Location**: `src/safelint/rules/test_coverage.py`
  (`_test_dir_contains` ~L286 `test_dir.rglob(name)`, reached via
  `_find_test_file` ~L143 from `test_dirs` config; same un-anchored
  `Path(td)` at ~L225 / ~L271).
- **What**: `test_dirs` entries are turned into bare `Path(d)` (un-anchored,
  un-resolved) and `rglob`-ed. A crafted config with
  `test_dirs = ["../../../../etc"]` or `["/etc"]` walks **outside the project
  root** probing for a candidate test filename. The result is reduced to a
  boolean (flips SAFE701 / SAFE702 on/off) - **read/stat only, no contents
  read or written**, no exfiltration channel.
- **Preconditions / why LOW**: both consuming rules are `enabled: false` by
  default; the attacker is a malicious committed config run by a victim, and
  the leak is only filesystem-structure existence bits. (`per_file_ignores` /
  `exclude_paths` are NOT affected - they are string-only `fnmatch` against
  already-discovered in-tree paths.)
- **Fix** (done, PR #81 / `2.6.1rc1`): `_find_test_file` routes each entry
  through `_contained_test_dir`. **Relative** entries are collapsed lexically
  (`os.path.normpath` - no filesystem access, so a non-existent / symlinked
  path neither raises nor is followed) and dropped if they escape the project
  root. **Absolute** entries are honoured as-is - they are an explicit,
  supported config choice (the test suite passes `str(tmp_path / "tests")`),
  and `cwd` is not reliably the project root for an absolute entry, so
  containing them would over-reject legitimate configs (the H1 over-rejection
  lesson). The residual absolute-path probe is near-zero risk (read/stat-only
  existence bit, opt-in rules, no exfiltration). The original "reject absolute
  paths" recommendation was revised here after the test suite showed absolute
  `test_dirs` is a supported feature.

### H4 - cache tmp write/rename has no `O_EXCL` / `O_NOFOLLOW` (defence-in-depth)

- **Severity**: LOW (hardening). **Location**: `src/safelint/core/_cache.py`
  (~L224-227: `tmp = path.with_suffix(".json.tmp")`, `tmp.write_text(...)`,
  `tmp.replace(path)`).
- **What**: the cache writes a deterministic-named tmp file then atomically
  renames. If `.safelint_cache/` is attacker-controlled, a pre-planted symlink
  at the tmp name would be written through.
- **Preconditions / why LOW**: requires the attacker to already have write
  access to the victim's `.safelint_cache/` (and to predict the sha256 cache
  key) - with that access they can write the cache files directly anyway, so
  the symlink angle grants nothing. The cache dir is NOT config-controllable
  (it is `find_config_root()/".safelint_cache"`, a hardcoded constant).
- **Fix**: write the tmp file via `tempfile.mkstemp(dir=cache_dir)`
  (`O_CREAT | O_EXCL`) so a pre-planted tmp name / symlink can't be followed.
- **Fixed (PR #83)**: `LintCache.put` now creates the temp via
  `tempfile.mkstemp(dir=self.cache_dir, suffix=".json.tmp")` and writes through
  the returned fd with `os.fdopen(...)` inside a `with` (never reopening by
  name), then `Path(tmp).replace(path)`. `mkstemp` opens with
  `O_CREAT | O_EXCL` (plus `O_NOFOLLOW` where the platform provides it - POSIX,
  not Windows) under an unguessable random name; the cross-platform property
  comes from `O_EXCL` + the unpredictable name, so the old predictable
  `<key>.json.tmp` symlink-plant is structurally defeated. The
  raw-fd path is the one place `os` is justified here (no pathlib equivalent
  for an atomic exclusive temp create); documented inline for H6. Fail-open
  posture preserved (two `except OSError` arms, `# nosafe: SAFE203`). Test:
  `test_lint_cache_put_ignores_planted_deterministic_tmp_symlink`.

### H5 - `_maybe_seed_secondary_for_opencode` touch() follows a dangling `AGENTS.md` symlink

- **Severity**: LOW. **Location**: `src/safelint/_skill_install.py`
  (~L671: `if secondary.exists(): return` then `secondary.touch()`).
- **What**: a *non-dangling* `AGENTS.md` symlink is short-circuited
  (`exists()` follows it -> True -> return, and the later `_install_secondary`
  refuses symlinks). But `Path.exists()` returns **False for a dangling
  symlink**, so if `AGENTS.md` is a dangling symlink (e.g. ->
  `/victim/newfile`, target absent), `exists()` is False and `touch()`
  **follows the symlink and creates an empty file at the link target**. A
  file-creation primitive, not a content-write.
- **Preconditions / why LOW**: needs an attacker-planted dangling symlink at
  the project's `AGENTS.md`, a victim with `.opencode/` present, and a
  project-scope install run; the created file is empty and lands somewhere the
  victim can already write. No content control.
- **Fix**: add an explicit `if secondary.is_symlink(): return` (or
  `secondary.lstat()`-based check) before `touch()` - it must catch the
  dangling case that `exists()` misses.
- **Fixed (PR #83, hardened in #86)**: the guard is `if secondary.is_symlink()
  or secondary.exists(): return` (`is_symlink()` is lstat-based, True for a
  dangling symlink - the case `exists()` misses - and sits first). A review on
  #86 noted that the pre-check is still check-then-act, so the seed now also
  writes via an exclusive create (`_write_empty_file_exclusive`, `"xb"` /
  `O_CREAT | O_EXCL`) instead of `touch()`: a symlink appearing in the
  check-then-write window makes the create fail (`FileExistsError`, treated as a
  no-op) rather than being followed, closing the residual TOCTOU race. Tests:
  `test_install_opencode_does_not_follow_dangling_agents_md_symlink` plus
  `test_write_empty_file_exclusive_*` (creates / no-op-on-symlink / no-op-on-file).

### H6 - prefer `pathlib.Path` over `os.path` / `os` where a safe equivalent exists

- **Severity**: cleanup / consistency (no vulnerability of its own). **Scope**:
  whole `src/` tree. This is the final pass before closing the plan: a
  `Path`-first codebase reads better and gives fewer footguns than ad-hoc
  `os.path` string munging, but the migration must be **case-by-case** - some
  `os` calls have no clean `Path` equivalent and must stay (documented inline
  so a later reviewer does not "tidy" them into a regression).
- **What** (audit of remaining `os` usages, 2026-06-26):
  - `_skill_install._resolved_install_shape_ok` - **already migrated** in
    PR #82 from `os.path.realpath` to `Path.resolve(strict=False)` (the H1
    fix), and that file no longer imports `os`.
  - `cli.py` / `engine.py` `os.walk(target, followlinks=False)` - **keep**.
    `Path.walk(follow_symlinks=False)` only exists on Python 3.12+, but
    `requires-python = ">=3.11"`, and the `followlinks=False` is a deliberate
    security control (no symlink-dir descent / cycle). Revisit only if the
    Python floor moves to 3.12.
  - `cli.py` `os.environ.get("PRE_COMMIT")` - **keep**. Environment lookup;
    `Path` has no bearing.
  - `test_coverage.py` `os.path.normpath` (the H3 lexical containment) -
    **keep**. `normpath` collapses `..` **lexically without touching the
    filesystem**; `Path.resolve()` would hit the fs and follow symlinks, which
    is exactly what H3 must avoid. There is no pure-`pathlib` lexical-collapse
    equivalent, so this `os.path` use is correct and must stay.
  - `_cache.py` `tempfile.mkstemp` + `os.fdopen` (the H4 exclusive-create temp)
    - **keep**. There is no pathlib equivalent for an atomic exclusive temp
    create; the raw fd from `mkstemp` is written through `os.fdopen` without
    reopening by name. Added in PR #83, documented inline.
  - `cli.py` `os.environ.get("PRE_COMMIT")` - **keep**. Environment lookup;
    `Path` has no bearing, and no deceptive pathlib lookalike, so no inline
    note needed.
- **Fix / outcome (PR #84)**: the only genuinely migratable case was the H1
  path, done in PR #82. The remaining `os` uses are justified. The two with a
  *deceptive* pathlib lookalike - `os.walk` (looks like `Path.walk`, but that
  is 3.12+ and the floor is 3.11) and `os.path.normpath` (looks like
  `Path.resolve`, but that touches the fs) - now carry explicit "do not tidy
  to `Path`" inline comments at every call site (`engine._walk_supported_files`,
  `cli._walk_unavailable_extensions`, `test_coverage._contained_test_dir`).
  `os.fdopen` (H4) and `os.environ` need no note. If a future change introduces
  a new `os.path` call, default to `Path` unless one of the above exceptions
  applies. **This closes the audit's remediation list - H1-H6 all done.**

## Verified clean (recorded so the covered surface is auditable)

- **git subprocess** (`cli.py`): all four calls are list-form (never
  `shell=True`); the argv is a fixed string-literal subcommand + flags with
  **no interpolated or attacker-influenced element** (the only variable is
  `git_bin`, in argv[0]). `git` is resolved via `shutil.which("git")`
  (None-checked, falls back to scan-all if absent) - note `shutil.which`
  returns whatever PATH resolves to, so it is not *guaranteed* absolute if
  PATH itself holds relative entries; that is the standard PATH-trust
  assumption every git-shelling tool makes, not a safelint-specific flaw.
  Robust error handling. No injection.
- **File discovery** (`engine.py`): `os.walk(followlinks=False)` (no descent
  into symlinked dirs / no symlink-cycle) + `is_file()` pre-read guard. A
  symlinked file resolving to a regular file is read, but reading only lints
  it and parse errors emit kind + coordinates only (no content leak).
- **`per_file_ignores` / `exclude_paths`**: string-only `fnmatch.fnmatchcase`
  against in-tree paths; never reach the filesystem.
- **Config-discovery parent walk**: only changes which rules fire; no
  destructive write (the one filesystem-touching field is `test_dirs`, H3).
- **Cache key / dir**: sha256 content+config digest; dir is a hardcoded
  constant under the discovered root, not config-controllable.
- **`_validators.py`**: pure type validation, no filesystem access.

## Remediation sequencing (suggested)

Low urgency (no HIGH/MEDIUM, none default-flow-exploitable). Bundle as one
"security hardening" PR or fold into the next maintenance pass:

1. H3 (`test_dirs` containment) - the only one reachable purely through
   crafted config; smallest, most self-contained fix.
2. H1 + H2 (install/remove symlink containment) - related; do together with
   tests that assert refusal on a symlinked ancestor / raced target.
3. H4 + H5 (cache `mkstemp`, seed guard) - defence-in-depth, opportunistic.

Validation gate for the remediation PR (the project's standard `uv run`
invocation, matching CI):

```bash
uv run pytest                                  # coverage gate fail_under = 97
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/ --all-files --fail-on=error   # exactly as CI runs it; zero blocking violations
uv run mkdocs build --strict
```

Plus new tests proving each guard (a `--path` whose parent symlink redirects
to a different tree is refused while a real unusual parent still works, the
raced install target is not followed, the `test_dirs` escape is contained).

---

## SOC sign-off: C language addition (v2.7.0, PR #87)

Security review of the C-support branch (`feature/c-language-support`), reviewing
**only what the change introduced**, not pre-existing surface. **Verdict: no
security issues introduced; no behavioural regression to the other seven
languages.** Reviewed 2026-06-28.

safelint's threat model is unchanged and narrow: it reads source, parses with
Tree-sitter, and emits violations; it never executes the analysed code, opens
no network connections, and deserialises nothing.

- **Code execution: none.** The `system` / `popen` / `execl` / `dlopen` strings
  that appear in the diff are **config data** - C function names safelint
  *matches against in the user's code* (SAFE801 sinks, SAFE309/310 call lists),
  never invoked by safelint. No `subprocess` / `eval` / `exec` / `compile` /
  `pickle` / `__import__` / `socket` / file-write in any new code.
- **ReDoS: none.** One new regex, `_C_NOLINT`
  (`^//\s*(NOLINT(?:NEXTLINE|BEGIN|END)?)(?=\(|\s|$)(\([^)]*\))?`), has no nested
  quantifiers and no ambiguous alternation under a quantifier; `\s*` and
  `[^)]*` are linear, so it is linear in comment length. The macro-balance check
  (SAFE311) is `str.count()`, O(n).
- **Unbounded loops: none.** Every new loop is bounded - `for _ in range(16/32)`
  (declarator unwraps), `for ... in walk()/named_children` (finite AST), and the
  one `while len(stack) > 0` is an iterative worklist over a finite tree. No
  `while` on attacker-controlled input.
- **Path containment intact.** The H3 control (`_contained_test_dir` /
  `_find_test_file`) was **not modified**; the C test-file search reuses it. The
  diff to `test_coverage.py` only changed candidate-filename generation. Adding
  `.h` to the registry only means safelint parses `.h` files (its purpose);
  parse errors still emit coordinates only, no content leak.
- **Supply chain.** One new grammar, `tree-sitter-c` (official, pinned
  `>=0.23.0`, hash-locked in `uv.lock`) - same trust model as the seven existing
  grammars, already in SECURITY.md's documented scope. No new risk class.
- **Cache / skill-install surface (H1-H6) untouched.**

**Regression (other languages).** The branch edits shared files (the function-
shape rules, `side_effects`, `state_purity`, `test_coverage`, `loop_safety`,
`dataflow`, `_node_utils`, `config.py`), so non-C behaviour was re-verified:

- Full suite green at the time of this security review (1717 passed, including
  all 671 existing per-language rule tests for Python / JS / TS / Java / Rust /
  Go / PHP). The suite has since grown as later review rounds added C
  regression tests; the relevant invariant is that the full suite stays green,
  not the exact count.
- The shared refactors are behaviour-preserving: the new
  `_node_utils.function_name_node(node, lang)` returns
  `child_by_field_name("name")` for every non-C language (identical to the old
  inline code); `_func_display_name` keeps its JS anonymous-binding fallback;
  the `test_coverage` / `dataflow` dict-dispatch refactors (done for `PLR0911`)
  produce identical routing; and every `_BY_LANG` / `language`-tuple change is
  purely additive (a `"c"` entry appended, no existing entry touched).

---

## Follow-up audit (2026-07-02): full-repo SOC re-scan

**Type**: authorised internal defensive re-audit of safelint's own codebase,
after the C release (v2.7.0). **Method**: three parallel read-only surface
sweeps - (1) the skill-install flow (`_skill_install.py`), (2) the config /
cache / CLI / engine surface, (3) a repo-wide dangerous-pattern sweep plus a
line-by-line delta review of every `src/` change since the C SOC sign-off
commit (`734b26e`, 2026-06-28). Cross-checked against the H1-H6 remediations
and the GitHub Actions / dependency surface.

### Headline

- **No HIGH or MEDIUM findings.** The original H1-H6 fixes were re-verified as
  correctly implemented and tested (evidence below). No `eval` / `exec` /
  `subprocess`-of-user-code / deserialisation / network / new file I/O anywhere;
  the only subprocess remains the four list-form `git` calls; the only writes
  remain the sanctioned skill-installer (exclusive-create) and cache
  (`mkstemp`) paths.
- **The C language addition introduced no new security surface** and two of its
  changes are net security-positive (see delta review). Confirmed against the
  earlier C SOC sign-off.
- **Three new LOW / hardening items** (H7-H9). None is exploitable in the
  default no-flag flow; H7/H8 need a local attacker with directory-write access
  plus a race win, H9 is CI/CD supply-chain defence-in-depth.

### H7 - `AGENTS.md` secondary-file merge write is check-then-act (TOCTOU, the H2 class left open on this path)

- **Severity**: LOW. **Location**: `src/safelint/_skill_install.py`
  `_install_secondary` (~L1056-1065) and `_remove_secondary` (~L1075-1088),
  gated by `_secondary_target_writable_or_warn` (~L1021-1030).
- **What**: the writable-guard checks `target.is_symlink()` / `target.is_file()`,
  then the caller does `target.read_text()` and `target.write_text(...)`.
  `write_text` follows symlinks. A statically-committed malicious `AGENTS.md`
  symlink is caught by the check; the gap is a swap *after* the check - a
  concurrent local attacker replaces the regular `AGENTS.md` with a symlink to
  an arbitrary victim-writable file between the check and `write_text`, and
  safelint then writes the merged text (existing content + the fixed bundled
  section) through the link.
- **Preconditions / why LOW**: local write access to the directory holding
  `AGENTS.md` (project cwd or home) AND winning a tight race; the payload is
  not fully attacker-controlled (existing content plus a fixed bundled
  section). Not reachable in any default flow.
- **Why flagged**: this is the *identical* TOCTOU class as H2, which the plan
  judged worth fixing via exclusive create. H2 hardened the primary-file write;
  this secondary-file merge path is the one remaining `write_text`-follows-
  symlink site in the module, so leaving it non-atomic is inconsistent with the
  closed H2.
- **Fix**: write the merged content to an exclusive-create temp in the same
  directory and `os.replace()` it into place, or open the destination with
  `os.open(..., O_CREAT | O_TRUNC | O_NOFOLLOW)` (POSIX; `hasattr` guard for
  Windows, mirroring the H2 write-note) so a symlink appearing in the window
  makes the write fail rather than being followed. A merge (read-modify-write)
  cannot use plain `"xb"` because the target legitimately pre-exists, so this
  needs the temp-plus-replace shape, not the H2 exclusive-create helper as-is.

### H8 - `_remove_path` validates the resolved parent shape but deletes the unresolved path (ancestor-swap race)

- **Severity**: LOW (residual; same class as H1). **Location**:
  `src/safelint/_skill_install.py` `_remove_path` (~L1791-1804).
- **What**: `_resolved_install_shape_ok(path)` (the H1 guard) resolves the
  ancestors at check time; `_remove_existing(path)` then operates on the
  *original unresolved* `path`. In the no-race case this is intentional and
  correct (the `test_remove_path_accepts_shape_preserving_symlinked_parent`
  behaviour depends on deleting the unresolved leaf so terminal-symlink
  handling is preserved). The gap is purely the race: an attacker who controls
  an ancestor directory swaps an ancestor symlink between the `resolve()`
  validation and `_remove_existing`, redirecting the `unlink` / `rmtree` onto a
  different real tree.
- **Preconditions / why LOW**: `--path` is the documented opt-in "unusual
  location" escape hatch (user already accepts responsibility), AND the attack
  needs ancestor-directory write access AND a race win. `_remove_existing`
  unlinks a leaf symlink as the link (never follows it) and only reaches
  `shutil.rmtree` for a real directory target (rmtree refuses a symlinked
  top-level target), so the residual is confined to the ancestor-swap race, not
  the leaf.
- **Fix** (defensible to accept-and-document instead, given the opt-in escape
  hatch): resolve once and operate on the resolved path, or open the parent
  directory and remove the leaf relative to a directory fd (`os.unlink(name,
  dir_fd=...)`) so the validated parent and the acted-on parent are the same
  object. Weigh against H1's deliberate "delete the unresolved leaf so terminal
  symlinks are unlinked as links" behaviour - any fix must preserve that.

### H9 - GitHub Actions pinned to mutable refs (CI/CD supply-chain hardening)

- **Severity**: LOW (hardening). **Location**: `.github/workflows/*.yml`.
- **What**: third-party actions are pinned to mutable refs - `actions/checkout@v4`,
  `actions/upload-artifact@v4`, `actions/download-artifact@v4` (major-version
  tags), `astral-sh/setup-uv@v8.1.0` (patch tag), and most notably
  `pypa/gh-action-pypi-publish@release/v1` - a **moving branch ref** - in
  `publish.yml`, the one workflow that holds `id-token: write` (PyPI OIDC
  trusted publishing). A compromised or force-moved upstream ref would run in
  the release job's privileged context.
- **Preconditions / why LOW**: requires upstream action compromise (or a
  maintainer-account / tag-move on the action repo); not a safelint-code flaw.
  The blast radius is bounded by OIDC (no long-lived PyPI token to steal) and
  by least-privilege `permissions:` blocks (`contents: read` on ci/publish,
  scoped `id-token: write` only on the publish job).
- **Fix**: pin every third-party action to a full commit SHA (with a trailing
  `# vX.Y.Z` comment for readability), prioritising `publish.yml`'s
  `gh-action-pypi-publish` since it runs in the OIDC-privileged step. Dependabot
  can keep SHA pins updated (`package-ecosystem: github-actions`).
- **Note**: workflows are otherwise clean - no `pull_request_target`, no
  `github.event.*` / `head_ref` interpolation into `run:` blocks (no script
  injection), and the `publish.yml` tag-verify step reads the tag via the
  `GITHUB_REF` env var expansion (`TAG="${GITHUB_REF#refs/tags/v}"`), not via a
  `${{ }}` template into shell, so it is injection-safe.

### Re-verified clean (recorded so the covered surface stays auditable)

- **H1 / H2 / H5** (skill-install): implementations and tests present and
  correct - `_resolved_install_shape_ok` (called from `_remove_path`, resolve
  failure treated as refusal), `_write_new_file_exclusive` (`"xb"`), and the
  `_maybe_seed_secondary_for_opencode` `is_symlink() or exists()` guard plus
  `_write_empty_file_exclusive`. `skill status` / `path` do not print file
  bytes from a symlinked location (no read-leak primitive). `--client` is
  argparse-`choices`-restricted and every `install_relpath` is a fixed literal,
  so no traversal composition.
- **H3 / H4** (config / cache): `test_dirs` reaches the filesystem only through
  the `_contained_test_dir`-filtered `rglob`; the other two `test_dirs` sites
  (`_is_test_file`, `_paired_test_in_changed_under_test_dirs`) use `.absolute()`
  for lexical string-component comparison only (no fs access), so nothing
  bypasses containment. Cache `put` uses `mkstemp` + `os.fdopen` + `replace`
  and fails open; cache `get` treats malformed JSON / missing keys / wrong types
  / extra keys as a clean miss (no crash, no unvalidated replay without the
  attacker already owning the cache dir).
- **Config / output surface**: TOML via stdlib `tomllib`; rule config resolved
  by dict-key lookup with no `getattr` / `eval` / import from config values;
  preset resolution deep-copies and falls back on unknown names (never raises);
  JSON / SARIF go to stdout only via `json.dumps(ensure_ascii=False)` (escaped,
  no injection channel); `SAFE000` emits node-kind + coordinates only, never
  source content.
- **Repo-wide sweep**: zero `eval` / `exec` / `compile` / `pickle` / `marshal`
  / `yaml.load` / `ast.literal_eval`; zero network / socket; the five
  subprocess calls are all the list-form git invocations (`timeout=10`,
  `check=False`, `shutil.which("git")` at argv[0], no interpolated element);
  one env read (`PRE_COMMIT`, affects only hint wording); every regex is linear
  (no nested quantifiers / ambiguous alternation - including the Rust
  string-stripper `"(?:[^"\\]|\\.)*"` whose alternatives are disjoint on the
  first char, and the config-supplied Rust name matcher which is `re.escape`d);
  every `while` loop terminates (worklists over finite trees, parent-chain
  climbs, strict child-descent, sibling chains); the C `_scan_char` /
  `_strip_quoted` scanners are single-pass `for` loops whose index advances
  unconditionally.
- **Delta since the C SOC sign-off (`734b26e`)**: 19 `src/` commits, all pure
  Tree-sitter analysis logic. `dataflow_c` folded the recursive `_call_tainted`
  into the iterative worklist (`_classify_call` now returns argument nodes
  instead of recursing - termination re-verified: each pushed node is a strict
  descendant, entered at most once). `_node_utils.function_name_node`'s
  `range(16)` cap became `while node is not None` over the finite acyclic
  declarator chain (terminates). New `_C_NOLINT` regex and `re.sub(r"\s",...)`
  are linear. **Two changes are net security-positive**: trimming
  `scanf`/`read`/`recv` from `sources_c` (removes false tainting of count
  variables) and the intra-loop-goto tightening in `loop_safety` (closes a
  SAFE501 false-negative). No new I/O / subprocess / network / deserialisation
  / env read introduced.
- **Supply chain**: one runtime dependency (`tree-sitter>=0.23.0`); all eight
  grammars are opt-in extras (`tree-sitter-<lang>>=0.23.0`); `uv.lock` is
  hash-pinned (sha256) with every artifact URL on `files.pythonhosted.org`;
  publishing is PyPI Trusted Publishing (OIDC), no long-lived token. Dependabot:
  0 open alerts as of the scan.

### Corrections to the C SOC sign-off text (descriptions drifted post-sign-off; re-verified clean)

The 2026-06-28 sign-off above described code that later review rounds changed;
the delta review re-verified each as clean, but the sign-off's wording is now
stale and is corrected here rather than rewritten in place (it is a
point-in-time record):

- "the macro-balance check (SAFE311) is `str.count()`, O(n)" - it is now a
  stack-based bracket matcher over the quote-stripped text (still linear,
  single pass), not `str.count()`.
- the quoted `_C_NOLINT` pattern (`^//\s*(NOLINT...`) - the shipped pattern
  dropped the `^//\s*` prefix and matches against the marker-stripped comment
  body (`^(NOLINT...`), so it now also covers block-comment `/* NOLINT */`.
- "every new loop is bounded - `for _ in range(16/32)`" - several declarator
  walks are now unbounded `while node is not None` loops; they still terminate
  on the finite acyclic Tree-sitter tree (re-verified), but the stated
  invariant is "terminates on a finite tree", not "fixed iteration cap".

### Remediation sequencing for H7-H9

Low urgency (no HIGH/MEDIUM; none default-flow-exploitable). Bundle with the
next maintenance pass, or fold into the C++ / audit-remediation work:

1. **H9** (SHA-pin actions) - smallest, self-contained, no code; do first.
   Add a `github-actions` Dependabot ecosystem to keep pins fresh.
2. **H7** (secondary-write temp-plus-replace) - the notable one; mirror H2's
   posture on the merge path. Needs a test asserting a symlink planted at
   `AGENTS.md` in the write window is not followed.
3. **H8** (resolve-once / `dir_fd` remove, or accept-and-document) - decide
   between hardening and documenting the opt-in escape-hatch residual; either
   is defensible. Preserve H1's unlink-the-leaf-as-a-link behaviour.

Same validation gate as above applies to any remediation PR.
