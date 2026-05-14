# Project vs user scope

Every supported client can be installed at one of two scopes. The choice is independent of which client you're installing.

| | User scope (default) | Project scope (`--project`) |
|---|---|---|
| **Path** | `~/.<client>/...` | `<cwd>/.<client>/...` |
| **Activation** | Every session, every project | Only inside this project |
| **Best for** | Solo developer, one machine | Team-shared repos (commit the install) |
| **Auto-detect** | Triggered by markers under `~/` | Triggered by markers under `cwd` |

For the exact install path each client uses at each scope, see the per-client guide linked from the [AI clients overview](index.md).

## Symlink mode (developer loop)

`--symlink` links to the bundled location instead of copying. After `pip upgrade safelint`, the skill / rule reflects the new content immediately, no `safelint skill install --force` needed.

```bash
safelint skill install --symlink
safelint skill install --client cursor --symlink
```

For Claude installs, the symlink is **per-entry**: the install creates a real directory at the target and symlinks each top-level entry (`SKILL.md`, `languages/`, etc.) into it. Peer-client subdirectories like `cursor/` are never symlinked into the Claude install, they're for Cursor's own install path.

Caveat: symlink mode requires symlink support, POSIX shells, or Windows with developer mode enabled. If you hit "operation not permitted", drop the `--symlink` flag and use the default copy mode.
