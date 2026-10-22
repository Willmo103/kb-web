# Sprint: Code Review Issue Generator Skill & Remaining Audit Fixes

Draft PR tracking progress for the Code Review Issue Generator Skill and the remaining code audit fixes (#97 through #109).

### Linked to Main CI/CD Release
- References parent tracking PR: #113

### Issues Addressed in this Sprint
- [x] **Review Skill**: Reusable `code-review-issue-generator` skill (template, engine, sweep scanner, instructions)
- [x] **#98 (BUG-01)**: Fix non-ASCII credentials causing HTTP 500 in `hmac.compare_digest`
- [x] **#99 (BUG-03)**: Modernize MCP server to connect to PostgreSQL / central database rather than legacy SQLite
- [x] **#100 (HTML-01)**: Remove extra closing `</div>` on article view page closing layout container early
- [x] **#101 (TOOL-01)**: Add div imbalance and tab-pane checks to `verify_ui_templates.py`
- [x] **#102 (PERF-01)**: Optimize bulk maintenance jobs in `routers/admin.py` to stream/chunk rather than `.all()`
- [x] **#103 (PERF-02)**: Optimize agent board stats to use `SELECT DISTINCT` queries instead of scanning all rows
- [x] **#104 (PERF-03)**: Optimize crawler BFS to use `collections.deque` and batched URL checks
- [x] **#105 (QUAL-01)**: Replace `print()` with structured logging and remove silent error swallowing
- [x] **#106 (QUAL-02)**: Enforce timezone-aware UTC timestamps (`datetime.now(timezone.utc)`)
- [x] **#107 (CFG-01)**: Sync `pyproject.toml` version (0.5.10) and metadata with `CHANGELOG.md`
- [x] **#108 (CFG-02)**: Establish `[tool.ruff]` baseline configuration in `pyproject.toml`
- [x] **#109 (SEC-07)**: Prevent SSRF by validating target URLs against loopback, private IPv4/IPv6, and cloud metadata IPs
- [x] **#97 (SEC-08)**: Add HSTS header, drop deprecated `X-XSS-Protection`, update CDN integrity / headers

### Status
- All tasks implemented and verified.
- UI template check passed (25 templates, 0 warnings).
- Unit test suite passing.

