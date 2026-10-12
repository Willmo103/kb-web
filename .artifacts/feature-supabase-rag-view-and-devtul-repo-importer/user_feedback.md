# User Feedback Log

**Date**: October 09, 2026  
**Branch**: `feature/supabase-rag-view-and-devtul-repo-importer`  
**Source**: User discussion on Supabase FDW integration, RAG view architecture, and devtul repository importer.

---

## 1. Recorded User Feedback & Requirements

1. **Stale Branch `sprint-4-5` Resolution**:
   - The user confirmed that the stale `sprint-4-5` branch should be set aside / abandoned rather than merged, as it diverged too far and its implementation (using Docling for general document ingestion) was overcomplicated compared to lighter, more effective markdown-based approaches.
2. **Unified Supabase RAG View (`vw_rag_sources` / `vw_rag_items`)**:
   - The user has mapped this application's PostgreSQL database as a foreign server inside a Supabase instance.
   - Requirement: Create an abstracted RAG view over all sources that *could* become an article in `kb-web`:
     - Markdown notes (`notes` table)
     - Web pages, articles, and video transcripts (`fetched_pages` and `youtube_videos` tables)
     - In-browser code workspaces & project files (`workspaces` and `workspace_files` tables)
   - Schema target: Standard Supabase RAG format:
     - `id`: Unique identifier string across sources (`TEXT`)
     - `source_type`: Distinguishing source discriminator (`'note'`, `'web_page'`, `'youtube_video'`, `'workspace'`, `'repo'`)
     - `title`: Common title string (`TEXT`)
     - `content_chunk`: Unified chunk text / article content (`TEXT`)
     - `url`: Canonical resource locator URL (`TEXT`)
     - `embedding`: Vector representation (`vector(768)`)
     - `metadata`: JSONB containing shared metadata (tags, collections, timestamps, is_frozen, authors, vaults, file counts)
3. **`devtul` `rpr` Code & Repository Importer**:
   - Extract logic **exactly** from `devtul`'s `rpr` command (`dt rpr [PATH]` and `dt rpr clone <REPO_URL> --md`).
   - Use this as the primary pipeline for importing GitHub/Git repositories and local source code directories as rich markdown articles into `kb-web`.
   - The representation pipeline will generate:
     - Git metadata table (branch, commit hash, commit count, remote origin, author)
     - ASCII directory tree structure
     - Per-file metadata table (relative path, created date, modified date, byte size)
     - Code block syntax highlighting with language mapping
   - Expose this importer via:
     - Web App API endpoint (`/api/import/repo` and `/api/import/folder`) and UI import tab
     - CLI client command (`kb-web-cli import-repo <url>` or `--kb` flag integration)
