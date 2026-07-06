#!/usr/bin/env bash
# Pre-PR gate: every deterministic check, zero tokens. Run on each new code
# change BEFORE raising a PR; only when this is green is a semantic review
# worth spending tokens on.
#
# The full routine (see CLAUDE.md and the review setup):
#   1. ./scripts/pre-pr.sh          <- this script (formatting/lint/type/
#                                      self-lint/docs parity are all enforced
#                                      here and in the drift tests, for free)
#   2. /code-review                 <- one semantic pass in Claude Code
#                                      (logic bugs, security, side effects);
#                                      use `low` for docs-only changes,
#                                      `high` for risky ones
#   3. gh pr create ...
#   4. optional: /code-review --comment  <- mirror findings as inline PR
#                                           comments once the PR exists
#   5. optional: add the `claude-review` label on GitHub to trigger the
#      metered CI review (.github/workflows/claude-review.yml) - owner
#      opt-in per PR, off by default.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run pytest -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run safelint check src/ --all-files --fail-on=error
uv run --extra docs mkdocs build --strict

echo ""
echo "pre-PR gate green - ready for /code-review, then gh pr create"
