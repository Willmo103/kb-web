# Implementation Plan: Full-Stack Remediation & Development Branch Release

## 1. Executive Summary
- **Goal**: Systematically remediate all 18 identified issues across backend Python services, Jinja2 templates, and client-side JavaScript controllers on the active branch `feature/taxonomic-fact-extraction-mesh`.
- **Target Release**: Run full pre-commit verification (`uv run pytest`, `uv run python build.py`), update `CHANGELOG.md` and documentation, and push the verified changes to the `development` branch as directed.

---

## 2. Proposed Changes & Remediation Slices

### Slice 1: High-Severity Security Fixes
1. **`SEC-02` (Global Layout Stored XSS in `base.j2.html`)**:
   - Location: [`src/kb_web/templates/base.j2.html:732, 770`](file:///c:/src/kb-web/src/kb_web/templates/base.j2.html#L732-L770)
   - Add a robust `escapeHtml(str)` utility function in the `<script>` block of `base.j2.html`.
   - Sanitize `n.message` and `message` before HTML string concatenation in notification items and toast popups.
2. **`SEC-03` (Stored XSS in Agent Wiki & Themed Pages)**:
   - Location: [`src/kb_web/routers/agent_pages.py:107-113, 174-180`](file:///c:/src/kb-web/src/kb_web/routers/agent_pages.py#L107-L113)
   - Import `sanitize_html` from `..utils` (or `pages.py`).
   - Wrap `markdown.markdown()` output with `sanitize_html(rendered_body)` before template rendering for both topic wikis and themed canvas pages.
3. **`SEC-01` (Unescaped f-string Queries in `config.py`)**:
   - Location: [`src/kb_web/config.py:719-726`](file:///c:/src/kb-web/src/kb_web/config.py#L719-L726)
   - Replace raw f-strings with parameterized query bindings (`?` parameter placeholder).
4. **`SEC-04` (DOM XSS & Attribute Breakout in Collection & Import Views)**:
   - Locations: [`src/kb_web/templates/view_collection.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/view_collection.j2.html#L338), [`collection_editor.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/collection_editor.j2.html#L422), [`url_import.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/url_import.j2.html#L599)
   - Escape URLs in HTML attributes using `escapeHtml()` and replace inline `onclick="removeSingleItem('${item.url}')"` with dataset lookups or URL-encoded parameters.

### Slice 2: Correctness & Logic Fixes
5. **`BUG-01` (Worker Embedding Refresh Infinite Loop)**:
   - Location: [`src/kb_web/worker.py:452-462`](file:///c:/src/kb-web/src/kb_web/worker.py#L452-L462)
   - Add subquery filter so `_run_embedding_refresh` selects pages lacking chunk embeddings for the active model:
     `subq = select(ChunkEmbedding.source_id).where(ChunkEmbedding.model_name == job.model)`
     `session.query(FetchedPage).filter(FetchedPage.url.not_in(subq)).order_by(FetchedPage.fetched_at.asc()).first()`
6. **`BUG-02` (Workspace IDE Atomic Folder Deletion)**:
   - Location: [`src/kb_web/templates/workspace_ide.j2.html:1201-1209`](file:///c:/src/kb-web/src/kb_web/templates/workspace_ide.j2.html#L1201-L1209)
   - Replace client-side multi-file deletion loop with a single atomic call passing `folderPath` to `DELETE /api/workspaces/{id}/files` with proper `try...catch` error handling.
7. **`BUG-03` (Jinja Highlighter Lifecycle & Filter Regex)**:
   - Location: [`src/kb_web/static/js/jinja_highlighter.js:98-105, 260`](file:///c:/src/kb-web/src/kb_web/static/js/jinja_highlighter.js#L98-L105)
   - Add `destroy()` method to disconnect `ResizeObserver` and remove the `window` resize event listener.
   - Update parameter regex to allow filter pipes: `/\{\{\s*([a-zA-Z0-9_.]+)(?:\s*\|[^}]+)?\s*\}\}/g`.
8. **`BUG-04` (Admin Portal Highlighter Load Race)**:
   - Location: [`src/kb_web/templates/admin.j2.html:1660, 2647`](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html#L1660)
   - Relocate `<script src="/static/js/jinja_highlighter.js"></script>` into the `extra_head` block so it executes before inline script initialization.

### Slice 3: Performance & Configuration Cleanups
9. **`CONF-01` (SQLAlchemy 2.0 `declarative_base` Warning)**:
   - Location: [`src/kb_web/models_orm.py:7`](file:///c:/src/kb-web/src/kb_web/models_orm.py#L7)
   - Import `declarative_base` from `sqlalchemy.orm` instead of `sqlalchemy.ext.declarative`.
10. **`PERF-01` (Startup Ghost Stub Purge Optimization)**:
    - Location: [`src/kb_web/models_orm.py:867-884`](file:///c:/src/kb-web/src/kb_web/models_orm.py#L867-L884)
    - Consolidate per-row deletion loop into set-based `DELETE FROM ... WHERE url IN (SELECT url FROM fetched_pages WHERE title LIKE 'Archived Item (%%')`.
11. **`PERF-02` (Notes Vault Zip Batch Commit)**:
    - Location: [`src/kb_web/routers/notes.py:385-411`](file:///c:/src/kb-web/src/kb_web/routers/notes.py#L385-L411)
    - Batch all note additions into a single session commit for the entire zip archive.
12. **`PERF-03` (Taxonomy Notes Classification Query Optimization)**:
    - Location: [`src/kb_web/routers/taxonomy.py:175-180`](file:///c:/src/kb-web/src/kb_web/routers/taxonomy.py#L175-L180)
    - Exclude classified notes directly in SQL using `NOT IN (SELECT item_id FROM taxonomy_items WHERE item_type = 'note')`.

### Slice 4: Deprecations & Migration Guardrails
13. **`DEPR-01`**: Add `@deprecated` docstrings and runtime deprecation warnings to [`src/kb_web/taxonomy_state_machine.py`](file:///c:/src/kb-web/src/kb_web/taxonomy_state_machine.py) pointing developers to `TaxonomyEngine` and `taxonomy_entities`.
14. **`DEPR-02`**: Mark `article_embeddings`, `title_embeddings`, and `video_embeddings` in [`src/kb_web/models_orm.py`](file:///c:/src/kb-web/src/kb_web/models_orm.py) as legacy/deprecated in favor of `chunk_embeddings` and `context_statements`.
15. **`DEPR-03`**: Mark `get_db()` in [`src/kb_web/db.py`](file:///c:/src/kb-web/src/kb_web/db.py) with deprecation warnings.

---

## 3. Verification & Push Workflow
1. Run dedicated test suite: `uv run pytest tests/test_taxonomic_fact_extraction.py`.
2. Run full test suite: `uv run pytest`.
3. Run gated build pipeline: `uv run python build.py`.
4. Update `CHANGELOG.md` with all fixes and deprecation notices.
5. Merge / push branch increment into `development`.
