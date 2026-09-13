# User Feedback - UI Performance Evaluation, Pagination, & API Overhaul

## User Prompt & Feedback (Turn 1)
> "After the recent database migration the web UI is preforming much slower. I think that we need a UI overhaul. introducing pagination and reactive elements. Possibly shifting the backend to an API structure and the frontend to consume the API. I would also like to be able to use more of the routes as API routes for other applications like fetching articles or video transcripts, etc .
> 
> Evaluate how we can speed up the UI. Specifically the loading of the main page is the most laitent, I think it's because it is loading all of the articles.
> 
> I think that creating a database view or stored procedures to fetch and pre-process data might be an answer"

## User Feedback (Turn 2)
> "This all needs to be documented in an issue on the master branch before you start. The development should take place on a new branch of production. a new DRAFT pr should be opened from production into master (but not closed) Issues should be associated with the draft PR. 
> 
> Also we are phasing out the SQLITE support"

## Directives & Execution Constraints

1. **Document in an Issue on the `master` Branch**:
   - Check out `master`.
   - Document the issue in `issues.md` on `master` and commit/push.
   - Create the tracking issue in GitHub (`gh issue create`).

2. **Branching Strategy**:
   - Branch off `production`: Create feature branch `feature/ui-performance-api`.
   - All feature implementation, views, API routes, and reactive UI components will be developed on this branch.

3. **Draft Pull Request**:
   - Open a DRAFT Pull Request from `production` into `master` using `gh pr create --draft --base master --head production`.
   - Associate the newly created issue with the draft PR.
   - Keep the PR open (do NOT close or merge).

4. **Phasing Out SQLite Support**:
   - The architecture is shifting away from SQLite to PostgreSQL as the single standard production database engine.
   - Database views can leverage native PostgreSQL features (such as `string_agg` for collection aggregation, robust index scans, and JSON operators) without needing SQLite fallback parity.

## User Feedback (Turn 3)
> "This screen shot is from the test server. It is showing items that were previously deleted, before the migration, as articles which I cannot delete. 
> 
> the same thing is true for youtube videos that have been deleted, they are showing up as cards that can not be deleted.
> 
> Screenshot #2 is of the attempt to delete the page. It just returns a raw JSON that sates: `{"detail":"Target page profile not found."}` 
> 
> I think that something about the database logic is picking up the deleted pages. you need to check your logic and look for a bool that flags something as deleted. 
> 
> also the delete failure needs to be gracefully handled."

### Root Cause Analysis & Directives
1. **Foreign Key Integrity Violation in `handle_delete_page`**:
   - `handle_delete_page` in `src/kb_web/routers/admin.py` runs `session.query(FetchedPage).filter_by(url=url).delete()` before deleting child records, and never deletes records from `youtube_videos`, `video_embeddings`, `chunk_embeddings`, `collection_items`, or `collection_actions`.
   - In PostgreSQL, foreign keys (`youtube_videos_url_fkey`, `article_embeddings_url_fkey`, `collection_items_source_id_fkey`) reject deleting `fetched_pages` while child rows exist.
   - The handler caught the exception and blindly raised `HTTPException(status_code=404, detail="Target page profile not found.")`, returning raw JSON to the browser and rolling back the transaction.
2. **Resurrected Ghost Stubs (`title = 'Archived Item (...)'`)**:
   - In the legacy SQLite database, foreign keys were not enforced on deletion, leaving orphaned rows in `article_embeddings`, `title_embeddings`, `youtube_videos`, and `video_embeddings`.
   - During migration (`db_migrate_sqlite.py` and `admin.py` WebSocket import), placeholder records titled `Archived Item ({url})` with `NULL` content were created to satisfy PostgreSQL foreign keys.
   - These ghost stubs have no html, no markdown, and no description, but are picked up by `vw_page_cards`.
3. **Execution Directives**:
   - Fix `handle_delete_page` to cascade delete across all child tables in correct dependency order before removing `FetchedPage`.
   - Gracefully handle any deletion errors by redirecting with an alert banner instead of crashing with raw JSON.
   - Filter out orphaned / ghost stubs (`title LIKE 'Archived Item (%'` with null content) in `vw_page_cards` and provide an automatic purge / migration cleanup.
   - Update `db_migrate_sqlite.py` and `admin.py` to discard orphaned child records instead of synthesizing dummy `FetchedPage` records.
