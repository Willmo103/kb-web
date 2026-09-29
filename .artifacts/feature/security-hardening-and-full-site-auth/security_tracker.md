# Security Hardening & Full-Site Authentication Tracker

**Issue**: [#71](https://github.com/Willmo103/kb-web/issues/71)  
**PR**: [#72](https://github.com/Willmo103/kb-web/pull/72)  
**Branch**: `feature/security-hardening-and-full-site-auth`  
**Base**: `production`  
**Status**: Completed (All Tests & Pre-commit Checks Passed)

---

## Task Checklist

- [x] **1. Global Authentication Middleware & Route Protection**
  - [x] Implement `security_and_auth_middleware` in `src/kb_web/server.py`.
  - [x] Configure strict public path allowlist (`/login`, `/logout`, `/favicon.ico`, `/icon.png`, `/manifest.json`, `/sw.js`).
  - [x] Implement automatic UI redirect to `/login?next=...` for unauthenticated browser sessions.
  - [x] Implement 401 JSON response for unauthenticated API requests (`/api/...`).
  - [x] Implement dual-auth on `/api/...` (valid session cookie OR `X-API-Key` / `Bearer` token).
  - [x] Protect `/media` route against unauthenticated direct access (returns 401).

- [x] **2. Cookie & Session Security Hardening**
  - [x] Update `response.set_cookie` to set `SameSite=Lax`, `HttpOnly=True`, and auto-detect `Secure=True` on HTTPS/reverse-proxy (`X-Forwarded-Proto`).
  - [x] Implement IP-based sliding window rate-limiting on `/login` to thwart brute-force password attempts (max 5 failed attempts per 60s per IP -> 429 Too Many Requests).
  - [x] Add admin alert banner if default credentials (`admin123` / `kb-secret-key`) are detected.
  - [x] Enforce constant-time `hmac.compare_digest` for password and API key checks.

- [x] **3. HTTP Security Headers**
  - [x] Add headers injection: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`.

- [x] **4. Path Traversal & Ingestion Hardening**
  - [x] Audit and patch Obsidian vault `.zip` extraction in `notes.py` against ZipSlip traversal and relative path traversal tokens (`..`).
  - [x] Enforce strict path validation in workspace file creation and deletion endpoints (`workspaces.py`).
  - [x] Harden `ParsedUrl.from_url` in `models.py` against malformed port casting exceptions on non-standard URLs and Windows local path schemes.

- [x] **5. Verification & Testing**
  - [x] Add comprehensive test suite in `tests/test_security_hardening.py` (10 passed in 3.69s).
  - [x] Update existing tests to support authenticated client fixtures (`client` vs `unauth_client`).
  - [x] Verify full regression suite (`uv run pytest`) passes 100% (97 passed in 72s).
  - [x] Verify UI templates (`verify_ui_templates.py`: 21 templates, 0 warnings).
  - [x] Run build verification (`uv run python build.py`: build and artifact distribution succeeded).
  - [x] Generate VCS UAT testing report in `uat/reports/` and log in `uat/logs/`.
