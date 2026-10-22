# Walkthrough: Embedding Model Unification & Cross-Space Query Collision Fix

## Overview
This fix addresses the embedding model divergence where document chunks were generated using a hardcoded model (`"embeddinggemma"`), while search queries and article embeddings were embedded using another model (`"nomic-embed-text"` via `config.ollama_embedding_model`). Because Nomic and Gemma occupy completely incompatible vector spaces, calculating cosine distance between them returned degraded, near-zero, or meaningless similarity scores.

---

## Key Changes Made

### 1. Centralized Active Embedding Model Resolution (`src/kb_web/utils.py`)
- Created `get_active_embedding_model(session=None, config=None) -> str` as the canonical source of truth.
- Resolves the model from `config.ollama_embedding_model`, falling back gracefully and checking `SettingOllama(key="ollama_embedding_model")` or `SettingExternal(key="active_embedding_model")`.
- Defaulted canonical fallback to `"nomic-embed-text"`.

### 2. Document & Chunk Embedding Generation (`src/kb_web/utils.py`)
- **`generate_gemma_embeddings_for_page`** (aliased as **`generate_embeddings_for_page`**):
  - Removed hardcoded `emb_model = "embeddinggemma"`.
  - Now uses `model or getattr(config, "ollama_embedding_model", None) or get_active_embedding_model(config=config)`.
  - Dynamically formats document prefix `search_document: ` for models supporting it (`gemma` and `nomic`).
  - Explicitly sets `model_name=emb_model` when creating `ChunkEmbedding`.
  - Deletes stale chunks scoped to both `source_id` and `model_name`.
- **`update_article_embedding`**:
  - Accepts optional `model: Optional[str] = None`.
  - Uses `emb_model` consistently with `search_document: ` prefix.

### 3. Vector Similarity Retrieval & Filtering (`src/kb_web/utils.py`, `src/kb_web/rag_agent.py`)
- **`find_nearest_chunks`**:
  - Resolves query embedding model using `get_active_embedding_model()`.
  - **CRITICAL**: Filters `ChunkEmbedding.model_name == emb_model` for both PostgreSQL pgvector queries and SQLite fallback calculations. This completely eliminates cross-model vector distance calculations between incompatible embedding models.
- **`vector_rag_subagent` & `configured_rag_pipeline`**:
  - Removed hardcoded default `"embeddinggemma"`.
  - Dynamically resolves `active_model = get_active_embedding_model(session=session, config=config)`.
- **`get_similar_articles`**:
  - Added support for `query_vector` parameter across PostgreSQL and SQLite codepaths.

### 4. Admin, REST, and CLI Synchronization
- **`routers/admin.py`**:
  - When saving settings, updates `SettingExternal(key="active_embedding_model")` in addition to `SettingOllama` and `config.ollama_embedding_model`.
- **`routers/embeddings.py`**:
  - Synchronizes `config.ollama_embedding_model`, `SettingOllama`, and `SettingExternal` in `set_active_embedding_model`.
  - Resolves active model via `resolve_active_model(session=session, config=config)`.
- **`routers/cli_api.py`**:
  - Replaced hardcoded `"embeddinggemma"` in `/query-similar` and `/chat` with `get_active_embedding_model(config=config)`.
- **`worker.py`**:
  - Harmonized `embedding_refresh` job default model to `config.ollama_embedding_model`.
  - Passed `job_cfg.ollama_embedding_model` explicitly into both `update_article_embedding` and `generate_gemma_embeddings_for_page` in `wiki_curation` and `_run_embedding_refresh`.
- **`cli.py`**:
  - Added `kb-web-cli reindex-embeddings [--model MODEL]` command allowing on-demand reindexing of all document chunks with the active embedding model.

---

## Verification Results

### 1. Automated Unit Tests (`tests/test_embedding_unification.py`)
- `test_get_active_embedding_model_resolution`: Verified active embedding model resolution.
- `test_generate_embeddings_stores_model_name`: Verified chunks are stamped with the active model name.
- `test_find_nearest_chunks_strictly_filters_by_model`: Seeded chunks with different models and verified cross-model contamination is prevented.
- `test_api_active_model_sync`: Verified bidirectional synchronization between API and config.
- `test_cli_reindex_embeddings_help`: Verified CLI command registration.

### 2. Full Test Suite & Build Verification
- `uv run pytest`: **248 passed** in 248.94s.
- `uv run python build.py`: **[SUCCESS] Build verification pipeline completed successfully!**
