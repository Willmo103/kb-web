# User Feedback & Comprehensive Requirements

**Date**: 2026-10-19  
**Branch**: `feature/evals-datasets-jinja-worker-agents-run-history`

---

## 1. Model Categorization Hardening
- **Critical Requirement**: **No decision models (`d1`, `tev1`) should ever appear in the wiki/text generation evaluation model list**.
- **Issue**: `d1` was still showing up in the generation list because baseline model fallback (`config.ollama_model`) was inserted without re-validating against `classify_model_type()`.
- **Action**: Enforce strict filtering so `llm_models` contains ONLY models where `classify_model_type(m) == 'llm'`. Under no circumstances should `d1` or `tev1` appear in generation model selectors.

---

## 2. Dataset-Only Evaluations & Template Formatting
- **Remove Single Article Option**: Completely eliminate the "Single Input Text" mode from the Matrix Evaluation Studio. Evaluations must operate exclusively against datasets.
- **Dataset Field Access**: Allow formatting the eval prompt template using any and all fields from the selected dataset (e.g. `{{ data.title }}`, `{{ data.url }}`, `{{ data.md_content }}`, `{{ data.tags }}`, `{{ data.description }}`, `{{ data.fetched_at }}`).
- **Available Fields Explorer**: Provide an interactive view displaying all available fields for Jinja templating from the selected dataset, with click-to-insert support.
- **Randomized Dataset Sampling**: Add support and a control to randomize/shuffle item selection from the dataset rather than merely pulling sequential rows.

---

## 3. Real-Time Jinja Parameter Highlighting
- **Live Validation Highlighting**: In all Jinja template editors, implement real-time parameter syntax validation:
  - **Green**: Proper/matching parameter that exists in the active dataset schema (e.g. `{{ data.title }}`).
  - **Red**: Invalid, non-matching, or misspelled parameter (e.g. `{{ data.non_existent_key }}`).
- **Architecture**: Build a reusable JavaScript module (`static/js/jinja_highlighter.js`) to power live validation across the Evaluation Studio and Admin Agent configuration editors.

---

## 4. Strict Separation of SystemOne Decision Models
- **Fundamental Rule**: **SystemOne models (`d1`, `tev1`) DO NOT get tools, DO NOT get system messages, and DO NOT use chat sampling parameters (`temperature`, `top_p`, `top_k`, `num_predict`)**.
- **UI Reflection & Respect**:
  - Decision models must be isolated into their own dedicated section in the Admin Portal and must not be grouped with LLM agents.
  - The UI must completely hide/remove Tools, System Prompts, Thinking, Temperature, Top-P, Top-K, and Num Predict for SystemOne models.
  - The UI must ONLY display the `state` template and the `questions` schema (with `instructions`, `type`, and `criteria`).

---

## 5. Configurable & Extensible Worker Agents
- **Add New Agent**: Worker agents must be fully user-configurable, not just preconfigured. Users must be able to add new agents (`+ Create New Agent`), delete custom agents, and choose their architecture (`llm` vs `decision` vs `embedding`).
- **Test Before Publish ("n8n Frozen Commit Workflow")**:
  - Users must be able to test worker agent outputs against sample dataset rows like an eval before publishing.
  - Publishing an agent configuration creates a frozen, versioned snapshot commit (locking prompt, model, questions, and parameters).

---

## 6. Stored Evaluation Runs & Re-run Configurations
- **Persistent Run History**: All evaluation runs (whether completed, running, failed, or cancelled) must be stored in the database (`evaluation_runs`).
- **Live & Partial Results**: Results stream and persist progressively so partial runs can still be inspected.
- **Load & Re-run**:
  - Review historical eval runs with full outputs and metrics.
  - **Re-run**: Re-execute an evaluation with identical parameters.
  - **Load Configuration**: Restore prompts, model selections, and dataset configuration back into the active Studio form.
