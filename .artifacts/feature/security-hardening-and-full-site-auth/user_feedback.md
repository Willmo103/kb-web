# User Feedback & Requirements Record

**Date**: 2026-09-28  
**Branch**: `feature/security-hardening-and-full-site-auth`  
**Issue**: [#71](https://github.com/Willmo103/kb-web/issues/71)  

---

## User Request

> "I need to secure the whole website behind the admin password at this point. I also need to harden security across the application because its on the live open internet and also hosting a lot of my personal notes now."

---

## Action Items & Design Directives

1. **Full-Site Authentication Protection**:
   - The user has transitioned `kb-web` from an internal/public reading portal to a personal knowledge management platform hosting private notes, code workspaces, bookmarks, and internal reports.
   - The entire website must be gated behind authentication. Unauthenticated visitors must not see personal notes, articles, sites, embeddings, workspaces, or reports.
   - Direct browser visits to any page without a valid session cookie must redirect to `/login?next={url}`.
   - Public exceptions should be strictly limited to essential assets required to render the login page and mobile PWA: `/login`, `/favicon.ico`, `/icon.png`, `/manifest.json`, and `/sw.js`.
   - APIs (`/api/...`) should support dual authentication: valid session cookie or valid API key (`X-API-Key` or `Authorization: Bearer <token>`). Unauthenticated API requests must return `401 Unauthorized` with JSON error details rather than a 303 redirect.

2. **Security Hardening on the Live Open Internet**:
   - **Session Cookie Security**: Set `SameSite=Lax`, `HttpOnly=True`, and auto-detect `Secure=True` when running behind HTTPS/TLS or a reverse proxy forwarding `X-Forwarded-Proto: https`.
   - **Brute-Force & Rate-Limiting Protection**: Add in-memory sliding-window rate limiting on `/login` to thwart automated credential stuffing and dictionary attacks against the admin password.
   - **HTTP Security Headers Middleware**: Inject industry-standard security headers on all responses (`X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`).
   - **Media Download Gating**: Gate `/media/...` so media attachments and downloaded videos cannot be hotlinked or downloaded by unauthenticated bots.
   - **Path Traversal / Archive Hardening**: Audit and sanitize file paths in notes and workspace endpoints, including ZipSlip protection during Obsidian vault uploads.
   - **Security Health Indicator**: Add an administrative alert banner if the default password (`admin123`) or default API key is currently active.
