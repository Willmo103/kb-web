## Release v0.5.10 (Staging Production -> Master)

This pull request merges the verified `production` baseline into `master` following the repository tiered release lifecycle.

### Overview of Included Enhancements & Fixes

#### 1. Security & Hardening Quick Wins (SEC-01 through SEC-08)
- **Rate-Limit Spoofing Defense (SEC-01 / #93)**: Added trusted reverse proxy verification via `ipaddress` (`KB_TRUSTED_PROXIES`), evaluated untrusted hops from `X-Forwarded-For`, and enforced a 50-attempt global lockout ceiling.
- **Git Repo Import Subprocess Hardening (SEC-03 / #95)**: Added strict URL validation in `validate_repo_url()` and eliminated `shell=True` on Windows with `shutil.which("git")`, `--` argument separators, and `protocol.file.allow=never`.
- **Stored Markdown XSS Sanitization & CSP (SEC-02, SEC-08 / #94, #97)**: Integrated Rust-backed `nh3` sanitizer for wiki and article markdown. Injected strict `Content-Security-Policy`, `Strict-Transport-Security`, and `Permissions-Policy` headers.
- **Fail-Closed Default Credentials (SEC-04 / #96)**: Rejection of default key `kb-secret-key` unless explicit dev flag is present, with persistent UI security banners in `/admin`.
- **Cryptographic Random Session Secret (SEC-05 / #111)**: Decoupled HMAC cookie sessions from the admin password with a persistent 32-byte cryptographically random signing secret.
- **Scrypt Salted Password Hashing & Secret Redaction (SEC-06 / #110)**: Migrated plain passwords to salted `hashlib.scrypt` hashes, transparently migrating existing passwords on login. Redacted plaintext credentials from `kb-web.json` backup exports.
- **SSRF Prevention & Internal IP Guard (SEC-07 / #109)**: Hostname DNS resolution with `is_internal_ip()` guard blocking private, loopback, multicast, and cloud metadata addresses.

#### 2. Code Review & Performance Fixes (#98 through #108)
- **Non-ASCII Password Crash (#98)**: Replaced `hmac.compare_digest` with UTF-8 byte encoding `safe_compare_digest()`.
- **MCP Server PostgreSQL Connectivity (#99)**: Refactored `mcp_server.py` to use `db_session()` and ORM models for SQLite/PostgreSQL parity.
- **Article View Extra Closing Tag (#100)**: Fixed premature layout closing div in `view_page.j2.html`.
- **Template Verifier (#101)**: Updated `verify_ui_templates.py` to detect div tag imbalances and nested tab panes.
- **Bulk Maintenance & Crawler Performance (#102, #104)**: Chunked database iteration in background worker jobs; migrated BFS queue to `collections.deque`.
- **Agent Board Stats (#103)**: Replaced full-table scans with indexed count aggregations.
- **Logging & Timezone Standardization (#105, #106)**: Standardized UTC timestamps via `datetime.now(timezone.utc)` and structured logging.
- **Tooling & Version Sync (#107, #108)**: Updated pyproject version to `0.5.10` and established a clean `ruff` baseline.

#### 3. Media & Admin Portal Polish (#112 & Admin UI)
- **YouTube Offline Downloads Audio Fix (#112)**: Combined adaptive video+audio streams via `ffmpeg` in `yt-dlp` options and exposed format selection to `/admin`.
- **Quick Diagnostics Dark Mode Theme**: Replaced bright gradient classes with dark card tokens (`#111827`, border `#1e293b`).
- **Prompt Studio Monaco Editor Height**: Added CSS height rules and debounced resize listener preventing collapsed sliver in half-screen/responsive views.

---

### Verification
- `verify_ui_templates.py`: 25/25 templates verified with 0 warnings.
- Pytest suite: 199/199 unit and integration tests passing.
- Visual UAT: Dark mode diagnostics card and 500px Monaco editor verified in browser.
- Service deployment: Deployed and running on test server `websrvr`.
