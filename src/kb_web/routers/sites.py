import json
from urllib.parse import quote_plus
from typing import Optional, List
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..base import (
    _jinja_env,
    COOKIE_NAME,
    verify_session_token,
    db_session,
)
from ..models_orm import FetchedPage
from ..utils import get_url_basename

router = APIRouter()


def _parse_tags(tags_raw) -> List[str]:
    """Parses JSON-encoded or comma-separated tags into a clean list of strings."""
    if not tags_raw:
        return []
    if isinstance(tags_raw, list):
        return [str(t).strip() for t in tags_raw if t]
    if isinstance(tags_raw, str):
        try:
            parsed = json.loads(tags_raw)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if t]
            elif isinstance(parsed, str):
                parsed_inner = json.loads(parsed)
                if isinstance(parsed_inner, list):
                    return [str(t).strip() for t in parsed_inner if t]
                return [parsed.strip()]
        except Exception:
            return [t.strip() for t in tags_raw.split(",") if t.strip()]
    return []


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
    site_name = site.strip().lower()

    sites_dict = {}

    with db_session() as session:
        all_urls = session.query(FetchedPage.url).all()

        matching_urls = []
        for (u,) in all_urls:
            basename = get_url_basename(u)
            if basename == site_name:
                matching_urls.append(u)
            if basename not in sites_dict:
                sites_dict[basename] = {
                    "name": basename,
                    "pages_count": 0,
                }
            sites_dict[basename]["pages_count"] += 1

        if not matching_urls:
            return HTMLResponse(
                content=f"<h1>Site '{site_name}' has no imported pages.</h1>",
                status_code=404,
            )

        matching_rows = (
            session.query(
                FetchedPage.url,
                FetchedPage.title,
                FetchedPage.tags,
                FetchedPage.description,
                FetchedPage.fetched_at,
            )
            .filter(FetchedPage.url.in_(matching_urls))
            .all()
        )

        pages = [
            {
                "url": row.url,
                "safe_url": quote_plus(row.url),
                "title": row.title or row.url,
                "tags": _parse_tags(row.tags),
                "description": row.description or "",
                "fetched_at": row.fetched_at or "",
            }
            for row in matching_rows
        ]

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
