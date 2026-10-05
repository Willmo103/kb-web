# User Feedback & Requirements Record

- **Timestamp**: 2026-10-05T12:47:00-05:00
- **Branch**: `feature/admin-batch-delete-and-content-freeze`
- **Related Issues / PR**: Draft PR targeting `development`

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
