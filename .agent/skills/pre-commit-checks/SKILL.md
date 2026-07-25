---
name: pre-commit-checks
description: Runs pre-commit validation (uv sync, pytest suite, ruff lint checks, and build.py pipeline) for kb-web.
---
# Pre-Commit Checks Skill for kb-web

Use this skill before committing code or requesting final UAT approval.

## Execution Steps

1. **Synchronize Dependencies**:
   ```bash
   uv sync
   ```

2. **Run Pytest Suite**:
   ```bash
   uv run pytest
   ```

3. **Run Code Formatting & Lint Checks**:
   ```bash
   uv run ruff check .
   ```

4. **Verify Build Pipeline**:
   ```bash
   uv run python build.py
   ```

5. **Verify Clean Git Status**:
   ```bash
   git status
   ```
