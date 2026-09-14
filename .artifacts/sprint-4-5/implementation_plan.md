# Implementation Plan - Sprint 4: Unified Ingestion Sources Schema & Queue Processor

Execute Sprint 4 encompassing Issue #48, Sub-Issue #49, and Sub-Issue #50:
1. **Sub-Issue #49**: Implement top-level `sources` schema and `_processor_xref` service callback registry, relating child entities (`fetched_pages`, `youtube_videos`, `chunk_embeddings`) to sources via foreign key constraints, and seeding default pipeline stages.
2. **Sub-Issue #50**: Implement `IngestionWorker` state-driven queue processor daemon in `src/kb_web/queue_processor.py`, managing dynamic callback execution, stage transitions, retries, error logging, and Gotify alerts.

## User Review Required

> [!IMPORTANT]
> - **Non-Breaking Schema Extensions**: Existing tables (`fetched_pages`, `youtube_videos`, `chunk_embeddings`) remain fully operational with their existing primary keys, while gaining an optional `source_id` foreign key referencing `sources.id`.
> - **Background Daemon Lifecycle**: The `IngestionWorker` runs in a daemon thread managed by FastAPI's `lifespan` context manager, automatically polling for pending jobs with configurable intervals and graceful shutdown.
> - **Extensible Processor Registry**: `_processor_xref` allows registering new pipeline stages (such as Docling file converters in Sprint 5) simply by adding a record pointing to a Python module callback without modifying the core queue daemon.

---

## Proposed Changes

### Database & ORM Layer
#### [MODIFY] [models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py)
- Define `ProcessorXref`:
  - `__tablename__ = "_processor_xref"`
  - `id`: Integer primary key, autoincrement
  - `service_name`: String (e.g. `fetcher`, `wiki_summary`, `tagger`, `embeddings`)
  - `callback_path`: String (e.g. `kb_web.queue_processor:process_fetch`)
  - `stage`: String (e.g. `pre`, `process`, `post`)
  - `next_processor_id`: Integer, ForeignKey(`_processor_xref.id`), nullable=True
  - `is_active`: Boolean, default=True
  - `description`: Text, nullable=True
- Define `Source`:
  - `__tablename__ = "sources"`
  - `id`: String(36) UUID primary key (default uuid4)
  - `url`: Text, nullable=True, index=True
  - `file_hash`: String, nullable=True, index=True
  - `type`: String, nullable=False (`html`, `youtube`, `file`, `docling`)
  - `processor_id`: Integer, ForeignKey(`_processor_xref.id`), nullable=True, index=True
  - `path`: Text, nullable=True
  - `status`: String, default="pending" (`pending`, `processing`, `completed`, `failed`)
  - `retry_count`: Integer, default=0
  - `error_log`: Text, nullable=True
  - `timestamp`: String, default datetime isoformat
  - `metadata_json`: Text, nullable=True
- Add `source_id = Column(String(36), ForeignKey("sources.id"), nullable=True, index=True)` to `FetchedPage`, `YouTubeVideo`, and `ChunkEmbedding`.
- In `ensure_views_and_indexes()`:
  - Call `seed_default_processors(engine)` to pre-populate default pipeline stages in `_processor_xref`.

#### [NEW] [migrations/versions/e81c74291a24_add_sources_and_processor_xref.py](file:///c:/src/kb-web/migrations/versions/e81c74291a24_add_sources_and_processor_xref.py)
- Alembic migration creating `_processor_xref` and `sources` tables and adding `source_id` foreign keys.

---

### Queue Processor Daemon
#### [NEW] [queue_processor.py](file:///c:/src/kb-web/src/kb_web/queue_processor.py)
- Implement `IngestionWorker`:
  - Thread loop with `running` event and polling interval (default 2s).
  - `process_next_job()`: Atomically fetches next pending `Source` with an active `processor_id`.
  - Dynamic callback routing: resolves `callback_path` using `importlib` and calls handler.
  - Stage progression: on success, advances `source.processor_id` to `processor.next_processor_id` (or marks `status = "completed"` when `next_processor_id` is None).
  - Retry & Error handling: catches exceptions, increments `retry_count`, logs traceback in `error_log`, marks `status = "failed"` after max retries (3), and sends Gotify alert.
- Implement built-in callback handlers:
  - `process_fetch`: Fetches content via `httpx` or existing ingest sync.
  - `process_summary`: Invokes Ollama wiki summary.
  - `process_tags`: Invokes Ollama taxonomist.
  - `process_embeddings`: Invokes `generate_gemma_embeddings_for_page`.
  - `process_youtube_metadata`: Extracts video metadata and transcript.
  - `process_youtube_wiki`: Generates YouTube markdown wiki article.
- Implement helper `enqueue_source(url_or_path, source_type="html", collection_id=None, custom_instructions=None) -> str`.

---

### Application Lifecycle & Server
#### [MODIFY] [server.py](file:///c:/src/kb-web/src/kb_web/server.py)
- Start `IngestionWorker` background daemon thread during `lifespan(app)` startup.
- Stop `IngestionWorker` cleanly during `lifespan(app)` shutdown.

#### [MODIFY] [rest_api.py](file:///c:/src/kb-web/src/kb_web/routers/rest_api.py)
- Expose `GET /api/queue/jobs`: Returns paginated/filtered list of queue sources.
- Expose `POST /api/queue/enqueue`: Allows enqueuing new sources via REST API.

---

### Documentation & Sprint Tracker
#### [MODIFY] [sprint_4_job_queue.md](file:///c:/src/kb-web/.artifacts/analysis-issues-29-30/sprint_4_job_queue.md)
- Check off all task items.
#### [MODIFY] [sprint_tracker.md](file:///c:/src/kb-web/.artifacts/analysis-issues-29-30/sprint_tracker.md)
- Mark Sprint 4 as `[x]`.

---

### Tests
#### [NEW] [test_queue_processor.py](file:///c:/src/kb-web/tests/test_queue_processor.py)
- Test `Source` and `ProcessorXref` ORM models and relationships.
- Test `seed_default_processors` idempotency.
- Test `IngestionWorker` job processing:
  - Single stage execution.
  - Full pipeline progression (`pre` -> `process` -> `post` -> `completed`).
  - Failure handling, retry increments, and `failed` status transition.
  - Dynamic callback resolution and error trapping.
- Test queue REST API endpoints (`/api/queue/jobs`, `/api/queue/enqueue`).

---

## Verification Plan

### Automated Tests
- `uv run pytest tests/test_queue_processor.py`
- Full test suite: `uv run pytest`
- Template verification: `uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`
- Build pipeline: `uv run python build.py`

### Manual / Integration Verification
- Enqueue a test source URL and observe `IngestionWorker` advance it through `_processor_xref` stages to `completed`.
- Verify database state in PostgreSQL.
