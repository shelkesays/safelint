# Releasing

SafeLint releases are **automated**. You never pull, tag, push, or click "create
release" by hand. The one deliberate action is the **version bump** in
`pyproject.toml` - that commit is what authorises a release. Everything after the
merge (tag, PyPI upload, GitHub release, CHANGELOG dating, branch sync) is done
by GitHub Actions.

## The branch flow

Work happens on a `feature/*` branch that PRs into `development`, never straight
into `main`.

```
feature/*  --PR-->  development  --PR-->  main
   (work)        (RC releases)      (final release)
```

- A **pre-release** version (`X.Y.ZrcN`) releases from **`development`**.
- A **final** version (`X.Y.Z`) releases from **`main`**.

## Cutting a release-candidate (RC)

1. On your `feature/*` branch, when the work is ready, bump `project.version` in
   `pyproject.toml` to the next RC, e.g. `2.9.0rc1` (iterate `rc2`, `rc3`, ... on
   further rounds).
2. Add your CHANGELOG entries under `## [Unreleased]`. **Do not date the
   heading** - the workflow does that at the final release.
3. Open the PR into `development`, get it reviewed, and merge.

On merge, `publish.yml` runs: it sees a new pre-release version on `development`,
tags `v2.9.0rc1`, builds, publishes to PyPI (the `pypi-rc` environment, no
approval needed), and creates a GitHub **pre-release** whose notes are the
current `[Unreleased]` section.

## Cutting a final release

1. Open a `development -> main` PR.
2. In it, flip `project.version` to the final `X.Y.Z` (drop the `rcN` suffix).
   Leave the CHANGELOG heading as `## [Unreleased]`.
3. Merge.

On merge to `main`, `publish.yml`:

- **auto-dates the CHANGELOG**: renames `## [Unreleased]` to `## [X.Y.Z] -
  <date>`, re-adds an empty `## [Unreleased]`, updates the compare-link footers,
  and commits that to `main`;
- tags `vX.Y.Z`, builds, and publishes to PyPI (the `pypi` environment, which is
  **reviewer-gated** - a maintainer approves the production upload);
- creates the GitHub release with notes from the freshly-dated `[X.Y.Z]` section.

Then `sync-development.yml` resets `development` to `main` so the two branches
stay identical (and the next release branch always rebases cleanly).

## What is manual vs automated

| Manual (yours) | Automated (the workflows) |
|---|---|
| Choosing the version *number* | Creating and pushing the `vX.Y.Z` tag |
| Writing the CHANGELOG entries | Dating the CHANGELOG at the final release |
| Reviewing and merging the PRs | Building + publishing to PyPI |
| | Creating the GitHub release + notes |
| | Keeping `development` in sync with `main` |

Version numbers follow the project's semver rule: additive work (new rules,
languages, flags) is the next **MINOR** (`X.Y.0`); bugfixes and internal tooling
are the next **PATCH** (`X.Y.Z`); nothing is ever a MAJOR bump for additive work.

## How the gate decides

`publish.yml` runs on every push to `main` / `development`, but only releases
when **all** of these hold, otherwise it skips:

- `project.version` is not already tagged (so an ordinary push that did not bump
  the version does nothing), and
- the version type matches the branch (a pre-release only releases from
  `development`, a final only from `main`).

This is why a merge that does not change the version, or a stray final version on
`development`, is a safe no-op.

## The workflows and helpers

- `.github/workflows/publish.yml` - the branch-triggered release (gate -> build
  -> publish -> github-release). Its filename is kept as `publish.yml` so the
  PyPI Trusted-Publishing trust is unchanged.
- `.github/workflows/sync-development.yml` - resets `development` to `main` after
  each `main` push (reset-if-safe: only when `development` has no commits `main`
  lacks; otherwise it opens a tracking issue and fails, never clobbering work).
- `scripts/changelog_section.py` - extracts a CHANGELOG section as release notes.
- `scripts/date_changelog.py` - the final-release CHANGELOG date-stamp.
- `bin/sync.sh` - a local helper to fast-forward and check `main` / `development`
  before you start a feature (fast-forward-only, never discards local work).

## One-time setup (maintainers)

Already configured for this repo; documented here for reference and for forks:

- **`RELEASE_PAT`** secret - a fine-grained PAT (`contents: write`) used to push
  the tag / date-stamp commit to protected `main` and to force-push
  `development`. Its actor must be in the branch-ruleset bypass list.
- **`pypi` environment** - with a required-reviewer protection rule (the final
  release gate).
- **`pypi-rc` environment** - no protection rule (hands-off RC publishing).
- **PyPI Trusted Publishing** - the trusted-publisher entry (or entries) must
  trust the `publish.yml` workflow from **both** the `pypi` and `pypi-rc`
  environments (leave the Environment field blank for one entry, or add a second
  entry for `pypi-rc`).

The full design rationale, edge cases, and loop-safety notes live in
`plan/release-automation.md` in the repository.

## If a release step fails

The stages are independent jobs, so a later failure does not undo an earlier
success. For example, if the tag and PyPI upload succeeded but `github-release`
failed, the tag and PyPI release are already live - create the GitHub release
manually for that tag (`gh release create vX.Y.Z --notes-file <notes>
[--prerelease]`) and fix the workflow, rather than re-running (the gate would
skip a re-run because the tag now exists).
