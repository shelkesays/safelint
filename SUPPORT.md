# Getting help with SafeLint

SafeLint is a community-maintained open-source project. There's no paid support tier; the channels below are best-effort, but issues are read and responded to.

## Where to ask

| You want to… | Go here |
|---|---|
| **Report a bug** (false positive, missed violation, crash, unexpected output) | [Open an issue](https://github.com/shelkesays/safelint/issues/new). Please include the safelint version (`safelint --version`), the rule code involved (e.g. `SAFE101`), and a minimal code snippet that reproduces it |
| **Request a new feature** (a new rule, a new AI client, a new language) | Open an issue describing the use case. For new AI clients, include the marker convention you've seen in the wild (cwd / home paths); that's what we need to add a new `ClientSpec`. |
| **Ask "how do I do X with safelint"** | Check [`README.md`](README.md), [`CONFIGURATION.md`](CONFIGURATION.md), and [`AI_CLIENTS.md`](AI_CLIENTS.md) first; most usage questions are covered there. If still stuck, open a question issue |
| **Contribute a fix or new feature** | See [`CONTRIBUTING.md`](CONTRIBUTING.md); three contribution paths (rule / AI client / language) are documented with checklists |
| **Report a security vulnerability** | Email the maintainer directly at **srahul07@gmail.com**. Please don't open a public issue for security problems; give us time to ship a fix first |
| **Report Code of Conduct violations** | Email **srahul07@gmail.com**. See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for the full process |

## What to include in a bug report

The faster you give us reproducible context, the faster we can help:

1. **safelint version**: `safelint --version` or `pip show safelint`.
2. **The rule code that fired**: e.g. `SAFE101` (or "no rule fired" if your bug is "this should have flagged but didn't").
3. **Minimal code snippet**: the smallest Python file that reproduces the behaviour. Strip everything that isn't load-bearing.
4. **What you expected** vs. **what you saw**.
5. **Your config**: if you have a `safelint.toml` / `pyproject.toml` `[tool.safelint]` block, paste the relevant rule's config.
6. **Your invocation**: the exact `safelint check ...` command you ran.

A bug report with all six items typically gets answered same-day; a report missing the repro almost always gets a "could you share a minimal example?" reply first.

## Documentation

- [`README.md`](README.md), overview, install, quick start.
- [`CONFIGURATION.md`](CONFIGURATION.md), every CLI flag, every rule, every config option.
- [`AI_CLIENTS.md`](AI_CLIENTS.md), the twelve supported AI clients, per-client setup, troubleshooting.
- [`docs/json-schema.md`](docs/json-schema.md), the `--format json` output schema, for editor / plugin authors.
- [`CONTRIBUTING.md`](CONTRIBUTING.md), how to add new rules, AI clients, or languages.

## Response time expectations

This is a personal-time open-source project. Issues are typically read within a few days; substantive responses can take a week or two depending on complexity. **There's no SLA.** If something is genuinely urgent for you, the fastest path is usually to send a PR; that's far more likely to land quickly than a wait-for-fix issue.
