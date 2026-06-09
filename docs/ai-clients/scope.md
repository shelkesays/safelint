# Project vs user scope

Most supported clients can be installed at either of two scopes. The choice is independent of which client you're installing.

| | User scope (default) | Project scope (`--project`) |
|---|---|---|
| **Path** | `~/.<client>/...` | `<cwd>/.<client>/...` |
| **Activation** | Every session, every project | Only inside this project |
| **Best for** | Solo developer, one machine | Team-shared repos (commit the install) |
| **Auto-detect** | Triggered by markers under `~/` | Triggered by markers under `cwd` |

For the exact install path each client uses at each scope, see the per-client guide linked from the [AI clients overview](index.md).

## Project-scope-only clients

A few clients have **no user-scope file** at all, their cross-project "global rules" live in a cloud or UI rather than on disk. Currently this is just **Warp**: its project file is `<cwd>/WARP.md`, but Warp's "Global Rules" are managed through the Warp Drive UI, not `~/WARP.md`. For such a client:

- `safelint skill install --client warp` (without `--project`) exits 1 with a clear error rather than writing a file the client never reads. Pass `--project`.
- Auto-detection never falls back to the home directory for it (it has no home markers to match), so a bare `safelint skill install` only ever installs it project-scoped.

## Symlink mode (developer loop)

`--symlink` links to the bundled location instead of copying. After `pip upgrade safelint`, the skill / rule reflects the new content immediately, no `safelint skill install --force` needed.

```bash
safelint skill install --symlink
safelint skill install --client cursor --symlink
```

Every client installs a single file, so `--symlink` is one symlink at the install destination pointing at the bundled artefact inside the wheel. ``pip upgrade safelint`` reflects content changes immediately through the link.

Caveat: symlink mode requires symlink support, POSIX shells, or Windows with developer mode enabled. If you hit "operation not permitted", drop the `--symlink` flag and use the default copy mode.
