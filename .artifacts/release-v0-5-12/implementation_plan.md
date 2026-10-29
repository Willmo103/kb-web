# Implementation Plan — Merge `development` into `production` & `master` (v0.5.12) and Open Next-Stage Draft PR

## Goal
Synchronize the latest verified `v0.5.12` changes from `development` into `production` and `master`, push all three branches to `origin`, and open a new draft Pull Request from `production` targeting `master` for the next stage of development (`v0.5.13`).

## Steps
1. **Version Sync & Verification on `development`**:
   - Update `pyproject.toml` version from `0.5.11` to `0.5.12` to match `CHANGELOG.md` (`## [0.5.12] - 2026-10-28`).
   - Run pre-commit verification (`uv run python build.py`) to confirm all unit tests, ruff checks, and package builds pass.
   - Commit the release artifacts and version sync on `development` and push `origin/development`.
2. **Release Merge into `production` and `master` (`v0.5.12`)**:
   - Checkout `production`, merge `development`, and push `origin/production`.
   - Checkout `master`, merge `production`, and push `origin/master`.
3. **Initialize Next-Stage Development (`v0.5.13`) & Open Draft PR (`production` -> `master`)**:
   - Create `.artifacts/release_v0_5_13_pr_body.md` on `development`, merge into `production`, and push `origin/development` and `origin/production` so `production` has a tracking commit ahead of `master`.
   - Open a guarded draft Pull Request (`production` -> `master`) using `scripts/gh_safe.py` with structured logging in `.artifacts/gh-actions.log`.

