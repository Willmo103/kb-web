"""
FastAPI Router for authentication management in kb-web.
"""

import ipaddress
import threading
import time
from typing import Optional, Dict, List
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..base import (
    config,
    _jinja_env,
    COOKIE_NAME,
    SESSION_EXPIRATION_SECONDS,
    generate_session_token,
    verify_auth,
)
from ..config import verify_password, hash_password

router = APIRouter()

# In-memory sliding-window tracker for failed login attempts
_login_failed_attempts: Dict[str, List[float]] = {}
_global_failed_attempts: List[float] = []
_login_lock = threading.Lock()
MAX_FAILED_ATTEMPTS = 5
GLOBAL_MAX_FAILED_ATTEMPTS = 50
LOCKOUT_WINDOW_SECONDS = 60


def _is_trusted_proxy(ip_str: str) -> bool:
    """Checks whether the given IP address matches configured trusted_proxies list or CIDRs."""
    if not ip_str or ip_str == "unknown":
        return False
    trusted_raw = getattr(config, "trusted_proxies", "127.0.0.1, ::1")
    trusted_list = [p.strip() for p in trusted_raw.split(",") if p.strip()]
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for entry in trusted_list:
        try:
            if "/" in entry:
                if ip in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if ip == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False


def _get_client_ip(request: Request) -> str:
    """Extracts client IP considering trusted reverse-proxy headers (SEC-01)."""
    direct_ip = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(direct_ip):
        return direct_ip

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        hops = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        for hop in reversed(hops):
            if not _is_trusted_proxy(hop):
                return hop
        if hops:
            return hops[0]
    return direct_ip


@router.get("/login", response_class=HTMLResponse)
def get_login_page(next: Optional[str] = None) -> HTMLResponse:
    """Serves the login page to the user."""
    template = _jinja_env.get_template("login.j2.html")
    return HTMLResponse(content=template.render(is_admin=False, next=next))


@router.post("/login", response_model=None)
def handle_login(
    request: Request,
    password: str = Form(...),
    next: Optional[str] = Form(None),
) -> HTMLResponse | RedirectResponse:
    """Processes credential inputs, establishing cookie session records on success."""
    client_ip = _get_client_ip(request)
    now = time.time()

    # 1. Check rate limiting
    with _login_lock:
        # Check global lockout ceiling
        valid_global = [t for t in _global_failed_attempts if now - t < LOCKOUT_WINDOW_SECONDS]
        _global_failed_attempts[:] = valid_global
        if len(valid_global) >= GLOBAL_MAX_FAILED_ATTEMPTS:
            return HTMLResponse(
                content=_jinja_env.get_template("login.j2.html").render(
                    error="Service temporarily throttled due to excessive global login traffic. Please wait 60 seconds before trying again.",
                    is_admin=False,
                    next=next,
                ),
                status_code=429,
            )

        attempts = [t for t in _login_failed_attempts.get(client_ip, []) if now - t < LOCKOUT_WINDOW_SECONDS]
        _login_failed_attempts[client_ip] = attempts
        if len(attempts) >= MAX_FAILED_ATTEMPTS:
            remaining = int(LOCKOUT_WINDOW_SECONDS - (now - attempts[0]))
            return HTMLResponse(
                content=_jinja_env.get_template("login.j2.html").render(
                    error=f"Too many failed login attempts. Please wait {max(1, remaining)} seconds before trying again.",
                    is_admin=False,
                    next=next,
                ),
                status_code=429,
            )

    # 2. Timing-safe password evaluation (with automatic scrypt migration)
    is_valid, needs_migration = verify_password(password, config.admin_password)
    if not is_valid and config.admin_password_hash:
        is_valid, _ = verify_password(password, config.admin_password_hash)
        needs_migration = False

    if is_valid:
        if needs_migration:
            try:
                config.admin_password_hash = hash_password(password)
            except Exception:
                pass
        with _login_lock:
            _login_failed_attempts.pop(client_ip, None)

        expiry_time = now + SESSION_EXPIRATION_SECONDS
        session_token = generate_session_token(expiry_time)

        # Sanitize redirect target to prevent open redirect vulnerabilities
        redirect_target = next if next else "/"
        if redirect_target.startswith("http://") or redirect_target.startswith("https://"):
            parsed_next = urlparse(redirect_target)
            redirect_target = parsed_next.path
            if parsed_next.query:
                redirect_target += f"?{parsed_next.query}"

        # Prevent protocol-relative redirects (e.g. //evil.com)
        while redirect_target.startswith("//"):
            redirect_target = redirect_target[1:]
        if not redirect_target.startswith("/"):
            redirect_target = "/" + redirect_target

        response = RedirectResponse(url=redirect_target, status_code=303)

        # Automatic HTTPS detection for secure cookie transport
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto") == "https"
            or request.headers.get("x-forwarded-ssl") == "on"
        )

        response.set_cookie(
            key=COOKIE_NAME,
            value=session_token,
            httponly=True,
            samesite="lax",
            secure=is_https,
            max_age=SESSION_EXPIRATION_SECONDS,
        )
        return response

    # Failed attempt: record for IP rate limiting and global throttle
    with _login_lock:
        _login_failed_attempts.setdefault(client_ip, []).append(now)
        _global_failed_attempts.append(now)

    return HTMLResponse(
        content=_jinja_env.get_template("login.j2.html").render(
            error="Invalid security credentials.", is_admin=False, next=next
        ),
        status_code=401,
    )


@router.get("/logout")
def handle_logout() -> RedirectResponse:
    """Clears session state authentication credentials and returns to login."""
    response = RedirectResponse(url="/login?msg=Logged+out+successfully.", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.post(
    "/admin/change-password", dependencies=[Depends(verify_auth)], response_model=None
)
def handle_change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
) -> RedirectResponse:
    """Validates the current password and saves a new admin passcode."""
    stored_hash = getattr(config, "admin_password_hash", None)
    stored_pass = stored_hash if stored_hash else config.admin_password
    is_valid, _ = verify_password(current_password, stored_pass)
    if not is_valid:
        return RedirectResponse(
            url="/admin?error=Error:+Current+password+is+incorrect.",
            status_code=303,
        )

    clean_new = new_password.strip()
    if len(clean_new) < 8:
        return RedirectResponse(
            url="/admin?error=New+password+must+be+at+least+8+characters+long.",
            status_code=303,
        )

    config.admin_password = clean_new
    config.admin_password_hash = hash_password(clean_new)
    config.save()
    return RedirectResponse(
        url="/admin?msg=Password+successfully+updated.",
        status_code=303,
    )

