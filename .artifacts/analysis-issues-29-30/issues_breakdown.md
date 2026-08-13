# Issue Breakdown Analysis: #29 and #30

This document breaks down the remaining scope of **Issue #29** (Import Process Needs Major Refactor) and **Issue #30** (PostgreSQL | SQLAlchemy Support) into actionable, granular sub-issues.

---

## Breakdown of Issue #29: Ingestion Pipeline & Job-Queue Refactor

The remaining portions of Issue #29 (excluding the completed duplicate checks and video download triggers) focus on transitioning the linear import process to a background job-queue architecture, handling large file drops via WebSockets, caching Ollama logs/prompts, and exposing settings in the Admin panel.

### 1. [Sub-Issue] Job Queue Schema & State Management
* **Parent**: #29
* **Description**: Create a database structure to model import tasks.
* **Requirements**:
  - Define a new `job_queue` table with columns: `id` (int PK), `url_or_filepath` (text), `state` (text: `pending`, `fetching`, `extracting`, `embedding`, `completed`, `failed`), `options` (text/JSON configurations like collection IDs, target type, download video), `attempts` (int), `error_log` (text), `created_at` (text), `updated_at` (text).
  - Add helper functions in `src/kb_web/db.py` to enqueue new tasks and update existing job states.
  - Implement basic API endpoints to retrieve active/failed jobs to expose pipeline health status.

### 2. [Sub-Issue] Background Job Queue Processor Daemon
* **Parent**: #29
* **Description**: Implement a worker thread/service to execute the queue in the background.
* **Requirements**:
  - Implement a background loop or worker thread service (e.g. in `server.py` or as a separate daemon) that polls the `job_queue` table for `pending` or `failed` tasks (with exponential backoff retries).
  - Decouple the ingestion steps into vertical, self-contained processing functions:
    1. HTML/YouTube fetch
    2. Ollama wiki summary generation
    3. Tag extraction
    4. Text chunking & Gemma embeddings generation
    5. Video offline downloader
  - Hook up Gotify notification hooks to dispatch alerts containing exact error traces and recovery hints if a step in the pipeline fails.

### 3. [Sub-Issue] WebSocket File Ingestion & Drag-and-Drop Ingestion UI
* **Parent**: #29
* **Description**: Support large document uploads (250MB+) using WebSockets for stable progress transmission.
* **Requirements**:
  - Add a drag-and-drop file upload target area to the Import UI (`url_import.j2.html`).
  - Implement a FastAPI WebSocket route `/api/import/file/upload` to receive chunks of large files.
  - Emit real-time upload progress indicators back to the client-side UI before saving the original file on disk and enqueuing a docling-serve job.

### 4. [Sub-Issue] Standalone Ollama Chat Caching, Prompts Logs, & Settings Management
* **Parent**: #29
* **Description**: Create a logging cache and advanced settings configuration panel for Ollama model interactions.
* **Requirements**:
  - Design an `ollama_chat_cache` table storing `prompt_hash` (PK), `raw_prompt`, `raw_response_json`, `model_used`, and `settings_applied`.
  - Refactor all Ollama Client calls to search this cache before executing remote queries.
  - Expose advanced kwargs for `ollama.chat` in the Admin Dashboard, loading parameters dynamically from the database and using defaults if empty (omitting empty keys in python dict).
  - Expose a prompt history view left-joined against generated responses in the Admin Portal.

---

## Breakdown of Issue #30: PostgreSQL & SQLAlchemy Support

Issue #30 requires transitioning the storage layer from `sqlite-utils` to SQLAlchemy. Since `sqlite-utils` uses dictionary-based row mutations, database access must be abstracted to ORM models supporting both SQLite and PostgreSQL dialects.

### 5. [Sub-Issue] SQLAlchemy ORM Schema Definition
* **Parent**: #30
* **Description**: Declare SQLAlchemy models for all database tables and views.
* **Requirements**:
  - Translate the active SQLite schema definitions (including `fetched_pages`, `page_versions`, `site_wikis`, `youtube_videos`, `collections`, `collection_items`, `links`, `settings_ollama`, etc.) into SQLAlchemy Declarative Base models.
  - Map foreign key constraints, indexes, and unique constraints.
  - Configure views (`vault_master`, `repo_master`, `valid_repo_files`, etc.) as read-only SQLAlchemy models or mapping wrappers.

### 6. [Sub-Issue] Database Session & Driver Abstraction
* **Parent**: #30
* **Description**: Enable configuration-driven dialect selection supporting SQLite and PostgreSQL backends.
* **Requirements**:
  - Add `DATABASE_URL` (e.g. `postgresql://...`) to `Config`.
  - Implement SQLAlchemy connection engines, thread-scoped session managers, and transaction lifecycle middleware in `base.py`.
  - Integrate PostgreSQL connection pooling features (`pool_size`, `max_overflow`).

### 7. [Sub-Issue] Database Access Refactoring
* **Parent**: #30
* **Description**: Refactor all direct SQLite query instances to ORM methods.
* **Requirements**:
  - Systematically replace dictionary-based tables syntax (e.g. `db["fetched_pages"].upsert(...)` or `db.execute(...)`) with type-safe SQLAlchemy session queries across the router endpoints (`pages.py`, `admin.py`, `links.py`, `collections.py`, `cli_api.py`, `api.py`).

### 8. [Sub-Issue] Schema Migration Engine (Alembic Integration)
* **Parent**: #30
* **Description**: Add migrations versioning framework to manage database upgrades.
* **Requirements**:
  - Initialize Alembic within the repository.
  - Support automatic migration script generation by comparing active SQLAlchemy models against the targeted database schema.
  - Implement programmatic migrations check on server startup.

### 9. [Sub-Issue] SQLite-to-PostgreSQL Data Ingest Utility
* **Parent**: #30
* **Description**: Build a database translation CLI command to import SQLite dump rows to PostgreSQL.
* **Requirements**:
  - Create a new CLI command `kb-cli db migrate-to-postgres` that reads all tables from a local `kb.db` file, maps schemas, and bulk-inserts records into the configured PostgreSQL target database.
