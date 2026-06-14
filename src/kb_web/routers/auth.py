"""
FastAPI Router for authentication management in kb-web.
"""

import time
from typing import Optional
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, Form
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


@router.get("/login", response_class=HTMLResponse)
def get_login_page(next: Optional[str] = None) -> HTMLResponse:
    """Serves the login page to the user."""
    template = _jinja_env.get_template("login.j2.html")
    return HTMLResponse(content=template.render(is_admin=False, next=next))


@router.post("/login", response_model=None)
def handle_login(
    password: str = Form(...), next: Optional[str] = Form(None)
) -> HTMLResponse | RedirectResponse:
    """Processes credential inputs, establishing cookie session records on success."""
    if password == config.admin_password:
        expiry_time = time.time() + SESSION_EXPIRATION_SECONDS
        session_token = generate_session_token(expiry_time)

        redirect_target = next if next else "/"
        if redirect_target.startswith("http://") or redirect_target.startswith(
            "https://"
        ):
            parsed_next = urlparse(redirect_target)
            redirect_target = parsed_next.path
            if parsed_next.query:
                redirect_target += f"?{parsed_next.query}"
            if not redirect_target.startswith("/"):
                redirect_target = "/" + redirect_target

        response = RedirectResponse(url=redirect_target, status_code=303)
        response.set_cookie(
            key=COOKIE_NAME,
            value=session_token,
            httponly=True,
            samesite="lax",
            max_age=SESSION_EXPIRATION_SECONDS,
        )
        return response

    return HTMLResponse(
        content=_jinja_env.get_template("login.j2.html").render(
            error="Invalid security credentials.", is_admin=False, next=next
        )
    )


@router.get("/logout")
def handle_logout() -> RedirectResponse:
    """Clears session state authentication credentials."""
    response = RedirectResponse(url="/", status_code=303)
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
    if current_password != config.admin_password:
        return RedirectResponse(
            url="/admin?msg=Error:+Current+password+is+incorrect.",
            status_code=303,
        )

    config.admin_password = new_password
    config.save()
    return RedirectResponse(
        url="/admin?msg=Password+successfully+updated.",
        status_code=303,
    )
