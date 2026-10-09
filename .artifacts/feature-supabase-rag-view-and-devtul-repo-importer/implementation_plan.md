# Implementation Plan: Unified Supabase RAG View & devtul Repository Importer

**Branch**: `feature/supabase-rag-view-and-devtul-repo-importer`  
**Date**: October 09, 2026  
**Status**: Ready for User Review

---

## 1. Overview & Architecture

This feature delivers two interconnected capabilities:
1. **Unified Supabase RAG View (`vw_rag_items`)**:
   - Creates an abstracted, multi-source RAG view in PostgreSQL (with SQLite fallback compatibility) that maps across all content sources that can act as an "article":
     - Markdown notes (`notes`)
     - Ingested web pages & documents (`fetched_pages`)
     - YouTube video transcripts & metadata (`youtube_videos`)
     - Code repositories (`repo://`)
     - Coding workspaces & project files (`workspaces`, `workspace_files`)
   - Emits the standard Supabase RAG format: `(id, source_type, title, content_chunk, url, embedding, metadata JSONB)`.
   - Designed for direct consumption via foreign server / Foreign Data Wrapper (FDW) inside Supabase for pgvector similarity queries and edge functions.
2. **`devtul` `rpr` Repository & Code Importer Engine**:
   - Integrates the exact logic from `devtul`'s `RprCommand` and `rpr clone` pipeline.
   - Shallow clones Git repositories into an ephemeral sandbox, scans file trees respecting git-ignore and pattern matches, generates ASCII tree hierarchies, git metadata tables, per-file attribute tables, and syntax-highlighted codeblocks.
   - Persists the synthesized markdown representation into `fetched_pages` as a first-class knowledge article, immediately chunking and generating embeddings for full RAG indexing.
   - Exposes the importer via REST API (`POST /api/import/repo`), Web UI import portal (`/import`), and CLI command (`kb-web-cli import-repo`).

---

## 2. Component Breakdown

### A. Database Schema & Migration (`src/kb_web/models_orm.py`, `migrations/`)
- **Alembic Migration (`migrations/versions/..._add_unified_rag_view.py`)**:
  - Creates PostgreSQL view `vw_rag_items` uniting chunk embeddings and article records across `fetched_pages`, `notes`, `youtube_videos`, and `workspaces`.
  - Exposes columns:
    - `id`: Unique composite identifier (`chunk:page:...`, `chunk:note:...`, `article:page:...`, `workspace:file:...`).
    - `source_type`: Distinguisher (`'web_page'`, `'note'`, `'youtube_video'`, `'repo'`, `'document'`, `'workspace'`).
    - `title`: Unified entity title.
    - `content_chunk`: Searchable textual content chunk or full markdown content.
    - `url`: Canonical locator URL (`https://...`, `note:...`, `repo:...`, `workspace://...`).
    - `embedding`: Vector representation (`vector(768)`).
    - `metadata`: Comprehensive JSONB containing tags, collections, timestamps, `is_frozen`, creators, vault/folder attributes, and chunk metrics.
- **ORM & SQLite Compatibility (`models_orm.py`)**:
  - Update `ensure_views_and_indexes()` to safely maintain `vw_rag_items` in both PostgreSQL and SQLite environments.

### B. Repository Representation Engine (`src/kb_web/repo_importer.py`)
- **Exact `devtul` `rpr` Pipeline**:
  - Clone runner using `git.Repo.clone_from` with shallow depth option (`--depth 1` default).
  - Directory scanner using file filter options, Unix glob matching (`--match`), and exclude patterns (`--exclude`).
  - Git metadata extractor (commit, branch, author, remote origin).
  - ASCII tree generator for file hierarchy visualization.
  - Markdown builder with YAML frontmatter, Git tables, file metadata tables, and language-tagged fenced code blocks.
- **Article & RAG Ingestion Pipeline**:
  - Creates `FetchedPage` record with canonical URL `repo://{owner}/{repo}` or original HTTPS git URL.
  - Automatically runs chunking (`chunk_text`) and vector embeddings generation so the repository is instantly searchable via vector search and available in `vw_rag_items`.

### C. API & Web UI Integration (`src/kb_web/routers/`, `templates/`)
- **REST Endpoints (`src/kb_web/routers/rest_api.py` / `pages.py`)**:
  - `POST /api/import/repo`: Ingests git repository URL with parameters (`repo_url`, `depth`, `collection_id`, `match`, `exclude`).
  - `GET /api/rag/items`: Query endpoint returning data directly from `vw_rag_items` with filtering by `source_type` and pagination.
- **Web UI (`src/kb_web/templates/url_import.j2.html`)**:
  - Add "💻 Git Repository / Codebase" tab/form allowing one-click cloning and ingestion of GitHub/GitLab repositories.

### D. CLI Client Command (`kb-web-cli/src/kb_web_cli/main.py`)
- Add CLI command `kb-web-cli import-repo <url>`:
  - Options: `--depth`, `--collection`, `--match`, `--exclude`.
  - Can run representation locally or trigger remote server ingestion and print imported article status.

---

## 3. Verification Plan

### Automated Tests
- Create dedicated test suite `tests/test_rag_view_and_repo_importer.py`:
  - `test_vw_rag_items_view_created_and_queryable`: Verifies `vw_rag_items` returns notes, pages, and chunk embeddings with valid JSONB metadata and columns.
  - `test_repo_importer_build_markdown`: Tests markdown representation extraction (Git metadata, tree structure, codeblocks).
  - `test_api_import_repo_endpoint`: Tests `POST /api/import/repo` with mock git repository, verifying article creation and chunk embeddings.
  - `test_rag_items_api_endpoint`: Tests `GET /api/rag/items` query filtering.
- Full test pass: `uv run pytest` (100% pass across all existing 155 tests + new tests).
- UI template check: `verify_ui_templates.py` with 0 warnings.
- Build check: `uv run python build.py`.
