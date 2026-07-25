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
