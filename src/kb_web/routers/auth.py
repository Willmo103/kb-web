"""
FastAPI Router for authentication management in kb-web.
"""

import hmac
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

router = APIRouter()

# In-memory sliding-window tracker for failed login attempts by IP address
_login_failed_attempts: Dict[str, List[float]] = {}
_login_lock = threading.Lock()
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 60


def _get_client_ip(request: Request) -> str:
    """Extracts client IP considering standard reverse-proxy headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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

    # 2. Timing-safe password evaluation
    if hmac.compare_digest(password, config.admin_password):
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

    # Failed attempt: record for IP rate limiting
    with _login_lock:
        _login_failed_attempts.setdefault(client_ip, []).append(now)

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
    if not hmac.compare_digest(current_password, config.admin_password):
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
    config.save()
    return RedirectResponse(
        url="/admin?msg=Password+successfully+updated.",
        status_code=303,
    )
