# User Feedback Record - Collections Latency Optimization

**Date**: 2026-09-13
**Branch**: `feature/collections-performance`
**Author**: Will Morris / Agent

---

## 1. User Feedback Summary

During User Acceptance Testing (UAT) on the testing server (`http://192.168.0.32:8051`):
1. **Closing Previous Issue**:
   - The user confirmed that Issue #56 was verified and ready to be closed.
   - The development branch `feature/ui-performance-api` was verified and merged into `production`.
2. **New Latency Bottleneck Found on `/collections`**:
   - Navigating to `/collections` exhibited an unacceptable latency of **11.77+ seconds** waiting for server response (`Waiting for server response: 11.77 s`).
   - Response size was **256,181 bytes** (256 KB) of raw HTML.
   - UI shows **153 Ungrouped Pages** in a scrollable list, each with an "Organize" button.
   - The administrative user also has access to the "Assign Item" dropdown, which contains a select element of all items.

## 2. Screenshots Provided

1. **Network Header Details**:
   - Request URL: `http://192.168.0.32:8051/collections`
   - Method: `GET`
   - Status: `200 OK`
   - Content-Length: `256181`
   - Server: `uvicorn`
   - Cookie: `kb_session=...` (Authenticated as Admin)
2. **Request Timing Breakdown**:
   - Queueing: 8.61 ms
   - Connection start: 1.44 ms
   - Waiting for server response (TTFB): **11.77 s**
   - Content download: 2.64 ms
   - Total: **11.79 s**
3. **UI Appearance**:
   - `UNGROUPED PAGES (153)` list with title, URL, and "Organize" button for each page.

## 3. Required Action Items

1. Create a GitHub issue on `master` documenting the `/collections` 11.7s latency regression.
2. Associate the issue with the open Draft PR from `production` into `master` (PR #57).
3. Thoroughly analyze and profile the queries executed in `GET /collections` (`src/kb_web/routers/collections.py`).
4. Replace full-table scans and eager loading of heavy columns (`html_content`, `md_content`, `text_content`) with lightweight projections or paginated / reactive endpoints.
5. Optimize the "Ungrouped Pages" and "Assign Item" dropdown rendering so the response is fast (<100-200ms).
6. Verify against PostgreSQL test database and ensure all unit tests and build checks pass.
