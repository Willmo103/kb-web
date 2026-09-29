# Implementation Plan: Full-Site Authentication Guard & Application Security Hardening

**Issue**: [#71](https://github.com/Willmo103/kb-web/issues/71)  
**Branch**: `feature/security-hardening-and-full-site-auth`  

---

## 1. Overview & Architectural Goals

The objective is to transform `kb-web` from a partially public web portal into a fully authenticated, security-hardened personal knowledge repository suitable for direct exposure to the public internet.

---

## 2. Key Components & Changes

### A. Authentication & Access Control Architecture
1. **Global Authentication Middleware (`server.py`)**:
   - Create `SiteSecurityMiddleware` running on every incoming HTTP request.
   - Define strict allowlist for public paths:
     - `/login` (GET and POST)
     - `/favicon.ico`, `/icon.png`, `/manifest.json`, `/sw.js`
   - For all other requests:
     - Check session cookie (`kb_session` via `verify_session_token(token)`).
     - If request is to an API route (`/api/...`) or WebSocket, also check for valid `X-API-Key` or `Authorization: Bearer <token>` matching `config.api_key`.
     - If authenticated: proceed with request.
     - If unauthenticated:
       - For API calls (`/api/...`) or requests with `Accept: application/json`: return `401 Unauthorized` (`{"detail": "Authentication required."}`).
       - For UI browser requests: return `303 See Other` redirecting to `/login?next={encoded_request_url}`.
2. **Media File Protection**:
   - Replace open static mount `app.mount("/media", StaticFiles(...))` with an authenticated media streaming endpoint or guard middleware, ensuring media files (video clips, Obsidian image attachments) require valid authentication.
3. **Session Cookie Hardening**:
   - Update `set_cookie` in `routers/auth.py` to evaluate whether the request is HTTPS or forwarding `X-Forwarded-Proto == "https"` to set `secure=True`.
   - Ensure `httponly=True` and `samesite="lax"`.
4. **Login Brute-Force Rate Limiting**:
   - Implement an in-memory IP sliding-window tracker on `/login` attempts.
   - Allow up to 5 failed attempts per IP within a 1-minute window, followed by exponential backoff (e.g. 5-second delay) or temporary lockouts (`429 Too Many Requests`) for that IP.

### B. HTTP Security Headers
1. Inject standard security headers on every response in `SiteSecurityMiddleware`:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: SAMEORIGIN`
   - `X-XSS-Protection: 1; mode=block`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy: geolocation=(), microphone=(), camera=()`

### C. Ingestion & Path Traversal Hardening
1. **Obsidian Vault ZIP Extraction (`notes.py`)**:
   - Ensure all member paths inside `.zip` files are validated using `os.path.abspath` to guarantee they do not escape the destination directory (ZipSlip mitigation).
2. **Workspace & Note Path Sanitization**:
   - Enforce that virtual file paths cannot contain `..` or leading slashes attempting to traverse the server's local file system.

### D. Default Credential Warnings
1. Add a warning indicator in the Admin dashboard and logs if `config.admin_password == "admin123"` or `config.api_key == "kb-secret-key"`, urging the administrator to customize their credentials on the open web.

### E. Test Suite Harmonization
1. Update test fixtures:
   - Provide authenticated test clients by default in `test_server.py`, `test_rest_api.py`, `test_db_cli.py`, etc.
   - Add new tests in `test_security.py` specifically testing:
     - Unauthenticated UI request redirect to `/login`
     - Unauthenticated API request returns 401 JSON
     - Authenticated session cookie grants access
     - Valid API key grants access to `/api/...`
     - Invalid API key returns 401
     - Login rate limiting triggers 429 after threshold
     - HTTP security headers are present on responses
     - ZipSlip path traversal in vault upload is blocked
