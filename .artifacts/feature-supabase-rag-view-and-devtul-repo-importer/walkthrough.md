# Walkthrough: Unified Supabase RAG View & devtul Repo Importer

This document walks through the design, implementation, verification, and usage of the two key additions in version 0.5.6:
1. **Unified Supabase RAG View (`vw_rag_items`)**
2. **First-Class Git Repository Importer (`devtul` `rpr` Engine)**

---

## 1. Unified Supabase RAG View (`vw_rag_items`)

### Architecture & Design
To support direct querying from a remote Supabase instance (configured with a Foreign Data Wrapper / FDW over PostgreSQL), `kb-web` provides a consolidated view combining 5 content sources into a uniform RAG candidate schema:
- `chunk_embeddings` (source_type = 'articles'): Chunks derived from ingested web pages.
- `chunk_embeddings` (source_type = 'notes'): Chunks derived from Obsidian vault notes.
- `youtube_videos`: Ingested YouTube videos with descriptions and transcripts.
- `article_embeddings`: Fallback whole-article embeddings for pages without sub-chunks.
- `workspace_files`: Persistent multi-file workspace source code and scripts.

### Schema Contract
| Column | Type | Description |
|---|---|---|
| `id` | `VARCHAR` | Unique identifier (e.g. `page_chunk:url:0`, `note_chunk:url:0`, `video:id`, `ws_file:id`) |
| `source_type` | `VARCHAR` | Source category: `web_page`, `note`, `video`, `workspace` |
| `title` | `VARCHAR` | Title or label of source item |
| `content_chunk`| `TEXT` | RAG retrieval context payload / snippet |
| `url` | `VARCHAR` | Canonical URL or resource URI |
| `embedding` | `VECTOR(768)` or `TEXT` | Gemma embedding vector (or JSON array) |
| `metadata` | `JSONB` or `TEXT` | Source metadata (tags, vault, folder, language, timestamps) |

### Migration & Startup Initialization
- Migration file: [3d4e5f6a7b8c_add_unified_rag_view.py](file:///C:/src/kb-web/migrations/versions/3d4e5f6a7b8c_add_unified_rag_view.py)
- Startup check: Handled in [models_orm.py:ensure_views_and_indexes()](file:///C:/src/kb-web/src/kb_web/models_orm.py) with dual dialect support (PostgreSQL `CREATE OR REPLACE VIEW` with `jsonb_build_object`, SQLite fallback using `json_object`).

### REST API
- `GET /api/rag/items`: Supports `source_type` filtering, keyword queries, and pagination.

---

## 2. Git Repository & Codebase Importer (`devtul` Engine)

### Submodule Integration
- Submodule mapped at `packages/devtul` (`https://github.com/willmo103/devtul.git`).
- Pytest configuration isolated via `norecursedirs = [".venv", "packages", ...]` in [pyproject.toml](file:///C:/src/kb-web/pyproject.toml).

### Synthesis Engine (`src/kb_web/repo_importer.py`)
Clones repositories to temporary scratch storage using `git clone --depth <N>` and synthesizes a high-fidelity Markdown document containing:
1. **Header & Metadata Table**: Branch, commit hash, commit message, author, remote origin.
2. **ASCII Tree**: Full visual hierarchy formatted with `├──` and `└──` branches.
3. **Summary Table**: File path, line counts, byte sizes, and recognized syntax.
4. **Source Code Blocks**: Syntax-highlighted code blocks for every text file, respecting ignore patterns and `.gitignore`.

### Interfaces
- **Web UI**: In `/import` under the tab **"💻 Git Repo / Codebase"**. Includes real-time progress indicators, depth selectors, and filter globs.
- **REST API**: `POST /api/import/repo` accepting `{ "repo_url", "depth", "collection_id", "match", "exclude" }`.
- **CLI**: `kb-web-cli import-repo <url> [--depth 1] [--collection <id>] [--match <globs>] [--exclude <globs>]`.

---

## 3. Verification & Test Results
- Unit test suite: [tests/test_rag_view_and_repo_importer.py](file:///C:/src/kb-web/tests/test_rag_view_and_repo_importer.py) (6/6 tests passing).
- UI component templates: Verified 24/24 templates with 0 warnings.
