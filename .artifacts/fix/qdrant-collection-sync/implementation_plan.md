# Implementation Plan - Fix Qdrant Collection Export 404 & Collection Auto-Creation

Fix the missing `/collections/view/{collection_id}/sync` endpoint, ensure collections are automatically created in Qdrant with proper vector dimensions, and synchronize chunk embeddings and metadata with graceful error handling.

## User Review Required

> [!IMPORTANT]
> - **Collection Naming**: Collection titles are sanitized to Qdrant-compliant names (`^[a-zA-Z0-9_-]+$`). For example, `"General Collection"` becomes `"general_collection"`.
> - **API Key Fallback**: If `QDRANT_API_KEY` is not provided (or is empty `""`), requests to Qdrant will omit the `api-key` header, which is standard for local/private Qdrant instances.
> - **Auto-Creation When Empty**: If a collection does not yet have vector-indexed items, the endpoint will still create the collection in Qdrant (using the configured embedding dimension, 768 for `nomic-embed-text`) and return a success status indicating the collection was created with 0 points.

---

## Proposed Changes

### Backend: Collections Router
#### [MODIFY] [collections.py](file:///c:/src/kb-web/src/kb_web/routers/collections.py)
- Register route `@router.post("/collections/view/{collection_id}/sync", dependencies=[Depends(verify_auth)])` to match the exact URL called by `view_collection.j2.html`.
- Enhance `sync_collection_to_qdrant(db, collection_id: int)`:
  - Sanitize collection name: `col_name = re.sub(r"[^a-zA-Z0-9_-]", "_", collection.title.strip()).lower().strip("_") or f"col_{collection_id}"`.
  - For each collection item, check if `ChunkEmbedding` exists. If missing, invoke `generate_gemma_embeddings_for_page()` to generate embeddings on-demand.
  - Determine vector dimension (`vector_size = len(points[0]["vector"]) if points else 768`).
  - Always check if Qdrant collection exists via `GET {qdrant_url}/collections/{col_name}`.
  - If 404, create the collection via `PUT {qdrant_url}/collections/{col_name}` with Cosine distance and correct vector size.
  - If points exist, upsert points in batches to `{qdrant_url}/collections/{col_name}/points`.
  - Provide descriptive status and message in the returned tuple.

---

### Frontend: Collection View Template
#### [MODIFY] [view_collection.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_collection.j2.html)
- Update `syncQdrant()`:
  - Check `res.ok` before evaluating status.
  - Extract message safely: `data.message || data.detail || (res.ok ? "Sync successful." : "Sync failed (HTTP " + res.status + ")")`.
  - Display user-friendly error details in the status modal, preventing `"undefined"` from ever appearing.

---

### Tests
#### [NEW] [test_qdrant_sync.py](file:///c:/src/kb-web/tests/test_qdrant_sync.py)
- Test `POST /collections/view/{collection_id}/sync`:
  - Successfully creates collection and syncs points (mocking `httpx` and Qdrant).
  - Handles empty collection (creates Qdrant collection and reports 0 points).
  - Handles unconfigured Qdrant host URL gracefully.
  - Handles Qdrant server connection errors cleanly.

---

## Verification Plan

### Automated Tests
- Run `uv run pytest tests/test_qdrant_sync.py`
- Run full test suite: `uv run pytest`
- Run template verification: `uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`
- Run build pipeline: `uv run python build.py`

### Manual Verification
- Test against running Qdrant instance on `http://192.168.0.33:7333` using a local python test script.
- Verify status modal renders informative error and success messages.
