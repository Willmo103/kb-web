"""
FastAPI Router for Collections CRUD and AI-suggested groupings in kb-web.
"""

import json
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from ..base import (
    config,
    _jinja_env,
    _get_db,
    _get_ollama_client,
    COOKIE_NAME,
    verify_session_token,
    verify_auth,
)
from ..models import HTMLPage

router = APIRouter()


@router.get("/collections", response_class=HTMLResponse)
def list_collections(request: Request) -> HTMLResponse:
    """Lists all collections and ungrouped pages."""
    db = _get_db()
    collections_list = []
    ungrouped_pages = []

    if "collections" in db.table_names():
        try:
            # Get all collections with page count
            collections_list = list(db.execute_returning_dicts(
                """
                SELECT c.*, COUNT(f.url) as pages_count
                FROM collections c
                LEFT JOIN fetched_pages f ON c.id = f.collection_id
                GROUP BY c.id
                ORDER BY c.title ASC
                """
            ))
        except Exception as e:
            print(f"Error fetching collections: {e}")

    if "fetched_pages" in db.table_names():
        try:
            # Get all pages without a collection
            rows = db.execute_returning_dicts(
                "SELECT * FROM fetched_pages WHERE collection_id IS NULL ORDER BY ROWID DESC"
            )
            ungrouped_pages = [HTMLPage(**r) for r in rows]
        except Exception as e:
            print(f"Error fetching ungrouped pages: {e}")

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    template = _jinja_env.get_template("collections.j2.html")
    return HTMLResponse(
        content=template.render(
            collections=collections_list,
            ungrouped_pages=ungrouped_pages,
            is_admin=is_admin,
        )
    )


@router.post("/collections/create", dependencies=[Depends(verify_auth)])
def create_collection(title: str = Form(...)) -> RedirectResponse:
    """Creates a new collection in the database."""
    db = _get_db()
    title_clean = title.strip()
    if not title_clean:
        return RedirectResponse(url="/collections", status_code=303)

    try:
        db["collections"].insert({
            "title": title_clean,
            "created_at": datetime.now().isoformat()
        })
    except Exception as e:
        print(f"Failed to create collection: {e}")

    return RedirectResponse(url="/collections", status_code=303)


@router.get("/collections/view/{collection_id}", response_class=HTMLResponse)
def view_collection(request: Request, collection_id: int) -> HTMLResponse:
    """Renders all pages within a specific collection."""
    db = _get_db()
    try:
        collection = db["collections"].get(collection_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Collection not found.")

    pages = []
    if "fetched_pages" in db.table_names():
        try:
            rows = db.execute_returning_dicts(
                "SELECT * FROM fetched_pages WHERE collection_id = ? ORDER BY ROWID DESC",
                [collection_id]
            )
            pages = [HTMLPage(**r) for r in rows]
        except Exception as e:
            print(f"Failed to fetch collection pages: {e}")

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    template = _jinja_env.get_template("view_collection.j2.html")
    return HTMLResponse(
        content=template.render(
            collection=collection,
            pages=pages,
            is_admin=is_admin,
        )
    )


@router.post("/admin/pages/update-collection", dependencies=[Depends(verify_auth)])
def update_page_collection(
    url: str = Form(...),
    collection_id: Optional[int] = Form(None)
) -> RedirectResponse:
    """Assigns or updates the collection classification for an ingested page."""
    db = _get_db()
    try:
        # If collection_id is empty, it means "none" (remove from collection)
        val = int(collection_id) if collection_id else None
        db["fetched_pages"].update(url, {"collection_id": val})
    except Exception as e:
        print(f"Failed to update page collection: {e}")

    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)


@router.post("/admin/pages/remove-from-collection", dependencies=[Depends(verify_auth)])
def remove_page_from_collection(
    url: str = Form(...),
    redirect_to: str = Form("/collections")
) -> RedirectResponse:
    """Removes a page from its collection classification (sets collection_id to null)."""
    db = _get_db()
    try:
        db["fetched_pages"].update(url, {"collection_id": None})
    except Exception as e:
        print(f"Failed to remove page from collection: {e}")

    return RedirectResponse(url=redirect_to, status_code=303)


@router.post("/admin/collections/suggest", dependencies=[Depends(verify_auth)])
def suggest_collections() -> JSONResponse:
    """Queries Ollama to group ungrouped page titles into logical suggestions."""
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return JSONResponse(content={"suggestions": []})

    # Fetch all ungrouped pages
    rows = list(db.execute_returning_dicts(
        "SELECT url, title FROM fetched_pages WHERE collection_id IS NULL AND title IS NOT NULL"
    ))
    
    if not rows:
        return JSONResponse(content={"suggestions": [], "message": "No ungrouped pages available."})

    # Map titles to URLs
    title_to_url = {r["title"]: r["url"] for r in rows}
    titles = list(title_to_url.keys())

    system_prompt = (
        "You are an AI assistant that suggests logical collections to group web documents. "
        "You are provided with a list of document titles. Analyze them and suggest 3 to 6 logical collections. "
        "For each collection, specify its title and select the matching document titles exactly as provided. "
        "Each document title can belong to at most one collection. "
        "Respond ONLY with a valid JSON object of the following format: "
        '{"suggestions": [{"title": "Coding & Python", "matches": ["Introduction to Python", "Decorators in Python"]}]}. '
        "Do not output any conversational text, introductory statements, or markdown codeblocks outside the JSON."
    )

    try:
        client = _get_ollama_client()
        user_content = "Document Titles:\n" + "\n".join(titles)
        
        response = client.chat(
            model=config.ollama_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        )
        raw_text = response.message.content.strip()
        
        # Clean potential markdown wrapping
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1] == "```":
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()
            
        suggestions_data = json.loads(raw_text)
        
        # Convert matches back to URLs for the frontend
        formatted_suggestions = []
        for sug in suggestions_data.get("suggestions", []):
            sug_title = sug.get("title", "Unnamed Suggestion")
            matches = sug.get("matches", [])
            
            sug_pages = []
            for t in matches:
                if t in title_to_url:
                    sug_pages.append({
                        "url": title_to_url[t],
                        "title": t
                    })
                    
            if sug_pages:
                formatted_suggestions.append({
                    "title": sug_title,
                    "pages": sug_pages
                })
                
        return JSONResponse(content={"suggestions": formatted_suggestions})
    except Exception as e:
        print(f"Ollama collection suggestions failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate suggestions: {str(e)}"}
        )


@router.post("/admin/collections/accept-suggestion", dependencies=[Depends(verify_auth)])
def accept_suggestion(
    title: str = Form(...),
    urls_json: str = Form(...)
) -> RedirectResponse:
    """Accepts an AI grouping suggestion: creates the collection and associates the matching pages."""
    db = _get_db()
    title_clean = title.strip()
    if not title_clean:
        return RedirectResponse(url="/collections", status_code=303)

    try:
        collection_id = db["collections"].insert({
            "title": title_clean,
            "created_at": datetime.now().isoformat()
        }).last_rowid

        urls = json.loads(urls_json)
        for url in urls:
            db["fetched_pages"].update(url, {"collection_id": collection_id})
        print(f"AI Suggestion: Created collection '{title_clean}' and assigned {len(urls)} pages.")
    except Exception as e:
        print(f"Failed to create collection from AI suggestion: {e}")

    return RedirectResponse(url="/collections", status_code=303)

