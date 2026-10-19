# Implementation Plan - Eval Datasets, d1 SystemOne Overhaul, and Complete Agent Configuration Registry

This plan addresses all items from user feedback: multi-row dataset evaluations driven by report queries (minimum 20 rows), Jinja2 template formatting (`{{ data.<field> }}`), correcting Ollama `d1` `/v1/systemone` integration, exposing all Ollama agent calls in the Admin Portal, and providing full visibility and control over the background error diagnosis agent.

---

## 1. Architecture & Design

### A. Ollama `d1` / `/v1/systemone` Protocol Overhaul
1. **Clean Parameter Passing**:
   - `/v1/systemone` accepts strictly: `model`, `state`, `questions`, `images` (optional), and `keep_alive` (optional).
   - Strip all chat/LLM options (`options`, `temperature`, `num_predict`, `num_ctx`, etc.) before calling `systemone`.
2. **Standardized Question Definitions**:
   - `choice`: `{"type": "choice", "instructions": "...", "criteria": {"key": "desc", ...}}`
   - `noul`: `{"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}}`
   - `score`: `{"type": "score", "instructions": "...", "criteria": ["Level 0", "Level 1", ...]}`
3. **Robust Client Wrapper**:
   - Update `LoggedOllamaClient.systemone()` in `src/kb_web/base.py` to sanitize kwargs and support both `_client.systemone` and direct HTTP fallback to `/v1/systemone`.
   - Parse answers correctly: return calibrated probabilities, confidence, discrete choices, and scores with input tokens from `usage`.

### B. Central Agent Configuration Registry
1. **Database Schema (`AgentConfiguration` in `src/kb_web/models_orm.py`)**:
   - `id`: unique identifier string (e.g. `maintenance_agent`, `wiki_curation`, `tag_curation`, `link_crawler`, `rag_eval`, `synthetic_qa`, `article_chat`, `workspace_agent`, `taxonomy_agent`, `rag_synthesis`)
   - `name`: Human-readable title
   - `category`: `curation`, `crawler`, `diagnostics`, `coding`, `rag`, `taxonomy`
   - `type`: `llm`, `decision`, `embedding`, `coding`
   - `model`: e.g. `gemma4:e4b`, `d1`, `nomic-embed-text`
   - `system_prompt`: system message / prompt template
   - `user_prompt_template`: Jinja template for payload
   - `thinking`: integer boolean
   - `temperature`, `num_predict`, `num_ctx`, `top_p`, `top_k`
   - `tools`: JSON array of allowed tool primitives
   - `enabled`: integer boolean
   - `extra_options`: JSON string
2. **Log Error Agent Visibility & Control**:
   - Register `maintenance_agent` (`Error Diagnostics & Site Maintenance Agent`) with full controls: model, prompt, auto-diagnosis toggle, and max tokens.
3. **Admin Portal UI**:
   - Dedicated tab in `/admin` displaying all agent configurations with inline editing, tool selection, parameter tuning, and save actions.

### C. Report-Driven Eval Datasets & Jinja Templating
1. **Database Schema (`EvalDataset` in `src/kb_web/models_orm.py`)**:
   - `id`: primary key
   - `name`: dataset name
   - `description`: text
   - `query_config`: JSON of `ReportQueryRequest` (`base_table`, `selected_columns`, `filter_config`, `sort_config`, `joins_config`)
   - `row_count`: verified $\ge 20$ rows
   - `created_at`, `updated_at`: ISO timestamps
2. **New Tab in Evals Studio**: `Eval Datasets & Query Builder`:
   - Design report queries across `fetched_pages`, `youtube_videos`, `ollama_logs`, `notes`, etc.
   - Live query preview showing first 5 rows and total matching row count.
   - Enforce 20-row minimum rule before enabling "Save as Eval Dataset".
   - Dataset list with row counts, inspect, and delete.
3. **Multi-Row Dataset Evaluation Execution**:
   - In Prompt Matrix, Decision Gating, and Embedding benchmarks:
     - Toggle between "Single Input" and "Dataset Iteration (Report Rows)".
     - Select a saved Eval Dataset (or sample 20+ rows on the fly).
     - Jinja Template Editor: define template using `{{ data.<field> }}`.
     - Live preview of rendered input for row 0.
     - Batch execution over the rows with concurrency control, progress bar, and comprehensive results table.

---

## 2. Implementation Steps

1. **Database ORM Models (`src/kb_web/models_orm.py`)**:
   - Add `AgentConfiguration` and `EvalDataset`.
   - Add initial migration / bootstrap seeding in `src/kb_web/config.py` and `src/kb_web/server.py`.
2. **Ollama SystemOne Engine (`src/kb_web/base.py` & `src/kb_web/routers/evals.py`)**:
   - Refactor `LoggedOllamaClient.systemone()` to reject `options` and sanitize kwargs.
   - Update `POST /api/evals/decision/run` to support both single input and dataset rows with `instructions`, `type`, `criteria`.
3. **Eval Datasets APIs (`src/kb_web/routers/evals.py`)**:
   - `GET /api/evals/datasets`: List saved datasets.
   - `POST /api/evals/datasets/preview`: Preview report query & row count.
   - `POST /api/evals/datasets`: Save dataset (validating $\ge 20$ rows).
   - `POST /api/evals/matrix/run`: Support dataset iteration mode with Jinja template rendering.
   - `POST /api/evals/embedding/run`: Support dataset iteration mode with Jinja template rendering.
4. **Admin Portal Agent Configurations (`src/kb_web/routers/admin.py` & `src/kb_web/templates/admin.j2.html`)**:
   - Expose `GET /api/admin/agents` and `POST /api/admin/agents/{id}`.
   - Add dedicated Agent Configuration tab in `admin.j2.html` exposing every parameter for all 10+ agents including the maintenance/error log agent.
5. **Evals Studio UI (`src/kb_web/templates/evals.j2.html`)**:
   - Add Tab 4: "Eval Datasets & Query Builder".
   - Add "Dataset Iteration" mode in Tabs 1, 2, and 3 with Jinja template editor (`{{ data.<key> }}`), live row preview, execution progress bar, and results grid.
6. **Verification & Deployment**:
   - Run `verify_ui_templates.py`.
   - Add comprehensive tests in `tests/test_eval_datasets_and_d1.py`.
   - Run pytest suite.
   - Merge and deploy to `websrvr` (`/srv/kb-web-test` and `/srv/kb-web`).
   - Validate live via browser subagent.
