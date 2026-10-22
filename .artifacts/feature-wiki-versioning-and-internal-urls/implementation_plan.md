# Implementation Plan: Wiki Versioning & Internal URL Scheme Routing

## Overview
This implementation plan addresses two core requirements:
1. **Wiki Versioning**: Enable versioning of AI-generated and edited wikis (`FetchedPage.description`) whenever a wiki is regenerated (similar to page refetch versioning), with automatic database-level `CASCADE` deletion when the parent content is removed, plus UI version history inspection and restoration.
2. **Internal URL Routing & Dead Link Prevention**: Route synthetic entity schemes like `note://...` directly to the Notes Monaco Editor and `workspace://...` directly to the Workspace IDE, while preventing dead/inert protocol clicks across all templates and rendered Markdown.

---

## User Review Required

> [!IMPORTANT]
> **Key Architectural Decisions**:
> 1. **Dedicated `wiki_versions` Table vs Reusing `page_versions`**:
>    - `page_versions` archives full HTML and markdown content on refetch.
>    - When regenerating an AI wiki, the scraped web page does not change — only the distilled wiki (`description`) and title change.
>    - We introduce a dedicated `wiki_versions` table linked with `ForeignKey("fetched_pages.url", ondelete="CASCADE")` storing `id`, `url`, `title`, `wiki_content`, `model_name`, and `created_at`.
>    - This allows lightweight, fast wiki iterations without duplicating massive HTML blobs.
> 2. **Internal Link Handling (`note://`, `workspace://`)**:
>    - Provide both:
>      - **Server-side URL Dispatcher (`GET /open?url=...`)**: Safely translates entity URLs to their appropriate frontend routes (`/notes/edit?url=...`, `/workspaces/{id}`).
>      - **Template Helper (`resolve_entity_url`)**: Renders dedicated routing badges ("📝 Open Note", "💻 Open Workspace") instead of dead `target="_blank"` links.
>      - **Client-side Global Interceptor**: Intercepts `note://` and `workspace://` inside rendered markdown documents and wikis so user clicks inside content seamlessly route to the corresponding editor or workspace.

---

## Proposed Changes

### 1. Database Schema & ORM (`src/kb_web/models_orm.py`)
- Add `wiki_model = Column(String, nullable=True)` to `FetchedPage`.
- Add `WikiVersion` model:
  ```python
  class WikiVersion(Base):
      __tablename__ = "wiki_versions"

      id = Column(Integer, primary_key=True, autoincrement=True)
      url = Column(String, ForeignKey("fetched_pages.url", ondelete="CASCADE"), nullable=False, index=True)
      title = Column(String)
      wiki_content = Column(Text)
      model_name = Column(String, nullable=True)
      steering_instructions = Column(Text, nullable=True)
      created_at = Column(String)
  ```
- Register `("wiki_versions", "url")` in `ensure_views_and_indexes` index check.
- Add explicit deletion in all deletion controllers (`admin.py:handle_delete_page`, `rest_api.py:delete_single_article`, `admin_batch.py:purge_site_content`, `notes.py:delete_note_api`) to ensure cascade consistency across both PostgreSQL and SQLite.

### 2. Wiki Versioning, Model Selection & Steering Handlers (`src/kb_web/utils.py`, `src/kb_web/routers/admin.py`, `cli_api.py`, `worker.py`)
- In `extract_wiki_content` (`src/kb_web/utils.py`):
  - Add optional parameters `model: Optional[str] = None` and `steering_instructions: Optional[str] = None`.
  - When provided, inject steering instructions into the system prompt and invoke Ollama with the chosen model.
- In `handle_regenerate_wiki` (`POST /admin/regenerate/wiki` in `src/kb_web/routers/admin.py`):
  - Accept form parameters `model: Optional[str] = Form(None)` and `steering_instructions: Optional[str] = Form(None)`.
  - Before overwriting `page.description`, archive existing wiki into `WikiVersion(url=page.url, title=page.title, wiki_content=page.description, model_name=page.wiki_model or config.ollama_model, steering_instructions=..., created_at=...)`.
  - Update `page.description = wiki_entry`, `page.title = title`, and `page.wiki_model = effective_model`.
- In `handle_refetch_page` (`POST /admin/refetch`):
  - Archive existing `page.description` to `WikiVersion` alongside `PageVersion`.
- Add `POST /admin/wiki/restore`:
  - Accepts `url: str`, `version_id: int`.
  - Replaces current `page.description`, `page.title`, and `page.wiki_model` with the archived version, archiving current state as a new version.
- In `cli_api.py` (`cli_update_wiki`):
  - Archive current wiki before updating.


### 3. URL Resolution & Dispatch Service (`src/kb_web/base.py`, `src/kb_web/routers/pages.py`)
- In `src/kb_web/base.py`:
  - Add `resolve_entity_url(url: str) -> dict`:
    - Checks for `note://` -> target `/notes/edit?url={quote_plus(url)}`, label `📝 Open Note`.
    - Checks for `workspace://{id}/...` -> target `/workspaces/{id}`, label `💻 Open Workspace`.
    - Checks for `http://` / `https://` -> target `url`, label `↗️ Visit`.
    - Non-clickable fallback for unsupported or unknown protocols.
  - Register `resolve_entity_url` in Jinja globals.
- In `src/kb_web/routers/pages.py`:
  - Add `GET /open`:
    - Dispatches `note://` to notes editor, `workspace://` to workspace IDE, `http/https` to external page.
  - In `view_page`:
    - Query `wiki_versions` for the current article.
    - Support `wiki_version_id` query param to render a historical wiki version with a "Restore" button.

### 4. Template & Client-Side Interceptor (`templates/base.j2.html`, `view_page.j2.html`, `pages_list.j2.html`)
- In `base.j2.html`:
  - Add global click listener intercepting `note://` and `workspace://` links in rendered Markdown/HTML bodies, smoothly routing them to `/notes/edit?url=...` and `/workspaces/{id}`.
- In `view_page.j2.html`:
  - Display the "Target:" URL using `resolve_entity_url(page.url)`. If it is a Note or Workspace, render an action button to open the note editor or workspace instead of an external link.
  - **Generating Model Attribution Badge**: Display the model that generated the current wiki (e.g. `🤖 Model: {page.wiki_model or 'Default LLM'}`) directly above the wiki content.
  - **On-the-Fly Model Selection & Steering Modal**:
    - Convert "🔄 Regenerate Wiki" button to open an interactive modal (`openRegenerateWikiModal()`).
    - Modal provides an Ollama completion model dropdown (pre-selected with active model or current wiki model) and a multi-line steering instructions textarea.
    - Form posts `model` and `steering_instructions` to `/admin/regenerate/wiki`.
  - **Wiki Version History**:
    - Display a dedicated **Wiki Version History** selector if multiple wiki versions exist, showing each version's timestamp, generating model name, and active version indicator.
    - When inspecting an archived wiki version (`?wiki_version_id=...`), show an alert banner with "Viewing Archived Wiki Version (from {timestamp}, Model: {model_name}) — [Restore this Version] [Back to Current]".
- In `pages_list.j2.html`:
  - In article card secondary links, use `resolve_entity_url(page.url)` to show "📝 Note" or "💻 Workspace" links rather than broken outbound links.

---

## Verification Plan

### Automated Unit Tests
- Create `tests/test_wiki_versions_and_url_routing.py`:
  - `test_wiki_version_creation_and_cascade_delete`: Verify `WikiVersion` records are created and cascade-deleted when `FetchedPage` is deleted.
  - `test_regenerate_wiki_archives_previous_version`: Verify regenerating a wiki archives the prior wiki.
  - `test_restore_wiki_version`: Verify restoring a previous wiki version updates `page.description`.
  - `test_open_redirect_endpoints`: Verify `/open?url=note://...` routes to `/notes/edit` and `/open?url=workspace://123/...` routes to `/workspaces/123`.
  - `test_resolve_entity_url_helper`: Test internal URL parsing, workspace ID extraction, and non-http disabling.
- Run dedicated test: `uv run pytest tests/test_wiki_versions_and_url_routing.py`.
- Run full test suite: `uv run pytest`.
- Run pre-commit build pipeline: `uv run python build.py`.

### Documentation & Git Delivery
- Update `CHANGELOG.md` under `[0.5.11]` documenting wiki versions and internal link routing.
- Commit all changes to `feature/wiki-versioning-and-internal-urls`.
- Merge and push to `development`.
