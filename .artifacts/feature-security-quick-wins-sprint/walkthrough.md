# Walkthrough - Security Quick Wins Sprint & Credential Hygiene

**Sprint Branch**: `feature/security-quick-wins-sprint`  
**Tracking Draft PR**: [#113](https://github.com/Willmo103/kb-web/pull/113) -> `master`  
**Associated GitHub Issues Addressed**:
- **SEC-01 (Fixes #93)**: Rate-limit spoofing bypass via `X-Forwarded-For`
- **SEC-03 (Fixes #95)**: Git repository import argument injection & `shell=True` on Windows
- **SEC-02 (Fixes #94 & #97)**: Stored Markdown/HTML XSS + Content Security Policy (CSP)
- **SEC-04 (Fixes #96)**: Fail-closed default credentials (`admin123` / `kb-secret-key`)
- **SEC-05 (Fixes #111)**: Cryptographically random session secret decoupled from admin password
- **SEC-06 (Fixes #110)**: Salted `scrypt` password hashing & secret redaction in `kb-web.json`

---

## 1. Vulnerability Analysis & Applied Fixes

### SEC-01: Rate-Limit Spoofing Defense (`routers/auth.py`, `config.py`, `routers/admin.py`, & `templates/admin.j2.html`)
- **Issue**: `_get_client_ip()` previously trusted the first IP in `X-Forwarded-For` unconditionally. Attackers could rotate random fake IP headers to bypass the 5-attempt rate limit.
- **Resolution**:
  - Added `trusted_proxies` to `config.py` (defaults to loopback `127.0.0.1, ::1`), configurable via `KB_TRUSTED_PROXIES` and exposed in the Admin Portal under General Settings per Rule 7.
  - In `auth.py`, `_get_client_ip()` verifies `request.client.host` against `trusted_proxies` using `ipaddress` host and CIDR network checks. If untrusted, `request.client.host` is used directly. If trusted, it traverses `X-Forwarded-For` right-to-left to extract the rightmost untrusted peer.
  - Implemented a 50-attempt global lockout ceiling (`_global_failed_attempts`) over 60 seconds to thwart distributed brute-force attempts.

### SEC-03: Safe Git Repository Ingestion (`repo_importer.py`)
- **Issue**: `clone_repo()` passed user-supplied URLs to `git clone` with `shell=True` on Windows. Arguments starting with `-` triggered option injection, while `file://` or local paths allowed filesystem exfiltration.
- **Resolution**:
  - Created `validate_repo_url()`: strictly enforces URL schema (`https`, `http`, `ssh`, or `git@` SCP), forbids leading dashes, and blocks `file://` and local filesystem paths.
  - Resolved `git` using `shutil.which("git") or "git"` with `shell=False` across all platforms.
  - Added `-c protocol.file.allow=never`, safe depth bounds (`1 <= depth <= 100`), and a `--` argument separator before the clone URL and destination.

### SEC-02: Stored Markdown/HTML XSS Sanitization & CSP (`utils.py`, `routers/pages.py`, & `server.py`)
- **Issue**: Markdown was rendered to HTML and injected directly into Jinja2 templates via `| safe` without sanitization. Ingested malicious web pages or AI wiki summaries could execute arbitrary script payloads. CSP was absent.
- **Resolution**:
  - Integrated high-performance Rust-backed `nh3` HTML sanitizer (`sanitize_html()`). Strips `<script>`, `<iframe>`, inline event handlers (`onerror`, `onload`), and `javascript:` URIs while preserving formatting, syntax highlighting code blocks, and tables.
  - Wrapped `rendered_wiki_html` and `rendered_md_html` in `sanitize_html()`.
  - Added strict `Content-Security-Policy` header in `_inject_security_headers()`.

### SEC-04: Fail-Closed Default Credentials (`base.py`, `config.py`, `templates/admin.j2.html`)
- **Issue**: The public default key `kb-secret-key` was accepted for full API access, and default password `admin123` allowed open web access.
- **Resolution**:
  - `verify_api_key()` and `is_request_authenticated()` now fail closed, rejecting `kb-secret-key` with HTTP 401 unless explicit development flag `KB_ALLOW_INSECURE_DEFAULTS=1` is set.
  - Persistent alert banners in the Admin Portal and navigation header warn when default credentials are active.

### SEC-05: Independent Session Secret (`base.py`, `config.py`)
- **Issue**: HMAC session signatures were derived directly from `hashlib.sha256(config.admin_password)`. Knowing the password allowed offline forgery, and changing the password invalidated all sessions.
- **Resolution**:
  - Generated and persisted an independent 32-byte cryptographically secure session signing secret (`KB_SESSION_SECRET` or `settings_external`), fully decoupling HMAC cookie verification from administrative passwords.

### SEC-06: Scrypt Password Hashing & Secret Redaction (`config.py`, `routers/auth.py`)
- **Issue**: Passwords were stored in plaintext and exported to `kb-web.json` backup files.
- **Resolution**:
  - Implemented `hash_password()` and `verify_password()` using standard library `hashlib.scrypt` with random 16-byte salts (`scrypt$<salt>$<hash>`).
  - Transparent migration: verifying existing plaintext passwords automatically migrates them to scrypt hashes.
  - Redacted sensitive credentials (`admin_password`, `api_key`) in `kb-web.json` exports.

---

## 2. Test Verification

- **Automated Unit Tests**: Added 8 comprehensive regression tests in `tests/test_security_hardening.py` covering:
  - Untrusted client `X-Forwarded-For` spoofing lockout defense.
  - Trusted proxy traversal and rightmost untrusted extraction.
  - Git repository URL validation (argument injection and local file protocol rejection).
  - `nh3` HTML sanitization against XSS payloads.
  - Content-Security-Policy header injection.
  - Fail-closed API key rejection for `kb-secret-key`.
  - `scrypt` password hashing and verification.
  - Session secret stability across password changes.
  - Secret redaction in `kb-web.json`.
- **Pre-commit Gating**:
  - `verify_ui_templates.py`: 25 templates checked, 0 warnings.
  - Full pytest suite (197 tests).
