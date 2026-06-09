# Troubleshooting

## "could not auto-detect an AI client"

Means neither cwd nor home had any of the registered markers. Either:

1. The AI client isn't installed on this machine. Install it first, *then* run `safelint skill install`.
2. You want a specific client regardless of detection. Use `--client <name>` explicitly; the error message lists the exact commands.

## "Warp does not support user-scope install"

Warp is **project-scope only**, its cross-project "Global Rules" are managed through the Warp Drive UI, not a home-directory file. So `safelint skill install --client warp` (without `--project`) exits 1 with this error rather than writing a `~/WARP.md` that Warp never reads. Re-run with `--project` to install `<cwd>/WARP.md`:

```bash
safelint skill install --client warp --project
```

## "target already exists. Use --force to replace it."

A previous install is in the way. Pass `--force` to replace it. SafeLint refuses to silently overwrite by default to protect against losing a customised skill folder.

## Cursor doesn't seem to pick up the rule

Cursor reads `.cursor/rules/*.mdc` files at window load. After installing, you need to **reload the Cursor window** (Command Palette → "Developer: Reload Window"), the rule isn't hot-reloaded.

## Claude Code doesn't seem to pick up the skill

Same idea, Claude Code loads skills on session start. Open a new conversation or restart the app.

## "I want to inspect the bundled files without installing"

```bash
safelint skill path                  # bundle root directory
safelint skill path --client claude  # <bundle>/claude/SKILL.md (file)
safelint skill path --client cursor  # <bundle>/cursor/safelint.mdc (file)
```

Without `--client`, prints the bundle root directory - the shared `languages/<lang>.md` addendums sit at `<that path>/languages/<lang>.md`. With `--client <name>`, prints a specific bundled file you can pass to `cat` to see what the agent is reading (e.g. `cat $(safelint skill path --client cursor)`).
