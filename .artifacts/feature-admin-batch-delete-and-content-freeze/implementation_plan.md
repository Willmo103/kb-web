# Implementation Plan: Admin Batch-Delete Utility, Content Freeze & Immutability, and CI Fix

This implementation plan details the architectural design, database migrations, REST endpoints, UI enhancements, and test suite for the Admin Batch-Delete utility, Content Freeze & Immutability safeguards, CI submodule checkout resolution, taxonomy purge neutralization, and the new `live-server-test` skill.

---

## 1. Problem Statement & Requirements

1. **GitHub Actions CI Master Failure**:
   - The push to `master` failed in CI (`test-and-release.yml`) because `actions/checkout@v4` ran without submodules, and `.gitmodules` pointed to `./kb-web-cli` rather than the public upstream repository `https://github.com/Willmo103/kb-web-cli.git`. As a result, tests importing `from kb_web_cli.main import app as cli_app` threw `ModuleNotFoundError`.
   - **Resolution**: Update `.gitmodules`, configure `.github/workflows/test-and-release.yml` with `submodules: recursive`, and add graceful import guards in tests.

2. **Content Freeze & Immutability (`is_frozen`)**:
   - The user requires the ability to mark any item (article, Obsidian note, video) as **frozen and immutable**.
   - When frozen, an item must reject:
     - AI Wiki generation / re-generation (`/api/pages/{id}/generate-wiki` -> HTTP 400).
     - Tag curation / editing (`/api/pages/{id}/tags`, `/api/notes/{id}/tags` -> HTTP 400).
     - Title and content updates (`PUT /api/notes/{id}`, `/api/pages/{id}` -> HTTP 400).
     - Source URL re-fetching (`/api/pages/{id}/refetch` -> HTTP 400).
   - UI must display a prominent `❄️ Frozen` badge and a secure Freeze/Unfreeze toggle button, with edit actions disabled when frozen.

3. **Admin Batch-Delete Utility**:
   - Administrators need the ability to cleanly batch-delete:
     - Whole collections/folders of Obsidian notes (by note IDs or slash-delimited folder prefix, e.g. `work/old-vault/`).
     - Virtual sites and all their associated pages, embeddings, and links (`/api/sites/{domain}/all`).
     - Videos and associated embeddings, optionally unlinking/deleting media files from disk.
     - Articles / pages across collections.
   - Must execute in single database transactions with foreign key cascades, orphan cleanup, and confirmation modals.

4. **Taxonomy Purge Neutralization**:
   - The one-time migration (`0a9b8c7d6e5f_one_time_taxonomy_purge.py`) previously added to clear categorizations from production ran during test server deployment, inadvertently wiping out taxonomy categories and items on the test server.
   - **Resolution**: Neutralize `migrations/versions/0a9b8c7d6e5f_one_time_taxonomy_purge.py` `upgrade()` to a no-op (`pass`) and remove purge commands from `src/kb_web/scripts/deploy_migrations.py`.

5. **`live-server-test` Skill**:
   - User requirement: "Create a skill: Live server test - This uses curl to test out the running production server (its only online while the UAT testing is going) You can reach the test server at https://kb-test.willmo.dev. Don't do any admin stuff, but I want you to audit the site routes."
   - Target server: `https://kb-test.willmo.dev`
   - Must perform non-destructive, read-only route auditing using `curl` across public, authenticated, API, and static asset routes.
   - Must avoid all admin operations, state-changing endpoints, or mutations.

---

## 2. Architecture & Data Flow

```mermaid
graph TD
    subgraph UI_Layer ["UI & Dashboard Layer"]
        PageProfile["Article Profile (view_page.j2.html)"]
        NoteEditor["Note Editor & Tree (notes_list.j2.html)"]
        AdminDashboard["Admin Maintenance (admin.j2.html)"]
        SiteView["Site Profile (view_site.j2.html)"]
    end

    subgraph Freeze_Guard ["Immutability Guard Layer"]
        CheckFreeze{"is_frozen == 1?"}
        BlockMutation["Reject Mutation (HTTP 400 Frozen)"]
        AllowMutation["Allow Update / Regeneration"]
    end

    subgraph Batch_Delete_Service ["Admin Batch-Delete Engine"]
        BatchNotes["Batch Delete Notes (by IDs or folder prefix)"]
        BatchSites["Batch Delete Site & Cascading Pages"]
        BatchVideos["Batch Delete Videos & Media"]
        BatchPages["Batch Delete Pages & Embeddings"]
    end

    subgraph Storage ["Database & Storage"]
        Postgres["PostgreSQL / SQLite Database"]
        DiskMedia["~/.kb/media/videos"]
        Qdrant["Vector Indexes"]
    end

    subgraph Live_Audit ["Live Server Route Audit Skill"]
        CurlClient["curl CLI Engine"]
        TestServer["https://kb-test.willmo.dev"]
        RouteAudit["Read-Only Route Status & Header Audit"]
    end

    PageProfile -->|Generate Wiki / Edit Tags / Refetch| CheckFreeze
    NoteEditor -->|Save Note / Update Tags| CheckFreeze
    CheckFreeze -->|Yes| BlockMutation
    CheckFreeze -->|No| AllowMutation

    AdminDashboard -->|Batch Request| Batch_Delete_Service
    SiteView -->|Delete Site + Pages| BatchSites
    NoteEditor -->|Delete Folder / Checked Notes| BatchNotes

    BatchNotes --> Postgres
    BatchSites --> Postgres
    BatchVideos --> Postgres
    BatchVideos --> DiskMedia

    CurlClient --> RouteAudit
    RouteAudit -->|GET/HEAD (No Admin)| TestServer
```

---

## 3. Database Schema Changes & Migration

### Schema Updates (`src/kb_web/models_orm.py`)
- `FetchedPage`: Add `is_frozen = Column(Integer, default=0, index=True)`.
- `Note`: Add `is_frozen = Column(Integer, default=0, index=True)`.
- `YouTubeVideo`: Add `is_frozen = Column(Integer, default=0, index=True)`.
- Update `ensure_views_and_indexes` to ensure SQLite also adds the column if missing on older test databases.

### Alembic Migration
- Migration `1b2c3d4e5f6a_add_content_is_frozen_column.py`:
  - `upgrade()`: Adds `is_frozen INTEGER DEFAULT 0` with indexes to `fetched_pages`, `notes`, and `youtube_videos`.
  - `downgrade()`: Removes the columns.
- Migration `0a9b8c7d6e5f_one_time_taxonomy_purge.py`:
  - Neutralize `upgrade()` to `pass` so no automated taxonomy wipes occur during migrations.

---

## 4. REST Endpoints & Immutability Enforcement

### A. Freeze & Immutability Routes
- `POST /api/pages/{url:path}/freeze`: Toggles `is_frozen` (0 &rarr; 1 or 1 &rarr; 0) for an article.
- `POST /api/notes/{id}/freeze`: Toggles `is_frozen` for a note.
- `POST /api/videos/{video_id}/freeze`: Toggles `is_frozen` for a video.
- **Guard Validation**:
  - `POST /api/pages/{url:path}/generate-wiki`: Check `page.is_frozen`. If 1, return `{"error": "Item is frozen and immutable", "frozen": True}`, HTTP 400.
  - `POST /api/pages/{url:path}/tags`: Check `page.is_frozen`. If 1, reject with HTTP 400.
  - `POST /api/pages/{url:path}/refetch`: Check `page.is_frozen`. If 1, reject with HTTP 400.
  - `PUT /api/notes/{id}`: Check `note.is_frozen`. If 1, reject with HTTP 400.
  - `POST /api/notes/{id}/tags`: Check `note.is_frozen`. If 1, reject with HTTP 400.

### B. Batch-Delete Endpoints
- `POST /api/admin/batch-delete`:
  - Unified admin batch-deletion router.
- `DELETE /api/notes/batch`: Batch deletes notes by array of IDs or by folder prefix (e.g. `work/archive/`). Deletes associated embeddings and collection mappings.
- `DELETE /api/sites/{domain}/all`: Cascade deletes all pages for the virtual site, along with article embeddings, chunk embeddings, versions, and collection items.
- `DELETE /api/videos/batch`: Deletes video records and embeddings, with option to delete local `.mp4`/`.webm` media files.
- `DELETE /api/pages/batch`: Deletes list of URLs and their embeddings, snapshots, and collection items.

---

## 5. UI & UX Enhancements

1. **Article Profile (`view_page.j2.html`)**:
   - Prominent badge: `❄️ Frozen` when `is_frozen == 1`.
   - Freeze button: "❄️ Freeze Content" / "🔓 Unfreeze Content".
   - Disabled states for "Regenerate Wiki", "Regenerate Tags", and "Re-fetch Page" when frozen.
2. **Note Editor & List (`note_editor.j2.html` & `notes_list.j2.html`)**:
   - Editor shows "❄️ Frozen Note" badge and read-only mode in Monaco Editor when frozen.
   - Notes list includes multi-select checkboxes for batch deletion and a sticky "Batch Actions" toolbar.
   - Folder tree context action: "🗑️" delete folder/vault with item count confirmation.
3. **Site List & Profile (`sites_list.j2.html` & `view_site.j2.html`)**:
   - "🗑️ Delete Site & All Pages" action button with confirmation modal.
4. **Admin Dashboard (`admin.j2.html`)**:
   - Administrative Batch Operations & Content Purge panel in Backups & Database tab.

---

## 6. GitHub Actions CI & Test Import Fix

1. **`.gitmodules`**:
   - Update `url = https://github.com/Willmo103/kb-web-cli.git`.
2. **`.github/workflows/test-and-release.yml`**:
   - Add `submodules: recursive` to `actions/checkout@v4`.
3. **`tests/test_cli_auth_and_workspaces.py` & `tests/test_rag_agent_and_reports.py`**:
   - Wrap `from kb_web_cli.main import app as cli_app` in `try...except ImportError` so test collection never hard crashes even if the submodule directory is unpopulated.

---

## 7. Taxonomy Purge Removal

1. In `migrations/versions/0a9b8c7d6e5f_one_time_taxonomy_purge.py`:
   - Replace table deletion statements in `upgrade()` with `pass`.
2. In `src/kb_web/scripts/deploy_migrations.py`:
   - Remove table deletion commands from `rollback_single()`.

---

## 8. Live Server Test Skill (`live-server-test`)

1. Skill directory: `.agents/skills/live-server-test/`
   - `SKILL.md`: Metadata and workflow for running non-destructive live route audits against running instances (e.g., `https://kb-test.willmo.dev`).
   - `scripts/audit_live_routes.py`: Python CLI tool executing `curl` probes across:
     - Public routes: `/api/health`, `/login`, `/manifest.json`, `/favicon.ico`
     - Protected UI routes: `/`, `/pages`, `/sites`, `/notes`, `/collections`, `/conversations`, `/reports`, `/reports/rag`, `/taxonomy`, `/workspaces`
     - Protected API routes: `/api/sites`, `/api/articles`, `/api/tags`, `/api/notes`
     - Static assets: `/static/style.css`
   - Guards: Explicitly excludes any admin routes (`/admin/*`) or HTTP mutating methods (`POST`, `PUT`, `DELETE`).
2. Register skill in `GEMINI.md`.

---

## 9. Verification & Testing Plan

1. **Verify Taxonomy Neutralization**:
   - Inspect `0a9b8c7d6e5f_one_time_taxonomy_purge.py` and `deploy_migrations.py`.
   - Run tests to confirm taxonomy operations work as expected.
2. **Execute Live Route Audit**:
   - Run `audit_live_routes.py` against `https://kb-test.willmo.dev`.
   - Output structured audit report with status codes, redirects, content types, and latency.
3. **Regression Verification**:
   - Run full pytest suite (`uv run pytest`) across all test modules.
   - Run build verification (`uv run python build.py`).
   - Run UI template check (`verify_ui_templates.py`).
