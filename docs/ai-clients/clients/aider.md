# aider

**Markers:** `.aider.conf.yml`, `.aider.conf.yaml`, or `CONVENTIONS.md` in the project root for project-scope; `~/.aider.conf.{yml,yaml}` for user-scope.

**Install location:**

- User-scoped: `~/CONVENTIONS.md`
- Project-scoped: `<cwd>/CONVENTIONS.md` — **Recommended for team-shared repos — commit the file.**

**One-time setup (mandatory):** aider does **not** auto-load `CONVENTIONS.md`. Wire it in by adding a `read:` entry to your `.aider.conf.yml`:

```yaml
# .aider.conf.yml (project) or ~/.aider.conf.yml (user-global)
read:
  - CONVENTIONS.md
```

The post-install message reminds you of this — without the `read:` entry, aider won't see safelint's conventions.

**How to invoke after install:**

Once `read:` is wired up, run `aider` (no flags). The conventions are loaded as part of aider's system context. Then ask aider *"run safelint"* / *"lint with safelint"* — same prompts as the other clients.

**Manual install:**

```bash
safelint skill install --client aider --project   # then wire `read: [CONVENTIONS.md]` into .aider.conf.yml
safelint skill install --client aider             # user-global
```

See [Manual install](../manual-install.md) for the full flag reference.
