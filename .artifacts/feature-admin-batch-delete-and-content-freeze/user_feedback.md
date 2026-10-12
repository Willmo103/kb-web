# User Feedback & Requirements Record

- **Timestamp**: 2026-10-05T15:25:00-05:00
- **Branch**: `feature/admin-batch-delete-and-content-freeze`
- **Related Issues / PR**: Draft PR #79 targeting `development`

---

## 1. User Requests (Turn 8)

1. **GitHub Actions CI Master Failure Investigation**:
   - Issue: The last push to `master` failed in CI.
   - User Request: Investigate why tests failed using GitHub CLI (`gh`).
   - Resolution: Update `.gitmodules` to full remote URL, update `.github/workflows/test-and-release.yml` with `submodules: recursive`, and add graceful import handling in tests.

2. **Admin Batch-Delete Utility**:
   - User Request: Admin ability to batch-delete whole collections of Obsidian notes, sites, videos, and articles.

3. **Frozen & Immutable Content (`is_frozen`)**:
   - User Request: Make any content item (article, note, video) frozen and immutable to changes.

---

## 2. User Requests (Turn 9)

1. **Remove Taxonomy Removal Migration**:
   - User Request: "we need to remove the taxonomy removal.. I just wiped out my test server taxonomy."
2. **Create New Skill: `live-server-test`**:
   - User Request: "I want you to create a skill: Live server test - This uses curl to test out the running production server (its only online while the UAT testing is going) You can reach the test server at https://kb-test.willmo.dev. Don't do any admin stuff, but I want you to audit the site routes."

---

## 3. User Requests (Turn 10)

1. **Add Migration Back In & Fix `item_class` Undefined Column**:
   - Issue: App crashed with:
     `(psycopg2.errors.UndefinedColumn) column taxonomy_items.item_class does not exist`
     when accessing `GET /taxonomy`.
   - User Request: "okay add the migration back in,. it broke the hell out of the app."
   - Analysis:
     - The taxonomy purge in `0a9b8c7d6e5f_one_time_taxonomy_purge.py` needs to be restored so corrupt/test classification states can be cleaned.
     - Additionally, the PostgreSQL schema is missing the `item_class` column on `taxonomy_items` because `ensure_views_and_indexes` was only checking PRAGMA for SQLite, not PostgreSQL!
   - Solution:
     - Restore `0a9b8c7d6e5f_one_time_taxonomy_purge.py` purge statements.
     - Add explicit column checks in PostgreSQL initialization within `models_orm.ensure_views_and_indexes`:
       `ALTER TABLE taxonomy_items ADD COLUMN IF NOT EXISTS item_class VARCHAR(32) DEFAULT 'Notes';`
       `ALTER TABLE fetched_pages ADD COLUMN IF NOT EXISTS is_frozen INTEGER DEFAULT 0;`
       `ALTER TABLE notes ADD COLUMN IF NOT EXISTS is_frozen INTEGER DEFAULT 0;`
       `ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS is_frozen INTEGER DEFAULT 0;`
     - Add migration ensuring `item_class` exists on `taxonomy_items`.

2. **Persistent Error Storage on Server for Debugging**:
   - User Request: "ALSO i need these error messages (sent to gotify) to be stored on the server in a way that you can view them for debugging. this could be a CLI route idk"
   - Requirements:
     - Intercept uncaught server exceptions in `gotify_error_logging_handler` / `post_error_to_gotify`.
     - Persist structured error logs to `server_error_logs` table (ORM `ServerErrorLog`) and append to `~/.kb/logs/server_errors.jsonl`.
     - Fields: `id`, `timestamp`, `error_type`, `error_message`, `stack_trace`, `request_method`, `request_url`, `query_params`, `client_ip`, `agent_feedback`.
     - Expose REST API: `GET /api/errors`, `GET /api/errors/{id}`, `GET /api/errors/search`.
     - Expose CLI commands: `kb-web-cli error list`, `kb-web-cli error view <id>`, `kb-web-cli error search <term>`.
     - Expose Admin UI view: In `/admin/logs` or dedicated tab.

3. **Background Sidecar Maintenance Agent**:
   - User Request: "I need errors to trigger the agent to give imeadiate feedback before I even get to fixing it. e.g. I want to have an agent that is for maintaining the website. I want to give it a tool to search the source code. I want it to have a tool to view the artifacts. I wantto have it auto prompted with errors (limit it to 3000 characters and give it a tool to search the errors for terms) this should all be a side car thing that can run in the background."
   - Requirements:
     - Sidecar architecture: Can run in background via daemon process or FastAPI background queue.
     - Auto-prompt on error: Truncates error details to 3000 characters and triggers maintenance agent analysis.
     - Tools provided to Maintenance Agent:
       1. `search_source_code`: searches files in `src/kb_web`, `tests/`, `migrations/` for symbols, classes, or patterns.
       2. `view_artifacts`: views markdown plans, walkthroughs, UAT reports, and feedback artifacts.
       3. `search_errors`: searches historical server error logs for terms.
     - Stores generated diagnostic feedback directly back onto the `ServerErrorLog` record and/or dispatches to Gotify.
