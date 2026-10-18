---
name: code-review-issue-generator
description: Generates an interactive, single-page HTML code audit and review report with ready-to-post GitHub issues, dynamic severity charts, filters, search, and a guarded issue-creation script.
---

# Code Review & Issue Generator Skill

Use this skill when auditing a codebase for bugs, misconfigurations, HTML defects, security vulnerabilities, or performance bottlenecks. It compiles findings into a beautiful, interactive, self-contained HTML report that enables users to inspect issues, toggle selections, add review notes, and either copy payloads for the agent or download a guarded PowerShell script to create issues with GitHub CLI (`gh`).

---

## Capabilities & Architecture

1. **Standalone Dark-Mode Glassmorphic Report**:
   - Dynamic conic-gradient severity donut chart.
   - Filter chips for Severity (`Critical`, `High`, `Medium`, `Low`) and Category (`Security`, `Bug`, `HTML`, `Performance`, `Code Quality`, `Config`, etc.).
   - Instant client-side search across issue IDs, titles, filenames, and markdown bodies.
   - Expandable raw Markdown previews with exact text ready for GitHub issues.
   - Local storage persistence for checkbox states and reviewer notes.
2. **Guarded GitHub Issue Creation**:
   - Generates a standalone PowerShell script (`create_audit_issues.ps1`).
   - Dry-run preview listing existing issues to prevent duplicates.
   - Requires explicit `YES` confirmation before issuing API calls.
   - Passes bodies via `--body-file` to prevent shell-quoting and newline corruption.
   - Automatically logs results to `.artifacts/gh-actions.log`.
3. **Agent Loopback**:
   - "📋 Copy selection for agent" copies a structured JSON payload directly to the clipboard so the user can paste it straight back to the AI assistant.

---

## Finding Data Schema

Each finding passed to the generator should follow this structure:

```json
{
  "id": "SEC-01",
  "sev": "High",
  "cat": "Security",
  "labels": ["bug", "security"],
  "loc": "src/kb_web/routers/auth.py:31-69",
  "title": "Security: Rate limit bypass via X-Forwarded-For",
  "sum": "One-line executive summary of the issue.",
  "body": "## Summary\nDetailed markdown description...",
  "status": "Optional status badge (e.g. In progress)"
}
```

---

## Quick Start & Usage

### 1. Automated Static Sweep
Run the heuristics scanner across Python files and Jinja2 templates:

```bash
uv run python .agents/skills/code-review-issue-generator/scripts/sweep_codebase.py \
  --root . \
  --output .artifacts/sweep_findings.json
```

### 2. Generate Interactive Report
Compile findings into a standalone HTML presentation:

```bash
uv run python .agents/skills/code-review-issue-generator/scripts/generate_audit_report.py \
  --input .artifacts/sweep_findings.json \
  --output .artifacts/code_audit_report.html \
  --repo "Willmo103/kb-web" \
  --title "kb-web Code Audit — Findings & Proposed Issues"
```

### 3. Programmatic Usage in Python Agents

```python
from pathlib import Path
from agents.skills.code_review_issue_generator.scripts.generate_audit_report import generate_report

findings = [
    {
        "id": "BUG-01",
        "sev": "High",
        "cat": "Bug",
        "labels": ["bug"],
        "loc": "src/module/auth.py:42",
        "title": "Bug: Authentication error handling crashes on None",
        "sum": "Missing None check leads to unhandled AttributeError.",
        "body": "## Summary\nWhen user is None...",
    }
]

generate_report(
    findings=findings,
    repo="Willmo103/kb-web",
    title="Sprint Audit",
    output_path=Path(".artifacts/audit_report.html"),
)
```
