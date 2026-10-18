# Implementation Plan — Agent Skills, Durable Memory, and Repository Code Audit

Branch: `feature/agent-skills-memory-and-code-audit`

## Summary of Deliverables

1. **Durable Agent Working Memory (`.agents/memory/`)**:
   - Establish `.agents/memory/README.md` explaining purpose and guidelines for durable cross-session learning.
   - Record `package_caveats.md` capturing known quirks (`yt-dlp` format selection, Python `hmac.compare_digest` ASCII constraints, Windows PowerShell path quoting, SQLite multi-statement syntax, Jinja2 block containment).
   - Record `github_cli_guardrails.md` capturing safe invocation rules for the `gh` tool.
   - Update `documentation_rules.md` adding Section 6: Mandatory Agent Working Memory guidelines to record package issues and look out for durable lessons.

2. **Guarded GitHub CLI Skill (`.agents/skills/gh-cli-operations/`)**:
   - Create `SKILL.md` detailing safety principles:
     - No autonomous merges/closes of PRs or issues without explicit user instruction.
     - Mandate `--draft` and `--base development` for active work.
     - Mandatory `--body-file` and path quoting to prevent shell mangling.
     - Structured JSON logging to `.artifacts/gh-actions.log`.
   - Provide `scripts/gh_safe.py` CLI wrapper utility with subcommands `status`, `create-issue` (with duplicate detection), and `create-pr`.
   - Update `GEMINI.md` index of agent skills.

3. **Repository Code Audit & Interactive Dashboard**:
   - Comprehensive static analysis and inspection of security, bugs, HTML/template defects, outdated components, and performance bottlenecks.
   - Delivered `.artifacts/feature-agent-skills-memory-and-code-audit/code_audit_report.html` interactive dashboard allowing selective issue filtering, previewing, and creation.
   - 19 issues documented and filed/staged on repository.

4. **Synchronize & Merge**:
   - Integrate with YouTube download audio fix (`fix/youtube-download-audio-112`).
   - Merge `feature/agent-skills-memory-and-code-audit` into `development`, and merge `development` into `production`.
