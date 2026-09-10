# Git & Submodule Management Rules

This rule outlines git practices for managing branches, commit messages, and submodules within `kb-web`.

---

## 1. Branching Strategy
- Always create dedicated feature branches off the latest `production` branch (e.g. `feature/...`, `fix/...`, or `agent/...`).
- Ensure `production` is cleanly pulled (`git pull origin production`) before creating a branch checkpoint.

## 2. Commit Message Guidelines
- Write clear, imperative commit messages summarizing the technical intent (e.g., `feat: add Qdrant semantic vector index search`, `fix: resolve YouTube transcript parsing timeout`).
- Include references to issue numbers or task IDs where applicable.

## 3. Working Directory Hygiene
- Ensure the git working tree is clean (`git status`) before running UAT checks or declaring a task complete.
- Build artifacts in `dist/` and temporary cache files (`.venv`, `.pytest_cache`, `.ruff_cache`) MUST be git-ignored.

## 4. Sprint Execution Workflow
- **Discovery**: Locate the active sprint checklist under `.artifacts/analysis-issues-29-30/`.
- **Branching**: Switch to `production`, `git pull`, and checkout a new branch: `feature/sprint-<number>-<description>`.
- **Draft PR**: Push the branch and open a draft PR back into `production` (`gh pr create --draft`).
- **Tracking**: Associate targeted sprint issues to the PR. As tasks are completed, change `[ ]` to `[x]` in the sprint tracker artifact, committing it along with code edits.
- **Delivery**: Once all tests and UAT checks pass, transition the PR from draft to ready for review (`gh pr ready`), add review comments on design/schemas where helpful, and leave the PR open for the user to merge.
