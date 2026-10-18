# Walkthrough - Model Evaluation Studio (`/evals`), Raw Reporting Export, and Worker Registry Cleanup

## Summary of Completed Changes

### 1. Model Evaluation Studio (`/evals`) & Calibration Portal
- **New Dedicated Router (`src/kb_web/routers/evals.py`)**:
  - `GET /evals`: Renders the Model Evaluation Studio with session authentication, discovering available Ollama models (with automatic fallbacks and default model preselection), active prompt templates, and sample articles/notes.
  - `POST /api/evals/content`: Allows loading complete raw markdown or text for any saved article or personal note directly into the evaluation studio with one click.
  - `POST /api/evals/matrix/run`: Runs side-by-side matrix execution of models × prompts across sample text, capturing response markdown, latency (ms), token metrics, and tokens per second (`tok/s`).
  - `POST /api/evals/decision/run`: Evaluates structured multi-question decision gating using the new default `d1` decision model (16,384 context window) or `tev1` via native `client.systemone`. Extracts discrete choices, probability percentages (`noul`), and reasoning chains.
  - `POST /api/evals/embedding/run`: Benchmarks embedding models against search queries and candidate texts, computing vector dimensions, inference latency, and cosine similarity rankings.
- **Top-Level Navigation (`src/kb_web/templates/base.j2.html`)**:
  - Added `🧪 Evals` links to both the desktop navigation bar and the mobile drawer menu.
- **Responsive UI Template (`src/kb_web/templates/evals.j2.html`)**:
  - Full support for light mode and muted neon dark mode (`html.dark`).
  - Three distinct interactive tabs:
    1. **Prompt & Model Matrix**: Model selection pills, active prompt definition cards, sample article loader, latency & token speed pills, formatted markdown view, and raw copy.
    2. **Decision Gating**: `d1` model selector (16k context window default), interactive JSON State Editor, JSON Questions Editor, preset loaders (Link Discovery Gating, Wiki Synthesis Candidate, Taxonomy Routing), and visual probability bars.
    3. **Embedding Retrieval**: Multi-model comparison, query input, candidate block editor, and ranked similarity score progress bars.

### 2. Transparent Decision Model Configuration (`src/kb_web/config.py`)
- Added `decision_model` property defaulting to `"d1"`.
- Persisted in `settings_ollama` and exportable in JSON backups per Rule 7 (Strict Configuration Transparency & Admin Exposure Rule).

### 3. Raw Untruncated Report Data Exports (`src/kb_web/routers/reports.py`)
- **Bug Fixed**: In `/api/reports/export`, downloading CSV, XLSX, or JSON previously yielded literal UI placeholder tokens like `[Content: 77,805 chars]`.
- **Resolution**: Updated `export_report_data()` to set `fetch_heavy=True` and bypass placeholder shortening, streaming complete raw text content directly to export downloads.

### 4. Ollama Request Logs Catalog Exposure (`src/kb_web/routers/reports.py` & `src/kb_web/templates/admin.j2.html`)
- Registered `ollama_logs` in `TABLE_METADATA` with heavy-column protection on `messages` and `response`.
- Added a `📊 Ollama Model Logs` button in the Admin Portal linking to `/reports?table=ollama_logs`.

### 5. Worker Registry Cleanup (`src/kb_web/worker.py` & `src/kb_web/templates/admin.j2.html`)
- Eliminated placeholder `tag_curation` (`Tag Taxonomy Agent`) job from the worker engine registry and admin dashboard, leaving only active jobs prior to building the refactored autonomous curation agents.

---

## Verification & Test Results

1. **Jinja2 UI Template & Div Balance Verification**:
   - `python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py` passed with 0 warnings across all 26 HTML templates.
2. **Dedicated Unit Test Suite (`tests/test_evals_studio.py`)**:
   - `test_evals_studio_page_requires_auth`: PASSED (303 redirect to `/login`).
   - `test_evals_studio_page_authenticated`: PASSED (200 OK with tabs).
   - `test_evals_content_fetch_article`: PASSED.
   - `test_evals_matrix_run_mock`: PASSED (model matrix execution & token speed).
   - `test_evals_decision_run_mock`: PASSED (`d1` systemone gating answers & choices).
   - `test_evals_embedding_run_mock`: PASSED (cosine similarity ranking).
   - `test_worker_tag_curation_removed`: PASSED (`tag_curation` eliminated).
   - `test_reports_export_raw_untruncated`: PASSED (`[Content:` placeholder absent).
3. **Core Server Test Suite**:
   - `uv run pytest tests/test_server.py tests/test_system_prompts_admin.py -v`: 62 out of 62 tests passed.
