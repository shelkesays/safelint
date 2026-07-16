#!/usr/bin/env bash
#
# Pre-feature sync check: confirm main and development are level before you start
# a new feature branch, and fast-forward the local copies of both to origin.
#
# With the server-side sync-development workflow running, main and development are
# normally already identical after each release, so this is usually just a
# fast-forward plus a green "in sync" line. It never force-pushes on its own - if
# it finds development ahead of main it tells you, so you decide.
#
# Usage:  bin/sync.sh
#
set -euo pipefail

git fetch origin main development --tags --prune

MAIN=$(git rev-parse origin/main)
DEV=$(git rev-parse origin/development)

if [ "$MAIN" = "$DEV" ]; then
  echo "✓ main and development are in sync (${MAIN:0:7})"
else
  AHEAD=$(git rev-list origin/development ^origin/main --count)
  BEHIND=$(git rev-list origin/main ^origin/development --count)
  echo "✗ out of sync: main=${MAIN:0:7} development=${DEV:0:7} (development +${AHEAD} / -${BEHIND})"
  if [ "$AHEAD" -eq 0 ]; then
    echo "  development has nothing main is missing -> safe to reset:"
    echo "    git branch -f development origin/main && git push --force-with-lease origin development"
  else
    echo "  development has ${AHEAD} commit(s) not in main -> do NOT reset (unmerged work)."
  fi
fi

# Fast-forward the local branches to origin so a new feature starts clean.
# Fast-forward-ONLY: this never rewrites local history. If a local branch has
# diverged (local commits not on origin) it is left untouched with a note, so
# you never silently lose work. Uncommitted changes abort the local update
# entirely (nothing is checked out or moved).
if [ -n "$(git status --porcelain)" ]; then
  echo "working tree has uncommitted changes - skipping local fast-forward (commit or stash first)."
  exit 0
fi

CURRENT=$(git branch --show-current)
for b in main development; do
  if [ "$b" = "$CURRENT" ]; then
    git merge --ff-only --quiet "origin/$b" 2>/dev/null \
      && echo "  ${b} fast-forwarded." \
      || echo "  ${b} has diverged from origin/${b} - left as-is (fast-forward only)."
  else
    # Update a non-checked-out branch ref, fast-forward-only (git fetch refuses
    # a non-ff update without '+', so divergence fails safely).
    git fetch --no-tags --quiet . "refs/remotes/origin/${b}:refs/heads/${b}" 2>/dev/null \
      && echo "  ${b} fast-forwarded." \
      || echo "  ${b} has diverged from origin/${b} - left as-is (fast-forward only)."
  fi
done
