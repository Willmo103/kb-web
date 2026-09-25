# Implementation Plan - Webpage URL Crawl Discovery, Interactive Selection, & AI Pre-Checking

This plan introduces an interactive URL crawler that allows users to discover candidate links on a webpage first, review and select them using a selection interface, optionally use AI to pre-select high-value content links via structured LLM output, and enqueue the selected URLs for batch scraping.

Resolves [Issue #60](https://github.com/Willmo103/kb-web/issues/60) associated with Draft PR [#57](https://github.com/Willmo103/kb-web/pull/57).

## User Review Required

> [!IMPORTANT]
> - **Selection Controls**: The UI will provide multi-select checkboxes by default with a "Select All / Invert / Deselect" bar and search filter, alongside a single-choice mode if only one URL from the crawl should be ingested.
> - **AI Pre-Checking**: Uses Ollama with structured JSON schema (`format="json"`) to evaluate link value, separating substantive articles/docs from boilerplate (TOS, privacy, login, social).
> - **Batch Scraping Execution**: Selected URLs can be ingested asynchronously via `BackgroundTasks` with live database status updates and optional Gotify notifications.

## Open Questions

- Would you prefer the AI pre-check to prioritize **only documentation/articles** by default, or should we include a text input field where you can specify an optional crawl topic/objective (e.g., *"only select blog posts about transformers"* or *"only select API reference pages"*)?
- When starting the scrape for selected URLs, would you prefer a **background batch queue** (allowing you to continue browsing) with Gotify notification on completion, or a **live streaming progress modal**? (We plan to support both: live progress when initiated from the importer, and background processing for large batches).

## Proposed Changes

---

### Component: Backend Crawler & AI Discovery Endpoints

#### [NEW] [crawler.py](file:///c:/src/kb-web/src/kb_web/crawler.py)
Create a dedicated link extraction and candidate analysis module:
- `extract_candidate_links(seed_url: str, same_domain: bool = True, max_links: int = 200) -> tuple[str, list[dict]]`:
  - Fetches seed page HTML via `httpx`.
  - Parses `<a>` tags with BeautifulSoup, extracting text and `href`.
  - Normalizes relative links using `urljoin`.
  - Strips URL fragments (`#...`) and query trackers.
  - Filters out protocols like `mailto:`, `javascript:`, `tel:`.
  - Cross-references against `FetchedPage` table to mark `already_ingested: bool`.
- `ai_curate_candidate_links(seed_url: str, page_title: str, links: list[dict], topic_hint: Optional[str] = None, client=None) -> dict`:
  - Calls Ollama with structured JSON schema (`format="json"`).
  - Prompts model to categorize and select high-value substantive content URLs while filtering out utility/navigational links.
  - Returns selected URL list and curation reasoning.

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
Add dedicated API endpoints under `/api/crawl/`:
- `POST /api/crawl/discover`:
  - Receives `url`, `same_domain_only: bool`.
  - Calls `extract_candidate_links` and returns JSON payload of discovered candidate links.
- `POST /api/crawl/ai-filter`:
  - Receives list of discovered links, page title, and optional topic prompt.
  - Calls `ai_curate_candidate_links` and returns AI-recommended URLs and reasoning.
- `POST /api/crawl/enqueue`:
  - Receives `urls: list[str]`, `collection_id: Optional[int]`, `new_collection_title: Optional[str]`.
  - Enqueues batch scraping in background tasks, reporting immediate success with total queued.

---

### Component: UI & Templates

#### [MODIFY] [url_import.j2.html](file:///c:/src/kb-web/src/kb_web/templates/url_import.j2.html)
- Add a two-tab navigation at the top of the Wiki Importer:
  - **Single Page Ingest** (existing mode)
  - **🕷️ Crawl & Discover** (new interactive discovery mode)
- In the Crawl & Discover view:
  - **Seed URL input** with "🔍 Discover Links" button and "Same Domain Only" toggle.
  - **Interactive Candidate Links Section**:
    - Sticky toolbar with:
      - "Select All", "Deselect All", "Select New Only" buttons.
      - Live search filter input.
      - **"🤖 AI Pre-Select" button** with pulse loading animation.
      - Selection counter: `Selected: X / Y links`.
    - Discovered links table/card list:
      - Checkbox for each candidate.
      - Clean link title + anchor text + domain badge.
      - Visual indicator for `Already in Library` vs `New`.
      - Direct preview icon (opens link in new tab).
    - AI Explanation banner showing LLM reasoning when AI pre-check is triggered.
    - Target Collection dropdown selector.
    - **"🚀 Scrape Selected URLs (X)"** submission button.

#### [MODIFY] [view_page.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html)
- Update the "Recursive Web Crawl" modal button on wiki pages to offer "Discover & Select Links" directly, launching the discovery interface prefilled with the current page URL.

---

## Verification Plan

### Automated Tests
- Create dedicated unit test file `tests/test_crawler.py`:
  - `test_extract_candidate_links`: Verify link extraction, normalization, deduplication, and database existence flagging.
  - `test_api_crawl_discover`: Verify `/api/crawl/discover` endpoint with mock HTML.
  - `test_api_crawl_ai_filter`: Test AI structured JSON prompt execution and response parsing with mocked Ollama client.
  - `test_api_crawl_enqueue`: Test batch queue endpoint and collection assignment.
- Run complete test suite:
  ```powershell
  uv run pytest tests/test_crawler.py
  uv run pytest
  ```
- Run pre-commit checks:
  ```powershell
  uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py
  uv run python build.py
  ```

### Manual Verification
- Test entering a documentation site URL (e.g. `https://fastapi.tiangolo.com/tutorial/`).
- Click "Discover Links" and confirm list of ~50 candidate URLs renders with titles and domains.
- Click "🤖 AI Pre-Select" and confirm high-value tutorial links are checked while github/social/TOS links are unchecked.
- Select/unselect individual links.
- Submit to queue and verify pages are ingested cleanly into the chosen collection.
