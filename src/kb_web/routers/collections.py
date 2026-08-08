"""
FastAPI Router for Collections CRUD, AI-suggested groupings, and Qdrant sync in kb-web.
"""

import json
import time
import os
import re
import uuid
import httpx
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse

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
from ..utils import generate_gemma_embeddings_for_page
from ..config import DEFAULT_RAG_SYSTEM_PROMPT, DEFAULT_TAXONOMY_SYSTEM_PROMPT
from ..db import get_general_collection_id

router = APIRouter()


# --- Qdrant Sync & Offline Queue Utilities ---

def save_sync_locally(col_name: str, points: list[dict]) -> None:
    offline_dir = config.configs_dir.parent / "qdrant_offline"
    offline_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{col_name}_{int(time.time())}.json"
    filepath = offline_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"collection_name": col_name, "points": points}, f, indent=4)
    print(f"Saved Qdrant sync locally: {filepath}")


def flush_local_syncs(qdrant_url: str, headers: dict) -> None:
    offline_dir = config.configs_dir.parent / "qdrant_offline"
    if not offline_dir.exists():
        return
    import glob
    files = glob.glob(str(offline_dir / "*.json"))
    if not files:
        return
        
    with httpx.Client(timeout=15.0) as client:
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                col_name = data["collection_name"]
                points = data["points"]
                vector_size = len(points[0]["vector"]) if points else 768
                
                # Check/create collection
                res = client.get(f"{qdrant_url}/collections/{col_name}", headers=headers)
                if res.status_code == 404:
                    client.put(f"{qdrant_url}/collections/{col_name}", headers=headers, json={
                        "vectors": {
                            "size": vector_size,
                            "distance": "Cosine"
                        }
                    }).raise_for_status()
                    
                # Upload points
                batch_size = 100
                for i in range(0, len(points), batch_size):
                    batch = points[i:i+batch_size]
                    client.put(f"{qdrant_url}/collections/{col_name}/points", headers=headers, json={
                        "points": batch
                    }).raise_for_status()
                    
                # Delete successfully flushed file
                os.remove(filepath)
                print(f"Successfully flushed offline sync file: {filepath}")
            except Exception as e:
                print(f"Failed to flush offline sync file {filepath}: {e}")


def sync_collection_to_qdrant(db, collection_id: int) -> tuple[bool, str]:
    qdrant_url = config.qdrant_host_url
    qdrant_key = config.qdrant_api_key
    
    if not qdrant_url:
        return False, "Qdrant Host URL is not configured."
        
    try:
        collection = db["collections"].get(collection_id)
    except Exception:
        return False, "Collection not found."
        
    col_name = re.sub(r'[^a-zA-Z0-9_-]', '_', collection["title"]).lower()
    
    # Gather points
    items = list(db["collection_items"].rows_where("collection_id = ?", [collection_id]))
    
    points = []
    for item in items:
        source_type = item["source_type"]
        source_id = item["source_id"]
        
        # Get chunk embeddings
        chunks = list(db["chunk_embeddings"].rows_where("source_type = ? AND source_id = ?", [source_type, source_id]))
        item_note = item.get("item_note") or ""
        taxonomy_path = item.get("taxonomy_path") or ""
        
        for chunk in chunks:
            chunk_num = chunk["chunk_number"]
            try:
                vector = json.loads(chunk["chunk_vector"])
            except Exception:
                continue
                
            pt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_type}:{source_id}:{chunk_num}"))
            
            payload = {
                "source_type": source_type,
                "source_id": source_id,
                "source_title": chunk.get("source_title") or source_id,
                "chunk_number": chunk_num,
                "chunk_content": chunk.get("chunk_content") or "",
                "created_at": chunk.get("created_at") or datetime.now().isoformat(),
                "item_note": item_note,
                "taxonomy_path": taxonomy_path
            }
            
            points.append({
                "id": pt_id,
                "vector": vector,
                "payload": payload
            })
            
    if not points:
        return True, "Collection is empty. Nothing to sync."
        
    vector_size = len(points[0]["vector"])
        
    headers = {}
    if qdrant_key:
        headers["api-key"] = qdrant_key
        
    client_timeout = httpx.Timeout(15.0)
    with httpx.Client(timeout=client_timeout) as client:
        try:
            res = client.get(f"{qdrant_url}/collections/{col_name}", headers=headers)
            if res.status_code == 404:
                create_res = client.put(f"{qdrant_url}/collections/{col_name}", headers=headers, json={
                    "vectors": {
                        "size": vector_size,
                        "distance": "Cosine"
                    }
                })
                create_res.raise_for_status()
            elif res.status_code != 200:
                res.raise_for_status()
        except Exception as conn_err:
            save_sync_locally(col_name, points)
            return False, f"Qdrant connection error. Saved sync locally. Details: {conn_err}"
            
        try:
            batch_size = 100
            for i in range(0, len(points), batch_size):
                batch = points[i:i+batch_size]
                upsert_res = client.put(f"{qdrant_url}/collections/{col_name}/points", headers=headers, json={
                    "points": batch
                })
                upsert_res.raise_for_status()
        except Exception as upsert_err:
            save_sync_locally(col_name, points)
            return False, f"Qdrant point upload failed. Saved sync locally. Details: {upsert_err}"
            
    try:
        flush_local_syncs(qdrant_url, headers)
    except Exception as flush_err:
        print(f"Warning: Failed to flush local syncs: {flush_err}")
        
    return True, f"Successfully synced {len(points)} points to Qdrant collection '{col_name}'."


# --- Endpoints ---

@router.get("/collections", response_class=HTMLResponse)
def list_collections(request: Request) -> HTMLResponse:
    """Lists all collections and ungrouped pages."""
    db = _get_db()
    collections_list = []
    ungrouped_pages = []

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    if "collections" in db.table_names():
        try:
            # Get all collections with page count from many-to-many table
            collections_list = list(db.execute_returning_dicts(
                """
                SELECT c.*, COUNT(ci.id) as pages_count
                FROM collections c
                LEFT JOIN collection_items ci ON c.id = ci.collection_id
                GROUP BY c.id
                ORDER BY c.title ASC
                """
            ))
            
            # Filter out private collections for non-admin users
            if not is_admin:
                collections_list = [c for c in collections_list if c.get("visibility") != "private"]
        except Exception as e:
            print(f"Error fetching collections: {e}")

    if "fetched_pages" in db.table_names():
        try:
            # Get pages not assigned to any collection except possibly General Collection
            general_id = get_general_collection_id(db)
            rows = db.execute_returning_dicts(
                """
                SELECT * FROM fetched_pages 
                WHERE url NOT IN (
                    SELECT source_id FROM collection_items WHERE collection_id != ?
                )
                ORDER BY ROWID DESC
                """,
                [general_id]
            )
            ungrouped_pages = [HTMLPage(**r) for r in rows]
        except Exception as e:
            print(f"Error fetching ungrouped pages: {e}")

    # Fetch all pages to populate dropdowns in collections management panel
    all_pages_list = []
    if is_admin and "fetched_pages" in db.table_names():
        try:
            all_pages_list = [HTMLPage(**r) for r in db["fetched_pages"].rows]
        except Exception:
            pass

    template = _jinja_env.get_template("collections.j2.html")
    return HTMLResponse(
        content=template.render(
            collections=collections_list,
            ungrouped_pages=ungrouped_pages,
            all_pages=all_pages_list,
            is_admin=is_admin,
        )
    )


@router.post("/collections/create", dependencies=[Depends(verify_auth)])
def create_collection(
    title: str = Form(...),
    visibility: str = Form("public")
) -> RedirectResponse:
    """Creates a new collection in the database."""
    db = _get_db()
    title_clean = title.strip()
    if not title_clean:
        return RedirectResponse(url="/collections", status_code=303)

    try:
        db["collections"].insert({
            "title": title_clean,
            "visibility": visibility,
            "rag_system_prompt": DEFAULT_RAG_SYSTEM_PROMPT,
            "taxonomy_system_prompt": DEFAULT_TAXONOMY_SYSTEM_PROMPT,
            "general_system_context": "{}",
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

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    if not is_admin and collection.get("visibility") == "private":
        raise HTTPException(status_code=403, detail="Unauthorized: This is a private collection.")

    pages = []
    if "fetched_pages" in db.table_names() and "collection_items" in db.table_names():
        try:
            # Query pages joined with collection_items order
            rows = list(db.execute_returning_dicts(
                """
                SELECT f.*, ci.item_note, ci.taxonomy_path, ci.item_order
                FROM fetched_pages f
                JOIN collection_items ci ON f.url = ci.source_id
                WHERE ci.collection_id = ?
                ORDER BY ci.item_order ASC, ci.id DESC
                """,
                [collection_id]
            ))
            for r in rows:
                coll_title = None
                coll_id = None
                try:
                    coll_rows = list(db.execute_returning_dicts(
                        """
                        SELECT c.id, c.title FROM collections c
                        JOIN collection_items ci ON c.id = ci.collection_id
                        WHERE ci.source_id = ? AND c.id != 1
                        """,
                        [r["url"]]
                    ))
                    if coll_rows:
                        coll_title = ", ".join([col["title"] for col in coll_rows])
                        coll_id = coll_rows[0]["id"]
                except Exception:
                    pass
                r["collection_title"] = coll_title
                r["collection_id"] = coll_id
            pages = [HTMLPage(**r) for r in rows]
        except Exception as e:
            print(f"Failed to fetch collection pages: {e}")

    # Fetch all pages list for additions dropdown
    all_pages_list = []
    if is_admin and "fetched_pages" in db.table_names():
        try:
            all_rows = list(db.execute_returning_dicts("SELECT * FROM fetched_pages"))
            for r in all_rows:
                coll_title = None
                coll_id = None
                try:
                    coll_rows = list(db.execute_returning_dicts(
                        """
                        SELECT c.id, c.title FROM collections c
                        JOIN collection_items ci ON c.id = ci.collection_id
                        WHERE ci.source_id = ? AND c.id != 1
                        """,
                        [r["url"]]
                    ))
                    if coll_rows:
                        coll_title = ", ".join([col["title"] for col in coll_rows])
                        coll_id = coll_rows[0]["id"]
                except Exception:
                    pass
                r["collection_title"] = coll_title
                r["collection_id"] = coll_id
            all_pages_list = [HTMLPage(**r) for r in all_rows]
        except Exception:
            pass

    template = _jinja_env.get_template("view_collection.j2.html")
    return HTMLResponse(
        content=template.render(
            collection=collection,
            pages=pages,
            all_pages=all_pages_list,
            is_admin=is_admin,
        )
    )


@router.post("/collections/view/{collection_id}/save-items", dependencies=[Depends(verify_auth)])
def save_collection_items(
    collection_id: int,
    urls_json: str = Form(...)
) -> JSONResponse:
    """Saves the exact set and ordered sequence of items inside a collection."""
    db = _get_db()
    try:
        urls = json.loads(urls_json)
        
        # Clear existing items
        db["collection_items"].delete_where("collection_id = ?", [collection_id])
        db.conn.commit()
        
        # Insert items with reordered position
        for idx, url in enumerate(urls):
            # Check page type
            is_video = False
            if "youtube_videos" in db.table_names():
                try:
                    if db["youtube_videos"].get(url):
                        is_video = True
                except Exception:
                    pass
            source_type = "videos" if is_video else "articles"
            
            db["collection_items"].insert({
                "collection_id": collection_id,
                "source_type": source_type,
                "source_id": url,
                "item_note": "",
                "taxonomy_path": "",
                "item_order": idx,
                "added_at": datetime.now().isoformat()
            })
            
        return JSONResponse(content={"status": "success", "message": f"Successfully updated {len(urls)} collection items."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/collections/view/{collection_id}/save-settings", dependencies=[Depends(verify_auth)])
def save_collection_settings(
    collection_id: int,
    visibility: str = Form("public"),
    rag_system_prompt: str = Form(""),
    taxonomy_system_prompt: str = Form(""),
    general_system_context: str = Form("{}"),
) -> RedirectResponse:
    """Updates visibility and agent configuration settings for a collection."""
    db = _get_db()
    try:
        db["collections"].update(collection_id, {
            "visibility": visibility,
            "rag_system_prompt": rag_system_prompt,
            "taxonomy_system_prompt": taxonomy_system_prompt,
            "general_system_context": general_system_context,
        })
    except Exception as e:
        print(f"Failed to save collection settings: {e}")
    return RedirectResponse(url=f"/collections/view/{collection_id}", status_code=303)


@router.post("/collections/view/{collection_id}/sync", dependencies=[Depends(verify_auth)])
def sync_collection_endpoint(collection_id: int) -> JSONResponse:
    """Endpoint to trigger collection point synchronization to Qdrant."""
    db = _get_db()
    success, msg = sync_collection_to_qdrant(db, collection_id)
    if success:
        return JSONResponse(content={"status": "success", "message": msg})
    return JSONResponse(status_code=500, content={"status": "error", "message": msg})


@router.post("/admin/pages/update-collection", dependencies=[Depends(verify_auth)])
async def update_page_collection(
    request: Request,
    url: str = Form(...),
    collection_id: Optional[str] = Form(None)
) -> RedirectResponse:
    """Assigns or updates the collection classification for an ingested page (supports multi-select)."""
    db = _get_db()
    try:
        form_data = await request.form()
        collection_ids = form_data.getlist("collection_ids")
        
        # Fallback to single collection_id if collection_ids is empty
        if not collection_ids and collection_id:
            collection_ids = [collection_id]
            
        # Delete existing items for this source ID except General Collection
        general_id = get_general_collection_id(db)
        db["collection_items"].delete_where("source_id = ? AND collection_id != ?", [url, general_id])
        db.conn.commit()
        
        # Check type
        is_video = False
        if "youtube_videos" in db.table_names():
            try:
                if db["youtube_videos"].get(url):
                    is_video = True
            except Exception:
                pass
        source_type = "videos" if is_video else "articles"
        
        for cid in collection_ids:
            if not cid:
                continue
            val = int(cid)
            try:
                db["collection_items"].insert({
                    "collection_id": val,
                    "source_type": source_type,
                    "source_id": url,
                    "item_note": "",
                    "taxonomy_path": "",
                    "item_order": 9999,
                    "added_at": datetime.now().isoformat()
                })
            except Exception:
                pass # Already exists
            
    except Exception as e:
        print(f"Failed to update page collection: {e}")

    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)


@router.post("/admin/pages/remove-from-collection", dependencies=[Depends(verify_auth)])
def remove_page_from_collection(
    url: str = Form(...),
    redirect_to: str = Form("/collections")
) -> RedirectResponse:
    """Removes a page from its collection classification in the many-to-many relationship."""
    db = _get_db()
    try:
        # If redirected to a view_collection, we parse the ID and remove it specifically
        collection_id = None
        match = re.search(r"/collections/view/(\d+)", redirect_to)
        if match:
            collection_id = int(match.group(1))
            
        if collection_id:
            db["collection_items"].delete_where("collection_id = ? AND source_id = ?", [collection_id, url])
        else:
            db["collection_items"].delete_where("source_id = ? AND collection_id != 1", [url])
        db.conn.commit()
    except Exception as e:
        print(f"Failed to remove page from collection: {e}")

    return RedirectResponse(url=redirect_to, status_code=303)


@router.get("/admin/collections/populate-general", dependencies=[Depends(verify_auth)])
def populate_general_collection_stream() -> StreamingResponse:
    """Streams the bulk migration populator that seeds each document into the General Collection."""
    db = _get_db()
    general_id = get_general_collection_id(db)
    async def populate_stream():
        yield """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>General Collection Seed Process</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Outfit', sans-serif; background-color: #F4EFEA; }
    </style>
</head>
<body class="text-gray-850 min-h-screen antialiased flex flex-col justify-center items-center">
    <div class="w-full max-w-xl bg-white p-8 rounded-xl border border-gray-200 shadow-lg mx-4">
        <h1 class="text-xl font-bold text-gray-900 mb-4 flex items-center gap-2">
            <span>⚙️</span> Seed General Collection (id={general_id})
        </h1>
        <p class="text-sm text-gray-500 mb-6" id="status-text">Scanning database pages...</p>
        
        <div class="w-full bg-gray-200 rounded-full h-3 mb-6 overflow-hidden">
            <div id="progress-bar" class="bg-indigo-600 h-3 rounded-full transition-all duration-200" style="width: 0%"></div>
        </div>
        
        <div class="bg-gray-950 text-gray-200 font-mono text-xs p-4 rounded-lg h-64 overflow-y-auto space-y-1" id="terminal-logs">
            <div class="text-gray-500">[SYSTEM] Initialization...</div>
        </div>
    </div>
    <script>
        const progressBar = document.getElementById('progress-bar');
        const statusText = document.getElementById('status-text');
        const terminalLogs = document.getElementById('terminal-logs');
        
        function updateProgress(message, percentage) {
            statusText.innerText = message;
            progressBar.style.width = percentage + '%';
            addLog(message);
        }
        
        function addLog(text) {
            const div = document.createElement('div');
            div.innerText = "[" + new Date().toLocaleTimeString() + "] " + text;
            terminalLogs.appendChild(div);
            terminalLogs.scrollTop = terminalLogs.scrollHeight;
        }
    </script>
""".replace("{general_id}", str(general_id))
        client = _get_ollama_client()
        if "fetched_pages" not in db.table_names():
            yield f"<script>updateProgress({json.dumps('Error: fetched_pages table not found!')}, 100);</script>\n"
            return
            
        pages = list(db["fetched_pages"].rows)
        total_pages = len(pages)
        yield f"<script>addLog({json.dumps(f'Found {total_pages} total pages to process.')});</script>\n"
        
        for idx, page in enumerate(pages):
            url = page["url"]
            title = page.get("title") or url
            desc = page.get("description") or ""
            tags_json = page.get("tags") or "[]"
            # Check if it should be excluded from General Collection
            exclude = bool(page.get("exclude_from_general"))
            if exclude:
                log_msg = f"Excluding: {title} (exclude_from_general is set)"
                yield f"<script>addLog({json.dumps(log_msg)});</script>\n"
                continue
                
            # Check if it already exists in general_collection
            is_present = False
            try:
                if list(db["collection_items"].rows_where("collection_id = ? AND source_id = ?", [general_id, url])):
                    is_present = True
            except Exception:
                pass
                
            if is_present:
                percentage = int(((idx + 1) / total_pages) * 100)
                skip_msg = f"Skipping {title[:35]}... (Already in General Collection)"
                yield f"<script>updateProgress({json.dumps(skip_msg)}, {percentage});</script>\n"
                continue
                
            # Log starting item
            yield f"<script>addLog({json.dumps(f'Processing {idx+1}/{total_pages}: {title[:35]}...')});</script>\n"

            # Ask agent for parameters: <taxonomical/path/in/general/collection> <collection_action_note>
            # Compile taxonomy system instructions utilizing DB configurations and taxonomy tree context
            try:
                collection_general = db["collections"].get(general_id)
                system_instructions = compile_taxonomy_system_prompt(collection_general, db)
            except Exception:
                system_instructions = (
                    "You are an expert taxonomist. Categorize the document into a virtual filetree system "
                    "representing the General Collection of all knowledge. "
                    "Output ONLY a valid JSON object matching the format: "
                    '{"taxonomy_path": "/Folder/Subfolder/Filename.md", "action_note": "A short, 1-sentence description of what this note contains."}'
                )
            
            user_msg = f"URL: {url}\nTitle: {title}\nDescription: {desc}\nTags: {tags_json}"
            
            taxonomy_path = f"/uncategorized/{title[:20].replace(' ', '_')}.md"
            action_note = "Imported to General Collection."
            
            yield f"<script>addLog({json.dumps('Querying Ollama taxonomy agent...')});</script>\n"
            try:
                resp = client.chat(
                     model=config.ollama_model,
                     messages=[
                          {"role": "system", "content": system_instructions},
                          {"role": "user", "content": user_msg}
                     ],
                     format="json",
                     think=False
                )
                args = json.loads(resp.message.content)
                taxonomy_path = args.get("taxonomy_path", taxonomy_path)
                action_note = args.get("action_note", action_note)
                yield f"<script>addLog({json.dumps(f'Taxonomy classification complete: {taxonomy_path}')});</script>\n"
            except Exception as llm_err:
                # Fallback on failure
                warn_msg = f"Warning: Ollama prompt failed, using default paths: {llm_err}"
                yield f"<script>addLog({json.dumps(warn_msg)});</script>\n"
            
            # Create collection_items row
            is_video = False
            if "youtube_videos" in db.table_names():
                try:
                    if db["youtube_videos"].get(url):
                        is_video = True
                except Exception:
                    pass
            source_type = "videos" if is_video else "articles"
            
            try:
                yield f"<script>addLog({json.dumps('Saving collection item record to database...')});</script>\n"
                db["collection_items"].insert({
                    "collection_id": general_id,
                    "source_type": source_type,
                    "source_id": url,
                    "item_note": f"# {title}\n\n{action_note}",
                    "taxonomy_path": taxonomy_path,
                    "item_order": idx,
                    "added_at": datetime.now().isoformat()
                })
                
                # Create collection_actions row
                db["collection_actions"].insert({
                    "collection_id": general_id,
                    "action_type": "add_item",
                    "source_type": source_type,
                    "source_id": url,
                    "note": action_note,
                    "created_at": datetime.now().isoformat()
                })
                db.conn.commit()
                yield f"<script>addLog({json.dumps('Committed collection item records.')});</script>\n"
                
                # Make sure Gemma embeddings exist for this url
                yield f"<script>addLog({json.dumps('Generating Gemma chunk embeddings...')});</script>\n"
                generate_gemma_embeddings_for_page(db, url, config, client)
                db.conn.commit()
                yield f"<script>addLog({json.dumps('Committed Gemma chunk embeddings.')});</script>\n"
                
            except Exception as db_err:
                err_msg = f"DB Error writing {title[:35]}: {db_err}"
                yield f"<script>addLog({json.dumps(err_msg)});</script>\n"
                
            percentage = int(((idx + 1) / total_pages) * 100)
            proc_msg = f"Processed: {title[:30]} -> {taxonomy_path}"
            yield f"<script>updateProgress({json.dumps(proc_msg)}, {percentage});</script>\n"
            
        yield f"<script>updateProgress({json.dumps('General Collection Seed Complete!')}, 100); setTimeout(() => {{ window.location.href = '/collections'; }}, 1500);</script>\n"

    return StreamingResponse(
        populate_stream(),
        media_type="text/html",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@router.post("/admin/collections/suggest", dependencies=[Depends(verify_auth)])
def suggest_collections() -> JSONResponse:
    """Queries Ollama to group ungrouped page titles into logical suggestions."""
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return JSONResponse(content={"suggestions": []})

    # Fetch all pages not in any collection except General
    general_id = get_general_collection_id(db)
    rows = list(db.execute_returning_dicts(
        """
        SELECT url, title FROM fetched_pages 
        WHERE url NOT IN (
            SELECT source_id FROM collection_items WHERE collection_id != ?
        )
        AND title IS NOT NULL
        """,
        [general_id]
    ))
    
    if not rows:
        return JSONResponse(content={"suggestions": [], "message": "No ungrouped pages available."})

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
            ],
            format="json",
            think=False,
        )
        raw_text = response.message.content.strip()
        
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1] == "```":
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()
            
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if json_match:
            raw_text = json_match.group(0)

        suggestions_data = json.loads(raw_text)
        
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
            "visibility": "public",
            "rag_system_prompt": DEFAULT_RAG_SYSTEM_PROMPT,
            "taxonomy_system_prompt": DEFAULT_TAXONOMY_SYSTEM_PROMPT,
            "general_system_context": "{}",
            "created_at": datetime.now().isoformat()
        }).last_rowid

        urls = json.loads(urls_json)
        for url in urls:
            is_video = False
            if "youtube_videos" in db.table_names():
                try:
                    if db["youtube_videos"].get(url):
                        is_video = True
                except Exception:
                    pass
            source_type = "videos" if is_video else "articles"
            
            db["collection_items"].insert({
                "collection_id": collection_id,
                "source_type": source_type,
                "source_id": url,
                "item_note": "",
                "taxonomy_path": "",
                "item_order": 9999,
                "added_at": datetime.now().isoformat()
            })
            
        print(f"AI Suggestion: Created collection '{title_clean}' and assigned {len(urls)} pages.")
    except Exception as e:
        print(f"Failed to create collection from AI suggestion: {e}")

    return RedirectResponse(url="/collections", status_code=303)


# --- Notes CRUD & Agent Chat Endpoints ---

def compile_taxonomy_system_prompt(collection, db) -> str:
    prompt = collection.get("taxonomy_system_prompt") or DEFAULT_TAXONOMY_SYSTEM_PROMPT
    
    # 1. Compute taxonomy tree string
    taxonomy_lines = []
    col_id = collection["id"]
    
    # Add collection items
    if "collection_items" in db.table_names():
        items = list(db["collection_items"].rows_where("collection_id = ?", [col_id]))
        for item in items:
            path = item.get("taxonomy_path") or f"/uncategorized/{item['source_id'][-20:]}"
            taxonomy_lines.append(f"- [Item] {path} ({item['source_id']})")
        
    # Add collection notes
    if "collection_notes" in db.table_names():
        notes = list(db["collection_notes"].rows_where("collection_id = ?", [col_id]))
        for note in notes:
            path = note.get("taxonomy_path") or f"/{note['title']}"
            taxonomy_lines.append(f"- [Note] {path}")
        
    taxonomy_tree_str = "\n".join(sorted(taxonomy_lines)) if taxonomy_lines else "No items in this collection."
    
    # 2. Extract general context variables
    context_vars = {}
    try:
        context_vars = json.loads(collection.get("general_system_context") or "{}")
    except Exception:
        pass
        
    # 3. Add default context variables
    context_vars["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    context_vars["taxonomy_tree_str"] = taxonomy_tree_str
    
    # 4. Replace double curly braces variables e.g. {{datetime}}
    for k, v in context_vars.items():
        placeholder_2 = "{{" + k + "}}"
        val_str = str(v)
        prompt = prompt.replace(placeholder_2, val_str)
        
    return prompt


def compile_system_prompt(collection, db) -> str:
    prompt = collection.get("rag_system_prompt") or "You are a helpful knowledge assistant for this collection."
    
    # 1. Compute taxonomy tree string
    taxonomy_lines = []
    col_id = collection["id"]
    
    # Add collection items
    if "collection_items" in db.table_names():
        items = list(db["collection_items"].rows_where("collection_id = ?", [col_id]))
        for item in items:
            path = item.get("taxonomy_path") or f"/uncategorized/{item['source_id'][-20:]}"
            taxonomy_lines.append(f"- [Item] {path} ({item['source_id']})")
        
    # Add collection notes
    if "collection_notes" in db.table_names():
        notes = list(db["collection_notes"].rows_where("collection_id = ?", [col_id]))
        for note in notes:
            path = note.get("taxonomy_path") or f"/{note['title']}"
            taxonomy_lines.append(f"- [Note] {path}")
        
    taxonomy_tree_str = "\n".join(sorted(taxonomy_lines)) if taxonomy_lines else "No items in this collection."
    
    # 2. Extract general context variables
    context_vars = {}
    try:
        context_vars = json.loads(collection.get("general_system_context") or "{}")
    except Exception:
        pass
        
    # 3. Add default context variables
    context_vars["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    context_vars["taxonomy_tree_str"] = taxonomy_tree_str
    
    # 4. Replace double curly braces variables e.g. {{datetime}}
    for k, v in context_vars.items():
        # We can also do plain python replace for {{var}}
        placeholder_2 = "{{" + k + "}}"
        val_str = str(v)
        prompt = prompt.replace(placeholder_2, val_str)
        
    return prompt


@router.post("/collections/view/{collection_id}/notes/create", dependencies=[Depends(verify_auth)])
def create_collection_note(
    collection_id: int,
    title: str = Form("untitled_note.md"),
    taxonomy_path: str = Form("/untitled_note.md")
) -> JSONResponse:
    db = _get_db()
    
    # Ensure note title ends with .md
    if not title.lower().endswith(".md"):
        title += ".md"
        
    # Ensure taxonomy path starts with /
    if not taxonomy_path.startswith("/"):
        taxonomy_path = "/" + taxonomy_path
        
    # Adjust taxonomy path to include title if it does not
    if not taxonomy_path.endswith(title):
        taxonomy_path = (taxonomy_path.rstrip("/") + "/" + title)

    try:
        now = datetime.now().isoformat()
        note_id = db["collection_notes"].insert({
            "collection_id": collection_id,
            "title": title,
            "content": "# " + title.replace(".md", "").replace("_", " ").title() + "\n\nStart writing here...",
            "taxonomy_path": taxonomy_path,
            "created_at": now,
            "updated_at": now
        }).last_rowid
        db.conn.commit()
        return JSONResponse(content={"status": "success", "note_id": note_id, "title": title, "taxonomy_path": taxonomy_path})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/collections/view/{collection_id}/notes/update", dependencies=[Depends(verify_auth)])
def update_collection_note(
    collection_id: int,
    note_id: int = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    taxonomy_path: str = Form(...)
) -> JSONResponse:
    db = _get_db()
    
    # Cleanups
    if not title.lower().endswith(".md"):
        title += ".md"
    if not taxonomy_path.startswith("/"):
        taxonomy_path = "/" + taxonomy_path
    if not taxonomy_path.endswith(title):
        taxonomy_path = (taxonomy_path.rstrip("/") + "/" + title)

    try:
        db["collection_notes"].update(note_id, {
            "title": title,
            "content": content,
            "taxonomy_path": taxonomy_path,
            "updated_at": datetime.now().isoformat()
        })
        db.conn.commit()
        return JSONResponse(content={"status": "success", "message": "Note updated successfully."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/collections/view/{collection_id}/notes/delete", dependencies=[Depends(verify_auth)])
def delete_collection_note(
    collection_id: int,
    note_id: int = Form(...)
) -> JSONResponse:
    db = _get_db()
    try:
        db["collection_notes"].delete(note_id)
        db.conn.commit()
        return JSONResponse(content={"status": "success", "message": "Note deleted successfully."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/collections/view/{collection_id}/items/update-note", dependencies=[Depends(verify_auth)])
def update_collection_item_note(
    collection_id: int,
    url: str = Form(...),
    item_note: str = Form(...),
    taxonomy_path: str = Form(...)
) -> JSONResponse:
    db = _get_db()
    try:
        rows = list(db["collection_items"].rows_where("collection_id = ? AND source_id = ?", [collection_id, url]))
        if not rows:
            return JSONResponse(status_code=404, content={"status": "error", "message": "Collection item not found."})
        
        item_id = rows[0]["id"]
        db["collection_items"].update(item_id, {
            "item_note": item_note,
            "taxonomy_path": taxonomy_path
        })
        db.conn.commit()
        return JSONResponse(content={"status": "success", "message": "Collection item note updated successfully."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/collections/view/{collection_id}/agent-chat", dependencies=[Depends(verify_auth)])
def collection_agent_chat(
    collection_id: int,
    message: str = Form(...),
    active_file_id: Optional[str] = Form(None),
    active_file_type: Optional[str] = Form(None),
    history_json: str = Form("[]")
) -> JSONResponse:
    db = _get_db()
    try:
        collection = db["collections"].get(collection_id)
    except Exception:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Collection not found."})
        
    system_prompt = compile_system_prompt(collection, db)
    
    try:
        history = json.loads(history_json)
    except Exception:
        history = []
        
    active_file_context = ""
    if active_file_id and active_file_type:
        if active_file_type == "note":
            try:
                note = db["collection_notes"].get(int(active_file_id))
                active_file_context = (
                    f"--- ACTIVE FILE --- \n"
                    f"Type: Markdown Note\n"
                    f"Title: {note['title']}\n"
                    f"Taxonomy Path: {note['taxonomy_path']}\n"
                    f"Content:\n{note['content']}\n"
                    f"--------------------\n"
                )
            except Exception:
                pass
        elif active_file_type == "item":
            try:
                rows = list(db["collection_items"].rows_where("collection_id = ? AND source_id = ?", [collection_id, active_file_id]))
                if rows:
                    item = rows[0]
                    page_row = db["fetched_pages"].get(active_file_id)
                    title = page_row.get("title") or active_file_id
                    desc = page_row.get("description") or ""
                    active_file_context = (
                        f"--- ACTIVE FILE --- \n"
                        f"Type: Ingested Item ({item['source_type']})\n"
                        f"Title: {title}\n"
                        f"Source URL: {active_file_id}\n"
                        f"Taxonomy Path: {item['taxonomy_path']}\n"
                        f"Description/Summary:\n{desc}\n"
                        f"Item Note:\n{item['item_note']}\n"
                        f"--------------------\n"
                    )
            except Exception:
                pass

    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    user_content = message
    if active_file_context:
        user_content = f"{active_file_context}\nUser Query: {message}"
        
    messages.append({"role": "user", "content": user_content})
    
    try:
        client = _get_ollama_client()
        response = client.chat(
            model=config.ollama_model,
            messages=messages,
            think=False
        )
        agent_reply = response.message.content
        return JSONResponse(content={"status": "success", "reply": agent_reply})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Ollama agent chat failed: {str(e)}"})


@router.get("/collections/view/{collection_id}/editor", response_class=HTMLResponse)
def view_collection_editor(request: Request, collection_id: int) -> HTMLResponse:
    """Renders the split-pane collection notes workspace."""
    db = _get_db()
    try:
        collection = db["collections"].get(collection_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Collection not found.")

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    if not is_admin and collection.get("visibility") == "private":
        raise HTTPException(status_code=403, detail="Unauthorized: This is a private collection.")

    # Fetch collection items
    items = []
    if "fetched_pages" in db.table_names() and "collection_items" in db.table_names():
        try:
            items = list(db.execute_returning_dicts(
                """
                SELECT f.url, f.title, f.md_content, f.description, ci.item_note, ci.taxonomy_path, ci.item_order, ci.source_type
                FROM fetched_pages f
                JOIN collection_items ci ON f.url = ci.source_id
                WHERE ci.collection_id = ?
                ORDER BY ci.item_order ASC, ci.id DESC
                """,
                [collection_id]
            ))
        except Exception as e:
            print(f"Failed to fetch collection editor items: {e}")

    # Fetch collection custom notes
    notes = []
    if "collection_notes" in db.table_names():
        try:
            notes = list(db["collection_notes"].rows_where("collection_id = ?", [collection_id], order_by="title ASC"))
        except Exception as e:
            print(f"Failed to fetch collection editor notes: {e}")

    template = _jinja_env.get_template("collection_editor.j2.html")
    return HTMLResponse(
        content=template.render(
            collection=collection,
            items=items,
            notes=notes,
            is_admin=is_admin,
            ollama_model=config.ollama_model
        )
    )


@router.post("/admin/pages/toggle-exclude", dependencies=[Depends(verify_auth)])
def toggle_page_exclusion(
    url: str = Form(...),
    exclude: int = Form(0)
) -> RedirectResponse:
    """Toggles the exclude_from_general flag for an ingested page/video."""
    db = _get_db()
    try:
        db["fetched_pages"].update(url, {"exclude_from_general": exclude})
        db.conn.commit()
        
        # If set to exclude (1), delete from General Collection collection_items
        if exclude == 1:
            general_id = get_general_collection_id(db)
            db["collection_items"].delete_where("collection_id = ? AND source_id = ?", [general_id, url])
            db.conn.commit()
            print(f"Exclusion: Excluded {url} from General Collection and removed its collection item entry.")
    except Exception as e:
        print(f"Failed to toggle page exclusion: {e}")
    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)



