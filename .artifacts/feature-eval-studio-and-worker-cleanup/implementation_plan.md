# Implementation Plan - Eval Studio, Worker Cleanup, Ollama Logs & Reporting Download Fix

## Overview
This sprint addresses the immediate architectural alignment and UX requirements:
1. **Reporting Export Fix**: Ensure downloads (CSV, XLSX, JSON) export raw un-truncated content while the UI grid maintains preview tokens (`[Content: 77,805 chars]`).
2. **Ollama Model Logs Exposure**: Expose `ollama_logs` in the Reports schema catalog and Admin Portal for request/response auditability.
3. **Worker Registry Cleanup**: Eliminate the `Tag Taxonomy Agent` (`tag_curation`) from `src/kb_web/worker.py` and the Admin Portal dashboard.
4. **Dedicated Top-Level `/evals` Page**: Implement a rich, side-by-side Evaluation Studio for Prompt, Decision (`d1` 16k context), and Embedding model matrix testing.

---

## User Review Required
> [!IMPORTANT]
> The `/evals` page will be accessible directly from the top navigation bar, allowing interactive side-by-side comparisons of prompts, decision questions (`d1`), and embedding retrievals before we build the refactored autonomous worker agents.

---

## Proposed Changes

### 1. Fix Reporting Export Bug (`src/kb_web/routers/reports.py`)
- In `export_report_data()`:
  - Force `req.fetch_heavy = True` when invoking `_build_sql_query`.
  - Skip `_format_heavy_placeholder()` so full raw text (e.g. `notes.content`, `fetched_pages.md_content`) is streamed into CSV, XLSX, and JSON downloads.

### 2. Expose `ollama_logs` in Reports & Admin Portal
- In `src/kb_web/routers/reports.py`:
  - Add `ollama_logs` to `TABLE_METADATA`:
    - Columns: `id`, `timestamp`, `model`, `prompt_type`, `messages` (heavy), `options`, `response` (heavy), `duration`, `status`.
  - Import `OllamaLog` from `models_orm.py` to allow query building and introspection.
- In `src/kb_web/templates/admin.j2.html`:
  - Add an "Ollama Model Logs" quick filter button linking to `/reports?table=ollama_logs`.

### 3. Eliminate Tag Taxonomy Agent from Worker Registry (`src/kb_web/worker.py` & `admin.j2.html`)
- In `src/kb_web/worker.py`:
  - Remove `self.jobs["tag_curation"]` registration from `_register_default_jobs()`.
- In `src/kb_web/templates/admin.j2.html`:
  - Remove the `Tag Taxonomy Agent` card from the worker section.

### 4. Implement Dedicated Top-Level `/evals` Page
- Create router `src/kb_web/routers/evals.py`:
  - `GET /evals`: Renders `evals.j2.html`.
  - `POST /api/evals/matrix/run`: Executes model and prompt matrix test runs against sample articles.
  - `POST /api/evals/decision/run`: Tests decision gating questions against `d1` or other models with custom state objects.
  - `POST /api/evals/embedding/run`: Tests retrieval recall across embedding models.
- Register `evals.router` in `src/kb_web/server.py`.
- Add "Evals" navigation link in `src/kb_web/templates/base.j2.html`.
- Create template `src/kb_web/templates/evals.j2.html`:
  - Clean retro neon/slate aesthetic matching the design system.
  - Interactive multi-model and multi-prompt runner.
  - Side-by-side diff and comparative cards.

---

## Verification Plan

### Automated Verification
1. **Template Syntax & DOM Balance**:
   - Run `python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py` to ensure all 26 templates pass.
2. **Pytest Suite**:
   - Run `uv run pytest tests/test_system_prompts_admin.py tests/test_server.py tests/test_security_hardening.py`.
3. **Export Verification**:
   - Verify that `/api/reports/export` with a note row downloads full content rather than `[Content: ... chars]`.

### Manual & Visual Verification
4. Inspect `/evals` in browser via subagent or live test.
5. Verify `/reports` table selector lists "Ollama Model Logs".
