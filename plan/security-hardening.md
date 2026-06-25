# Security hardening plan (internal audit, 2026-06-25)

**Type**: defensive-security hardening backlog (not a feature). Authorised
internal audit of safelint's own codebase.

**Status**: findings documented; remediation not started. The checklist under
[Findings](#findings) tracks the items to close in a focused PR.

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
  deliberately). The git subprocess is list-form with compile-time-constant
  argv (no injection). File discovery does not descend into symlinked
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

- [ ] H1 - `skill remove --path` symlinked-ancestor containment
- [ ] H2 - install write TOCTOU symlink race (`os.open` `O_NOFOLLOW` / `O_EXCL`)
- [ ] H3 - `test_dirs` config glob containment vs project root
- [ ] H4 - cache tmp write via `mkstemp` (`O_EXCL` + unguessable name)
- [ ] H5 - `_maybe_seed_secondary_for_opencode` dangling-symlink `touch()` guard

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
- **Fix**: anchor and contain `test_dirs` entries against the resolved project
  root before globbing - reject absolute paths and any entry that escapes the
  root after `(root / td).resolve()` / `is_relative_to(root)`, or skip entries
  with `..` / absolute components.

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
