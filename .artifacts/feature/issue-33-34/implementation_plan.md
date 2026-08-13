# Implementation Plan - Resolve Issue #33 and #34

This plan addresses:
1. **Issue #33**: Checking for duplicate URLs during import and archiving the existing page if content has changed, bypassing Ollama LLM execution if content is identical.
2. **Issue #34**: Adding a dynamic check on the import page to detect YouTube URLs, show a option to download the video, and handle downloading in parallel in the background during URL import.

## User Review Required

> [!IMPORTANT]
> The implementation updates the `/import/url` GUI stream, `/api/import/html`, `/api/import/page`, the CLI import endpoint `/import/url`, and `ingest_url_sync`. If a duplicate URL is supplied:
> - If content hash has NOT changed, the import process immediately succeeds and skips heavy Ollama extraction.
> - If content HAS changed, it archives the current database row in `page_versions` and runs extraction to create a new page version in `fetched_pages`.
>
> We will also introduce a `download_video` toggle on the import page, defaulting to 'no' but enabling background video download via the existing downloader if set to 'yes'.

## Proposed Changes

### Import Page & UI

#### [MODIFY] [url_import.j2.html](file:///c:/src/kb-web/src/kb_web/templates/url_import.j2.html)
- Add a hidden container (`#videoDownloadDiv`) with radio buttons styled with Tailwind CSS to choose whether to download the video.
- Add an event listener to the `#url` input. When it detects a YouTube URL, it shows the video download radio buttons. If not, it hides them.

---

### Backend Endpoints & Core Logic

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Import `background_video_downloader` from `.pages`.
- Update `handle_url_import` signature to accept `background_tasks: BackgroundTasks` and `download_video: Optional[str] = Form(None)`.
- Inside `handle_url_import`, after fetching the page content, check if the URL already exists in `fetched_pages`.
  - Compare `md_content_hash` of the fetched page with the DB version.
  - If identical, yield a status update, link to the collection (if requested and not linked), trigger background video download if requested, and redirect to the page view.
  - If changed, archive the existing page row to `page_versions` before running LLM extraction and upserting the new page version.
  - Trigger video download in background tasks if `download_video == "yes"`.

#### [MODIFY] [cli_api.py](file:///c:/src/kb-web/src/kb_web/routers/cli_api.py)
- Implement duplicate content check and version archiving in `cli_import_url()`. Skip LLM extraction if content is unchanged.

#### [MODIFY] [api.py](file:///c:/src/kb-web/src/kb_web/routers/api.py)
- Implement duplicate content check and version archiving in `/api/import/html` and `/api/import/page`. Skip LLM extraction if content is unchanged.

#### [MODIFY] [utils.py](file:///c:/src/kb-web/src/kb_web/utils.py)
- Implement duplicate content check and version archiving in `ingest_url_sync()`. Skip LLM extraction if content is unchanged.

---

## Verification Plan

### Automated Tests
- Run `uv run pytest` to ensure existing tests pass.
- Add new unit tests to `tests/test_server.py` verifying duplicate import behavior (same content vs changed content, archiving check).

### Manual Verification
- Start the server (`uv run python build.py` then run the dev server).
- Open the import page, enter a YouTube URL, confirm the "YouTube Video Detected" option appears.
- Choose "Yes, download video" and submit, verifying the streaming progress logs the background download task trigger.
