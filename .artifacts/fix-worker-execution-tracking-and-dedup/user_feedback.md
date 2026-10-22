# User Feedback & Request Log

## Request Overview
- **Date**: 2026-10-22
- **Branch**: `fix/worker-execution-tracking-and-dedup`
- **Issue**: Autonomous worker agent is looping on one item (`ssd1306.py`), running fact extraction repeatedly (every 15–20 seconds) and producing continuous success notifications for the same target item.
- **User Instruction**:
  > "agent is still looping on one item need to track executions and targets to avoid duplicates if filtering wont work"

## Key Observations & Diagnostics
1. **Current Failure Mode**:
   - `_run_fact_extraction` relies on subquery filtering `FetchedPage.url.not_in(select(ContextStatementORM.source_uri))`.
   - If SQL `NOT IN` encounters NULLs, or if the stored `source_uri` format differs from `FetchedPage.url`, or if a run extracts 0 statements / skips, the page is not excluded by the subquery and is picked again on the very next scheduler tick.
   - The worker lacks an execution tracking log or record of which targets (URLs) have been processed by which server jobs.
2. **User's Requirement**:
   - Add persistent target-level execution tracking across worker jobs (e.g. `WorkerJobExecution` model).
   - In `AutonomousWorker`, track which targets have been executed per job, and filter out already processed targets even if downstream artifact filtering fails.
   - Maintain an in-memory dedup cache (`_recent_targets`) to prevent duplicate runs within the same scheduler loop / session.
   - Support marking executions as `success`, `skipped`, `failed` with item counts and timestamps.
