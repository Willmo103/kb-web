# Architecture Plan: UI Performance Speedup, Pagination, & REST API Overhaul

## Problem & Background

Following the v0.2.0 database migration to PostgreSQL and SQLAlchemy ORM, the web UI experienced significant latency, particularly on the root page (`/` and `/pages`).

Root causes:
1. **Model Hydration of Heavy Content**: `session.query(FetchedPage)` eagerly loads `html_content` (full raw HTML files, 100KB–5MB+ each) and `md_content` for every row, pulling tens to hundreds of megabytes across the wire into Python RAM on every request.
2. **Catastrophic N+1 Query Loop**: In `pages.py`, for every single page in the database, a separate SQL query is executed sequentially to check collection membership (`session.query(Collection).join(CollectionItem)...filter(CollectionItem.source_id == page_obj.url)`). For 500 pages, this triggers 500 individual round-trip queries over the database connection.
3. **Duplicate Full Table Scan**: The entire `FetchedPage` table is loaded a second time (`session.query(FetchedPage).all()`) to calculate site hostnames and counts.
4. **Unindexed Tables & No Pagination**: `fetched_pages.fetched_at` and `collection_items.source_id` lack database indexes, and queries lack `LIMIT`/`OFFSET`.

Per user guidance:
- SQLite support is being phased out in favor of PostgreSQL as the primary database engine.
- All work must be documented in an issue on the `master` branch before development starts.
- A new DRAFT PR will be opened from `production` into `master` and linked with the issues.
- Development will take place on a dedicated feature branch off `production`: `feature/ui-performance-api`.

---

## User Review Required

> [!IMPORTANT]
> **SQLite Deprecation & Native PostgreSQL Database View**:
> Since SQLite support is being phased out, we can use native PostgreSQL features in our database view:
> - Use `string_agg(c.title, ', ')` to aggregate multiple collections into a single string directly in SQL.
> - Exclude heavy columns (`html_content`, `md_content`) from the view.
> - Pre-index `fetched_pages(fetched_at DESC)`, `collection_items(source_id)`, and `youtube_videos(creator)`.
> This reduces the main page query from `1 + 500` queries down to **1 single index-backed query** executing in under 10ms.

---

## Step-by-Step Execution Plan

### Step 1: Document Issue on `master` Branch & GitHub Issue Creation
1. Switch to `master` branch: `git checkout master && git pull origin master`.
2. Add the new issue to `issues.md` on `master` documenting:
   - UI Performance regression post-migration.
   - Database view creation and indexing for page summaries.
   - Standardized REST API endpoints (`/api/articles`, `/api/videos`, `/api/videos/transcript`, `/api/sites`, `/api/tags`).
   - Frontend pagination and reactive client overhaul.
   - Phasing out SQLite support.
3. Commit and push the updated `issues.md` on `master`.
4. Create the corresponding GitHub issue via `gh issue create`.

### Step 2: Branch Creation & Draft Pull Request
1. Checkout `production` and pull latest: `git checkout production && git pull origin production`.
2. Create feature branch off `production`: `git checkout -b feature/ui-performance-api`.
3. Open a DRAFT PR from `production` into `master`:
   `gh pr create --draft --base master --head production --title "Release v0.3.0: UI Performance Speedup, Pagination, & REST API Overhaul" --body "..."`
4. Associate the new issue with the draft PR.

### Step 3: Database View & Index Migration (PostgreSQL)
1. Add an Alembic migration creating:
   - Index `idx_fetched_pages_fetched_at` on `fetched_pages (fetched_at DESC)`.
   - Index `idx_collection_items_source_id` on `collection_items (source_id)`.
   - View `vw_page_cards`:
     ```sql
     CREATE OR REPLACE VIEW vw_page_cards AS
     SELECT 
         f.url,
         f.title,
         f.description,
         f.tags,
         f.fetched_at,
         f.collection_id,
         y.creator,
         y.video_id,
         y.duration,
         y.view_count,
         y.thumbnail_url,
         string_agg(c.title, ', ') AS collection_title,
         MIN(c.id) AS collection_first_id
     FROM fetched_pages f
     LEFT JOIN youtube_videos y ON f.url = y.url
     LEFT JOIN collection_items ci ON f.url = ci.source_id AND ci.collection_id != 1
     LEFT JOIN collections c ON ci.collection_id = c.id
     GROUP BY f.url, f.title, f.description, f.tags, f.fetched_at, f.collection_id,
              y.creator, y.video_id, y.duration, y.view_count, y.thumbnail_url;
     ```
2. Update `models_orm.py`:
   - Map declarative model `PageCardView` to `vw_page_cards`.
   - Add index declarations on `FetchedPage` and `CollectionItem`.

### Step 4: Standardized REST API Endpoints
Create `src/kb_web/routers/rest_api.py` exposing:
- `GET /api/articles`: Paginated (`page`, `limit`), search (`q`), tag filter (`tag`), sorting.
- `GET /api/articles/detail`: Full article details with markdown and wiki summary.
- `GET /api/videos`: Paginated video cards (`creator`, `tag`, `page`, `limit`).
- `GET /api/videos/transcript`: Video transcript segments, plain text transcript, and chapter breakdown.
- `GET /api/sites`: Aggregated domain list with page counts and sample URLs.
- `GET /api/tags`: Unique tags list with item counts.
Register router in `server.py`.

### Step 5: Frontend Pagination & Reactive UI Overhaul
1. Refactor `src/kb_web/routers/pages.py`:
   - Use `PageCardView` with pagination (`limit`, `offset`) on `/` and `/pages`.
   - Optimize site domain aggregation query using `session.query(FetchedPage.url).all()`.
2. Update `src/kb_web/templates/pages_list.j2.html`:
   - Add responsive pagination controls (Previous, Next, Page Numbers, Page Size selector).
   - Add reactive JavaScript client controller:
     - 300ms debounced search without page reloads.
     - Instant tab switching between Articles, Videos, and Sites.
     - Deep-linkable URL parameters (`history.pushState`).
     - Skeleton loading placeholders for cards.

---

## Proposed Changes

### Database Layer
- **[NEW]** `migrations/versions/c72b89d412e1_add_page_card_view_and_indexes.py`
- **[MODIFY]** `src/kb_web/models_orm.py`

### Backend REST API Layer
- **[NEW]** `src/kb_web/routers/rest_api.py`
- **[MODIFY]** `src/kb_web/server.py`
- **[MODIFY]** `src/kb_web/routers/pages.py`

### Frontend UI Layer
- **[MODIFY]** `src/kb_web/templates/pages_list.j2.html`

### Tests & Documentation
- **[NEW]** `tests/test_rest_api.py`
- **[MODIFY]** `issues.md` (on `master`)
- **[MODIFY]** `CHANGELOG.md`

---

## Verification Plan

### Automated Tests
- `uv run pytest`: Run full test suite ensuring all 54 existing tests pass.
- Run new tests in `tests/test_rest_api.py` for API pagination, transcripts, and filtering.
- Run pre-commit UI template verification: `python scripts/verify_ui_templates.py`.

### Manual & Performance Verification
- Benchmark query execution time on `GET /` and `GET /api/articles`.
- Test UI via browser subagent:
  - Page navigation and items-per-page selector.
  - Debounced search filtering.
  - Video transcript extraction API endpoint.
