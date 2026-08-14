# Sprint Tracker: Ingestion Job-Queue & PostgreSQL Migration

This document serves as the master checklist and progress tracker for the planned sprints to implement the PostgreSQL/SQLAlchemy migration and the job-queue pipeline refactor.

## Sprints Checklist

### [x] Sprint 1: Dev Environment & Baseline Migrations (Issue #37) -> [Details](./sprint_1_dev_env.md)
* **Goal**: Establish a local PostgreSQL container, baseline schema documentation, and Alembic migrations deployment scripts.
* **Sub-Issues to Resolve**:
  - `[x]` Sub-Issue 0: DevContainer PostgreSQL & pgvector Setup (Issue #38)
  - `[x]` Sub-Issue 1: Database Schema Docs & SQLite baseline (Issue #39)
  - `[x]` Sub-Issue 2: Alembic Baseline Migration & Deploy Scripts (Issue #40)

### [/] Sprint 2: SQLAlchemy ORM & pgvector Searches (Issue #41) -> [Details](./sprint_2_orm_pgvector.md)
* **Goal**: Map declarative ORM models and transition embedding vector queries to use `pgvector`.
* **Sub-Issues to Resolve**:
  - `[/]` Sub-Issue 3: pgvector Extension & Embeddings Refactor (Issue #42)
  - `[/]` Sub-Issue 4: SQLAlchemy ORM Schema mapping (Issue #43)
  - `[/]` Sub-Issue 5: Database Session & Driver Abstraction (Issue #44)

### [ ] Sprint 3: Core Database Access Refactoring & Migration Utility (Issue #45) -> [Details](./sprint_3_core_refactor.md)
* **Goal**: Replace direct `sqlite_utils` table queries with ORM queries and implement a sqlite-to-postgres migrator.
* **Sub-Issues to Resolve**:
  - `[ ]` Sub-Issue 6: Database Access Refactoring (Issue #46)
  - `[ ]` Sub-Issue 7: SQLite-to-PostgreSQL Data Ingest Utility (Issue #47)

### [ ] Sprint 4: Unified Ingestion Sources Schema & Queue Processor (Issue #48) -> [Details](./sprint_4_job_queue.md)
* **Goal**: Refactor the linear ingestion flow into a database-driven queue processor driven by a top-level `sources` schema.
* **Sub-Issues to Resolve**:
  - `[ ]` Sub-Issue 8: Top-Level Ingestion Sources & Processing Registry Schema (Issue #49)
  - `[ ]` Sub-Issue 9: State-Driven Job Queue Processor Daemon (Issue #50)

### [ ] Sprint 5: WebSocket Ingestion, Docling, & Cache Settings (Issue #51) -> [Details](./sprint_5_docling_ollama.md)
* **Goal**: Add WebSocket file upload chunking, integrate `docling-serve` parsing, and cache Ollama chats.
* **Issues & Sub-Issues to Resolve**:
  - `[ ]` Issue #36: Add `docling-serve` Support and File Imports
  - `[ ]` Sub-Issue 10: WebSocket File Ingestion & Drag-and-Drop Ingestion UI (Issue #52)
  - `[ ]` Sub-Issue 11: Standalone Ollama Chat Caching, Prompts Logs, & Settings Management (Issue #53)
