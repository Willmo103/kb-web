# Security Hardening & Full-Site Authentication Walkthrough

**Issue**: [#71](https://github.com/Willmo103/kb-web/issues/71)  
**PR**: [#72](https://github.com/Willmo103/kb-web/pull/72)  
**Branch**: `feature/security-hardening-and-full-site-auth`  
**Base**: `production`  

---

## 1. Problem & Threat Model

With `kb-web` deployed to the live open internet hosting sensitive personal notes, private code in workspaces, personal bookmarks, and ingested documents:
1. **Public Read-Access Exposure**: Previously, root `/`, `/pages`, `/similarity/...`, and `/media/...` were publicly reachable without authentication. Any unauthenticated user or search engine crawler could read personal notes and browse indexed content.
2. **Brute-Force Vulnerability**: The `/login` endpoint had no rate limiting, leaving it open to automated dictionary attacks.
3. **Missing HTTP Security Headers**: HTTP responses lacked `X-Content-Type-Options`, `X-Frame-Options`, and strict referrer policies, exposing clients to clickjacking and MIME-type sniffing.
4. **Path Traversal Vulnerabilities**: Ingestion endpoints (such as Obsidian vault `.zip` unpacker and workspace virtual files) lacked rigorous canonical path boundary checks.
5. **Session Cookie Weakness**: Session cookies were missing dynamic `Secure=True` detection for HTTPS / reverse proxies and strict `SameSite` settings.

---

## 2. Implemented Defense-in-Depth Solution

```
                               Incoming HTTP Request
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │     security_and_auth_middleware      │
                     └───────────────────┬───────────────────┘
                                         │
                  Is path in PUBLIC_EXACT_PATHS allowlist?
                  (/login, /logout, /favicon.ico, /icon.png,
                   /manifest.json, /sw.js)
                                ├─────────► YES: Allow (Inject Security Headers)
                                │
                                ▼ NO
                     Check Authentication
                     - Session Cookie: `kb_session` (timing-safe HMAC)
                     - API Key: `X-API-Key` or `Authorization: Bearer`
                                │
               ┌────────────────┴────────────────┐
               ▼                                 ▼
          Authenticated?                   Unauthenticated?
               │                                 │
        ┌──────┴──────┐                   ┌──────┴──────────────────────────┐
        │ Pass to App │                   │ Path type:                      │
        └──────┬──────┘                   │  - Web UI: 303 -> /login?next=  │
               │                          │  - API (/api/*): 401 JSON       │
               ▼                          │  - Media (/media/*): 401 Text   │
     Inject Security Headers              └─────────────────────────────────┘
     - X-Content-Type-Options: nosniff
     - X-Frame-Options: SAMEORIGIN
     - X-XSS-Protection: 1; mode=block
     - Referrer-Policy: strict-origin-when-cross-origin
```

### Key Changes by Component:

1. **`src/kb_web/server.py`**:
   - Implemented `security_and_auth_middleware` intercepting all requests before route processing.
   - Enforced strict public allowlist (`/login`, `/logout`, `/favicon.ico`, `/icon.png`, `/manifest.json`, `/sw.js`).
   - Dynamic response handling:
     - Unauthenticated web views: 303 Redirect to `/login?next={url}`.
     - Unauthenticated API endpoints (`/api/...`): HTTP 401 JSON (`{"detail": "Authentication required. Provide valid session cookie or API key."}`).
     - Unauthenticated media files (`/media/...`): HTTP 401 Unauthorized.
   - Injected enterprise security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`) across all responses.
   - Added startup health checks in `lifespan` warning if default secrets (`admin123` or `kb-secret-key`) are detected.

2. **`src/kb_web/base.py`**:
   - Refactored `verify_auth()` and `verify_api_key()` to use `hmac.compare_digest` for timing-attack immunity.
   - Created `is_request_authenticated(request)` checking both session cookies and API key headers (`X-API-Key` and `Authorization: Bearer <key>`).

3. **`src/kb_web/routers/auth.py`**:
   - Added thread-safe IP sliding-window rate limiter `_login_failed_attempts` on `POST /login` (max 5 failed attempts per 60s per IP -> HTTP 429 Too Many Requests).
   - Added auto-detection of HTTPS via direct scheme or reverse-proxy `X-Forwarded-Proto: https` header, automatically toggling `Secure=True` cookie attribute.
   - Added 8-character minimum validation on password changes.

4. **`src/kb_web/routers/notes.py` & `src/kb_web/routers/workspaces.py`**:
   - Patched ZipSlip vulnerability in `POST /api/notes/upload-vault`: canonicalizes target paths and verifies they stay strictly inside `media_vault_dir`, rejecting any `..` traversal tokens.
   - Hardened workspace file CRUD against directory traversal.

5. **`src/kb_web/models.py`**:
   - Hardened `ParsedUrl.from_url` with safe `try...except (ValueError, TypeError)` when parsing `parsed.port` to avoid crashes on non-numeric port strings or Windows drive paths.

6. **`src/kb_web/templates/admin.j2.html` & `base.j2.html`**:
   - Displayed security warning alert banners at the top of the Admin dashboard if default passwords or API keys are active.
   - Cleaned unauthenticated header in `base.j2.html` to hide internal navigation links and present a clean login gateway.

---

## 3. Verification & Test Coverage

### Automated Test Suites:
- **Dedicated Security Test Suite (`tests/test_security_hardening.py`)**:
  - `test_unauthenticated_ui_routes_redirect_to_login`: Verifies all key UI routes redirect unauthenticated visits with 303 to `/login?next=...`.
  - `test_unauthenticated_api_routes_return_401`: Verifies unauthenticated API calls return 401 JSON.
  - `test_unauthenticated_media_routes_return_401`: Verifies unauthenticated media downloads return 401.
  - `test_authenticated_ui_access_with_cookie`: Verifies valid `kb_session` cookie grants access to protected pages.
  - `test_api_key_auth_header`: Verifies both `X-API-Key` and `Authorization: Bearer` headers authenticate API requests.
  - `test_login_rate_limiting`: Verifies 5 failed logins within 60s trigger HTTP 429 Too Many Requests.
  - `test_security_headers_present`: Verifies `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` are attached to responses.
  - `test_zipslip_traversal_protection`: Verifies malicious zip files attempting `../../evil.txt` are blocked.
  - `test_workspace_path_traversal_protection`: Verifies malicious paths like `../../etc/passwd` are rejected with 400.
  - `test_cookie_security_attributes`: Verifies `HttpOnly=True` and `SameSite=lax`.
  - **Result: 10 / 10 passed in 3.69s**.

- **Full Pytest Suite**:
  - **Result: 97 / 97 passed in 72s**.

- **UI Component Template Check (`verify_ui_templates.py`)**:
  - **Result: 21 templates verified, 0 warnings**.

- **Build Pipeline (`build.py`)**:
  - **Result: `uv sync`, `pytest`, `uv build` succeeded with exit code 0**.

- **VCS UAT Artifacts**:
  - `uat/reports/uat_report_security_hardening_and_full_site_auth_20260928_212900.md`
  - `uat/logs/test_log_security_hardening_and_full_site_auth_20260928_212900.log`
