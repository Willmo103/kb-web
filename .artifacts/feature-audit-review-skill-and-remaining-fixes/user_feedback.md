# User Feedback — feature/audit-review-skill-and-remaining-fixes (2026-10-18)

## Directives
1. **Create Review Skill**:
   - Create a dedicated review skill (`code-review-issue-generator`) derived from the instructions and process of the code audit.
   - Build a reusable template (`templates/audit_report_template.html`) and CLI/programmatic engine (`scripts/generate_audit_report.py`) to reproduce the interactive single-page HTML audit report with ready-to-post GitHub issues from arguments/JSON provided by another agent.
   - Include `scripts/sweep_codebase.py` for automated static heuristics sweep across Python files and Jinja2 templates.
   - Provide complete `SKILL.md` instructions with YAML frontmatter, execution workflows, schema specifications, and examples.

2. **Knock Out Remaining Audit Issues**:
   - **#98 (BUG-01)**: Fix non-ASCII credentials causing HTTP 500 in `hmac.compare_digest` (ensure UTF-8 byte encoding / safe comparison).
   - **#99 (BUG-03)**: Modernize MCP server to connect to PostgreSQL / central database rather than legacy SQLite.
   - **#100 (HTML-01)**: Fix extra closing `</div>` on article view page closing layout container early.
   - **#101 (TOOL-01)**: Add div imbalance and pane-nesting checks into `verify_ui_templates.py`.
   - **#102 (PERF-01)**: Optimize bulk maintenance jobs in `routers/admin.py` to stream/chunk rather than `.all()` with single monolithic transaction.
   - **#103 (PERF-02)**: Optimize agent board stats to use `SELECT DISTINCT` queries instead of scanning all rows.
   - **#104 (PERF-03)**: Optimize crawler BFS to use `deque` and batched URL checks.
   - **#105 (QUAL-01)**: Replace bare prints with logging in key server paths and remove silent swallowing of exceptions.
   - **#106 (QUAL-02)**: Enforce timezone-aware UTC timestamps (`datetime.now(timezone.utc)`).
   - **#107 (CFG-01)**: Sync `pyproject.toml` version (0.5.10) and metadata with `CHANGELOG.md`.
   - **#108 (CFG-02)**: Establish `[tool.ruff]` baseline configuration in `pyproject.toml`.
   - **#109 (SEC-07)**: Prevent SSRF by validating target URLs against loopback, private IPv4/IPv6, and cloud metadata IPs.
   - **#97 (SEC-08)**: Add HSTS header, drop deprecated `X-XSS-Protection`, update CDN integrity / Tailwind Play CDN notes.

3. **Lifecycle & Quality Assurance**:
   - Run unit test suite and verify UI templates pass with 0 warnings.
   - Link all issues in commits (`Fixes #98, Fixes #99, ...`).
   - Merge to `development` and `production` following repository standards.
