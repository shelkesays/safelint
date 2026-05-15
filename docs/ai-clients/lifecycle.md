# Updating, removing, and freshness checks

Once a skill is installed, three commands cover the rest of its lifecycle: `update`, `remove`, and `status`.

## Updating after a safelint upgrade

Copy mode (default) is a snapshot, `pip upgrade safelint` doesn't touch the installed skill until you re-run the install. Two ways to refresh:

```bash
pip install --upgrade safelint
safelint skill update                     # idempotent, no-op if everything is fresh
# or, if you want to force-refresh customised installs back to bundled:
safelint skill update --force
```

`safelint skill update` runs a drift check first and only re-installs the locations whose content has actually changed. With `--force`, it re-installs every detected install regardless of drift. The `--client`, `--project`, and `--symlink` flags work the same way as on `install`. The one meaningful difference is `--client auto`'s scope:

- **`install --client auto`** asks *"which AI client(s) is this user using?"*, by scanning marker files like `CLAUDE.md` or `.cursor/`.
- **`update --client auto`** asks *"what's already installed?"*, by scanning the actual install paths.

So the `update`-side answer is empty for a user who has marker files but hasn't installed anything yet (use plain `install` for that). Conversely, `update`/`remove` will still target installs whose markers have since been deleted.

**Targeting one client across both scopes:** `safelint skill update --client cursor` (without `--project`) refreshes matching Cursor installs in *both* the user scope (`~/.cursor/...`) and the project scope (`<cwd>/.cursor/...`), explicit `--client` is cross-scope by default. To narrow it down to just the project scope, add `--project`:

```bash
safelint skill update --client cursor             # both scopes
safelint skill update --client cursor --project   # project scope only
```

`--client` and `--project` are independent filters, `--client` picks the client; `--project` picks the scope. `skill remove` follows the same rule.

**Shape preservation:** `update` (with or without `--force`) does **not** convert install modes silently. A symlink-mode install stays a symlink after refresh; a copy-mode install stays a copy. Pass `--symlink` explicitly if you want to *switch* a copy install to symlink mode mid-flight, but note that `--symlink` only takes effect for installs that `update` actually re-installs. If the install is already fresh, use `safelint skill update --force --symlink` to convert copy → symlink; symlink → copy must go through `remove` + `install` to be unambiguous.

For one-shot manual control, prefer the canonical, shape-preserving `skill update` form (this is what `skill update` was added for in v1.10, the legacy `skill install --force` still works, but it ignores existing-install shape and silently overwrites it, which is rarely what you want for an in-place refresh):

```bash
safelint skill update --force                    # auto-detected clients (install-path detection)
safelint skill update --client cursor --force    # or specific client (cross-scope)
```

Symlink mode picks up changes automatically; no re-install needed unless you want to re-run detection (e.g. after adding a new client to the project).

## Removing an installed skill

```bash
safelint skill remove                     # auto-detect and remove every install
safelint skill remove --client cursor     # only Cursor installs (both shapes)
safelint skill remove --symlink           # only symlink-shape installs (keep copies)
safelint skill remove --project           # only project-scope installs (keep user-scope)
safelint skill remove --path /unusual/place/.cursor/rules/safelint.mdc   # one specific location (must match a registered install shape)
safelint skill remove --dry-run           # preview without deleting
```

`safelint skill remove` mirrors install's auto-detect *for install paths* (not marker files): it scans `~/.claude/skills/safelint/SKILL.md`, `<cwd>/.claude/skills/safelint/SKILL.md`, `~/.cursor/rules/safelint.mdc`, `<cwd>/.cursor/rules/safelint.mdc` and removes whatever exists.

> **Security note on `--path PATH`:** the path you pass must match a registered install shape, i.e. its tail must equal one of the canonical install relpaths (`.cursor/rules/safelint.mdc`, `.codex/instructions.md`, `.continue/rules/safelint.md`, `.clinerules/safelint.md`, `.trae/rules/safelint.md`, `.antigravity/rules/safelint.md`, `.windsurfrules`, `GEMINI.md`, `.rules`, `CONVENTIONS.md`, `.claude/skills/safelint/SKILL.md`, `.github/copilot-instructions.md`). This guard prevents typos and shell-expansion accidents (e.g. `--path ~/.config` instead of `~/.cursor/...`) from triggering `shutil.rmtree` on the wrong directory. If you have a truly unrecognisable install location, remove it manually with `rm` after inspecting its contents.
>
> **codex secondary install (`AGENTS.md`):** when `AGENTS.md` exists at the install scope root, codex's secondary install writes a delimited section into it (and `remove` strips that section back out). For security, safelint **refuses to follow symlinks** at the secondary destination, if `AGENTS.md` is a symlink, install/update/remove all skip it and print a `safelint: warning: refusing to install/remove safelint section through symlink at ...` line on stderr. Replace the symlink with a real file before re-running if you want safelint to manage that location directly.

### What gets removed under each combination

The flags compose orthogonally, `--client` filters to one client, `--project` restricts to project scope, `--symlink` filters to symlink-shape installs. **The absence of a flag means "no filter"**, *not* "only the opposite":

| Invocation | What gets removed |
|---|---|
| `remove` (no flags) | Every detected install, copy + symlink, every client, both scopes |
| `remove --symlink` | Only symlink-shape installs (copy installs survive) |
| `remove --client cursor` | All detected Cursor installs (both shapes, both scopes) |
| `remove --client cursor --symlink` | Only symlink-shape Cursor installs |
| `remove --project` | All detected project-scope installs (user-scope survives) |
| `remove --client cursor --project --symlink` | Only project-scope, symlink-shape Cursor installs |
| `remove --path PATH` | Exactly one location, regardless of every other flag |

In particular, `safelint skill remove` **without `--symlink` removes both shapes**, it's not a "remove copies only" command. The `--symlink` flag is a filter you can opt into when you want to be selective; without it, cleanup is comprehensive.

### Filesystem-level safety

`remove` only deletes from the install location. The bundled files inside `site-packages/` are never touched, regardless of install mode:

- **Copy install (single file)**, `target.unlink()` deletes the file.
- **Copy install (directory tree)**, `shutil.rmtree(target)` walks and deletes the materialised tree.
- **Symlink install (single file)**, `target.unlink()` deletes the **symlink**, not its bundled target.
- **Symlink install (per-entry directory layout, Claude `--symlink`)**, `shutil.rmtree(target)` removes the directory; inner symlinks are deleted but their targets in the bundled package stay intact.

So you can run `remove` freely without worrying about damaging the wheel, the worst case is "I have to re-run `install` to get the skill back".

### Other flags

`--path PATH` is the escape hatch for unusual install locations, overrides every other flag, removes exactly that one path, errors on stderr if the path doesn't exist. `--dry-run` previews what would be removed without touching anything; useful for documentation / CI sanity checks before commit. Each line of `--dry-run` output includes the install shape (`copy` or `symlink`) so you know what `remove` would do at that location.

## Checking whether your installed skill is current

Two ways to verify:

```bash
# Dedicated subcommand: pipe-friendly, exits 1 if any install differs
safelint skill status

# Or, opt in to a single-shot check at the start of a normal lint run
safelint check --check-skill-freshness --all-files .
```

`safelint skill status` iterates every registered AI client and both scopes (user / project), reports each detected install location as **fresh** or **differs from bundled**, and exits 0 only when every detected install matches the current bundle. Useful in CI:

```bash
safelint skill status || safelint skill update
```

`safelint check --check-skill-freshness` is the same check folded into a normal lint run, it prints a stderr warning per stale install but **does not** fail the lint (informational only). The flag is opt-in so day-to-day `safelint check` invocations stay fast (no extra FS scan).

Note: customising your installed skill (the bundled `README.md` explicitly invites it) will surface as **differs from bundled** until you re-install. That's expected, the diagnostic message includes "or ignore if you've customised it".
