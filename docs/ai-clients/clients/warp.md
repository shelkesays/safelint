# Warp

[Warp](https://warp.dev) is a terminal-native AI coding agent. Its project rules / context file is `WARP.md` (or the cross-agent `AGENTS.md`) at the repo root, auto-discovered by Warp's AI when the workspace is the project directory.

**Markers:** `WARP.md` or `.warp/` in the project root for project-scope detection. `.warp/` is Warp's user-config directory (themes, prefs, AI settings) and its presence in cwd signals an active Warp user even before a project `WARP.md` is committed.

**Install location:**

- Project-scoped (the only supported scope): `<cwd>/WARP.md`, auto-discovered by Warp's AI when invoked from the repo. **Recommended for team-shared repos, commit the file.**
- User-scoped is **not supported.** Warp's "Global Rules" feature (cross-project AI context) is managed through the Warp Drive UI (Personal > Rules), not a home-directory file. There's no `~/WARP.md` or `~/.warp/WARP.md` that Warp reads, so safelint refuses to write one.

If you ask for a user-scope install explicitly, safelint exits with a clear error and writes nothing:

```text
$ safelint skill install --client warp
safelint: error: Warp does not support user-scope install (it doesn't
read from a home-directory file). Re-run with --project to install
at <cwd>/WARP.md.
```

**How to invoke after install:**

Restart Warp (or reload its AI panel). The `WARP.md` file is auto-discovered when Warp's AI is active in the project. Then ask Warp *"run safelint"* / *"lint with safelint"*, same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client warp --project   # canonical, the only supported form
```

`--project` is required. See [Manual install](../manual-install.md) for the full flag reference and the [project vs user scope](../scope.md) page for the scope semantics.
