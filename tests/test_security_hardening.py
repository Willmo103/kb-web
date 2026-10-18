import io
import time
import zipfile
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app, config as server_config
from kb_web.base import (
    COOKIE_NAME,
    generate_session_token,
    verify_session_token,
    is_request_authenticated,
)
from kb_web.routers.auth import _login_failed_attempts, _login_lock


@pytest.fixture(autouse=True)
def setup_api_key():
    orig_key = server_config.api_key
    if not server_config.api_key:
        server_config.api_key = "test-secret-key"
    yield
    server_config.api_key = orig_key


@pytest.fixture
def unauth_client() -> TestClient:
    """Fixture providing an unauthenticated client."""
    return TestClient(app)


@pytest.fixture
def auth_client() -> TestClient:
    """Fixture providing a client authenticated via session cookie."""
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture
def api_key_client() -> TestClient:
    """Fixture providing a client authenticated via X-API-Key header."""
    return TestClient(app, headers={"X-API-Key": server_config.api_key or "test-secret-key"})


def test_public_endpoints_accessible(unauth_client: TestClient):
    """Verifies that public metadata and authentication endpoints remain reachable."""
    # 1. Login page
    resp = unauth_client.get("/login")
    assert resp.status_code == 200
    assert "Passphrase" in resp.text
    assert "Knowledge Base Gateway" in resp.text

    # 2. Manifest and PWA assets
    resp = unauth_client.get("/manifest.json")
    assert resp.status_code == 200
    assert resp.json()["short_name"] == "KB Wiki"

    resp = unauth_client.get("/sw.js")
    assert resp.status_code == 200
    assert "serviceWorker" in resp.text or "addEventListener" in resp.text

    # 3. Logout clears cookie and returns to login
    resp = unauth_client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_all_ui_routes_redirect_unauthenticated(unauth_client: TestClient):
    """Verifies that every UI endpoint redirects unauthenticated requests to /login."""
    ui_routes = [
        "/",
        "/pages",
        "/sites",
        "/notes",
        "/notes/editor",
        "/workspaces",
        "/conversations",
        "/reports",
        "/collections",
        "/links",
        "/admin",
        "/import",
        "/similarity/compare",
        "/similarity/graph",
    ]
    for route in ui_routes:
        resp = unauth_client.get(route, follow_redirects=False)
        assert resp.status_code == 303, f"Route {route} did not redirect (status {resp.status_code})"
        assert "/login?next=" in resp.headers["location"], f"Route {route} location missing /login?next="


def test_api_routes_return_401_for_unauthenticated(unauth_client: TestClient):
    """Verifies that API endpoints return 401 JSON when accessed without authentication."""
    api_routes = [
        "/api/articles",
        "/api/videos",
        "/api/sites",
        "/api/tags",
        "/api/notes",
        "/api/notes/tree",
        "/api/workspaces",
        "/api/conversations",
        "/api/reports/tables",
        "/api/embeddings/models",
    ]
    for route in api_routes:
        resp = unauth_client.get(route)
        assert resp.status_code == 401, f"Route {route} returned {resp.status_code} instead of 401"
        data = resp.json()
        assert "Unauthorized" in data.get("detail", "")


def test_media_assets_require_authentication(unauth_client: TestClient, auth_client: TestClient):
    """Verifies that media downloads cannot be hotlinked or accessed without authentication."""
    resp = unauth_client.get("/media/notes/test_photo.png")
    assert resp.status_code == 401
    assert "Unauthorized" in resp.text


def test_api_key_header_authentication(unauth_client: TestClient):
    """Verifies that X-API-Key and Authorization: Bearer headers authorize API access."""
    # 1. Without key -> 401
    resp = unauth_client.get("/api/articles")
    assert resp.status_code == 401

    # 2. With valid X-API-Key -> 200
    resp = unauth_client.get(
        "/api/articles",
        headers={"X-API-Key": server_config.api_key},
    )
    assert resp.status_code == 200

    # 3. With valid Bearer token -> 200
    resp = unauth_client.get(
        "/api/articles",
        headers={"Authorization": f"Bearer {server_config.api_key}"},
    )
    assert resp.status_code == 200

    # 4. With invalid API key -> 401
    resp = unauth_client.get(
        "/api/articles",
        headers={"X-API-Key": "invalid-secret-key-probe"},
    )
    assert resp.status_code == 401


def test_session_cookie_authenticates_ui_and_api(auth_client: TestClient):
    """Verifies that a valid session cookie grants full access to UI pages and API endpoints."""
    # UI pages
    assert auth_client.get("/pages").status_code == 200
    assert auth_client.get("/notes").status_code == 200
    assert auth_client.get("/workspaces").status_code == 200
    assert auth_client.get("/reports").status_code == 200
    assert auth_client.get("/admin").status_code == 200

    # API endpoints
    assert auth_client.get("/api/articles").status_code == 200
    assert auth_client.get("/api/workspaces").status_code == 200


def test_http_security_headers_present(unauth_client: TestClient, auth_client: TestClient):
    """Verifies that industry-standard HTTP security headers are injected onto all responses."""
    for client, route in [(unauth_client, "/login"), (auth_client, "/pages"), (unauth_client, "/manifest.json")]:
        resp = client.get(route)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_login_rate_limiting(unauth_client: TestClient):
    """Verifies that repeated failed login attempts from an IP trigger 429 Too Many Requests."""
    # Clear prior recorded attempts for test IP
    test_ip = "testclient"
    with _login_lock:
        _login_failed_attempts.pop(test_ip, None)

    # 5 failed attempts
    for _ in range(5):
        resp = unauth_client.post("/login", data={"password": "wrong_password"})
        assert resp.status_code == 401
        assert "Invalid security credentials" in resp.text

    # 6th attempt should be blocked with 429
    resp = unauth_client.post("/login", data={"password": "wrong_password"})
    assert resp.status_code == 429
    assert "Too many failed login attempts" in resp.text

    # Successful login resets the counter once window resets or lockout expires
    with _login_lock:
        _login_failed_attempts.pop(test_ip, None)
        from kb_web.routers.auth import _global_failed_attempts
        _global_failed_attempts.clear()

    login_resp = unauth_client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    assert COOKIE_NAME in login_resp.cookies

    # Clean up after test
    with _login_lock:
        _login_failed_attempts.pop(test_ip, None)
        _global_failed_attempts.clear()



def test_workspace_path_traversal_blocked(auth_client: TestClient):
    """Verifies that directory traversal sequences in workspace files are blocked."""
    # Create test workspace
    create_resp = auth_client.post(
        "/api/workspaces",
        json={"name": "Traversal Test", "template": "blank"},
    )
    assert create_resp.status_code == 200
    ws_id = create_resp.json()["id"]

    # Traversal file upsert attempt
    bad_upsert = auth_client.post(
        f"/api/workspaces/{ws_id}/files",
        json={"path": "../../../etc/passwd", "content": "malicious"},
    )
    assert bad_upsert.status_code == 400
    assert "traversal" in bad_upsert.json().get("detail", "").lower()

    # Traversal file delete attempt
    bad_delete = auth_client.request(
        "DELETE",
        f"/api/workspaces/{ws_id}/files",
        json={"path": "../../../sensitive.py"},
    )
    assert bad_delete.status_code == 400


def test_change_password_length_validation(auth_client: TestClient):
    """Verifies that passwords under 8 characters are rejected."""
    resp = auth_client.post(
        "/admin/change-password",
        data={
            "current_password": server_config.admin_password,
            "new_password": "short",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "at+least+8+characters" in resp.headers["location"]


def test_login_rate_limiting_trusted_proxy_and_spoofing_defense(unauth_client: TestClient, monkeypatch):
    """Verifies that untrusted clients cannot bypass lockout by rotating X-Forwarded-For (SEC-01)."""
    from kb_web.routers.auth import _login_lock, _login_failed_attempts, _get_client_ip
    from starlette.requests import Request

    # 1. Direct untrusted client cannot spoof IP via X-Forwarded-For
    monkeypatch.setattr(server_config, "trusted_proxies", "10.0.0.1")

    # Mock request where client host is NOT in trusted proxies
    scope = {
        "type": "http",
        "client": ("198.51.100.25", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.199")],
    }
    req = Request(scope)
    assert _get_client_ip(req) == "198.51.100.25"

    # 2. When client IS trusted proxy, extract right-most untrusted hop
    scope_trusted = {
        "type": "http",
        "client": ("10.0.0.1", 54321),
        "headers": [(b"x-forwarded-for", b"203.0.113.50, 10.0.0.2")],
    }
    req_trusted = Request(scope_trusted)
    # 10.0.0.2 is not in trusted_proxies (only 10.0.0.1 is), so it returns 10.0.0.2
    assert _get_client_ip(req_trusted) == "10.0.0.2"


def test_repo_import_url_validation():
    """Verifies that dangerous repo URLs, argument injection, and local file paths are blocked (SEC-03)."""
    import pytest
    from kb_web.repo_importer import validate_repo_url

    # Argument injection
    with pytest.raises(ValueError, match="cannot begin with a dash"):
        validate_repo_url("--upload-pack=touch /tmp/pwned")

    # Local file protocol
    with pytest.raises(ValueError, match="Local filesystem or file://"):
        validate_repo_url("file:///etc/passwd")

    with pytest.raises(ValueError, match="Local filesystem path"):
        validate_repo_url("/home/user/repo")

    # Dangerous protocols
    with pytest.raises(ValueError, match="Unsupported repository URL protocol"):
        validate_repo_url("ftp://example.com/repo.git")

    # Valid URLs
    assert validate_repo_url("https://github.com/Willmo103/kb-web.git") == "https://github.com/Willmo103/kb-web.git"
    assert validate_repo_url("http://gitlab.com/group/project") == "http://gitlab.com/group/project"
    assert validate_repo_url("git@github.com:Willmo103/kb-web.git") == "git@github.com:Willmo103/kb-web.git"


def test_html_sanitizer_and_stored_xss_protection():
    """Verifies that nh3 sanitizes malicious markdown/HTML outputs (SEC-02)."""
    from kb_web.utils import sanitize_html

    malicious_input = (
        "<h1>Safe Heading</h1>"
        "<script>alert('xss')</script>"
        "<img src='x' onerror='alert(document.cookie)'>"
        "<a href='javascript:alert(1)'>Click me</a>"
        "<p>Safe paragraph with <a href='https://example.com'>link</a>.</p>"
    )

    clean_output = sanitize_html(malicious_input)

    assert "<script>" not in clean_output
    assert "alert(" not in clean_output
    assert "onerror" not in clean_output
    assert "javascript:" not in clean_output
    assert "<h1>Safe Heading</h1>" in clean_output
    assert "https://example.com" in clean_output


def test_content_security_policy_header_present(unauth_client: TestClient):
    """Verifies that Content-Security-Policy is injected onto responses (SEC-02)."""
    resp = unauth_client.get("/login")
    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'self'" in csp


def test_fail_closed_default_api_key(unauth_client: TestClient, monkeypatch):
    """Verifies that kb-secret-key is rejected unless allow_insecure_defaults is set (SEC-04)."""
    from kb_web.base import verify_api_key
    from starlette.requests import Request
    from fastapi import HTTPException
    import pytest

    monkeypatch.setattr(type(server_config), "api_key", property(lambda self: "kb-secret-key"))
    monkeypatch.setattr(type(server_config), "allow_insecure_defaults", property(lambda self: False))

    scope = {
        "type": "http",
        "headers": [(b"x-api-key", b"kb-secret-key")],
    }
    req = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(req)
    assert exc_info.value.status_code == 401
    assert "disabled for security" in exc_info.value.detail


def test_scrypt_password_hashing_and_verification():
    """Verifies that scrypt password hashing and transparent verification work correctly (SEC-06)."""
    from kb_web.config import hash_password, verify_password

    pw = "SuperSecurePassword987!"
    hashed = hash_password(pw)

    assert hashed.startswith("scrypt$")
    assert pw not in hashed

    # Valid password against hash
    is_valid, needs_mig = verify_password(pw, hashed)
    assert is_valid is True
    assert needs_mig is False

    # Invalid password against hash
    is_valid_wrong, _ = verify_password("WrongPassword!", hashed)
    assert is_valid_wrong is False

    # Plaintext backward compatibility
    plain_stored = "legacy-plaintext-pass"
    is_valid_plain, needs_mig_plain = verify_password(plain_stored, plain_stored)
    assert is_valid_plain is True
    assert needs_mig_plain is True


def test_session_secret_independence(monkeypatch):
    """Verifies that session secret is decoupled from admin password changes (SEC-05)."""
    from kb_web.base import _get_session_secret, generate_session_token, verify_session_token
    import time

    # Initialize secret
    secret_1 = _get_session_secret()
    token = generate_session_token(time.time() + 3600)
    assert verify_session_token(token) is True

    # Change admin password
    orig_pass = server_config.admin_password
    try:
        server_config.admin_password = "a-brand-new-different-password"
        secret_2 = _get_session_secret()
        # Session secret is stable and independent of password
        assert secret_1 == secret_2
        assert verify_session_token(token) is True
    finally:
        server_config.admin_password = orig_pass


def test_config_save_redacts_credentials(tmp_path, monkeypatch):
    """Verifies that saving config does not dump plaintext secrets (SEC-06)."""
    monkeypatch.setattr(server_config, "configs_dir", tmp_path)
    monkeypatch.setattr(server_config, "_admin_password", "super-secret-cleartext")
    monkeypatch.setattr(server_config, "_admin_password_hash", None)
    monkeypatch.setattr(server_config, "_api_key", "secret-api-key-12345")

    server_config.save()

    import json
    saved_file = tmp_path / "kb-web.json"
    assert saved_file.exists()
    with open(saved_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("admin_password") == "[REDACTED]"
    assert data.get("api_key") == "[REDACTED]"
    assert "trusted_proxies" in data
