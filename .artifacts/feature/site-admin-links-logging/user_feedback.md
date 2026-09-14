# User Feedback Record - Site, Admin, Links & Logging Fixes

**Date**: 2026-09-13
**Branch**: `feature/site-admin-links-logging`
**Author**: Will Morris / Agent

---

## 1. User Feedback Summary

During UAT testing on the live/test environment (`https://kb.willmo.dev` and local test server):
1. **Virtual Site Page Latency & Tag Display Misconfiguration**:
   - Navigating to virtual site pages (e.g. `/view/site?domain=youtu.be`) has a high latency of **7.61+ seconds** waiting for server response.
   - Tags on the site page are rendered in a severely corrupted manner: each individual character and quote/bracket is displayed in its own tag pill (e.g. `[ " a i s a f e t y " , " g e n e r a t i v e a i " ... ]`).
2. **Admin Dashboard Latency**:
   - Navigating to `/admin` takes **7.92+ seconds** waiting for server response (cfOrigin: 7.75s).
3. **`/links` 500 Internal Server Error**:
   - Navigating to `/links` returns a **500 Internal Server Error** ("Internal Server Error. An unexpected error occurred. Logged to admin console.").
4. **Server Logging Broken**:
   - The user cannot diagnose errors because live server details are not being logged to the database or displayed on the Web UI.
   - The log viewer only displays Alembic and testing messages (e.g. `[2026-09-13T21:43:33.441602] INFO in plugins: setup plugin alembic.ext.checkconstraint_byname`). Live HTTP requests, route execution times, and 500 error stack traces are absent from the database log table / UI.

## 2. Screenshot Telemetry & Evidence

1. **Screenshot 1 (`youtu.be` site profile)**:
   - Profile of 58 ingested pages under domain `youtu.be`.
   - Tags displayed as individual characters in separate pills.
2. **Screenshot 2 (Network timing for site view)**:
   - Waiting for server response: **7.61 s**
   - Content download: 548.26 ms
   - Total: 8.17 s
3. **Screenshot 3 (Headers for `/links`)**:
   - URL: `https://kb.willmo.dev/links`
   - Method: `GET`
   - Status: `500 Internal Server Error`
   - Server: `cloudflare`
   - cfOrigin: 1419 ms
4. **Screenshot 4 (Browser view for `/links`)**:
   - "Internal Server Error. An unexpected error occurred. Logged to admin console."
5. **Screenshot 5 (Network timing for `/admin`)**:
   - URL: `/admin`
   - Waiting for server response: **7.92 s**
   - Total: 8.14 s
6. **Log Excerpt Provided**:
   - Only alembic plugin setup messages are present in `system_logs`. No application-level or request-level logs recorded.

## 3. Required Action Items

1. Open a GitHub issue on `master` documenting these 4 interrelated issues.
2. Associate the issue with the open Draft PR #57 (`production` -> `master`).
3. Investigate and resolve the root cause of the `/links` 500 Internal Server Error.
4. Investigate and fix the broken database logging mechanism so live server logs and error stack traces are properly written to `system_logs` and visible in `/admin/logs`.
5. Optimize the `/admin` dashboard queries to eliminate the 7.9s latency.
6. Optimize the `/view/site` queries to eliminate the 7.6s latency and fix tag deserialization formatting.
7. Run all pre-commit tests and verifications.
