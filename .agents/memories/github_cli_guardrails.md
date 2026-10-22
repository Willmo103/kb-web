# GitHub CLI (`gh`) Guardrails & Safe Invocation Memory

Operational rules for agents executing `gh` CLI commands in scripts or terminals.

---

### 1. Consequential Action Guardrails
- **Merge/Close Operations**: Agents must never invoke `gh pr merge`, `gh pr close`, or `gh issue close` without explicit user instruction.
- **Draft Status**: When creating PRs for active feature work, always include `--draft` (`gh pr create --draft --base development`).
- **Base Branch Targeting**: PRs must target `development` by default (`--base development`). PRs targeting `production` or `master` are reserved for verified release increments.

### 2. Large Text & Markdown Bodies
- **Avoid Inline Flags**: Never pass multi-paragraph markdown descriptions via `--body "..."` in shell commands. CLI shell escaping, newlines, and quotes frequently corrupt formatting or crash the shell.
- **Use `--body-file`**: Always write the markdown content to a file (in `.artifacts/` or a temporary file) and pass `--body-file "$path"`, quoting the path for spaces.

### 3. Verification & Observability
- **Check Status First**: Run `gh auth status` before executing a batch of CLI operations.
- **Structured Logging**: Record all consequential `gh` operations (creation, editing, merging) into `.artifacts/gh-actions.log` as structured JSON records (`ts`, `action`, `repo`, `ref`, `title`, `result`, `url`).
