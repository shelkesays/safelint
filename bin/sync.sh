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
CURRENT=$(git branch --show-current)
for b in main development; do
  git checkout --quiet "$b"
  git reset --hard --quiet "origin/$b"
done
# Leave you on development (the branch you cut features from), or where you were.
git checkout --quiet "${CURRENT:-development}"
echo "local main and development fast-forwarded to origin."
