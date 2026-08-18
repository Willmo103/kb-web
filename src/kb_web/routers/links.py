"""
FastAPI Router for managing and tracking regular, non-ingested web links.
"""

from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from ..base import (
    _jinja_env,
    COOKIE_NAME,
    verify_session_token,
    verify_auth,
    db_session,
)
from ..models_orm import Link

router = APIRouter()


@router.get("/links", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def view_links(request: Request) -> HTMLResponse:
    with db_session() as session:
        links_list = session.query(Link).order_by(Link.click_count.desc(), Link.id.desc()).all()

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    return HTMLResponse(
        _jinja_env.get_template("links.j2.html").render(
            request=request,
            links=links_list,
            is_admin=is_admin,
        )
    )


@router.post("/links/add", dependencies=[Depends(verify_auth)])
def add_link(
    url: str = Form(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
) -> RedirectResponse:
    url = url.strip()
    if not title:
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            title = parsed.netloc or url
        except Exception:
            title = url

    with db_session() as session:
        existing = session.query(Link).filter_by(url=url).first()
        if existing:
            existing.title = title.strip()
            existing.description = (description or "").strip()
        else:
            link = Link(
                url=url,
                title=title.strip(),
                description=(description or "").strip(),
                click_count=0,
                created_at=datetime.now().isoformat(),
                last_clicked_at="",
            )
            session.add(link)

    return RedirectResponse(url="/links", status_code=303)


@router.get("/links/go", dependencies=[Depends(verify_auth)])
def go_to_link(id: int) -> RedirectResponse:
    with db_session() as session:
        link = session.query(Link).filter_by(id=id).first()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found.")

        link.click_count += 1
        link.last_clicked_at = datetime.now().isoformat()
        redirect_url = link.url

    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/links/delete", dependencies=[Depends(verify_auth)])
def delete_link(id: int = Form(...)) -> RedirectResponse:
    with db_session() as session:
        link = session.query(Link).filter_by(id=id).first()
        if link:
            session.delete(link)
        else:
            raise HTTPException(status_code=404, detail="Link not found.")

    return RedirectResponse(url="/links", status_code=303)


@router.post("/links/import-bookmarks", dependencies=[Depends(verify_auth)])
async def import_bookmarks(file: UploadFile = File(...)) -> RedirectResponse:
    content_bytes = await file.read()
    content = content_bytes.decode("utf-8", errors="ignore")

    soup = BeautifulSoup(content, "html5lib")
    with db_session() as session:
        for a in soup.find_all("a", href=True):
            url = a["href"].strip()
            title = a.get_text().strip() or url
            existing = session.query(Link).filter_by(url=url).first()
            if not existing:
                session.add(
                    Link(
                        url=url,
                        title=title,
                        description="Imported from Bookmarks",
                        click_count=0,
                        created_at=datetime.now().isoformat(),
                        last_clicked_at="",
                    )
                )

    return RedirectResponse(url="/links", status_code=303)
