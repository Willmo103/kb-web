# Walkthrough: Content Freeze, Admin Batch-Delete Suite, and CI Fix

## Summary of Completed Work

This sprint focused on delivering critical administrative governance tools, content protection safeguards, and fixing GitHub Actions CI pipelines:

1. **Master CI Pipeline Resolution**: Diagnosed and resolved the submodule cloning and import failure on GitHub Actions runners.
2. **Content Freeze & Immutability (`is_frozen`)**: Added full-stack content freeze support across pages, notes, and videos, locking down AI wiki generation, tag edits, and updates.
3. **Admin Batch-Delete Suite**: Built administrative batch purge utilities for Obsidian notes (by IDs, folder hierarchy, or vault), virtual site domains (with cascading page and embedding cleanup), videos (with media cleanup on disk), and pages.
4. **UI UAT Verification**: Updated templates with badges, batch toolbars, and controls, passing all template verification checks and unit test suites (140/140 tests passing).

---

## 1. Master CI Pipeline Resolution

### Root Cause
GitHub Actions workflow run `#37267390865` on `master` failed with:
`ModuleNotFoundError: No module named 'kb_web_cli'` during test collection in `test_cli_auth_and_workspaces.py` and `test_rag_agent_and_reports.py`.
- **Cause 1**: `.gitmodules` used a relative URL `./kb-web-cli` which failed resolution on remote runners when cloning submodules.
- **Cause 2**: `.github/workflows/test-and-release.yml` used default `actions/checkout@v4` without `submodules: recursive`.
- **Cause 3**: Test files directly imported `kb_web_cli` at module top-level without defensive fallback guards.

### Resolution
- **Submodule URL**: Configured `.gitmodules` to use absolute URL `https://github.com/Willmo103/kb-web-cli.git`.
- **Workflow Checkout**: Added `submodules: recursive` under `actions/checkout@v4` in `.github/workflows/test-and-release.yml`.
- **Defensive Test Guards**: Wrapped `kb_web_cli` imports in `try...except ImportError` with `pytest.skip` guards if submodule is absent.

---

## 2. Content Freeze & Immutability Engine

### Database & ORM
- Added `is_frozen = Column(Integer, default=0, index=True)` to:
  - `FetchedPage` (articles, mirrored notes, web pages)
  - `Note` (Obsidian notes & code snippets)
  - `YouTubeVideo` (video records)
- Added `is_frozen: Optional[int] = 0` to `HTMLPage` Pydantic model.
- Created Alembic migration `migrations/versions/1b2c3d4e5f6a_add_content_is_frozen_column.py`.
- Added automatic SQLite migration check in `models_orm.ensure_views_and_indexes()`.

### Immutability Route Guards
When `is_frozen == 1`:
- **AI Wiki Generation**: Blocked at `POST /admin/regenerate/wiki`. Returns redirect with error message and bypasses LLM calls.
- **Tag Generation & Manual Edits**: Blocked at `POST /admin/regenerate/tags` and `POST /admin/update/tags`.
- **Page Refetching**: Blocked at `POST /admin/refetch/page`.
- **YouTube Metadata Updates**: Blocked at `POST /admin/regenerate/youtube-metadata`.
- **Note Editing**: Blocked at `PUT /api/notes/{id}` with `HTTP 400 Bad Request` ("Note is frozen and immutable to edits.").
- **Background Tasks**: `_process_note_in_background()` skips re-tagging and mutations if `note.is_frozen == 1`.

### Freeze Endpoints
- `POST /admin/freeze/page`: Toggles freeze status on a page, synchronizing to associated `Note` or `YouTubeVideo`.
- `POST /api/pages/{url_path}/freeze`: Programmatic JSON API to toggle freeze state on an article.
- `POST /api/notes/{note_id}/freeze`: Programmatic JSON API to toggle freeze state on a note.
- `POST /api/videos/{video_id}/freeze`: Programmatic JSON API to toggle freeze state on a video.
- `POST /api/admin/batch-freeze`: Bulk freeze/unfreeze endpoint for notes, pages, or videos.

---

## 3. Admin Batch-Delete Engine

Implemented in `src/kb_web/routers/admin_batch.py` with helper `_cascade_delete_page_urls()` ensuring complete cleanup of embeddings (`article_embeddings`, `title_embeddings`, `video_embeddings`, `chunk_embeddings`), taxonomy items, versions, collections, and links:

- **Batch Notes Deletion**:
  - `DELETE /api/notes/batch`: Accepts `note_ids: [...]`, `folder_prefix: "..."`, or `vault_name: "..."`. Cascades notes, mirrored `FetchedPage` entries, embeddings, and taxonomy items.
- **Batch Site Deletion**:
  - `DELETE /api/sites/{domain}/all`: Deletes an entire domain host and cascades all member pages, embeddings, versions, and site wiki documentation.
- **Batch Video Deletion**:
  - `DELETE /api/videos/batch`: Accepts `video_ids: [...]` or `urls: [...]` with optional `delete_media: true` to remove local files from `~/.kb/media/videos`.
- **Batch Pages Deletion**:
  - `DELETE /api/pages/batch`: Accepts a list of `urls` and cascades all dependent records.
- **Unified Batch Deletion Endpoint**:
  - `POST /api/admin/batch-delete`: Polymorphic entrypoint routing `notes`, `sites`, `videos`, and `pages`.

---

## 4. UI Enhancements

- **Article Viewer (`view_page.j2.html`)**:
  - Displays `❄️ Frozen` badge in article header when frozen.
  - Sidebar action button toggles between `❄️ Freeze Content` and `🔓 Unfreeze Content`.
  - Action buttons for wiki generation, tags, and refetch show locked disabled styling (`🔒 Wiki Locked (Frozen)`).
  - Monaco editor button indicates `View in Editor (Read-Only)` when note is frozen.
- **Note Editor (`note_editor.j2.html`)**:
  - Displays `❄️ Frozen Note` indicator badge next to title.
  - Header controls include `❄️ Freeze` / `🔓 Unfreeze` toggle button.
  - Sets Monaco Editor option `readOnly: true` when note is frozen.
  - Title input and Save button are locked and disabled.
- **Notes & Vaults Index (`notes_list.j2.html`)**:
  - Each note card has a multi-select checkbox and displays a `❄️ Frozen` badge if locked.
  - Sticky Batch Action Toolbar provides `Select All`, `❄️ Freeze`, `🔓 Unfreeze`, and `🗑️ Delete Selected`.
  - Sidebar Vault Hierarchy tree includes trash icons (`🗑️`) to delete whole folders or entire vaults.
- **Virtual Sites (`view_site.j2.html` & `sites_list.j2.html`)**:
  - Profile header and site list cards include "🗑️ Delete Site & All Pages" action buttons with safety confirmations.
  - Server Maintenance (`admin.j2.html`): Added dedicated "Administrative Batch Operations & Content Purge" panel in the Backups & Database tab supporting batch notes purging, domain purging, and bulk freeze/unfreeze operations.

---

## 5. Verification Results

- **Unit Test Suite**: 140/140 passed (`uv run pytest`) including new `tests/test_batch_delete_and_freeze.py`.
- **UI Template Verification**: 0 warnings across all 24 Jinja2 templates (`verify_ui_templates.py`).
- **Build Pipeline**: Distribution artifacts cleanly generated (`uv run python build.py`).
