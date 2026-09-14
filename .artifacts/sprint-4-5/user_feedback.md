# User Feedback - Turn 2026-09-13T21:49:52-05:00

## User Request
> "in branch \`sprint-4-5\` complete the code for issues 
> #48 #49 #50. complete the sprint, commit the code back to sprint-4-5 once done. Next will be sprint 5."

## Goals & Scope for Sprint 4
- **Parent Issue**: #48 (Sprint 4: Unified Ingestion Sources Schema & Queue Processor)
- **Sub-Issue 8 (#49)**: Top-Level Ingestion Sources & Processing Registry Schema:
  - Map `sources` table: `id` (UUID primary key), `url` (Text nullable), `file_hash` (Text nullable), `type` (Enum/String `source_type`), `processor_id` (Integer nullable foreign key), `path` (Text nullable), `timestamp` (DateTime / ISO text string), `status` (String: pending, processing, completed, failed), `retry_count` (Integer default 0), `error_log` (Text nullable).
  - Map `_processor_xref` table: `id` (Integer PK), `service_name` (Text), `callback_path` (Text), `stage` (String/Enum: pre, process, post), `next_processor_id` (Integer nullable FK), `is_active` (Boolean default True).
  - Relate child entities (`fetched_pages`, `youtube_videos`, `chunk_embeddings`) to `sources.id` via optional foreign key / reference column.
  - Seed default ingestion service stages inside `_processor_xref` during startup or migration (e.g. fetcher, summary/wiki, tags, embeddings).
- **Sub-Issue 9 (#50)**: State-Driven Job Queue Processor Daemon:
  - Implement `IngestionWorker` in `src/kb_web/queue_processor.py`.
  - Start queue worker background daemon thread in FastAPI `lifespan` or as a background service polling the `sources` table for items ready for processing.
  - Dynamic execution routing: import and call registered callback functions for the active `processor_id`.
  - Drive pipeline state progression: transition `processor_id` to next stage upon success, updating `status` and `timestamp`.
  - Error and retry handling: record stack traces in `error_log`, increment `retry_count`, mark `failed` when max retries exceeded, and send Gotify alert on critical failure.
- **Verification & Delivery**:
  - Comprehensive unit tests covering ORM models, seeding, queue processor state transitions, error handling, and worker execution.
  - Update `.artifacts/analysis-issues-29-30/sprint_4_job_queue.md` and `.artifacts/analysis-issues-29-30/sprint_tracker.md`.
  - Run full test suite, template checks, and build pipeline.
  - Commit all changes to `sprint-4-5` branch, push to `origin/sprint-4-5`.
  - Create draft PR into `production` if appropriate, comment on issues #48, #49, #50.
