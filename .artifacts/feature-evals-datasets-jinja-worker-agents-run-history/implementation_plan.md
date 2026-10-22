# Implementation Plan: Evals Datasets, Jinja Highlighting, SystemOne Isolation, Configurable Worker Agents, and Run History

**Branch**: `feature/evals-datasets-jinja-worker-agents-run-history`  
**Date**: 2026-10-19

---

## User Review Required

> [!IMPORTANT]
> **Strict SystemOne Isolation**: SystemOne models (`d1`, `tev1`) have 0 output tokens and evaluate states via single forward pass. They will be strictly segregated from LLM agents in the UI, with Tools, System Prompts, Thinking, and Sampling parameters completely removed.
>
> **Dataset-Only Matrix Evals**: The "Single Article" mode is removed in favor of dataset-driven evaluations with randomized sampling and live Jinja field insertion.
>
> **Worker Agent Publishing**: Worker agents will support a workflow lifecycle modeled after n8n/git releases: agents can be tested on sample rows in draft mode before creating a frozen published commit.

---

## Proposed Changes

### Track 1: Strict Model Filtering in Evals (`src/kb_web/routers/evals.py`)
- In `classify_model_type()`: enforce strict matching.
- In `view_evals_studio()`:
  - Fix baseline model insertion: only insert `config.ollama_model` into `llm_models` if `classify_model_type(config.ollama_model) == 'llm'`.
  - Add explicit post-filter: `llm_models = [m for m in llm_models if classify_model_type(m) == 'llm' and m not in ('d1', 'tev1')]`.
  - Guarantee that `d1` and `tev1` NEVER appear in Tab 1 (Matrix) or any text generation selector.

### Track 2: Dataset-Only Matrix Evals & Randomization (`src/kb_web/templates/evals.j2.html`, `src/kb_web/routers/evals.py`)
- Completely remove the "Single Input Text" tab and textarea.
- Matrix setup will default directly to Dataset Iteration.
- Add "Randomize Sample" checkbox (`randomize: true`).
- In `POST /api/evals/matrix/stream` and `POST /api/evals/matrix`:
  - When `randomize` is true, sample rows via random shuffle (`random.sample(rows, min(limit, len(rows)))`).
- Add an interactive **"Available Dataset Fields"** toolbar that displays clickable badges for all fields in the selected dataset schema (`{{ data.url }}`, `{{ data.title }}`, `{{ data.md_content }}`, `{{ data.tags }}`, `{{ data.description }}`), inserting them at cursor position.

### Track 3: Reusable Jinja Parameter Syntax & Validation Highlighting (`static/js/jinja_highlighter.js`)
- Create a standalone JavaScript module `static/js/jinja_highlighter.js`.
- Automatically parses Jinja parameter tags `{{\s*data\.([a-zA-Z0-9_]+)\s*}}`:
  - Renders a live parameter status badge bar directly beneath the editor:
    * **Green badge**: `{{ data.<key> }} ✓ Valid Field`
    * **Red badge**: `{{ data.<key> }} ✗ Unrecognized Field`
  - Validates in real time against the active dataset schema in Evals Studio or active agent variables in the Admin Portal.
  - Mount across `matrixJinjaTemplate` in `evals.j2.html` and `user_prompt_template` in `admin.j2.html`.

### Track 4: Strict UI Isolation of SystemOne Decision Models (`src/kb_web/templates/admin.j2.html`)
- Segregate SystemOne decision agents into a separate, dedicated section: **"⚖️ SystemOne Decision Gates (Deterministic Forward Pass)"**.
- Strip all LLM-specific parameters from SystemOne agents:
  - **Remove**: Tools, System Prompt, Thinking toggle, Temperature, Top P, Top K, Num Predict.
  - **Retain ONLY**: Model name, Context window (`num_ctx`), State Template (`user_prompt_template`), and Questions & Criteria schema (`extra_options.questions`).
- Prominently display the architectural distinction in the UI header.

### Track 5: Configurable Worker Agents & Frozen Commit Workflow (`src/kb_web/models_orm.py`, `src/kb_web/agent_config.py`, `src/kb_web/routers/admin.py`, `src/kb_web/templates/admin.j2.html`)
- Add fields to `AgentConfiguration` in `models_orm.py`:
  - `version`: Integer revision counter (default: 1).
  - `is_published`: Integer flag (0 = draft, 1 = published).
  - `frozen_snapshot_json`: Text storing the frozen configuration snapshot.
- Add `+ Create New Agent` modal and backend endpoint `POST /api/admin/agents/create` allowing users to configure new custom worker agents.
- Add `DELETE /api/admin/agents/{agent_id}` to delete custom worker agents.
- Add `POST /api/admin/agents/{agent_id}/test-run` to execute a draft test against a sample row.
- Add `POST /api/admin/agents/{agent_id}/publish` to freeze and version the agent configuration like an n8n workflow release.

### Track 6: Persistent Evaluation Run History & Re-run / Load Configurations (`src/kb_web/models_orm.py`, `src/kb_web/routers/evals.py`, `src/kb_web/templates/evals.j2.html`)
- Add `EvaluationRun` ORM model in `models_orm.py`:
  - `id`: Auto-incrementing primary key.
  - `eval_type`: String (`matrix`, `decision`, `embedding`).
  - `title`: String descriptor.
  - `status`: String (`running`, `completed`, `failed`, `cancelled`).
  - `config_json`: JSON containing models, prompts, dataset ID, sampling settings, and parameters.
  - `results_json`: JSON storing streaming results and completed outputs.
  - `metrics_json`: JSON storing duration, token metrics, and cell counts.
  - `created_at`, `completed_at`: Timestamps.
- Update `POST /api/evals/matrix/stream` to initialize an `EvaluationRun` record and flush partial results continuously.
- Add Tab 5 (**"Run History & Saved Configurations"**) in `evals.j2.html`:
  - Displays table of all runs (past, ongoing, failed).
  - **Load Configuration**: Populates prompts, model checkboxes, and dataset selectors with the exact saved settings.
  - **Re-run**: Directly triggers the evaluation again.

---

## Verification Plan

### Automated Tests
1. `tests/test_evals_model_isolation.py`:
   - Verify `d1` and `tev1` never appear in `llm_models`.
   - Verify randomized dataset selection in `POST /api/evals/matrix/stream`.
2. `tests/test_agent_lifecycle_and_systemone.py`:
   - Test creating a custom worker agent via `POST /api/admin/agents/create`.
   - Test testing a draft worker agent on sample rows.
   - Test publishing/freezing an agent configuration into a versioned commit snapshot.
   - Verify SystemOne agents have no tools or system prompts.
3. `tests/test_evaluation_run_history.py`:
   - Test `EvaluationRun` persistence, partial results logging, and re-run/load endpoints.
4. Pre-commit check suite:
   - `verify_ui_templates.py` on all templates.
   - `uv run pytest`.
   - `uv run python build.py`.
