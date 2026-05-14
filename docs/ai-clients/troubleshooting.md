# Troubleshooting

## "could not auto-detect an AI client"

Means neither cwd nor home had any of the registered markers. Either:

1. The AI client isn't installed on this machine, install it first, *then* run `safelint skill install`.
2. You want a specific client regardless of detection, use `--client <name>` explicitly. The error message lists the exact commands.

## "target already exists. Use --force to replace it."

A previous install is in the way. Pass `--force` to replace it. SafeLint refuses to silently overwrite by default to protect against losing a customised skill folder.

## Cursor doesn't seem to pick up the rule

Cursor reads `.cursor/rules/*.mdc` files at window load. After installing, you need to **reload the Cursor window** (Command Palette → "Developer: Reload Window"), the rule isn't hot-reloaded.

## Claude Code doesn't seem to pick up the skill

Same idea, Claude Code loads skills on session start. Open a new conversation or restart the app.

## "I want to inspect the bundled files without installing"

```bash
safelint skill path                  # Claude skill directory
safelint skill path --client cursor  # Cursor MDC file path
```

Useful for `cat $(safelint skill path)/SKILL.md` to see what the agent is reading.
