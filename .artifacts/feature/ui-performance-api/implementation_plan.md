# Cascade Deletion Fix, Ghost Stub Purge, & Graceful Error Handling

Resolves Issue #56: Fixes the database foreign key violation preventing deletion of articles and YouTube videos, purges resurrected dummy stubs (`Archived Item`), and handles deletion errors gracefully in the UI.

---

## User Review Required

> [!IMPORTANT]
> - **Cascade Deletion Across Child Tables**:
>   When an administrator deletes an article or YouTube video via `/admin/delete/page` or `DELETE /api/articles`, the handler will delete records from dependent tables in correct dependency order before deleting `fetched_pages`:
>   1. `article_embeddings` (`url`)
>   2. `title_embeddings` (`url`)
>   3. `video_embeddings` (`url`)
>   4. `chunk_embeddings` (`source_id`)
>   5. `youtube_videos` (`url`)
>   6. `collection_items` (`source_id`)
>   7. `collection_actions` (`source_id`)
>   8. `page_versions` (`url`)
>   9. `links` (`url`)
>   10. `fetched_pages` (`url`)
>   This eliminates PostgreSQL `ForeignKeyViolation` exceptions completely.
>
> - **Purging Resurrected "Archived Item" Ghost Stubs**:
>   The 22 items appearing in Screenshot #1 titled `Archived Item (<url>)` were synthesized during migration because orphaned embeddings existed in SQLite from previously deleted pages. We will:
>   1. Update `vw_page_cards` view to exclude stubs with no HTML and no markdown content.
>   2. Provide automated database cleanup in `ensure_views_and_indexes()` to purge orphaned stubs where `title LIKE 'Archived Item (%'` and both `html_content` and `md_content` are NULL.
>   3. Update `db_migrate_sqlite.py` and `admin.py` WebSocket import to prune orphaned child records rather than synthesizing dummy parent pages.
>
> - **Graceful Deletion Feedback**:
>   Eliminates raw JSON responses (`{"detail":"Target page profile not found."}`) on form submissions. On failure, redirects to `/?error=...` with a visible, dismissible UI banner. On success, redirects to `/?msg=...`.

---

## Proposed Changes

### 1. Administrative Delete Handler & REST API

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Refactor `handle_delete_page`:
  - Handle URL decoding (`unquote_plus(url)`).
  - Delete child rows across `article_embeddings`, `title_embeddings`, `video_embeddings`, `chunk_embeddings`, `youtube_videos`, `collection_items`, `collection_actions`, `page_versions`, `links`, and finally `fetched_pages`.
  - Replace `raise HTTPException(status_code=404, detail="Target page profile not found.")` with graceful redirect:
    `RedirectResponse(url=f"/?error={quote_plus('Failed to delete entry: ' + str(err))}", status_code=303)`.
  - On success, redirect to `/?msg=Entry+successfully+deleted.`

#### [MODIFY] [rest_api.py](file:///c:/src/kb-web/src/kb_web/routers/rest_api.py)
- Add `DELETE /api/articles`:
  - Accepts `url: str = Query(...)`.
  - Performs clean cascade deletion and returns `{ "status": "success", "url": url }`.

---

### 2. Database View & Migration Cleanup

#### [MODIFY] [models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py)
- Update `vw_page_cards` definition in `ensure_views_and_indexes()`:
  - Add `WHERE (f.title NOT LIKE 'Archived Item (%' OR (f.html_content IS NOT NULL AND f.html_content != '') OR (f.md_content IS NOT NULL AND f.md_content != '') OR (y.video_id IS NOT NULL AND y.duration IS NOT NULL))`
- In `ensure_views_and_indexes(engine)`:
  - Add routine to clean up orphaned ghost records where `f.title LIKE 'Archived Item (%'` and `html_content IS NULL` and `md_content IS NULL`.

#### [MODIFY] [db_migrate_sqlite.py](file:///c:/src/kb-web/src/kb_web/scripts/db_migrate_sqlite.py)
- Remove synthesis of `Archived Item ({url_val})` stubs. If `parent` does not exist in `fetched_pages`, skip importing orphaned child records to prevent resurrecting deleted pages.

---

### 3. UI Template Enhancements

#### [MODIFY] [pages_list.j2.html](file:///c:/src/kb-web/src/kb_web/templates/pages_list.j2.html)
- Ensure both `msg` and `error` query parameters render styled dismissible alert toasts at the top of the dashboard.

---

### 4. Verification & Testing

#### [NEW / MODIFY] [test_server.py](file:///c:/src/kb-web/tests/test_server.py) & [test_rest_api.py](file:///c:/src/kb-web/tests/test_rest_api.py)
- Add regression tests:
  - Cascade deletion of page associated with YouTube video and embeddings.
  - Deletion failure graceful redirect without raw JSON.
  - Ghost stub exclusion from `vw_page_cards`.

---

## Verification Plan

### Automated Tests
- Run `uv run pytest tests/test_rest_api.py`
- Run `uv run pytest tests/test_server.py`
- Run full pytest suite `uv run pytest` (59+ tests passing)
- Run `uv run python build.py`

### Manual / Browser Verification
- Test deletion of YouTube video page and article page.
- Verify `/?error=...` displays clean alert banner in UI instead of raw JSON.
- Verify `vw_page_cards` no longer shows ghost `Archived Item` cards.
