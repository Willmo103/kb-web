# Issue & Fix Documentation: Ingestion hangs and thread lockups

## Issue 1: YouTube Transcript Wiki Generation Hangs (Reasoning Latency & Event-Loop Block)

### Exact Trigger & Symptom
When importing YouTube URLs with long transcripts, the ingestion progress bar froze at `20%` (fetching) or `55%` (Ollama prompts), and the request eventually timed out or hung the server indefinitely.

### Root Cause
1. **Reasoning Latency Multiplication**: In `extract_wiki_content` (`src/kb_web/utils.py`), transcripts exceeding the maximum length were split into chunks. For each chunk, the LLM chat call was issued with `think=config.ollama_think`. When a reasoning model was active, it thought for up to 90 seconds per chunk. Multiple consecutive chunk requests multiplied this latency, causing hangs.
2. **Event-Loop Starvation**: The async generator `stream_ingestion` in `src/kb_web/routers/admin.py` executed synchronous, blocking CPU-bound and network I/O functions (`fetch_url`, `extract_wiki_content`, etc.) directly on the main event loop. This blocked Starlette/FastAPI from processing any concurrent tasks or yielding keep-alive updates to the browser.

### Resolution
1. **Disabled reasoning for intermediate steps**: Set `think=False` for all intermediate chunk summaries and tag/collection classification calls. Only the final compilation/reasoning step respects `think=config.ollama_think`.
2. **Yielded event-loop execution**: Wrapped all blocking synchronous ingestion operations in `await run_in_threadpool(...)` from `fastapi.concurrency` inside the `stream_ingestion` async generator, letting FastAPI run these tasks in its background thread pool while keeping the main loop responsive.

---

## Issue 2: Thread-Safety Database Locks in Background Tasks

### Exact Trigger & Symptom
Background tasks like "Crawl From Here" or "Download Video Offline" intermittently locked the database or failed with database closure exceptions.

### Root Cause
The main request thread's thread-local `db_handle` (returned by `_get_db()`) was passed into FastAPI `BackgroundTasks`. Background tasks are executed on separate background threadpool threads, causing multiple threads to share and close the same SQLite connection handle.

### Resolution
Removed the `db_handle` parameter from `run_recursive_crawl` and `background_video_downloader` worker routines. Inside the workers, a thread-local SQLite connection is retrieved independently by calling `_get_db()`.
