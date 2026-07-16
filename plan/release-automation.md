# Release automation: RC + final releases, auto-sync, and release notes

**Type**: CI/CD + release-process change. Removes the manual `pull -> tag -> push
-> release` dance and the recurring `development` / `main` divergence that forces
squash-over-rebase. **Not** a code or rule change.

**Status**: planned, not started. Design confirmed with the owner; this doc is
the review artifact before any workflow changes land. High-stakes (touches PyPI
publishing and branch protection), so review this end to end first.

**Confirmed decisions** (owner): release notes come from the **CHANGELOG
section**; the post-merge sync **resets `development` to `main` only when safe**
(never clobbers in-flight dev work); write this plan first.

---

## 1. The problem, and the root-cause fix

`main` receives each release as a **squashed** commit (one new SHA); `development`
carries the **individual** commits of that same work. Same content, different
SHAs, so the next release branch cut from `development` cannot rebase onto `main`
- hence the forced squash-merge and the repeated "this branch can't be rebased".

Root-cause fix: **after every merge to `main`, reset `development` to `main`** so
they are byte-identical again. The next release branch then rebases cleanly. This
single change (piece A below) removes the divergence class entirely.

## 2. The two release types (unchanged shape, automated tail)

| | Trigger branch | Version shape | Tag | PyPI | GitHub release |
|---|---|---|---|---|---|
| **RC** | merge into `development` | `X.Y.0rcN` | `vX.Y.0rcN` | pre-release | pre-release |
| **Final** | merge into `main` | `X.Y.0` | `vX.Y.0` | release | release |

**The signal to release is the version in `pyproject.toml`.** This matches the
project's existing "the version bump is a deliberate committed edit" rule: the
bump *is* the release trigger. The automation releases a version exactly once
(guarded by "does the tag already exist"), only from the correct branch.

**What stays manual (by design):** setting `project.version` and **writing** the
CHANGELOG entries - the deliberate, reviewed edits on the
`feature -> development` (RC bump) and `release -> main` (production bump) PRs.
**Dating** the CHANGELOG is now automated (the workflow flips
`[Unreleased] -> [X.Y.Z] - date` at tag time; see C), so the separate dating step
goes away. Everything after the merge - date-stamp, tag, PyPI, GitHub release,
dev sync - is automated.

## 3. Pieces to build

### A. Auto-sync `development` -> `main` (reset-if-safe)

New workflow `.github/workflows/sync-development.yml`, on `push: main`:

1. Fetch `main` and `development`.
2. **Safety gate**: compute `git rev-list origin/development ^origin/main` (commits
   on development NOT in main). If **empty** -> safe to reset. If **non-empty**
   -> in-flight dev work exists; **do not reset**. Instead open/append a tracking
   issue (or fail with a clear message) and stop.
3. If safe: `git reset --hard origin/main` on development and
   `git push --force-with-lease origin development`.

```yaml
name: Sync development with main
on: { push: { branches: [main] } }
permissions: { contents: write }
concurrency: { group: sync-development, cancel-in-progress: false }
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>   # pin, matches H9 convention
        with: { fetch-depth: 0, ref: development, token: ${{ secrets.RELEASE_PAT }} }
      - run: |
          git fetch origin main development --quiet
          AHEAD=$(git rev-list origin/development ^origin/main --count)
          if [ "$AHEAD" -ne 0 ]; then
            echo "::error::development has $AHEAD commit(s) not in main - refusing to reset."
            exit 1   # or: gh issue create ...
          fi
          git reset --hard origin/main
          git push --force-with-lease origin development
```

Why `--force-with-lease` even after the safety gate: defence against a race
(someone pushing to development between the gate and the push).

**Note on why reset is safe here:** in the release flow (development -> release ->
main), at final-merge time development's content is already in main, so the gate
passes and the reset only realigns SHAs, losing nothing.

### B. Auto-release on version bump (tag + PyPI + GitHub release, one workflow)

Rewrite the existing `publish.yml` from **tag-triggered** to **branch-push
triggered**, doing tag + build + PyPI + GitHub release in one workflow. Keeping
the filename `publish.yml` **preserves the PyPI Trusted-Publishing trust** (which
is bound to owner/repo + workflow filename + `pypi` environment), so no PyPI
reconfiguration is needed.

On `push` to `main` / `development`:

1. **Read version** from `pyproject.toml`.
2. **Classify + branch-guard**:
   - rc-suffixed (`rc|a|b|dev` per PEP 440) -> only proceed on `development`.
   - final (`X.Y.Z`, no suffix) -> only proceed on `main`.
   - mismatch (rc on main, final on development) -> **skip** (no-op).
3. **Already-released guard**: if tag `vX.Y.Z` exists -> **skip** (the common case
   for a push that did not bump the version).
4. **Release**:
   - **Final only**: run `scripts/date_changelog.py X.Y.Z` (flip
     `[Unreleased] -> [X.Y.Z] - <date>`, re-add empty `[Unreleased]`, update
     footers), commit to `main` with the bypass token. (RC: skip - stays
     `[Unreleased]`.)
   - Create + push tag `vX.Y.Z` at the (post-date-stamp) commit. GITHUB_TOKEN
     suffices for the tag *if* everything is one workflow; but because the final
     path commits to `main` and tags, use the bypass token here too for
     consistency. This still side-steps the "GITHUB_TOKEN cannot trigger another
     workflow" gotcha because PyPI + release run in the same job.
   - `uv build`; publish to PyPI via OIDC trusted publishing (unchanged from
     today's publish job, still `environment: pypi`, still `id-token: write`).
   - `gh release create vX.Y.Z --prerelease?=<rc> --notes "<changelog section>"`.

The existing "verify tag matches project.version" guard is retained in spirit
(here it *is* the version being released, so the check becomes "tag does not yet
exist for this version").

```yaml
name: Publish to PyPI            # keep the name -> PyPI trust unchanged
on: { push: { branches: [main, development] } }
permissions: { contents: read }
jobs:
  gate:
    runs-on: ubuntu-latest
    outputs: { release: ${{ steps.g.outputs.release }}, version: ${{ steps.g.outputs.version }}, prerelease: ${{ steps.g.outputs.prerelease }} }
    steps:
      - uses: actions/checkout@<sha>
        with: { fetch-depth: 0 }
      - id: g
        run: |
          V=$(python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
          echo "version=$V" >> $GITHUB_OUTPUT
          if echo "$V" | grep -qE '(rc|a|b|\.dev)[0-9]*$'; then PRE=true; BR=development; else PRE=false; BR=main; fi
          echo "prerelease=$PRE" >> $GITHUB_OUTPUT
          if [ "${GITHUB_REF_NAME}" != "$BR" ]; then echo "release=false" >> $GITHUB_OUTPUT; exit 0; fi
          if git rev-parse "v$V" >/dev/null 2>&1; then echo "release=false" >> $GITHUB_OUTPUT; else echo "release=true" >> $GITHUB_OUTPUT; fi
  build:
    needs: gate
    if: needs.gate.outputs.release == 'true'
    ...  # tag, uv build, upload-artifact (as today)
  publish:
    needs: build
    environment: { name: pypi, url: https://pypi.org/p/safelint }
    permissions: { id-token: write }
    ...  # download-artifact + pypa/gh-action-pypi-publish (as today)
  github-release:
    needs: [gate, publish]
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@<sha>
      - run: |
          NOTES=$(python scripts/changelog_section.py "${{ needs.gate.outputs.version }}")
          gh release create "v${{ needs.gate.outputs.version }}" \
            --title "v${{ needs.gate.outputs.version }}" \
            ${{ needs.gate.outputs.prerelease == 'true' && '--prerelease' || '' }} \
            --notes "$NOTES"
        env: { GH_TOKEN: ${{ github.token }} }
```

(Tag creation can live in the `build` job's first step, or a dedicated `tag` job
before `build`; keep it before PyPI so a failed tag aborts the release.)

### C. Release notes from the CHANGELOG (`scripts/changelog_section.py`)

A small script: given a version, print the matching `CHANGELOG.md` section body
(everything between its heading and the next `## ` heading).

- **RC** (`X.Y.0rcN`): return the current `## [Unreleased]` block - rc changelogs
  stay under Unreleased until the production tag.
- **Final** (`X.Y.0`): return the `## [X.Y.0] - <date>` block. If no dated section
  for that version exists, **fail loudly** (the human forgot to date the CHANGELOG
  on the release PR) rather than shipping wrong / empty notes.

Iterative parse (no regex-heavy logic; obey safelint's own rules if it ever lints
this). Deterministic, unit-testable with a fixture CHANGELOG.

**CHANGELOG dating - decision (auto-date):** the workflow performs the
`## [Unreleased] -> ## [X.Y.Z] - <release-day>` flip itself, on a **final** release
only. This matches the project's existing rule that the heading "flips at tag
time" - and in the automated flow the release workflow *is* tag time - so it
removes the manual dating (and the separate dating PR) entirely. Clean split of
responsibility is preserved: the human sets `project.version` (the deliberate
decision); the workflow only date-stamps to match.

Mechanics (`scripts/date_changelog.py <version>`, run before tag + PyPI on a
final):
1. Rename `## [Unreleased]` -> `## [X.Y.Z] - <YYYY-MM-DD>` (date from the workflow
   run - real, accurate, no `Date.now()` sandbox issue).
2. Re-insert an empty `## [Unreleased]` above it.
3. Update the reference-style compare footers: add
   `[X.Y.Z]: .../compare/vPREV...vX.Y.Z` and repoint
   `[Unreleased]: .../compare/vX.Y.Z...HEAD`.
4. Commit to `main` (needs the bypass token), then tag **that** commit.

Safety:
- **No loop**: the flip-commit re-triggers the workflow, but `vX.Y.Z` now exists,
  so the tag-exists guard (B.3) skips the second run.
- **Idempotent**: if `## [X.Y.Z]` is already dated (a re-run), the script is a
  no-op - it never double-flips.
- **Sync**: piece A then resets `development` to `main`, so development inherits
  the dated CHANGELOG + fresh `[Unreleased]`.

`date_changelog.py` gets its own unit test (fixture CHANGELOG -> asserts heading
flip + empty Unreleased re-added + footers updated + idempotency). RC releases do
not date (they publish notes from the live `[Unreleased]`, unchanged).

### D. Local pre-feature sync script (`bin/sync.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail
git fetch origin main development --tags --prune
M=$(git rev-parse origin/main); D=$(git rev-parse origin/development)
if [ "$M" = "$D" ]; then
  echo "✓ main and development are in sync ($(git rev-parse --short origin/main))"
else
  AHEAD=$(git rev-list origin/development ^origin/main --count)
  echo "✗ out of sync: main=${M:0:7} development=${D:0:7} (development +$AHEAD)"
  [ "$AHEAD" -eq 0 ] && echo "  -> safe to reset; run: git push --force-with-lease origin development after reset" \
                     || echo "  -> development has unmerged work; do NOT reset"
fi
# Fast-forward-ONLY - never discards local work. Skip entirely if the tree is
# dirty; leave a diverged branch untouched (a note, not a reset).
[ -n "$(git status --porcelain)" ] && { echo "dirty tree - skipping"; exit 0; }
cur=$(git branch --show-current)
for b in main development; do
  if [ "$b" = "$cur" ]; then
    git merge --ff-only "origin/$b" || echo "  $b diverged - left as-is"
  else
    git fetch --no-tags . "refs/remotes/origin/$b:refs/heads/$b" \
      || echo "  $b diverged - left as-is"
  fi
done
```

With piece A running server-side, this is normally just a fast-forward + a green
"in sync" line before `git checkout -b feature/... development`.

## 4. One-time setup (owner)

1. **`RELEASE_PAT` secret** (or a GitHub App token): a fine-grained PAT scoped to
   this repo with `contents: write`. Used by piece A to force-push `development`.
   Piece B does **not** need it (release runs entirely in one workflow via
   `GITHUB_TOKEN`).
2. **`development` branch protection**: allow the `RELEASE_PAT` actor (or the
   Actions app) to **force-push** - add it to the ruleset bypass list, or relax
   development's force-push restriction.
3. **Commit + tag on `main`**: the final path both commits the CHANGELOG
   date-stamp to `main` and creates the `v*` tag. Add the `RELEASE_PAT` actor to
   `main`'s ruleset bypass (push + tag creation), or the date-stamp commit and
   tag will be rejected. This is the same token as piece A.
4. **PyPI Trusted Publishing**: unchanged **iff** the workflow keeps the name
   `publish.yml` and the `pypi` environment. Verify the trusted-publisher entry
   does not pin a specific ref/tag (branch-push runs must be accepted).
5. **`pypi` GitHub environment**: keep as-is. If it has a required-reviewer
   protection rule, every auto-release will pause for that approval - decide
   whether to keep that gate (a nice safety valve) or drop it for hands-off RC
   publishing.

## 5. Edge cases and failure modes

- **Version pushed but not on its branch** (rc landed on main, or final on
  development): gate skips - no release. Safe.
- **Push that does not bump the version**: tag exists -> skip. Safe (most pushes).
- **development ahead of main at sync time**: piece A refuses to reset and
  notifies - no data loss.
- **Final version but CHANGELOG still `[Unreleased]`**: piece C fails loudly ->
  the release aborts before tagging -> fix the CHANGELOG and re-merge / re-run.
- **PyPI upload fails after tag push**: the tag exists but PyPI is missing. Re-run
  the workflow: gate sees the tag and skips, so add a manual re-publish path (or
  make the tag step idempotent and let a re-run resume from build). Document the
  recovery: delete the tag + re-run, or trigger a manual publish. **Keep a
  `workflow_dispatch` manual entry point** on `publish.yml` for exactly this.
- **Two rapid merges to development**: `concurrency` group on the release workflow
  serialises runs so two rc bumps cannot race the same tag.

## 6. Rollout plan

1. Land `scripts/changelog_section.py` and `scripts/date_changelog.py` + their
   tests first (no CI behaviour change; pure scripts, unit-tested).
2. Add `bin/sync.sh` (no CI, no credentials - immediate local value).
3. Owner creates `RELEASE_PAT` + configures development bypass + verifies PyPI
   trust / tag rules (section 4).
4. Rewrite `publish.yml` to branch-triggered (piece B) behind the gate; **test on
   a throwaway `X.Y.Zrc0`** bumped on `development` to confirm the full RC path
   (tag -> TestPyPI or PyPI -> pre-release) before trusting it for a real release.
5. Add `sync-development.yml` (piece A) last, once the release path is proven.
6. Update `docs/` release-process page + `CLAUDE.md` "Release workflow" to
   describe the automated tail (bump version + edit CHANGELOG, merge, done).

## 7. Non-goals / explicitly kept manual

- **Deciding the version number** and **writing CHANGELOG entries** stay human
  (the deliberate, reviewed edits). The automation never invents a version.
- **PR review / merge** stays human (the branch-protection gate is unchanged).
- **MAJOR version bumps** are never automated (additive = MINOR/PATCH only, per
  the project's semver rule).

## 8. Open decisions to confirm before implementing

1. **`RELEASE_PAT` vs GitHub App** for the cross-branch force-push - PAT is faster
   to set up; an App is cleaner long-term (no user-tied token). Recommend PAT to
   start, migrate to App later if desired.
2. **Keep the `pypi` environment reviewer gate?** Keeping it means every RC/final
   pauses for a one-click approval (a safety valve); dropping it makes releases
   fully hands-off. Recommend **keep** for finals, consider dropping for rc.
3. **On sync-refusal**: fail the workflow (loud, shows in Actions) vs open an
   issue (async). Recommend **fail + notify**.
