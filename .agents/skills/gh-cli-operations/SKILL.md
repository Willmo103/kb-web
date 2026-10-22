---
name: gh-cli-operations
description: Guarded execution wrapper for GitHub CLI (`gh`) operations with observability, structured JSON logging, and safety dry-runs.
---

# GitHub CLI (`gh`) Operations Skill

Use this skill whenever creating, updating, or reviewing GitHub issues, pull requests, and releases via `gh`.

## Guardrails & Principles

1. **Destructive & Consequential Action Guardrail**:
   - `gh pr merge`, `gh pr close`, and `gh issue close` must never be run autonomously without explicit user confirmation.
   - All PRs for active feature work must be opened as **Draft** (`--draft`) targeting `development` (`--base development`).
2. **Proper Shell Quoting & Multi-Line Markdown**:
   - Never pass inline multi-line markdown via `--body "..."`. Shell escaping often mangles quotes and formatting.
   - Always write markdown to a file (in `.artifacts/` or temporary file) and pass `--body-file "$file_path"`, quoting paths to accommodate spaces.
3. **Structured Observability & Logging**:
   - All actions must be logged to `.artifacts/gh-actions.log` as single-line JSON objects with timestamps, action type, repo, title, result (`ok` or `error`), and resulting URL.

## Helper Script

Use the dedicated helper script `scripts/gh_safe.py` for performing guarded operations:

```bash
# Check auth
uv run python .agents/skills/gh-cli-operations/scripts/gh_safe.py status

# Create an issue safely from markdown file
uv run python .agents/skills/gh-cli-operations/scripts/gh_safe.py create-issue --title "Bug: ..." --body-file ".artifacts/issue_body.md" --label "bug"

# Create a draft PR safely
uv run python .agents/skills/gh-cli-operations/scripts/gh_safe.py create-pr --title "feat: ..." --base "development" --draft --body-file ".artifacts/pr_description.md"
```
