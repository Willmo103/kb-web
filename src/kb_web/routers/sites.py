"""
FastAPI Router for virtual sites views in kb-web.
"""

from typing import Optional
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..base import (
    _get_db,
    _jinja_env,
    COOKIE_NAME,
    verify_session_token,
)
from ..models import HTMLPage
from ..utils import get_url_basename

router = APIRouter()


@router.get("/sites", response_class=HTMLResponse)
def view_all_sites(request: Request) -> RedirectResponse:
    """Redirects to the index page with view=sites."""
    return RedirectResponse(url="/?view=sites", status_code=303)


@router.get("/view/site", response_class=HTMLResponse)
def view_site_profile(
    request: Request,
    site: str = Query(...),
    msg: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
) -> HTMLResponse:
    """Renders the profile page for a specific virtual 'site', showing its pages."""
    db = _get_db()
    site_name = site.strip().lower()

    pages = []
    if "fetched_pages" in db.table_names():
        rows = list(db["fetched_pages"].rows)
        for row in rows:
            if get_url_basename(row["url"]) == site_name:
                pages.append(HTMLPage(**row))

    if not pages:
        return HTMLResponse(
            content=f"<h1>Site '{site_name}' has no imported pages.</h1>",
            status_code=404,
        )

    sites_dict = {}
    if "fetched_pages" in db.table_names():
        rows = list(db["fetched_pages"].rows)
        for row in rows:
            url = row["url"]
            basename = get_url_basename(url)
            if basename not in sites_dict:
                sites_dict[basename] = {
                    "name": basename,
                    "pages_count": 0,
                }
            sites_dict[basename]["pages_count"] += 1

    sorted_sites = sorted(
        sites_dict.values(), key=lambda x: (-x["pages_count"], x["name"])
    )

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    template = _jinja_env.get_template("view_site.j2.html")
    return HTMLResponse(
        content=template.render(
            site_name=site_name,
            pages=pages,
            other_sites=sorted_sites,
            is_admin=is_admin,
            msg=msg,
            error=error,
        )
    )
