# Implementation Plan: Fix Transcript Wiki Ingestion Hangs & Remove Cron Job Subsystem

This plan details the technical solution to prevent hangs during YouTube transcript wiki generation and outlines the complete excision of the cron job scheduling subsystem.

---

## User Review Required

> [!WARNING]
> **Database Table Dropping**:
> To completely clean up cron job infrastructure, we will drop the legacy tables `cron_jobs` and `cron_job_runs` during the next startup initialization in `src/kb_web/db.py`. Any existing cron schedules and history logs will be removed.

---

## Proposed Changes

### Ingestion & Utilities

#### [MODIFY] [utils.py](file:///c:/src/kb-web/src/kb_web/utils.py)
- **Optimize Reasoning Latency for Chunk Summaries**:
  - In `extract_wiki_content`, pass `think=False` for all intermediate chunk chat calls. Only the final compilation call should respect `think=config.ollama_think` (saving significant CPU/GPU reasoning latency).
- **Optimize Tags Extraction**:
  - In `extract_tags_content`, set `think=False` since category tag extraction is a simple classification task and does not require reasoning latency.

---

### Ingest streaming endpoint

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- **Prevent Event Loop Blocking**:
  - In `handle_url_import`, the async generator `stream_ingestion` executes synchronous blocking calls (`fetch_url`, `extract_wiki_content`, `extract_tags_content`, `update_article_embedding`, `generate_gemma_embeddings_for_page`).
  - Wrap these blocking calls inside `await run_in_threadpool(...)` from `fastapi.concurrency` so the FastAPI event loop is not blocked, allowing keep-alives and progress logs to stream to the browser in real-time.

---

### Removing Cron Job Subsystem

#### [MODIFY] [db.py](file:///c:/src/kb-web/src/kb_web/db.py)
- Remove `cron_jobs` and `cron_job_runs` table initialization blocks.
- Add code in `init_db` to drop `cron_jobs` and `cron_job_runs` tables if they exist in the database.

#### [DELETE] [cron_scheduler.py](file:///c:/src/kb-web/src/kb_web/cron_scheduler.py)
- Delete the scheduler task runner entirely.

#### [DELETE] [cron.py](file:///c:/src/kb-web/src/kb_web/routers/cron.py)
- Delete the cron administration router.

#### [DELETE] [cron_jobs.j2.html](file:///c:/src/kb-web/src/kb_web/templates/cron_jobs.j2.html)
- Delete the cron task management dashboard template.

#### [DELETE] [view_cron_job.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_cron_job.j2.html)
- Delete the individual cron job details template.

#### [MODIFY] [server.py](file:///c:/src/kb-web/src/kb_web/server.py)
- Remove references and imports of `cron_scheduler` and the `cron` router.

#### [MODIFY] [graph.py](file:///c:/src/kb-web/src/kb_web/routers/graph.py)
- Remove references and checks for `cron://` virtual URLs.

#### [MODIFY] [collections.py](file:///c:/src/kb-web/src/kb_web/routers/collections.py)
- Optimize collection suggestion LLM call on line 756 to pass `think=False`.

---

## Verification Plan

### Automated Tests
- Run `C:\Users\Will\.local\bin\uv.exe run pytest` to ensure no imports or dependencies are broken.
- Add a new unit test in `tests/test_server.py` verifying that no cron-related tables are created in the database and no cron routes are exposed.

### Manual Verification
- Ingest a YouTube URL page with a long transcript. Verify that progress logs stream in real-time to the browser without freezing at `20%` or `55%`, and that wiki generation completes successfully.
- Verify that navigating to `/admin/cron` returns a 404.
