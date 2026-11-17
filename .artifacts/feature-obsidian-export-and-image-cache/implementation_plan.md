# Implementation Plan: Obsidian Vault ZIP Export & Database-Backed Image Caching

## 1. Objectives
1. **Obsidian Vault ZIP Export Mode**:
   - Export all ingested web articles and YouTube transcripts (explicitly excluding `note://` Obsidian notes) into a single downloadable ZIP archive containing:
     - `_sources/<site>/<dot.joined.path>.md` with YAML frontmatter (`date_scraped`, `version`, `url`, `site`).
     - `articles/<collection>/<site>/<title>.md` containing the generated AI wiki with YAML frontmatter (`date_scraped`, `site`, `model_used`, `url`, `collection`, `tags`), Obsidian-formatted inline `#tags` below `# Title`, source link to `/_sources/...`, and local backlinks to nearest embedding neighbors under `/reference/articles/...`.
     - Automatic conflict resolution for duplicate article titles via LLM re-titling (`resolve_title_conflict`) with deterministic fallback.
2. **Database-Backed Image Caching & Public Asset Sync**:
   - New ORM model `CachedImage` (`cached_images` table): `image_hash` (SHA-256 PK), `original_url`, `content_type`, `data` (`LargeBinary`), `size_bytes`, `created_at`.
   - Public asset directory `src/kb_web/static/cached_images/` served at `/static/cached_images/<hash>.<ext>` and synced from DB.
   - Image extraction, download, hashing, DB storage, disk sync, and markdown/HTML link replacement during `fetch_url` / ingestion (`src/kb_web/image_cache.py`).
   - Lazy backfill endpoint (`POST /api/pages/cache-images`) triggered automatically when expanding "View Original Scraped Markdown Content" in `view_page.j2.html` (and callable directly).

---

## 2. Architecture & File Changes

### A. Database & ORM (`src/kb_web/models_orm.py`, `src/kb_web/scripts/deploy_migrations.py`)
- Add `CachedImage(Base)` ORM model in `models_orm.py` with `image_hash` (PK), `original_url`, `content_type`, `extension`, `data` (`LargeBinary`), `size_bytes`, `created_at`.
- Add `CREATE TABLE IF NOT EXISTS cached_images (...)` DDL in `deploy_migrations.py` and `db.py` `init_db` / `Base.metadata.create_all`.

### B. Image Caching Engine (`src/kb_web/image_cache.py`)
- `cache_image_from_url(url, session, base_url=None) -> Optional[str]`:
  - Validates URL (SSRF check), downloads image bytes via `httpx` (with size limit e.g. 10MB and content-type `image/*` validation).
  - Computes SHA-256 hash of binary data.
  - Upserts into `CachedImage` table if not already present.
  - Writes `<hash>.<ext>` to `static/cached_images/` if missing on disk.
  - Returns `/static/cached_images/<hash>.<ext>`.
- `cache_and_rewrite_markdown_images(md_content, base_url, session) -> tuple[str, int]`:
  - Finds markdown image links `![alt](url)` and HTML `<img src="url">` pointing to external `http(s)://` URLs.
  - Calls `cache_image_from_url` and rewrites URLs in place to `/static/cached_images/<hash>.<ext>`.
- `sync_cached_images_to_disk(session) -> int`:
  - Ensures all `CachedImage` records in DB are materialized in `static/cached_images/`.

### C. Ingestion & Lazy Backfill Integration (`src/kb_web/utils.py`, `src/kb_web/routers/pages.py`, `src/kb_web/templates/view_page.j2.html`)
- Hook `cache_and_rewrite_markdown_images` into `save_page` / `save_fetched_page_to_db` (or `pipeline.py` after `fetch_url`) when `cache_images_on_import` is enabled (configurable in `config.py` / Admin Portal, default `True`).
- Add `POST /api/pages/cache-images` in `routers/pages.py` accepting `{"url": ...}`, running `cache_and_rewrite_markdown_images` on `FetchedPage.md_content` (if not frozen, or updating cached image links cleanly), saving to DB, and returning `{ "updated": bool, "cached_count": int, "rendered_html": ... }`.
- In `templates/view_page.j2.html`, attach an `ontoggle` listener to the "View Original Scraped Markdown Content" `<details>` element that triggers `POST /api/pages/cache-images` if external image URLs are detected and hot-swaps the rendered container HTML.

### D. Obsidian Vault ZIP Export (`src/kb_web/obsidian_export.py`, `src/kb_web/routers/admin.py`, `src/kb_web/cli.py`, `src/kb_web/templates/admin.j2.html`)
- Create `src/kb_web/obsidian_export.py`:
  - Query all `FetchedPage` where `not url.startswith("note://")` (includes articles & YouTube transcripts).
  - Fetch latest `PageVersion` count/version per URL, latest `WikiVersion` per URL (content + `model_name`), `Collection` / `CollectionItem` mappings, and `ArticleEmbedding` / `ChunkEmbedding` vectors.
  - **`_sources/<site>/<dot_joined_path>.md`**:
    - `<site>` = `urlparse(url).netloc` (sanitized).
    - `<dot_joined_path>` = `'.'.join([p for p in urlparse(url).path.split('/') if p]) or 'index'` (plus query hash if needed for uniqueness, `.md` suffix).
    - Frontmatter: `url`, `site`, `date_scraped`, `version`.
    - Body: `md_content`.
  - **`articles/<collection>/<site>/<title>.md`**:
    - `<collection>` = collection title (or `Uncategorized`).
    - `<site>` = `urlparse(url).netloc`.
    - Title conflict resolution: track used `(collection, site, title_slug)` paths; if duplicate, call Ollama model (`resolve_title_conflict`) to generate a distinct title, falling back to `Title (<short_hash>)` if Ollama is unavailable.
    - Frontmatter: `title`, `url`, `site`, `collection`, `date_scraped`, `model_used`, `tags`.
    - Header below `# <Title>`: Obsidian inline tags (e.g. `#tag-one #tag-two` formatted safely with slashes/hyphens, no spaces).
    - Source link: `[Source Markdown](/_sources/<site>/<dot_joined_path>.md)` (and Obsidian wikilink option).
    - Nearest Neighbor Backlinks: compute cosine similarity across `ArticleEmbedding` (or averaged `ChunkEmbedding`) excluding `note://` URLs, select top-K neighbors (configurable `obsidian_export_neighbor_k`, default 5), and render local links under `## Related Articles` pointing to `/reference/articles/<collection>/<site>/<neighbor_title>.md`.
- Expose `GET /admin/export/obsidian` in `routers/admin.py` returning a downloadable `StreamingResponse` / `FileResponse` ZIP (`kb_obsidian_vault_YYYYMMDD_HHMMSS.zip`).
- Add **"Export Obsidian Vault (ZIP)"** button in `templates/admin.j2.html`.
- Add `kb-web-cli export obsidian` command in `src/kb_web/cli.py`.

### E. Configuration Transparency (`src/kb_web/config.py`)
- Expose `cache_images_on_import` (bool, default `True`), `image_cache_max_bytes` (int, default `10485760`), and `obsidian_export_neighbor_k` (int, default `5`) in `Config` and `/admin`.

---

## 3. Verification Plan
1. Unit tests in `tests/test_obsidian_export_and_image_cache.py`:
   - Test `CachedImage` DB persistence, SHA-256 deduplication, `static/cached_images/` disk sync, and markdown image URL rewriting.
   - Test lazy backfill `POST /api/pages/cache-images` endpoint.
   - Test Obsidian ZIP export structure (`_sources/`, `articles/`), exclusion of `note://` URLs, `<dot.joined.path>.md` naming, frontmatter fields (`date_scraped`, `version`, `site`, `model_used`), Obsidian `#tag` header formatting, title conflict resolution (mocked LLM + fallback), and nearest-neighbor backlinks under `/reference/articles/...` and `/_sources/...`.
2. Run `uv run python build.py` (full `pytest` suite + `uv sync`).
3. Run `ui-component-uat-check` (`verify_ui_templates.py`).
4. Update `CHANGELOG.md`, `README.md`, `GEMINI.md`, commit, merge to `development` and `production`, and push.
