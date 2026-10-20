# Implementation Plan: Embedding Model Unification & Consistency

## 1. Problem Summary & Architecture Review
The user identified an embedding model divergence across vector creation and vector query routines:
- `generate_gemma_embeddings_for_page` hardcoded `emb_model = "embeddinggemma"` for chunk generation and description embeddings.
- It created `ChunkEmbedding` without specifying `model_name`, defaulting to `"embeddinggemma"`.
- `update_article_embedding` used `getattr(config, "ollama_embedding_model", "nomic-embed-text")`.
- `find_nearest_chunks` generated query embeddings with `config.ollama_embedding_model` (e.g., `nomic-embed-text`), but calculated cosine distance across all `ChunkEmbedding` records without filtering by `model_name`.
- `cli_api.py` (`/query-similar` and `/chat`) hardcoded query embeddings to `"embeddinggemma"` while searching against `ArticleEmbedding` (embedded with Nomic).
- `rag_agent.py` and `rag_reports.py` fetched `SettingExternal(key="active_embedding_model")` with fallback `"embeddinggemma"`, completely bypassing `SettingOllama(key="ollama_embedding_model")` and `config.ollama_embedding_model`.

Because Nomic Embed Text (768-dim) and Gemma Embedding occupy completely different vector spaces, querying with Nomic against Gemma embeddings yields meaningless cosine similarities (near 0 or random noise).

---

## 2. Proposed Changes

### A. Centralized Active Embedding Model Resolution (`src/kb_web/utils.py`, `src/kb_web/config.py`)
1. Create a helper function `get_active_embedding_model(session=None, config=None) -> str`:
   - Checks `config.ollama_embedding_model`.
   - If session is available, checks `SettingOllama(key="ollama_embedding_model")` or `SettingExternal(key="active_embedding_model")`.
   - Falls back to `config.ollama_embedding_model` or `"nomic-embed-text"`.
2. Keep `SettingOllama(key="ollama_embedding_model")` and `SettingExternal(key="active_embedding_model")` synchronized whenever either is updated in `/admin` or `/api/embeddings/active-model`.

### B. Core Embedding Generation & Storage (`src/kb_web/utils.py`)
1. Refactor `generate_gemma_embeddings_for_page(db=None, url: str = None, config=None, client=None, model: Optional[str] = None)`:
   - Handle argument order flexibility (e.g. `url` passed as first arg).
   - Use `emb_model = model or getattr(config, "ollama_embedding_model", None) or get_active_embedding_model()`.
   - Use prefix `search_document: ` for models supporting it (`gemma` or `nomic`).
   - Explicitly store `model_name=emb_model` on `ChunkEmbedding`.
   - Delete previous chunks matching `(source_id=url, model_name=emb_model)` to avoid duplicate chunks.
   - Alias `generate_embeddings_for_page = generate_gemma_embeddings_for_page` for clear terminology.
2. Update `update_article_embedding`:
   - Accept optional `model: Optional[str] = None`.
   - Use unified `emb_model = model or getattr(config, "ollama_embedding_model", None) or get_active_embedding_model()`.
3. Fix `get_similar_articles`:
   - Add optional `query_vector: Optional[list] = None` and `collection_id: Optional[int] = None` to signature and handle query vectors properly for both PostgreSQL and SQLite.

### C. Vector Retrieval & Filtering (`src/kb_web/utils.py`, `src/kb_web/rag_agent.py`)
1. In `find_nearest_chunks`:
   - Resolve `emb_model = model or getattr(config, "ollama_embedding_model", None) or get_active_embedding_model()`.
   - Filter `ChunkEmbedding.model_name == emb_model` so similarity search strictly compares vectors in the SAME embedding space.
   - For SQLite fallback, also filter `ChunkEmbedding.model_name == emb_model`.
2. In `rag_agent.py` (`vector_rag_subagent` and `configured_rag_pipeline`):
   - Set default `active_model = None` resolving dynamically to `get_active_embedding_model()`.
   - Ensure query prompt prefix aligns with the active model.
   - Retain `ChunkEmbedding.model_name == active_model` filter.
3. In `routers/rag_reports.py`:
   - Unify active embedding model lookup with `get_active_embedding_model()`.

### D. CLI & Worker Jobs Alignment (`src/kb_web/routers/cli_api.py`, `src/kb_web/worker.py`, `src/kb_web/cli.py`)
1. In `cli_api.py`:
   - Replace hardcoded `"embeddinggemma"` in `/query-similar` and `/chat` with `get_active_embedding_model(session, config)`.
2. In `worker.py`:
   - Default `embedding_refresh` job model to `config.ollama_embedding_model`.
   - Pass `job.model` into `generate_gemma_embeddings_for_page(..., model=job.model)`.
   - In `wiki_curation`, pass `job_cfg.ollama_embedding_model` to both `update_article_embedding` and `generate_gemma_embeddings_for_page`.
3. In `cli.py`:
   - Add a CLI command `reindex-embeddings` allowing users/admins to reindex all pages with the active embedding model on demand (`kb-web-cli reindex-embeddings [--model MODEL]`).

### E. ORM Defaults & Verification (`src/kb_web/models_orm.py`, `src/kb_web/routers/pages.py`)
1. In `models_orm.py`:
   - Update `ChunkEmbedding.model_name` default to `"nomic-embed-text"`.
2. In `routers/pages.py`:
   - Avoid fallback to `"embeddinggemma"`; fallback to active model.

---

## 3. Verification Plan
1. **Unit & Integration Tests**:
   - Run `uv run pytest tests/test_rag_agent_and_reports.py`.
   - Run `uv run pytest tests/test_server.py -k embedding`.
   - Run `uv run pytest tests/test_evals_datasets_and_worker_agents.py`.
   - Verify full test suite: `uv run pytest`.
2. **Build Verification**:
   - Run `uv run python build.py`.
3. **Database Consistency Verification**:
   - Verify that chunks created with the active model are properly filtered and returned in search queries.
