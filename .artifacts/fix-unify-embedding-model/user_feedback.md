# User Feedback: Embedding Model Unification

## User Input
- **Date**: 2026-10-20
- **Feedback**:
  > "there is a mismatch with the model making vectors and the model embedding queries. everything needs ro use one embedding model or the oher. querying with comic against Gemma embedding is not returning good results."

## Problem Assessment
- Document vectors were indexed using one model (hardcoded `"embeddinggemma"` in `generate_gemma_embeddings_for_page`), while queries and article-level embeddings were using another (e.g. `nomic-embed-text` via `config.ollama_embedding_model`).
- Querying with Nomic embeddings against Gemma vector chunks results in incompatible vector spaces and cosine similarity degradation (near-zero or meaningless matches).
- In addition, vector search in `find_nearest_chunks` was not filtering by `ChunkEmbedding.model_name`, causing distance computations across disparate vector spaces.
- `rag_agent.py` and `rag_reports.py` relied on `SettingExternal(key="active_embedding_model")` with a hardcoded `"embeddinggemma"` fallback, bypassing `SettingOllama(key="ollama_embedding_model")` and `config.ollama_embedding_model`.

## Requirements
1. Unify vector generation, chunk embedding, article/video embedding, query embedding, and RAG retrieval across the entire codebase to use one single configurable embedding model (`config.ollama_embedding_model`).
2. Eliminate hardcoded `"embeddinggemma"` or `"nomic-embed-text"` divergences.
3. Explicitly set and filter `ChunkEmbedding.model_name` so similarity operations always operate within the same model's vector space.
4. Synchronize `SettingOllama(key="ollama_embedding_model")` and `SettingExternal(key="active_embedding_model")` so both API and Admin configurations are unified.
5. Provide a re-indexing utility or CLI command so existing chunks can be synchronized with the active embedding model.
