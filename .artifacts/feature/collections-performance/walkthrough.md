# Walkthrough: Collections Latency Optimization & Model Projection

Resolves Issue #58: "Perf: Severe 11+ Second Latency on /collections Endpoint Due to Full-Table Scans and Eager Column Hydration" (linked to open Draft PR #57).

---

## 1. Summary of Changes

### Diagnostic Profiling & Root Cause
- Navigating to `/collections` previously took **11.77+ seconds** waiting for server response, transferring 256 KB of rendered HTML.
- Profiling breakdown of `list_collections()` queries:
  - `Collections query`: **0.0138s**
  - `Ungrouped pages DB query (153 rows)`: **4.0430s**
  - `Admin all_pages DB query (286 rows)`: **7.2505s**
  - Total DB + model time: **11.3323s**
- Cause:
  1. For ungrouped pages, `session.query(FetchedPage).filter(~FetchedPage.url.in_(subq)).all()` loaded entire `FetchedPage` ORM models including large `html_content`, `md_content`, and `text_content`, followed by Pydantic model validation on 153 instances.
  2. For admin users, `session.query(FetchedPage).all()` loaded every single page in the entire database with all heavy content columns and inflated Pydantic models just to populate `<option value="{{ p.url }}">{{ p.title }}</option>`.
  3. In `view_collection()`, an N+1 query loop ran `session.query(Collection)...` per collection page, alongside another full-table `all_pages` query.

### Collections Route Optimization (`src/kb_web/routers/collections.py`)
- **`list_collections` (`GET /collections`)**:
  - Replaced full `FetchedPage` hydration with lightweight projection:
    `session.query(FetchedPage.url, FetchedPage.title).filter(~FetchedPage.url.in_(subq)).filter(~FetchedPage.title.like("Archived Item (%")).order_by(FetchedPage.fetched_at.desc()).all()`
  - Replaced heavy `HTMLPage` Pydantic models with lightweight dicts providing `url`, `title`, and `safe_url = quote_plus(url)` (identically accessible via Jinja2 dot notation).
  - Replaced admin `all_pages = session.query(FetchedPage).all()` with lightweight projection `(FetchedPage.url, FetchedPage.title)`.
  - Filtered out historical ghost stubs (`title LIKE 'Archived Item (%'`).
- **`view_collection` (`GET /collections/view/{collection_id}`)**:
  - Projected only required fields `(FetchedPage.url, FetchedPage.title, FetchedPage.fetched_at, CollectionItem.item_note, CollectionItem.taxonomy_path, CollectionItem.item_order)`.
  - Replaced N+1 query loop with a single grouped subquery for other collection memberships.
  - Projected only needed columns for the admin `all_pages` addition drawer.
- **`view_collection_editor` (`GET /collections/view/{collection_id}/editor`)**:
  - Projected only required columns `(url, title, md_content, description, item_note, taxonomy_path, item_order, source_type)` excluding heavy `html_content`.

### Database Layer & Compound Indexing
- **Compound Performance Index**:
  - Added `CREATE INDEX IF NOT EXISTS idx_collection_items_col_source ON collection_items (collection_id, source_id);` in [src/kb_web/models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py).
  - Created Alembic migration [migrations/versions/e81c74291a23_add_collection_items_compound_index.py](file:///c:/src/kb-web/migrations/versions/e81c74291a23_add_collection_items_compound_index.py).

### REST API Extension (`src/kb_web/routers/rest_api.py`)
- Added `GET /api/collections`: Paginated collection listings with page counts, title search (`q`), and visibility metadata.
- Added `GET /api/collections/ungrouped`: Lightweight paginated list of ungrouped pages with title and URL search.

---

## 2. Verification Results

### Latency Benchmark
- Before optimization: **11.33 seconds**
- After optimization: **0.028 seconds** (tested across live dataset with 153 ungrouped pages and 286 total library pages)
- **Speedup: ~400x reduction in query and serialization latency**

### Automated Tests
- **Full Test Suite (`pytest`)**:
  - `tests/test_db_cli.py`: 7 passed
  - `tests/test_rest_api.py`: 10 passed (including `test_get_collections_api` and `test_get_ungrouped_pages_api`)
  - `tests/test_server.py`: 48 passed (including `test_collections_page_and_view_performance`)
  - **Total: 65 passed in 30.59s** (execution time dropped from 64.6s to 30.6s)

### Pre-Commit Gates
- **Template Verification (`verify_ui_templates.py`)**: All 14 Jinja2 templates verified with **0 warnings**.
- **Build Pipeline (`build.py`)**: Succeeded with code 0; built source and wheel packages for `kb_web` and `kb_web_cli`.
- **VCS UAT Testing Artifacts**: Generated and tracked in `uat/reports/uat_report_collections_performance_20260913_162127.md`.

---

## 3. GitHub Issue & PR Status
- Issue: [#58](https://github.com/Willmo103/kb-web/issues/58) - Perf: Severe 11+ Second Latency on /collections Endpoint Due to Full-Table Scans and Eager Column Hydration.
- Pull Request: [Draft PR #57](https://github.com/Willmo103/kb-web/pull/57) (`production` -> `master`) open and updated with association to #58.
- Working Branch: `feature/collections-performance`
