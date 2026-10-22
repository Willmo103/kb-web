# Implementation Plan — Code Review Issue Generator Skill & Remaining Audit Fixes

## 1. Overview
This plan addresses two objectives requested by the user:
1. **New Skill: `code-review-issue-generator`**:
   - Turn the process and standalone interactive HTML review generator from the code audit into a formal, reusable agent skill in `.agents/skills/code-review-issue-generator/`.
   - Provide a template (`templates/audit_report_template.html`), an issue report generator engine (`scripts/generate_audit_report.py`), a code sweep scanner (`scripts/sweep_codebase.py`), and documentation (`SKILL.md`).
2. **Knock Out Remaining Audit Issues**:
   - **#98 (BUG-01)**: Fix non-ASCII credentials causing HTTP 500 in `hmac.compare_digest` with byte encoding.
   - **#99 (BUG-03)**: Modernize MCP server to connect to PostgreSQL / central database rather than legacy SQLite.
   - **#100 (HTML-01)**: Remove extra closing `</div>` on article view page closing layout container early.
   - **#101 (TOOL-01)**: Add div imbalance and tab-pane checks to `verify_ui_templates.py`.
   - **#102 (PERF-01)**: Optimize bulk maintenance jobs in `routers/admin.py` to stream/chunk rather than `.all()` with monolithic transaction.
   - **#103 (PERF-02)**: Optimize agent board stats to use `SELECT DISTINCT` queries instead of scanning all rows.
   - **#104 (PERF-03)**: Optimize crawler BFS to use `collections.deque` and batched URL checks.
   - **#105 (QUAL-01)**: Replace `print()` with structured logging and remove silent error swallowing.
   - **#106 (QUAL-02)**: Enforce timezone-aware UTC timestamps (`datetime.now(timezone.utc)`).
   - **#107 (CFG-01)**: Sync `pyproject.toml` version (0.5.10) and metadata with `CHANGELOG.md`.
   - **#108 (CFG-02)**: Establish `[tool.ruff]` baseline configuration in `pyproject.toml`.
   - **#109 (SEC-07)**: Prevent SSRF by validating target URLs against loopback, private IPv4/IPv6, and cloud metadata IPs.
   - **#97 (SEC-08)**: Add HSTS header, drop deprecated `X-XSS-Protection`, update CDN integrity / Tailwind Play CDN notes.

---

## 2. Proposed Changes

### Phase A: Code Review Skill (`.agents/skills/code-review-issue-generator/`)
- [ ] `SKILL.md`: Detailed skill guide explaining the audit workflow, CLI usage, JSON schema, and interactive web UI features.
- [ ] `templates/audit_report_template.html`: Self-contained, glassmorphic dark-mode single-page HTML template featuring:
  - Donut severity chart with SVG/CSS transitions
  - Severity and Category filtering chips
  - Instant client-side search across titles, files, and bodies
  - Markdown issue bodies with preview/details
  - Per-card review notes
  - Selection dock with bulk select/clear, JSON export, agent payload copy, and guarded PowerShell script generator (`create_audit_issues.ps1`) using `gh issue create --body-file` and structured logging to `.artifacts/gh-actions.log`.
- [ ] `scripts/generate_audit_report.py`: CLI and Python API tool to parse findings (from JSON file or CLI flags) and render the single-page HTML artifact.
- [ ] `scripts/sweep_codebase.py`: Reusable static heuristics scanner checking regexes (eval/exec, SQL f-strings, missing timeouts, naive datetimes, print statements, div balance, CDN integrity).

### Phase B: Correctness & HTML Bugs
- [ ] `src/kb_web/base.py` & `src/kb_web/config.py`:
  - Implement `safe_compare_digest(a: str, b: str) -> bool` using `.encode('utf-8')` so non-ASCII passwords or API keys do not throw `TypeError` (#98).
- [ ] `src/kb_web/templates/view_page.j2.html`:
  - Remove redundant closing `</div>` at line 443 (#100).
- [ ] `.agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`:
  - Add div open/close tag balance checker (ignoring `<script>` and comments) to prevent template regression (#101).

### Phase C: Outdated Architecture & SSRF Hardening
- [ ] `src/kb_web/mcp_server.py`:
  - Refactor to query SQLAlchemy `get_db_session()` and `FetchedPage` models rather than raw SQLite `db.sqlite` (#99).
- [ ] `src/kb_web/utils.py` & `src/kb_web/routers/pages.py`:
  - Add `validate_target_url(url: str, allow_internal: bool = False)` checking scheme and resolving IP against `ip.is_private`, `ip.is_loopback`, `ip.is_link_local`, `ip.is_reserved` (#109).
- [ ] `src/kb_web/server.py`:
  - Add `Strict-Transport-Security: max-age=31536000; includeSubDomains`, remove deprecated `X-XSS-Protection`, and add `Referrer-Policy` (#97).

### Phase D: Performance & Hygiene Optimizations
- [ ] `src/kb_web/routers/admin.py`:
  - Refactor `run_bulk_description_maintenance()` and `run_bulk_embedding_maintenance()` to process in chunks/batches with per-batch transaction commits (#102).
  - Replace bare `print()` with `logger.info()` / `logger.error()` (#105).
- [ ] `src/kb_web/agent_memory.py`:
  - Refactor `get_agent_board_summary()` to execute `SELECT DISTINCT` queries rather than `.all()` table scans (#103).
- [ ] `src/kb_web/routers/pages.py`:
  - Use `collections.deque` for crawler queue and batch URL pre-checks (#104).
- [ ] Datetime & Config:
  - Use `datetime.now(timezone.utc)` for consistent UTC timestamps (#106).
  - Update `pyproject.toml` version to `0.5.10`, update description, and add `[tool.ruff]` section (#107, #108).

### Phase E: Testing & Release
- [ ] Run `python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py` to ensure all templates pass.
- [ ] Run `pytest` to verify 100% test pass rate.
- [ ] Update `CHANGELOG.md` and `README.md`.
- [ ] Commit with issue associations (`Fixes #98, Fixes #99, Fixes #100, Fixes #101, Fixes #102, Fixes #103, Fixes #104, Fixes #105, Fixes #106, Fixes #107, Fixes #108, Fixes #109, Fixes #97`).
- [ ] Merge to `development` and `production`.

---

## 3. Verification Plan
- **Template Verifier**: `uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`
- **Unit Tests**: `uv run pytest tests/`
- **Audit Generator Test**: Run `python .agents/skills/code-review-issue-generator/scripts/generate_audit_report.py --help` and generate a test report.
