# User Feedback & Requirements

**Date**: 2026-10-19  
**Branch**: `feature/evals-filtering-worker-agents-and-builder`

---

## 1. Model Type Filtering Across Evaluation Types
- **Prompt & Model Matrix (LLMs)**: Filter available models to display only LLM completion/chat models (e.g., `gemma4:e4b`, `granite4.2:8b`, `llama3.2:latest`, `qwen3.5:2b`, etc.). Must **not** display SystemOne decision models (`d1`, `tev1`) or embedding models (`nomic-embed-text`, `embeddinggemma`, `all-minilm`).
- **Decision Gating Studio (SystemOne)**: Filter available models to display only decision models (`d1`, `tev1`, or models supporting `/v1/systemone`). Must **not** display embedding or standard LLM models.
- **Embedding Retrieval Benchmarks**: Filter available models to display only vector embedding models (`embeddinggemma`, `nomic-embed-text`, `mxbai-embed-large`, `all-minilm`). Must **not** display LLM completion models or SystemOne decision models.

---

## 2. Complete and Test Background Worker Agents
Implement and test the three currently planned/stubbed background worker agents in `src/kb_web/worker.py`:
1. **Synthetic QA Benchmark Agent (`synthetic_qa`)**:
   - Selects curated articles lacking synthetic evaluation pairs.
   - Generates realistic question-answer pairs with citation anchors using Ollama LLM.
   - Stores pairs in database/table for retrieval benchmarking and evaluation datasets.
2. **RAG Decision Evaluation Agent (`rag_eval`)**:
   - Takes generated synthetic QA pairs or evaluation questions.
   - Executes retrieval against Qdrant vectors and page content.
   - Scores retrieval quality, relevance, and factual grounding using `d1`/`tev1` decision model gating (`instructions`, `criteria`, `noul`).
   - Persists benchmark scores and metrics.
3. **Autonomous Outbound Link Discovery Crawler (`link_crawler`)**:
   - Discovers outbound URLs extracted from library article markdown and HTML.
   - Validates URLs against SSRF/internal IP guards (`validate_target_url`) and crawler domain rules.
   - Evaluates link relevance using decision gating (`d1` / `tev1` relevance gate preset).
   - Enqueues or fetches approved links into the ingestion pipeline.

---

## 3. Agent Builder Interface
- Provide an interactive **Agent Builder** interface (in the Admin Portal / Evals Studio) allowing users to:
  - Define new custom agents with unique ID, name, category (`curation`, `crawler`, `diagnostics`, `coding`, `rag`, `taxonomy`, `custom`), and call type (`llm`, `decision`, `embedding`, `coding`).
  - Configure target Ollama model, system prompt, user prompt template (supporting Jinja2 arguments like `{{ data.title }}`, `{{ data.content }}`), tools, thinking toggle, temperature, `num_ctx`, and `num_predict`.
  - Provide a live test harness to dry-run the custom agent against sample input or dataset rows before saving.
  - Persist new agents into the `agent_configurations` ORM table and make them available to worker jobs.
