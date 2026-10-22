# Implementation Plan - Worker Target Execution Tracking & Deduplication

## 1. Problem Statement
The autonomous server worker (`AutonomousWorker` in `src/kb_web/worker.py`) is repeatedly selecting and processing the exact same target item (`ssd1306.py`, or similar library items) every 15–20 seconds, resulting in repeated notifications and infinite processing loops.
Filtering based solely on downstream artifact presence (such as `FetchedPage.url.not_in(select(ContextStatementORM.source_uri))`) can fail due to:
- SQL `NOT IN` quirks when NULLs are present in subqueries.
- Format or protocol differences between `FetchedPage.url` and extracted statement `source_uri`.
- Extraction producing 0 statements or empty outputs (which leaves the page un-indexed by statements and perpetually candidate for extraction).
- Absence of a persistent job execution log that records target-level runs across all worker jobs.

## 2. Proposed Architecture & Solution

### A. Persistent `WorkerJobExecution` ORM Model
In [`src/kb_web/models_orm.py`](file:///c:/src/kb-web/src/kb_web/models_orm.py):
Define `WorkerJobExecution` representing an execution record for a specific job and target:
- `id`: Integer primary key, autoincrement.
- `job_id`: String, indexed (e.g., `"fact_extraction"`, `"wiki_curation"`, `"tag_curation"`, `"embedding_refresh"`).
- `target_id`: String, indexed (target page URL or resource ID).
- `status`: String (`"success"`, `"skipped"`, `"failed"`), indexed.
- `items_count`: Integer, default 0 (e.g. number of statements, tags, or summaries produced).
- `error_message`: Text, nullable=True.
- `executed_at`: String (ISO 8601 UTC timestamp).
- Composite index: `Index("ix_worker_job_target", "job_id", "target_id")`.

### B. Target Execution Tracking in `AutonomousWorker`
In [`src/kb_web/worker.py`](file:///c:/src/kb-web/src/kb_web/worker.py):
1. **In-Memory Target Cache**:
   - `self._recent_targets: Dict[str, Set[str]]` tracks targets processed during the current runtime session.
2. **Helper Methods**:
   - `log_target_execution(job_id: str, target_id: str, status: str, items_count: int = 0, error_message: Optional[str] = None)`
   - `is_target_executed(job_id: str, target_id: str, statuses: Tuple[str, ...]) -> bool`
3. **Hardened Candidate Selection**:
   - In `_run_fact_extraction`:
     - Exclude targets where `WorkerJobExecution.job_id == "fact_extraction"` and `status IN ("success", "skipped")`.
     - Exclude targets present in `self._recent_targets["fact_extraction"]`.
     - Harden subquery: ensure `ContextStatementORM.source_uri.isnot(None)`.
   - On completion:
     - If `len(statements) > 0`: log `status="success"`, `items_count=len(statements)`.
     - If `len(statements) == 0`: log `status="skipped"`, `items_count=0` (guarantees items yielding 0 facts do not loop).
     - If failed: log `status="failed"`, `error_message=str(e)` and add to in-memory cache to prevent tight error re-runs.
4. **Generalization Across Worker Jobs**:
   - Apply target execution tracking and logging to:
     - `_run_wiki_curation`
     - `_run_tag_curation`
     - `_run_embedding_refresh`

### C. Inspection & Management Endpoints
In [`src/kb_web/routers/worker.py`](file:///c:/src/kb-web/src/kb_web/routers/worker.py):
- `GET /api/jobs/{job_id}/executions`: Retrieve recent execution history for a job.
- `POST /api/jobs/{job_id}/executions/clear`: Clear target executions for a job if re-processing is desired.

### D. Automated Unit Tests
In `tests/test_worker_job_execution_tracking.py`:
- Verify `WorkerJobExecution` model persistence and querying.
- Verify that `_run_fact_extraction` logs execution and will not re-select the same target on subsequent cycles.
- Verify that zero-statement extractions are logged as `skipped` and do not loop.
- Verify in-memory deduplication cache.
- Verify execution clearance endpoint.

## 3. Verification & Gated Pre-Commit Checks
- Run `uv run pytest tests/test_worker_job_execution_tracking.py`
- Run full pytest test suite: `uv run pytest`
- Run build pipeline: `uv run python build.py`
- Update `CHANGELOG.md` under `[0.5.11]`
