# Claude Code

**Markers:** `CLAUDE.md`, `.claude/`, or `.claude.json` in the project root for project-scope; `~/.claude/` or `~/.claude.json` for user-scope. Any one marker is enough, detection picks the first one it finds.

**Install location:**

- User-scoped: `~/.claude/skills/safelint/SKILL.md`
- Project-scoped: `<cwd>/.claude/skills/safelint/SKILL.md`

Language-specific addendums (`languages/python.md`, etc.) are looked up on demand from the bundled package via `safelint skill path`, the same way every other client does it.

**How to invoke after install:**

Restart Claude Code (or open a new session). The skill registers automatically. Then in any conversation:

- *"run safelint"*
- *"lint my changes with safelint"*
- *"do a Power-of-Ten review on `src/api/auth.py`"*
- *"safelint check, all files"*

The skill takes over: invokes `safelint check ... --format json`, parses the output, groups violations by file (and by language when more than one is involved), and offers to walk through fixes.

**Manual install:**

```bash
safelint skill install --client claude            # user-scoped
safelint skill install --client claude --project  # project-scoped
```

See [Manual install](../manual-install.md) for the full flag reference.
