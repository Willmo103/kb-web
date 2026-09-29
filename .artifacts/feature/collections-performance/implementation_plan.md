# Implementation Plan: Optimize `/collections` Latency & Eliminate Heavy Full-Table Scans

Resolves Issue #58: "Perf: Severe 11+ Second Latency on /collections Endpoint Due to Full-Table Scans and Eager Column Hydration" (linked to open Draft PR #57).

---

## 1. Problem Description & Root Cause

During UAT testing on the test server (`http://192.168.0.32:8051/collections`), navigating to the `/collections` page took **11.77+ seconds** waiting for server response, transferring 256 KB of rendered HTML.

### Diagnostic Profiling Findings
Direct profiling of `list_collections()` queries in PostgreSQL revealed:
- `Collections query (6 cols)`: **0.0138s** (fast)
- `Ungrouped pages DB query (153 rows)`: **4.0430s** (slow)
- `Admin all_pages DB query (286 rows)`: **7.2505s** (extremely slow)
- **Total DB + Model serialization time**: **11.3323s**

### Root Causes
1. **Admin "Assign Item" Dropdown Eager Scan**:
   When an admin user is logged in, line 254 executes `session.query(FetchedPage).all()`. This pulls ALL 286+ pages in the database including multi-megabyte `html_content`, `md_content`, and `text_content` across PostgreSQL TCP connections, followed by JSON parsing and `HTMLPage` Pydantic model validation for every single page. The template only uses `(p.url, p.title)`.
2. **Ungrouped Pages Full Model Hydration**:
   Line 234 executes `session.query(FetchedPage).filter(~FetchedPage.url.in_(subq)).all()`. It pulls all columns for 153 ungrouped pages and inflates 153 full Pydantic models. The template only renders `(page.safe_url, page.title, page.url)`.
3. **N+1 Collections Lookups in `view_collection`**:
   In `view_collection()`, lines 348-356 run an individual query per collection page to find other collections it belongs to, plus another `session.query(FetchedPage).all()` for the add-pages sidebar.
4. **Missing Composite Index on `collection_items`**:
   Filtering `collection_items` by `collection_id != general_id` and matching `source_id` lacks a compound index on `(collection_id, source_id)`.

### Proof of Concept Benchmark
By projecting only `(FetchedPage.url, FetchedPage.title)` and eliminating Pydantic model inflation:
- Ungrouped pages dropped from **4.04s** -> **0.021s**
- Admin all_pages dropped from **7.25s** -> **0.006s**
- **Total latency dropped from 11.33s to 0.028s (a ~400x speedup!)**

---

## 2. User Review Required

> [!NOTE]
> All changes preserve existing template interfaces and behavior. Jinja2 templates access dictionary fields using identical dot notation (`page.safe_url`, `page.title`, `page.url`, `p.url`, `p.title`), requiring zero disruptive UI changes while cutting page load times by >99%.

> [!IMPORTANT]
> Ghost stubs (`title LIKE 'Archived Item (%'`) will be explicitly filtered out of `/collections` ungrouped pages and dropdown lists to ensure previously deleted pages never surface.

---

## 3. Proposed Changes

### Component 1: Route Optimization (`src/kb_web/routers/collections.py`)

#### [MODIFY] [collections.py](file:///c:/src/kb-web/src/kb_web/routers/collections.py)
1. **`list_collections` (`GET /collections`)**:
   - Refactor ungrouped pages query to project only `(FetchedPage.url, FetchedPage.title)` with `~FetchedPage.title.like('Archived Item (%')`.
   - Populate `ungrouped_pages` as lightweight dicts with `url`, `title`, and `safe_url = quote_plus(url)`.
   - Refactor `all_pages` query for admin dropdown to project only `(FetchedPage.url, FetchedPage.title)` ordered by title.
   - Eliminate heavy `HTMLPage` Pydantic model instantiation.
2. **`view_collection` (`GET /collections/view/{collection_id}`)**:
   - Refactor collection items query to project only required fields `(FetchedPage.url, FetchedPage.title, FetchedPage.fetched_at, CollectionItem.item_order, CollectionItem.item_note, CollectionItem.taxonomy_path)`.
   - Replace the N+1 query loop with a single grouped dictionary lookup for other collection memberships.
   - Refactor `all_pages` in `view_collection` to project only needed columns.
3. **`view_collection_editor` (`GET /collections/view/{collection_id}/editor`)**:
   - Project only required fields `(url, title, md_content, description)` excluding heavy `html_content`.

---

### Component 2: Database Layer & Indexing (`src/kb_web/models_orm.py` & Migrations)

#### [MODIFY] [models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py)
- In `ensure_views_and_indexes()`, add compound index:
  `CREATE INDEX IF NOT EXISTS idx_collection_items_col_source ON collection_items (collection_id, source_id);`

#### [NEW] [migrations/versions/e81c74291a23_add_collection_items_compound_index.py](file:///c:/src/kb-web/migrations/versions/e81c74291a23_add_collection_items_compound_index.py)
- Alembic migration creating index `idx_collection_items_col_source` on `collection_items(collection_id, source_id)`.

---

### Component 3: REST API Extension (`src/kb_web/routers/rest_api.py`)

#### [MODIFY] [rest_api.py](file:///c:/src/kb-web/src/kb_web/routers/rest_api.py)
- Add `GET /api/collections`: Paginated list of collections with item counts and visibility.
- Add `GET /api/collections/ungrouped`: Lightweight paginated endpoint for ungrouped pages.

---

### Component 4: Test Suite (`tests/test_server.py` & `tests/test_rest_api.py`)

#### [MODIFY] [test_server.py](file:///c:/src/kb-web/tests/test_server.py)
- Add performance assertions for `GET /collections` and `GET /collections/view/{id}` verifying response status 200, item counts, and fast execution.

#### [MODIFY] [test_rest_api.py](file:///c:/src/kb-web/tests/test_rest_api.py)
- Add unit tests for `GET /api/collections` and `GET /api/collections/ungrouped`.

---

## 4. Verification Plan

### Automated Tests
1. **Unit Tests**:
   `uv run pytest` (all 62+ tests passing).
2. **Template Check**:
   `uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py` (0 warnings).
3. **Build Pipeline**:
   `uv run python build.py` (clean build of packages).
4. **VCS UAT Report**:
   `uv run python .agents/skills/generate-uat-testing-artifact/scripts/generate_uat_report.py --task collections_performance --tester "Agent"`

### Manual / Latency Verification
- Execute `profile_collections.py` verifying that `/collections` query and serialization complete in <50ms (down from 11.3s).
- Verify UI rendering of collections list and ungrouped pages in browser.
