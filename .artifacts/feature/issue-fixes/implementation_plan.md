# Implementation Plan - Issue Fixes

This plan outlines the changes to resolve the four reported issues on the `kb-web` application, including branch creation, database configuration persistence, server log updates, collections behavior, and offline video badge indicators.

## User Review Required

> [!IMPORTANT]
> 1. **Configuration Migration**: All server configurations will be migrated to the database. We will automatically seed the database tables using the existing config file (`kb-web.json`) or environment variables on the first run.
> 2. **Version Control on Prompts**: Prompt edits in the Admin Portal will now insert a new version into the database and point the HEAD cursor to it, allowing the admin to view historical records and revert to any version with one click.
> 3. **Reverse Log Sorting**: Logs will now display with the most recent lines at the top of the interface and in the downloads.

## Open Questions

There are no open questions. The requirements are fully detailed in the issue descriptions.

## Proposed Changes

---

### Database Layer

#### [MODIFY] [db.py](file:///c:/src/kb-web/src/kb_web/db.py)
- Create `settings_ollama` and `settings_external` tables in `init_db(db)` to group config parameters.
- Create `agent_prompts` table in `init_db(db)` to store versioned prompts.
- Seed default values (or load from current `kb-web.json` file if it exists) during database initialization.

#### [MODIFY] [config.py](file:///c:/src/kb-web/src/kb_web/config.py)
- Modify `Config` getters/setters for settings (`ollama_host`, `ollama_model`, `ollama_embedding_model`, `ollama_think`, `max_input_length`, `api_key`, `gotify_url`, `gotify_token`, `qdrant_host_url`, `qdrant_api_key`, `similarity_threshold`) to query and save to the database settings tables.
- Modify `Config` getters/setters for `wiki_prompt` and `youtube_wiki_prompt` to check the `agent_prompts` table for the row matching `is_head = 1`.

---

### Collection & Importer Updates

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- In the `/import/url` POST handler (`handle_url_import`), change the default visibility of newly created collections from `"private"` to `"public"` so that they are visible on `/collections` dashboard by default.
- In `handle_url_import`, dynamically check whether the ingested page is a video (using `extract_youtube_video_id(page_data.url)`) and write the appropriate `source_type` (`"videos"` or `"articles"`) to `collection_items` rather than hardcoding `"articles"`.

#### [MODIFY] [collections.py](file:///c:/src/kb-web/src/kb_web/routers/collections.py)
- In `/collections` route, pass `all_pages` list to the template (already implemented, but ensure it fetches both articles and videos correctly).

#### [MODIFY] [collections.j2.html](file:///c:/src/kb-web/src/kb_web/templates/collections.j2.html)
- Add a sidebar form block (for admins) to assign any ingested page to a collection, using the `/admin/pages/update-collection` POST endpoint.

#### [MODIFY] [view_page.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html)
- Ensure that the collection details block (badge, "Change Collections" / "Add to Collection" buttons) works for videos. The queries in `pages.py` should be checked to make sure they return correct collection items for videos.

---

### Video Ingestion & Player

#### [MODIFY] [pages.py](file:///c:/src/kb-web/src/kb_web/routers/pages.py)
- In the `/view/page` endpoint (`view_saved_page`), check if the video has been downloaded by verifying if the file exists at the default media path: `config.configs_dir.parent / "media" / "videos" / f"{video_id}.mp4"` in addition to verifying the `local_path` column in `youtube_videos` table.
- Set `is_offline = True` if the file exists, so the video player displays `Saved Offline` and uses the local `<video>` tag instead of the YouTube `<iframe>`.

---

### Server Log View

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Change default logs count from `1000` to `100` in `/admin/logs` endpoint (`get_logs_view`).
- Read the last-selected lines limit from a `log_limit` cookie on the request if the `limit` query param is not specified.
- Set the `log_limit` cookie in the response when the `limit` parameter is explicitly passed.
- Remove the `rows.reverse()` call in both `get_logs_view` and `download_logs` to ensure the most current logs display at the top (reverse sorted).

#### [MODIFY] [logs.j2.html](file:///c:/src/kb-web/src/kb_web/templates/logs.j2.html)
- Update `changeLimit` JavaScript function to store the chosen line count in a `log_limit` cookie.
- Ensure the logs `pre` container displays the reverse sorted lines correctly.

---

### Prompt Version Control & Management

#### [NEW] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Add a new route `@router.post("/admin/prompts/set-head")` that takes `prompt_id` and `prompt_type` and updates the active HEAD prompt.

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- Display collapsible/accordion containers (`<details>`) under prompt input textareas to show past versions of `wiki_prompt` and `youtube_wiki_prompt` with version numbers, timestamps, and a "Use This Version" button.
- Add Javascript function `setPromptHead(id, type)` and a hidden form to submit HEAD changes.

## Verification Plan

### Automated Tests
- Run `uv run pytest` to ensure existing and new tests pass.
- Write unit tests in `tests/test_server.py` covering:
  - Video offline detection when local file is present vs absent.
  - Collections creation via import screen visibility status.
  - Server log reverse sorting, cookies persistence, and default count limits.
  - Configurations database serialization and versioned prompt rollback/HEAD updating.

### Manual Verification
- Launch server locally: `uv run kb-web serve --port 8050 --reload`
- Navigate to `/admin/logs` to confirm sorting, default limits, and cookie remembering works.
- Navigate to `/admin` to modify prompts, view version history, and click `Use This Version` to confirm rollbacks.
- Import a page, select new collection, verify it shows up on `/collections` dashboard and the item has proper collection hierarchy.
