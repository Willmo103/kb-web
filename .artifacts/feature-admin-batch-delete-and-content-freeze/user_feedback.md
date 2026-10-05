# User Feedback & Requirements Record

- **Timestamp**: 2026-10-05T14:18:00-05:00
- **Branch**: `feature/admin-batch-delete-and-content-freeze`
- **Related Issues / PR**: Draft PR #79 targeting `development`

---

## 1. User Requests (Turn 8)

1. **GitHub Actions CI Master Failure Investigation**:
   - Issue: The last push to `master` failed in CI.
   - User Request: Investigate why tests failed using GitHub CLI (`gh`).
   - Findings:
     - CI runs `actions/checkout@v4` without `submodules: recursive`.
     - `kb-web-cli` is a git submodule whose URL was set to a relative path `./kb-web-cli` instead of the public repo `https://github.com/Willmo103/kb-web-cli.git`.
     - `tests/test_cli_auth_and_workspaces.py` and `tests/test_rag_agent_and_reports.py` attempted `from kb_web_cli.main import app as cli_app`, causing `ModuleNotFoundError: No module named 'kb_web_cli'`.
     - Fix: Update `.gitmodules` to full remote URL, update `.github/workflows/test-and-release.yml` with `submodules: recursive`, and add graceful import handling in tests.

2. **Admin Batch-Delete Utility**:
   - User Request: Admin ability to batch-delete whole collections of Obsidian notes, sites, videos, and articles.
   - Requirements:
     - Batch deletion for Notes (by multi-select IDs or folder prefix).
     - Batch deletion for Sites (delete virtual site and cascade all associated pages and embeddings).
     - Batch deletion for Videos (delete video records, embeddings, and video media files).
     - Batch deletion for Pages / Articles (by multi-select IDs or collection cascade).
     - REST API endpoints and Admin Dashboard UI controls with confirmation safeguards.

3. **Frozen & Immutable Content (`is_frozen`)**:
   - User Request: Make any content item (article, note, video) frozen and immutable to changes (no wiki re-generation, tag editing, title/content editing).
   - Requirements:
     - Add `is_frozen = Column(Integer, default=0)` (0 = mutable, 1 = frozen) to `FetchedPage`, `Note`, and `YouTubeVideo`.
     - Enforcement:
       - Prevent wiki generation (`generate_wiki_background` / `/api/pages/{id}/generate-wiki` returns HTTP 400).
       - Prevent tag editing (returns HTTP 400 when frozen).
       - Prevent content/title editing (returns HTTP 400 when frozen).
       - Prevent source re-fetching (returns HTTP 400 when frozen).
     - UI:
       - Render "❄️ Frozen" badge and Freeze/Unfreeze toggle button on article view, note editor, and video profiles.
       - Disable edit buttons when content is frozen.
     - Alembic migration for the new `is_frozen` columns.

---

## 2. User Requests (Turn 9)

1. **Remove Taxonomy Removal Migration**:
   - Issue: The previously added one-time migration (`0a9b8c7d6e5f_one_time_taxonomy_purge.py`) ran automatically on test server startup via `deploy_migrations.py` during `alembic upgrade head`, causing all taxonomy categories, items, and agent taxonomy messages to be wiped out on the test server.
   - User Request: "we need to remove the taxonomy removal.. I just wiped out my test server taxonomy."
   - Resolution:
     - Neutralize `migrations/versions/0a9b8c7d6e5f_one_time_taxonomy_purge.py` `upgrade()` so it performs `pass` and does not delete taxonomy rows.
     - Remove leftover purge logic from `src/kb_web/scripts/deploy_migrations.py`.

2. **Create New Skill: `live-server-test`**:
   - User Request: "I want you to create a skill: Live server test - This uses curl to test out the running production server (its only online while the UAT testing is going) You can reach the test server at https://kb-test.willmo.dev. Don't do any admin stuff, but I want you to audit the site routes."
   - Scope:
     - Target host: `https://kb-test.willmo.dev`
     - Uses `curl` to probe and audit all core site routes (GET/HEAD, status codes, redirects, content types, security headers).
     - Strict guardrail: Read-only audit only; NO admin mutations (no POST/PUT/DELETE, no admin purge/freeze).
     - Document in `.agents/skills/live-server-test/` and `GEMINI.md`.
     - Execute the route audit immediately and report the detailed results.
