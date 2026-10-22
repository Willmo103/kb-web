# Walkthrough: Worker Target Execution Tracking & Loop Deduplication

## 1. Problem Solved
The autonomous server worker (`AutonomousWorker` in [`src/kb_web/worker.py`](file:///c:/src/kb-web/src/kb_web/worker.py)) was looping continuously on library items (such as `ssd1306.py`), re-running extraction and generating repeated success notifications every 15–20 seconds.
This loop persisted because:
1. Downstream artifact queries (such as `FetchedPage.url.not_in(select(ContextStatementORM.source_uri))`) fail when NULLs are encountered, when identifiers/schemes differ slightly, or when extraction yields zero statements.
2. PostgreSQL defaults to `NULLS FIRST` on descending queries, causing records without populated `fetched_at` timestamps to persistently sort to the top of the queue.
3. The server lacked a dedicated, persistent job execution tracking model recording which targets have been executed by specific jobs.

---

## 2. Changes Made

### A. Persistent ORM Model & Schema Migration
- File: [`src/kb_web/models_orm.py`](file:///c:/src/kb-web/src/kb_web/models_orm.py)
  - Created `WorkerJobExecution` with columns:
    * `id`: Integer primary key, autoincrement.
    * `job_id`: String, indexed (e.g. `"fact_extraction"`, `"wiki_curation"`, `"tag_curation"`, `"embedding_refresh"`).
    * `target_id`: String, indexed (page URL or resource key).
    * `status`: String, indexed (`"success"`, `"skipped"`, `"failed"`).
    * `items_count`: Integer, default 0 (e.g. number of statements or tags extracted).
    * `error_message`: Text, nullable.
    * `executed_at`: String (ISO 8601 UTC timestamp).
    * Composite index: `Index("ix_worker_job_target", "job_id", "target_id")`.
  - Added table creation and index setup in `ensure_views_and_indexes` across PostgreSQL and SQLite database engines.

### B. Autonomous Worker Engine Hardening
- File: [`src/kb_web/worker.py`](file:///c:/src/kb-web/src/kb_web/worker.py)
  - Added in-memory deduplication set: `self._recent_targets: Dict[str, Set[str]] = defaultdict(set)`.
  - Added helper methods:
    * `log_target_execution(job_id, target_id, status, items_count, error_message)`: Writes execution audit logs to `WorkerJobExecution` and records target in `_recent_targets`.
    * `get_executed_targets(job_id, statuses)`: Fetches set of executed target keys from memory and database.
    * `clear_target_executions(job_id)`: Clears execution history and resets deduplication.
    * `get_target_executions(job_id, limit)`: Returns recent execution history records.
  - Hardened job runners:
    * `_run_fact_extraction`:
      - Excludes targets already logged in `WorkerJobExecution` with status `"success"` or `"skipped"`.
      - Excludes targets in runtime `_recent_targets["fact_extraction"]`.
      - Added `.nullslast()` to `order_by(FetchedPage.fetched_at.desc().nullslast())` to prevent PostgreSQL NULL sorting quirks.
      - Filters out `NULL` and empty strings from `ContextStatementORM.source_uri` subquery.
      - Automatically logs `status="skipped"` with `items_count=0` when extraction produces zero statements, permanently terminating looping on un-extractable targets.
    * `_run_wiki_curation`: Excludes already executed targets, adds `.nullslast()`, and logs execution status.
    * `_run_tag_curation`: Excludes already executed targets, adds `.nullslast()`, and logs execution status.
    * `_run_embedding_refresh`: Excludes already executed targets, adds `.nullslast()`, and logs execution status.

### C. Inspection & Management Endpoints
- File: [`src/kb_web/routers/worker.py`](file:///c:/src/kb-web/src/kb_web/routers/worker.py)
  - `GET /api/jobs/{job_id}/executions`: Inspect recent target executions for a job.
  - `POST /api/jobs/{job_id}/executions/clear`: Clear execution records and in-memory cache.
  - `POST /admin/jobs/{job_id}/executions/clear`: Admin portal form redirect for resetting job executions.

---

## 3. Verification & Test Suite
- Test Suite: [`tests/test_worker_job_execution_tracking.py`](file:///c:/src/kb-web/tests/test_worker_job_execution_tracking.py)
  - `test_worker_job_execution_model_persistence`: Verified database model persistence and querying.
  - `test_autonomous_worker_execution_helpers`: Verified `log_target_execution`, `get_executed_targets`, and `clear_target_executions`.
  - `test_fact_extraction_deduplication_and_no_loop`: Verified that pages are sequentially processed and never re-selected on subsequent cycles.
  - `test_fact_extraction_zero_statements_logged_as_skipped`: Verified that pages yielding 0 statements are recorded as `skipped` and not re-executed.
  - `test_job_execution_api_endpoints`: Verified REST API execution inspection and clearing.
- Full Suite Verification:
  - `uv run pytest tests/test_worker_job_execution_tracking.py`: **5 passed in 5.14s**.
  - `uv run pytest tests/test_taxonomic_fact_extraction.py tests/test_jobs_framework_and_notifications.py`: **20 passed in 16.04s**.
  - `uv run python build.py`: **273 passed in 264.65s (100% clean)**.
