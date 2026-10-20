# Walkthrough: Model Evaluation Studio Dataset Overhaul, SystemOne Isolation & Worker Agents

## Overview
This iteration resolves all key user feedback items regarding the Model Evaluation Studio (`/evals`) and Admin Worker Agent Configuration (`/admin#tab-agents`):
1. **Decision Model Exclusion**: `d1` and `tev1` models are strictly excluded from completion and wiki generation selectors.
2. **Dataset-Only Matrix Evals**: Completely eliminated single input mode; Matrix evaluations run strictly against datasets with dataset fields and randomized sampling.
3. **Live Jinja Parameter Syntax Highlighter**: Reusable client-side module (`src/kb_web/static/js/jinja_highlighter.js`) featuring real-time validation badges (green for valid fields, red for invalid fields) and click-to-insert available fields explorer bar.
4. **Strict Isolation of SystemOne Decision Models**: Structurally segregated SystemOne models (`d1`, `tev1`) from generative LLMs in the Admin Portal, removing invalid options (tools, system messages, thinking, sampling hyperparameters).
5. **Configurable Worker Agents & Frozen Snapshots**: Users can create custom worker agents, test run them on sample articles, and publish frozen snapshot commits.
6. **Persistent Evaluation Run History**: Evaluations are stored in the `evaluation_runs` table with live streaming persistence, allowing inspection, re-running, and configuration loading.

---

## Key Changes

### 1. Static Asset Serving & Jinja Syntax Highlighter
- Added `app.mount("/static", StaticFiles(directory=...), name="static")` in [src/kb_web/server.py](file:///c:/src/kb-web/src/kb_web/server.py), whitelisted in CSP and security middleware.
- Created reusable client-side highlighter [src/kb_web/static/js/jinja_highlighter.js](file:///c:/src/kb-web/src/kb_web/static/js/jinja_highlighter.js) with:
  - Mirror backdrop overlay for textarea with caret tracking.
  - Live parameter validation status badge bar (green pills for valid fields, red pills with pulse animations for invalid fields).
  - Click-to-insert available fields explorer bar with tooltips and badge counters.

### 2. Model Evaluation Studio (`/evals`)
- **Strict Model Isolation**: In [src/kb_web/routers/evals.py](file:///c:/src/kb-web/src/kb_web/routers/evals.py), enforced `classify_model_type(m) == 'llm'` across completion model lists so `d1`, `tev1`, and any decision gate models never leak into text/wiki generation selectors.
- **Dataset-Only Evaluations**: Removed single input mode toggle and textarea from [src/kb_web/templates/evals.j2.html](file:///c:/src/kb-web/src/kb_web/templates/evals.j2.html). Added `#matrixRandomize` sampling checkbox and `#matrixRunTitle` input.
- **Dataset Fields Endpoint**: Added `GET /api/evals/datasets/{id}/fields` returning schema columns and sample row keys.
- **Persistent Evaluation Runs**:
  - Added `evaluation_runs` table in [src/kb_web/models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py).
  - Both SSE streaming `POST /api/evals/matrix/stream` and batch `POST /api/evals/matrix/run` initialize and update `EvaluationRun` records with live latency, token counts, and error summaries.
  - Added REST endpoints: `GET /api/evals/runs`, `GET /api/evals/runs/{id}`, and `DELETE /api/evals/runs/{id}`.
  - Added Tab 5 (**Run History**) in the Studio displaying all runs with status badges, date, duration, and actions (View Results modal, Load Config into Studio, and Delete).

### 3. Admin Worker Agent Configuration (`/admin`)
- **SystemOne Model Isolation**: Separated the Agent tab into **Section 1: SystemOne Decision Gating Models** and **Section 2: Generative LLM & Coding Worker Agents**.
  - For SystemOne cards, completely removed tools, system prompts, thinking mode, temperature, top_p, top_k, and num_predict. Only the state template and questions schema are presented.
- **Custom Worker Agent Creation & Deletion**:
  - Added "+ Create Worker Agent" button and modal dialog in [src/kb_web/templates/admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html).
  - Added `POST /api/admin/agents/create` and `DELETE /api/admin/agents/{id}` in [src/kb_web/routers/admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py).
- **Test Run & Frozen Snapshot Commit Workflow**:
  - Implemented `test_run_agent_config()` in [src/kb_web/agent_config.py](file:///c:/src/kb-web/src/kb_web/agent_config.py) supporting both SystemOne (`client.systemone`) and LLM (`client.chat`) executions against sample article data.
  - Added `publish_agent_config()` which serializes the full configuration into `frozen_snapshot_json`, increments the agent version number, records `published_at`, and marks `is_published=True`.
  - Added "Test Run" and "Publish Snapshot" actions with modal test runner in the Admin UI.

---

## Verification & Testing Results

1. **Targeted Unit Tests (`tests/test_evals_datasets_and_worker_agents.py`)**:
   - `test_decision_models_strict_classification_and_exclusion`: PASSED
   - `test_dataset_fields_endpoint`: PASSED
   - `test_fetch_dataset_rows_randomized_and_sequential`: PASSED
   - `test_evaluation_runs_api_lifecycle`: PASSED
   - `test_custom_worker_agent_lifecycle_and_frozen_snapshot`: PASSED
   - `test_systemone_agent_test_run_does_not_use_chat_or_tools`: PASSED
2. **UI Template Verification (`verify_ui_templates.py`)**:
   - Verified 29 templates: 0 warnings, all block structures and div tags validated.
3. **Full Pre-Commit Build Verification (`build.py`)**:
   - 242 unit tests passed in 201s (0 failures).
