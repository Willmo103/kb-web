# Walkthrough: Wiki Versioning, Model Steering & Internal URL Scheme Routing

This walkthrough outlines the architectural additions, API enhancements, UI improvements, and automated verification suites implemented for AI Wiki versioning, model steering modal dialogs, and synthetic URL resolution (`note://`, `workspace://`).

---

## 1. Feature Architecture Overview

### A. Dedicated Wiki Versioning & Cascade Life-Cycle
- **`WikiVersion` Model (`src/kb_web/models_orm.py`)**:
  - Columns: `id`, `url`, `title`, `wiki_content`, `model_name`, `steering_instructions`, `created_at`.
  - Configured with native DB foreign key `ForeignKey("fetched_pages.url", ondelete="CASCADE")` and SQLAlchemy relationship `wiki_versions = relationship("WikiVersion", cascade="all, delete-orphan", passive_deletes=True)`.
  - Enabled `PRAGMA foreign_keys=ON` on SQLite database connections in `src/kb_web/base.py`.
  - Added `wiki_model` column to `FetchedPage` and pre-aggregated database view `vw_page_cards`.
  - Guaranteed multi-dialect cascade deletion across `admin.py:handle_delete_page`, `rest_api.py:delete_single_article`, `notes.py:delete_note_api`, and `admin_batch.py:_cascade_delete_page_urls`.

### B. Interactive Model Selection & Custom Steering Modal
- **On-the-Fly Model Picker**:
  - Replaced the direct POST submit button with an interactive modal form triggered by `openRegenerateWikiModal()`.
  - Dynamically lists installed Ollama completion models with the current model pre-selected.
- **Steering Directives Textarea**:
  - Allows users to provide optional steering directives (e.g., bulleted technical architecture, executive summary, code snippet focus).
  - Directives are cleanly appended to system curation prompts in `src/kb_web/utils.py:extract_wiki_content` across both standard and chunked multi-part summarization workflows.
- **Reciprocal Archival & Model Recording**:
  - Before writing the new wiki content in `POST /admin/regenerate/wiki`, the existing wiki entry is safely archived into `WikiVersion` along with its prior generating model name.
  - The new `wiki_model` is saved directly to `FetchedPage.wiki_model`.
  - On `/view/page`, the generating model is prominently displayed via an `🤖 Model: <model_name>` badge.

### C. Historical Version Selector & Instant Restoration
- **History Navigation**:
  - Rendered version pills (`v1`, `v2`, `Latest`) directly in the wiki card header on `/view/page`.
  - Historical version view (`/view/page?url=...&wiki_version_id=<id>`) displays a notice banner with the version's creation timestamp, generating model, and custom steering badge.
- **Restoration Endpoint (`POST /admin/wiki/restore`)**:
  - Restores a selected historical version as active while reciprocally archiving the current active wiki into a new `WikiVersion`.

### D. Synthetic Scheme URL Resolution (`note://`, `workspace://`)
- **`resolve_entity_url(url: str) -> dict` (`src/kb_web/base.py`)**:
  - `note://{vault}/{folder}/{slug}` or `note://{vault}/{slug}` -> routes directly to the Monaco editor (`/notes/edit?url=note%3A%2F%2F...`).
  - `workspace://{workspace_id}/snapshot/{tag}` or `workspace://{workspace_id}` -> routes directly to the in-browser IDE (`/workspaces/{workspace_id}`).
  - `http://` / `https://` -> external target with `target="_blank"`.
  - Unrecognized pseudo-schemes -> rendered as disabled/non-clickable badges, preventing dead browser clicks.
- **Server Dispatcher (`GET /open?url=...`) (`src/kb_web/routers/pages.py`)**:
  - Seamless 303 redirect endpoint dispatching any URL to its internal or external destination.
- **Global Markdown & Link Interceptor (`src/kb_web/templates/base.j2.html`)**:
  - Global click listener on `a[href^="note://"]` and `a[href^="workspace://"]` preventing default navigation and routing smoothly through `/open?url=...`.

---

## 2. Test Verification Summary

### Comprehensive Unit & Integration Test Battery (`tests/test_wiki_versions_and_url_routing.py`)
- `test_wiki_version_orm_and_cascade_delete`: PASSED
- `test_resolve_entity_url_utility`: PASSED
- `test_open_dispatcher_endpoint`: PASSED
- `test_regenerate_wiki_archives_old_and_records_model`: PASSED
- `test_restore_wiki_endpoint`: PASSED
- `test_batch_and_notes_cascade_deletes_wiki_versions`: PASSED
- `test_view_page_renders_wiki_versions_and_model`: PASSED

### Gated Pre-Commit Suite
- **UI Component UAT Verification**: `uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py` -> 29 HTML templates verified, 0 warnings.
- **Full Test Suite (`uv run pytest`)**: 268 passed, 0 failed in 201s.
- **Packaging & Build Pipeline (`uv run python build.py`)**: `[SUCCESS] Build verification pipeline completed successfully!`
