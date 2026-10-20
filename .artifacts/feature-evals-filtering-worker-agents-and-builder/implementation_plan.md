# Implementation Plan: Evals Model Type Filtering, Worker Agents Completion, and Agent Builder

**Action Directory**: `.artifacts/feature-evals-filtering-worker-agents-and-builder/`  
**Git Branch**: `feature/evals-filtering-worker-agents-and-builder`

---

## 1. Overview & Objectives

This implementation delivers three user-requested capabilities:
1. **Model Type Filtering in Model Evaluation Studio (`/evals`)**:
   - Filter available models by type across tabs so LLM completion models, SystemOne decision models, and vector embedding models are strictly isolated to their respective evaluation workflows.
2. **Complete & Test 3 Worker Agents (`src/kb_web/worker.py`)**:
   - **Synthetic QA Benchmark Agent (`synthetic_qa`)**: Generate realistic Q&A pairs from library articles to evaluate retrieval quality.
   - **RAG Decision Evaluation Agent (`rag_eval`)**: Benchmark vector retrieval against ground truth using `d1`/`tev1` decision gating.
   - **Autonomous Outbound Link Discovery Crawler (`link_crawler`)**: Discover outbound links from curated articles, vet them via `d1` relevance gating, and queue approved knowledge.
3. **Interactive Agent Builder Interface (`/admin` Tab 6)**:
   - Provide an interface to create, test, and register custom agents with fine-grained parameter controls (`model`, `call_type`, `system_prompt`, `user_prompt_template`, `thinking`, `num_ctx`, `num_predict`, `tools`).
   - Include a live test harness to dry-run custom prompts before deployment.

---

## 2. Proposed Changes

### Phase A: Model Type Classification & Evals Studio Filtering
- **`src/kb_web/routers/evals.py`**:
  - Implement `classify_ollama_model(model_name, details, capabilities)`:
    - `"decision"`: `model_name in ("d1", "tev1")` or `"decision"` in name or `"systemone"` in name.
    - `"embedding"`: `capabilities` has `"embedding"` or family in `("bert", "gemma-embedding", "nomic-bert")` or name has `"embed"`, `"minilm"`, `"bge"`.
    - `"llm"`: All standard completion/chat models (`capabilities` has `"completion"`, not decision, not embedding).
  - Update `view_evals_studio`:
    - Fetch `/api/tags` and classify models into `llm_models`, `decision_models`, and `embedding_models`.
    - Pass lists to `evals.j2.html`.
  - Expose `category` in `GET /api/evals/models/info`.
- **`src/kb_web/templates/evals.j2.html`**:
  - Tab 1 (Matrix): Render only `llm_models`.
  - Tab 2 (Decision): Render `decision_models` as selection pills with default `d1`.
  - Tab 3 (Embedding): Dynamically render `embedding_models` pills/checkboxes.

---

### Phase B: Complete Background Worker Agents
- **`src/kb_web/models_orm.py`**:
  - Add `SyntheticQAItem`: `id`, `page_id`, `url`, `question`, `ground_truth_answer`, `context_snippet`, `created_at`.
  - Add `RAGEvalResult`: `id`, `qa_id`, `model`, `score`, `noul`, `reasoning`, `created_at`.
- **`src/kb_web/worker.py`**:
  - Complete `_run_synthetic_qa()`:
    - Selects an unbenchmarked page.
    - Calls Ollama LLM to synthesize 2 Q&A pairs.
    - Parses JSON and saves to `synthetic_qa_items`.
  - Complete `_run_rag_eval()`:
    - Selects an un-evaluated QA item.
    - Runs Qdrant vector retrieval for the question.
    - Calls `d1`/`systemone` to score whether retrieved chunks contain the ground-truth answer.
    - Persists score into `rag_eval_results`.
  - Complete `_run_link_crawler()`:
    - Scans recent `FetchedPage.links`.
    - Validates target URLs (`validate_target_url` SSRF guard).
    - Evaluates URL relevance with `d1` decision gating (`relevance_gate`).
    - Auto-queues approved URLs via `import_html_from_url`.

---

### Phase C: Agent Builder Interface
- **`src/kb_web/routers/admin.py` & `src/kb_web/agent_config.py`**:
  - `POST /api/admin/agents`: Create/register custom agent in `agent_configurations`.
  - `DELETE /api/admin/agents/{id}`: Delete custom agent.
  - `POST /api/admin/agents/test-run`: Dry-run custom agent with sample input, returning stream/response, tokens/sec, and latency.
- **`src/kb_web/templates/admin.j2.html`**:
  - Add "+ Create Custom Agent" modal on Tab 6 (**Agent Configurations**).
  - Form fields: Agent ID, Name, Category, Call Type, Model (filtered by call type), System Prompt, Jinja2 Template, Thinking, Context/Predict, Tools.
  - "Test Run" button with response console.

---

## 3. Verification & Testing

1. **Unit Tests**:
   - `tests/test_evals_model_filtering.py`: Verify model classification logic and tab-specific model isolation.
   - `tests/test_worker_agents_execution.py`: Mock Ollama and verify full execution of `synthetic_qa`, `rag_eval`, and `link_crawler`.
   - `tests/test_agent_builder_api.py`: Verify creation, test-run, update, and deletion of custom agent configurations.
2. **Template Verification**:
   - Run `verify_ui_templates.py` on `admin.j2.html` and `evals.j2.html`.
3. **Full Suite & UAT**:
   - `uv run pytest`
   - `uv run python build.py`
   - Live browser testing on `https://kb-test.willmo.dev/evals` and `/admin`.
