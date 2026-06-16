"""
Base shared dependencies, configuration, and route guards for kb-web.
"""

import time
import hashlib
import threading
import jinja2
import ollama
import sqlite_utils
from urllib.parse import quote_plus
from fastapi import Request, HTTPException

from .config import Config
from .db import init_db

# Instantiate global configuration
config = Config()

# Set up Jinja2 environment utilizing PackageLoader for clean packaging
_jinja_env = jinja2.Environment(loader=jinja2.PackageLoader("kb_web", "templates"))

COOKIE_NAME = "kb_session"
SESSION_EXPIRATION_SECONDS = 3600 * 24  # 24 hours

_local = threading.local()
_init_lock = threading.Lock()
_db_initialized = False


def _get_db() -> sqlite_utils.Database:
    """Helper dependency to retrieve a clean database handle."""
    global _db_initialized
    db_path = config.db_path
    db = getattr(_local, "db", None)
    db_path_cached = getattr(_local, "db_path", None)
    if db is None or db_path_cached != db_path:
        import sqlite3

        conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        db = sqlite_utils.Database(conn)
        if not _db_initialized:
            with _init_lock:
                if not _db_initialized:
                    init_db(db)
                    _db_initialized = True
        _local.db = db
        _local.db_path = db_path
    return db


def _get_ollama_client() -> ollama.Client:
    """Helper to dynamically instantiate the Ollama client based on configured host."""
    return ollama.Client(host=config.ollama_host)


def _get_session_secret() -> bytes:
    """Derives a cryptographically secure key for session signatures from the admin password."""
    return hashlib.sha256(config.admin_password.encode("utf-8")).digest()


def generate_session_token(expiry_time: float) -> str:
    """Generates a tamper-proof session token containing the expiration timestamp."""
    import hmac

    payload = str(int(expiry_time))
    secret = _get_session_secret()
    signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session_token(token: str) -> bool:
    """Verifies a signed token's cryptographic signature and expiration."""
    if not token or "." not in token:
        return False
    try:
        import hmac

        payload, signature = token.split(".", 1)
        expiry_time = int(payload)
        if expiry_time < time.time():
            return False

        secret = _get_session_secret()
        expected_signature = hmac.new(
            secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected_signature)
    except Exception:
        return False


def verify_auth(request: Request) -> None:
    """Security route guard ensuring requests contain a valid session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token or not verify_session_token(token):
        redirect_url = f"/login?next={quote_plus(str(request.url))}"
        raise HTTPException(status_code=303, headers={"Location": redirect_url})


def verify_api_key(request: Request) -> None:
    """Security guard verifying API Key header matching KB_API_KEY."""
    api_key_header = request.headers.get("X-API-Key")
    if not api_key_header:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key_header = auth_header[7:]
        else:
            api_key_header = auth_header

    if config.api_key:
        if api_key_header != config.api_key:
            raise HTTPException(
                status_code=401, detail="Unauthorized: Invalid API key."
            )
