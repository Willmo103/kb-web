# Implementation Plan - Security Quick Wins Sprint & Credential Hygiene

**Sprint Branch**: `feature/security-quick-wins-sprint`  
**Tracking Draft PR**: [#113](https://github.com/Willmo103/kb-web/pull/113) -> `master`  
**Associated GitHub Issues**: #93, #94, #95, #96, #97, #110, #111  

---

## 1. Objectives & Scope

### Task 1: Security Quick Wins
1. **SEC-01 (Issue #93) - Rate-Limit Spoofing Fix**:
   - Prevent attackers from bypassing login brute-force lockouts by rotating spoofed `X-Forwarded-For` headers.
   - Introduce a configurable `trusted_proxies` setting in `src/kb_web/config.py` (exposed in Admin Portal `/admin` per Rule 7).
   - Only parse and trust `X-Forwarded-For` if `request.client.host` is verified against `trusted_proxies` (supporting exact IPs and CIDR ranges via `ipaddress`).
   - When trusted, extract the right-most untrusted IP address from the proxy chain.
   - Add a global lockout ceiling across all IPs to thwart distributed brute-force attacks.

2. **SEC-03 (Issue #95) - Git Repo Import Argument Injection & Shell Elimination**:
   - Secure `clone_repo` and git helper subprocesses in `src/kb_web/repo_importer.py`.
   - Remove `shell=True` on Windows by resolving `shutil.which("git")` and passing tokenized argument arrays directly.
   - Validate repository URLs: reject URLs starting with `-` (argument injection) or using local file protocols (`file://`, local paths).
   - Pass `-c protocol.file.allow=never` and `--` delimiter before repository URLs in `git clone`.
   - Validate and bound clone `depth` (`1 <= depth <= 100`).

3. **SEC-02 (Issues #94 & #97) - Stored XSS Sanitization & Content Security Policy (CSP)**:
   - Sanitize all rendered Markdown/HTML before passing it to Jinja2 `| safe` in `src/kb_web/routers/pages.py` using `nh3` (high-performance Rust-based HTML sanitizer).
   - Strip unsafe elements (`<script>`, `<iframe>`, `object`, `embed`, inline event handlers `onerror`, `onload`, `javascript:` URIs) while preserving rich formatting, code blocks, tables, and links.
   - Add robust Content-Security-Policy (CSP) headers in `_inject_security_headers()` in `src/kb_web/server.py`.
   - Remove obsolete/insecure `X-XSS-Protection: 1; mode=block` (set to `0` or remove per OWASP) and add modern security headers.

4. **SEC-04 (Issue #96) - Fail-Closed Default Credentials**:
   - Prevent open web deployments from being compromised by well-known default credentials (`admin123` / `kb-secret-key`).
   - Reject the default API key (`kb-secret-key`) for authenticated access unless explicit dev override `KB_ALLOW_INSECURE_DEFAULTS=1` is set.
   - Detect default password (`admin123`) and render a persistent, prominent warning banner in the Admin Portal and navigation header.
   - Add clear warning logs on server startup when default credentials are in use.

---

### Task 2: Credential Hygiene ("Feeling Froggy" Stretch Goal)
5. **SEC-05 (Issue #111) - Cryptographically Random Session Secret**:
   - Decouple session token signing from `config.admin_password`.
   - Generate and persist a dedicated 32-byte cryptographically random session secret (`secrets.token_bytes(32)`) or read from `KB_SESSION_SECRET`.
   - Changing the admin password no longer leaks or dictates HMAC token verification keys.

6. **SEC-06 (Issue #110) - Password Hashing & Secret Redaction**:
   - Replace plaintext password verification with standard Python 3 `hashlib.scrypt` (salted password hashing, zero external C dependencies).
   - Support seamless backward-compatible upgrade: if the stored password in config/DB is plaintext, verify and automatically migrate to hashed format on successful login.
   - Redact secrets (`admin_password`, `session_secret`, `api_key`) from `kb-web.json` export snapshots, diagnostic dumps, and log outputs.

---

## 2. Technical Implementation Architecture

### A. Rate-Limiting & Trusted Proxies (`auth.py` & `config.py`)
```python
# In src/kb_web/routers/auth.py
def _is_trusted_proxy(ip_str: str) -> bool:
    proxies = [p.strip() for p in config.trusted_proxies.split(",") if p.strip()]
    client_ip = ipaddress.ip_address(ip_str)
    for proxy in proxies:
        if "/" in proxy:
            if client_ip in ipaddress.ip_network(proxy):
                return True
        elif client_ip == ipaddress.ip_address(proxy):
            return True
    return False

def _get_client_ip(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(host):
        return host
    
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Traverse right-to-left
        hops = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        for hop in reversed(hops):
            if not _is_trusted_proxy(hop):
                return hop
    return host
```

### B. Safe Git Ingestion (`repo_importer.py`)
```python
# Disallow argument injection or local file protocols
if repo_url.startswith("-") or repo_url.startswith("/"):
    raise ValueError("Invalid repository URL format.")
parsed = urlparse(repo_url)
if parsed.scheme not in ("http", "https", "ssh", "git") and not re.match(r"^git@[\w.-]+:", repo_url):
    raise ValueError(f"Unsupported or dangerous repository protocol: {parsed.scheme}")

git_bin = shutil.which("git") or "git"
cmd = [git_bin, "-c", "protocol.file.allow=never", "clone", "--depth", str(safe_depth), "--", repo_url, str(clone_path)]
subprocess.run(cmd, shell=False, capture_output=True, text=True, check=True)
```

### C. HTML Sanitization (`pages.py`, `utils.py`) & CSP (`server.py`)
```python
import nh3

def sanitize_html(html_str: str) -> str:
    """Sanitize rendered HTML from Markdown using nh3 allowlist."""
    return nh3.clean(
        html_str,
        tags={"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code", "em", "strong",
              "ul", "ol", "li", "blockquote", "table", "thead", "tbody", "tr", "th", "td",
              "a", "img", "hr", "br", "span", "details", "summary"},
        attributes={
            "a": {"href", "title", "target", "rel"},
            "img": {"src", "alt", "title", "width", "height"},
            "code": {"class"},
            "pre": {"class"},
            "span": {"class"},
            "th": {"align", "style"},
            "td": {"align", "style"},
        },
        url_schemes={"http", "https", "mailto"},
    )
```

### D. Fail-Closed Authentication & Session Protection (`base.py`, `config.py`)
```python
INSECURE_DEFAULT_API_KEY = "kb-secret-key"
INSECURE_DEFAULT_PASSWORD = "admin123"

# verify_api_key in base.py:
if config.api_key == INSECURE_DEFAULT_API_KEY and not config.allow_insecure_defaults:
    raise HTTPException(status_code=401, detail="Default API key disabled for security. Configure KB_API_KEY.")
```

---

## 3. Test Plan & Verification

1. **Unit & Integration Tests**:
   - `tests/test_security_hardening.py`:
     - Test spoofed `X-Forwarded-For` is ignored when client is untrusted.
     - Test valid proxy traversal when client is trusted.
     - Test global lockout ceiling.
     - Test git argument injection (`--upload-pack`, `file://` protocol) raises validation errors.
     - Test `nh3` sanitizes XSS payloads (`<script>`, `onerror`, `javascript:`) in rendered Markdown.
     - Test CSP header presence and format.
     - Test fail-closed rejection of `kb-secret-key` when `KB_ALLOW_INSECURE_DEFAULTS` is disabled.
     - Test password hashing and session signature derivation.
2. **Pre-commit Gating**:
   - `uv run pytest`
   - `uv run python verify_ui_templates.py`
   - `uv run python build.py`
3. **Commit Association**:
   - Commits will reference issue IDs: `Refs #93`, `Fixes #93`, `Refs #95`, `Fixes #95`, `Refs #94`, `Fixes #94`, `Refs #96`, `Fixes #96`, `Refs #110`, `Refs #111`.
4. **Draft PR Updates**:
   - Update PR #113 description and task checklist as each vulnerability fix lands.
