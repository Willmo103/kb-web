# Git & Submodule Management Rules

This rule outlines git practices for managing branches, commit messages, and submodules within `kb-web`.

---

## 1. Branching Strategy & Tiered Release Lifecycle
The repository follows a strict 3-tier branch hierarchy:
1. `development`: The primary trunk branch for active day-to-day development.
   - All feature, bugfix, and sprint branches (`feature/...`, `fix/...`, `agent/...`) MUST branch off the latest `development` branch (`git checkout -b feature/... development`).
   - Pull requests for ongoing work are opened into `development` (`gh pr create --draft --base development`).
2. `production`: The pre-release staging and verified baseline branch.
   - Once features, unit tests, and UAT pass all pre-commit verification checks (`uv run pytest`, `build.py`), verified increments are merged from `development` into `production`.
3. `master`: The stable long-term production release line.
   - Merged from `production` only when formal major releases are cut and deployed.

## 2. Commit Message Guidelines
- Write clear, imperative commit messages summarizing the technical intent (e.g., `feat: add Qdrant semantic vector index search`, `fix: resolve YouTube transcript parsing timeout`).
- Include references to issue numbers or task IDs where applicable.

## 3. Working Directory Hygiene
- Ensure the git working tree is clean (`git status`) before running UAT checks or declaring a task complete.
- Build artifacts in `dist/` and temporary cache files (`.venv`, `.pytest_cache`, `.ruff_cache`) MUST be git-ignored.

## 4. Sprint & Feature Execution Workflow
- **Discovery**: Review the active issue or sprint tracker under `.artifacts/`.
- **Branching**: Switch to `development`, ensure it is up to date (`git pull origin development`), and checkout a new branch: `feature/<name>` or `fix/<name>`.
- **Draft PR**: Push the branch and open a draft PR back into `development` (`gh pr create --draft --base development`).
- **Tracking**: Associate targeted issues to the PR. As tasks are completed, commit along with code edits and test artifacts.
- **Delivery to Production**: Once all tests pass and UI UAT is approved, merge from `development` into `production`. Cut releases to `master` when major milestones are ready.
