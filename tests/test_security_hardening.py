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

    login_resp = unauth_client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    assert COOKIE_NAME in login_resp.cookies


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
