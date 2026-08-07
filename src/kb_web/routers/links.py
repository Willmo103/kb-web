"""
FastAPI Router for managing and tracking regular, non-ingested web links.
"""

import json
import re
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from ..base import (
    config,
    _get_db,
    _jinja_env,
    COOKIE_NAME,
    verify_session_token,
    verify_auth,
)

router = APIRouter()


@router.get("/links", response_class=HTMLResponse)
def view_links(request: Request) -> HTMLResponse:
    db = _get_db()
    links_list = []
    if "links" in db.table_names():
        links_list = list(db["links"].rows_where(order_by="click_count DESC, id DESC"))
        
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
    description: Optional[str] = Form(None)
) -> RedirectResponse:
    db = _get_db()
    
    url = url.strip()
    if not title:
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            title = parsed.netloc or url
        except Exception:
            title = url

    try:
        db["links"].insert({
            "url": url,
            "title": title.strip(),
            "description": (description or "").strip(),
            "click_count": 0,
            "created_at": datetime.now().isoformat(),
            "last_clicked_at": ""
        }, pk="id")
        db.conn.commit()
    except Exception as e:
        if "UNIQUE" in str(e) or "unique" in str(e).lower():
            try:
                row = list(db["links"].rows_where("url = ?", [url]))
                if row:
                    db["links"].update(row[0]["id"], {
                        "title": title.strip(),
                        "description": (description or "").strip()
                    })
                    db.conn.commit()
            except Exception:
                raise HTTPException(status_code=400, detail=f"Link already exists or invalid: {e}")
        else:
            raise HTTPException(status_code=400, detail=str(e))
            
    return RedirectResponse(url="/links", status_code=303)


@router.get("/links/go")
def go_to_link(id: int) -> RedirectResponse:
    db = _get_db()
    try:
        row = db["links"].get(id)
    except Exception:
        raise HTTPException(status_code=404, detail="Link not found.")
        
    click_count = row.get("click_count", 0) + 1
    db["links"].update(id, {
        "click_count": click_count,
        "last_clicked_at": datetime.now().isoformat()
    })
    db.conn.commit()
    
    return RedirectResponse(url=row["url"], status_code=303)


@router.post("/links/delete", dependencies=[Depends(verify_auth)])
def delete_link(id: int = Form(...)) -> RedirectResponse:
    db = _get_db()
    try:
        db["links"].delete(id)
        db.conn.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    return RedirectResponse(url="/links", status_code=303)


@router.post("/links/import-bookmarks", dependencies=[Depends(verify_auth)])
async def import_bookmarks(file: UploadFile = File(...)) -> RedirectResponse:
    db = _get_db()
    content_bytes = await file.read()
    content = content_bytes.decode("utf-8", errors="ignore")
    
    soup = BeautifulSoup(content, "html5lib")
    links_added = 0
    for a in soup.find_all("a", href=True):
        url = a["href"].strip()
        title = a.get_text().strip() or url
        existing = list(db["links"].rows_where("url = ?", [url]))
        if not existing:
            db["links"].insert({
                "url": url,
                "title": title,
                "description": "Imported from Bookmarks",
                "click_count": 0,
                "created_at": datetime.now().isoformat(),
                "last_clicked_at": ""
            }, pk="id")
            links_added += 1
            
    if links_added > 0:
        db.conn.commit()
        
    return RedirectResponse(url="/links", status_code=303)
