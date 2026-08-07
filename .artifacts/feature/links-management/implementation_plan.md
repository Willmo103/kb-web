# Implementation Plan - Links Tracking and CLI Ingestion Fixes

This plan details the implementation of a regular webpage link-saving and usage-tracking system, a Chromium HTML bookmarks importer, and fixes for server-side CLI ingestion timeouts.

## User Review Required

> [!NOTE]
> We will add a new database table `links` to store links that are saved without full ingestion. We will also add a dashboard view (`/links`) to manage these links.

---

## Proposed Changes

### Database Layer

#### [MODIFY] [db.py](file:///c:/src/kb-web/src/kb_web/db.py)
- Create `links` table inside `init_db` if it does not exist:
  ```python
  if "links" not in db.table_names():
      db["links"].create(
          {
              "id": int,
              "url": str,
              "title": str,
              "description": str,
              "click_count": int,
              "created_at": str,
              "last_clicked_at": str
          },
          pk="id"
      )
      db["links"].create_index(["url"], unique=True)
  ```

---

### Ingestion & CLI Fixes Layer

#### [MODIFY] [utils.py](file:///c:/src/kb-web/src/kb_web/utils.py)
- Guard the `think` parameter when calling `client.chat()` in `extract_wiki_content` and other functions so it is only passed if `config.ollama_think` is `True`. This ensures backward compatibility with older Ollama server versions.
- Let exceptions bubble up from `extract_wiki_content` and `extract_tags_content` instead of silently returning `"Ingestion Backup"`.
- Restore the `generate_gemma_embeddings_for_page` implementation block.

#### [MODIFY] [cli_api.py](file:///c:/src/kb-web/src/kb_web/routers/cli_api.py)
- Replace circular import `from ..server import _jinja_env` with `from ..base import _jinja_env`.
- Ensure all blocking AI extraction steps in `cli_import_url` run safely.

---

### Links Management Layer

#### [NEW] [links.py](file:///c:/src/kb-web/src/kb_web/routers/links.py)
Create a new router for managing and tracking regular links:
- `GET /links`: Renders the links management dashboard.
- `POST /links/add`: Adds a new regular link.
- `GET /links/go`: Redirects the user to the target link and increments `click_count` and updates `last_clicked_at` in the database.
- `POST /links/delete`: Deletes a link.
- `POST /links/import-bookmarks`: Parses an uploaded Chromium HTML bookmarks file using `BeautifulSoup` and inserts all links.

#### [NEW] [links.j2.html](file:///c:/src/kb-web/src/kb_web/templates/links.j2.html)
- Renders the links dashboard with outfit styling.
- Displays a table/list of links, description, click count, created date, and last clicked date.
- Form to add new link (URL + description).
- Form to upload a Chromium bookmarks `.html` file.
- Uses redirect `/links/go?id=<id>` when clicking links to track usage.

#### [MODIFY] [base.j2.html](file:///c:/src/kb-web/src/kb_web/templates/base.j2.html)
- Add a navigation link to `🔗 Links` (`/links`).

#### [MODIFY] [server.py](file:///c:/src/kb-web/src/kb_web/server.py)
- Import and mount the `links` router.

---

### Verification Plan

### Automated Tests
- Run `.\.venv\Scripts\python.exe -m pytest` to verify the existing unit test suite passes.
- Add new unit tests inside `tests/test_server.py` verifying bookmarks parsing, link creation, redirects tracking, and deletion.

### Manual Verification
- Access the `/links` dashboard, add a regular link, click on it, and verify that the click count updates.
- Export Chromium bookmarks HTML, upload it, and verify imported links are populated.
