# Security Hardening & Full-Site Authentication Tracker

**Issue**: [#71](https://github.com/Willmo103/kb-web/issues/71)  
**Branch**: `feature/security-hardening-and-full-site-auth`  
**Base**: `production`  

---

## Task Checklist

- [ ] **1. Global Authentication Middleware & Route Protection**
  - [ ] Implement `SiteSecurityMiddleware` in `src/kb_web/server.py`.
  - [ ] Configure strict public path allowlist (`/login`, `/favicon.ico`, `/icon.png`, `/manifest.json`, `/sw.js`).
  - [ ] Implement automatic UI redirect to `/login?next=...` for unauthenticated browser sessions.
  - [ ] Implement 401 JSON response for unauthenticated API requests (`/api/...`).
  - [ ] Implement dual-auth on `/api/...` (valid session cookie OR `X-API-Key` / `Bearer` token).
  - [ ] Protect `/media` route against unauthenticated direct access.

- [ ] **2. Cookie & Session Security Hardening**
  - [ ] Update `response.set_cookie` to set `SameSite=Lax`, `HttpOnly=True`, and auto-detect `Secure=True` on HTTPS/reverse-proxy.
  - [ ] Implement IP-based sliding window rate-limiting on `/login` to thwart brute-force password attempts.
  - [ ] Add admin alert banner if default credentials (`admin123` / `kb-secret-key`) are detected.

- [ ] **3. HTTP Security Headers**
  - [ ] Add headers middleware: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`.

- [ ] **4. Path Traversal & Ingestion Hardening**
  - [ ] Audit and patch Obsidian vault `.zip` extraction in `notes.py` against ZipSlip traversal.
  - [ ] Enforce path validation in workspace file creation.

- [ ] **5. Verification & Testing**
  - [ ] Add comprehensive test suite in `tests/test_security_hardening.py`.
  - [ ] Update existing tests to support authenticated client fixtures.
  - [ ] Verify full regression suite (`uv run pytest`) passes 100%.
  - [ ] Verify UI templates (`verify_ui_templates.py`).
  - [ ] Run build verification (`uv run python build.py`).
  - [ ] Generate VCS UAT testing report in `uat/`.
