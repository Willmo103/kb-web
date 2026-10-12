# Walkthrough: Field-Tested Resolutions for Notes Cascading Deletion, Workspace UX & Taxonomy Graph Harness

**Branch**: `feature/workspace-ux-notes-cascade-taxonomy-graph`  
**Date**: October 07, 2026  
**Status**: Verified & Ready for Review (PR #79)

---

## 1. Overview of Delivered Features & Fixes

This release resolves 9 critical field-tested TODO items across notes management, workspace IDE capabilities, and the autonomous taxonomy classification state machine:

1. **Robust Notes Cascading Deletion**: Eliminated foreign key constraint failures by introducing a comprehensive `_cascade_delete_notes()` helper cleaning all 10 dependent tables (`chat_conversations`, `chat_messages`, `chunk_embeddings`, `taxonomy_items`, `collection_items`, `collection_actions`, `article_embeddings`, `title_embeddings`, `video_embeddings`, `page_versions`, `links`, and mirrored `fetched_pages`), while maintaining category count synchronization and frozen-content guards. Added direct delete buttons in both the note editor and notes list card view. Fixed route collision between `/api/notes/batch` and `/api/notes/{note_id}`.
2. **Workspace `README.md` Markdown Formatting & Live Preview**: Fixed starter template markdown string indentation and formatting issues, and added an in-browser live rendered Markdown runner using `marked.js` with GitHub Dark styling.
3. **AI Prompt-Driven Workspace Creation**: Enabled natural language prompt-based workspace initialization (`prompt` field in `WorkspaceCreateRequest`). Ollama generates the project architecture, file list, and working code, with automated JSON fallback and heuristic synthesis.
4. **Flexible Project Types & Gist Mode**: Removed the strict 3-template limitation. Workspaces now support arbitrary custom project types, multi-file Gists, and Markdown Wiki Studios, while dynamically activating runners (Python Pyodide WASM, Web Preview, Markdown Live Runner, or Gist file summaries).
5. **Real-Time Ollama Loaded Models Display**: Added `/api/ps` introspection to detect models actively loaded in VRAM/memory. Highlighted actively loaded models (`🟢 In VRAM`) at the top of the workspace IDE model selector and in the admin settings dashboard.
6. **Targeted Notes Re-Taxonomy Classification**: Implemented `POST /api/taxonomy/classify-notes` supporting vault filtering, batch limits, and `force_reclassify` overrides. Added dedicated "🏷️ Classify Notes" action buttons in both the notes list UI and taxonomy management portal.
7. **Workspace Collapsible Directory Tree & Drag-and-Drop VFS**: Replaced flat folder/`.keep` file displays with a true collapsible directory tree using `<details open>`, `📁` folder badges, folder creation, folder deletion, and native HTML5 drag-and-drop file movement between root and directories.
8. **Taxonomy Slug Collision Retry Loop & Unique Slug Backstop**: Implemented a feedback loop in `_synthesize_new_category()` that catches duplicate slug collisions and re-prompts the LLM with collision context to either pick a unique name or merge into the existing domain. Backed by `_ensure_unique_slug()` to prevent database unique constraint crashes.
9. **Taxonomy Source Metadata Enrichment**: Enriched classification states and prompts with item provenance metadata (vault, folder path, collection, version, age, syntax, and source URL) across Notes, Web Pages, and Workspaces.

---

## 2. Key Code & Template Changes

### Backend Routers & Models
- `src/kb_web/models.py`:
  - Added optional `prompt: Optional[str] = None` and default `template: Optional[str] = "web-game"` to `WorkspaceCreateRequest`.
- `src/kb_web/routers/notes.py`:
  - Added `_cascade_delete_notes(session, note_ids, urls)` cascading 10 dependent tables and updating taxonomy item counts.
  - Added `DELETE /api/notes/{note_id}` guarded by `is_frozen` check.
- `src/kb_web/routers/admin_batch.py`:
  - Refactored `batch_delete_notes()` to delegate to `_cascade_delete_notes()`.
- `src/kb_web/server.py`:
  - Re-ordered router registration so `admin_batch.router` precedes `notes.router` to prevent static `/api/notes/batch` from being captured as an integer `{note_id}` parameter.
- `src/kb_web/routers/workspaces.py`:
  - Corrected template starter markdown formatting in `_create_workspace_files()`.
  - Added `_generate_workspace_from_prompt()` handling dictionary and list responses from Ollama with heuristic fallback.
  - Added `/api/models` endpoint querying `{ollama_host}/api/ps` for `loaded_models`.
  - Enhanced `list_workspace_models()` to return `loaded_models` list alongside available models.
- `src/kb_web/routers/taxonomy.py`:
  - Added `ClassifyNotesRequest` schema and `POST /api/taxonomy/classify-notes` endpoint.
- `src/kb_web/taxonomy_state_machine.py`:
  - Added `_format_metadata_summary()` extracting vault, folder path, source URL, syntax, age, and collections.
  - Added `_ensure_unique_slug(session, slug)` ensuring slugs never conflict in database.
  - Added slug collision retry loop (up to 3 turns) and domain merge detection in `_synthesize_new_category()`.
  - Enriched prompt payloads in `_create_cold_start_category()`, `classify_item_class()`, `evaluate_category_fit_tev1()`, and `classify_single_item()`.

### Frontend Templates
- `src/kb_web/templates/note_editor.j2.html`:
  - Added "🗑️ Delete" action button with confirmation dialog and `deleteCurrentNote()` handler.
- `src/kb_web/templates/notes_list.j2.html`:
  - Added per-note "🗑️" delete button with `deleteSingleNote(id, title)`.
  - Added "🏷️ Classify Notes" button triggering `triggerClassifyNotes()` modal/API call.
- `src/kb_web/templates/workspaces_list.j2.html`:
  - Added AI Prompt input textarea for prompt-driven generation.
  - Expanded template selector to include arbitrary project types, Gists, and Markdown Wiki Studio.
- `src/kb_web/templates/workspace_ide.j2.html`:
  - Hierarchical collapsible directory tree (`<details open>`, folder badges, new file inside folder, delete folder).
  - HTML5 drag-and-drop file movement (`handleDragStart`, `handleDragOver`, `handleDragLeave`, `handleDrop`).
  - Integrated `runMarkdownPreview()` using `marked.js` and `runGistPreview()` runners.
  - Prioritized `🟢 In VRAM (Currently Loaded)` optgroup in model selector.
- `src/kb_web/templates/taxonomy.j2.html`:
  - Added "🏷️ Classify Notes" button with `triggerNotesTaxonomyClassification()` helper.
- `src/kb_web/templates/admin.j2.html`:
  - Added "⚡ Check Loaded Models" button and `🟢 (In VRAM)` indicators in model list.

---

## 3. Verification & Quality Gates

### Automated Testing
- New unit and integration test suite: `tests/test_notes_cascade_and_workspace_ux.py`
  - `test_cascade_delete_single_note`: Verified cascade deletion across 10 dependent tables and category count updates.
  - `test_cascade_delete_blocked_when_frozen`: Verified `400 Bad Request` guard when attempting to delete frozen notes.
  - `test_workspace_creation_with_prompt`: Verified Ollama prompt generation and fallback multi-file structure.
  - `test_workspace_models_loaded_introspection`: Verified `/api/ps` parsing and `loaded_models` VRAM flag.
  - `test_classify_notes_endpoint`: Verified targeted notes classification with vault filtering.
  - `test_taxonomy_slug_collision_retry`: Verified agent loop re-prompts on collision and creates unique slug.
  - `test_taxonomy_metadata_enrichment`: Verified provenance metadata serialization in classification prompts.
- Full pytest suite: **155 passed, 0 failures** (2m 47s execution time).
- UI Template verification: `uv run python verify_ui_templates.py` - **0 warnings across 24 templates**.
- Build verification: `uv run python build.py` - package wheel cleanly generated in `dist/`.
- VCS UAT Artifact: Generated and committed in `uat/reports/uat_report_workspace_ux_notes_cascade_taxonomy_20261007_000656.md` and `uat/logs/test_log_workspace_ux_notes_cascade_taxonomy_20261007_000656.log`.
