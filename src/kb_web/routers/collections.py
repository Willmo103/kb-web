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
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
    StreamingResponse,
)

from ..base import (
    config,
    _jinja_env,
    _get_ollama_client,
    COOKIE_NAME,
    verify_session_token,
    verify_auth,
    db_session,
)
from ..models import HTMLPage
from ..models_orm import Collection, CollectionItem, CollectionNote, CollectionAction, FetchedPage, YouTubeVideo, ChunkEmbedding
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
                res = client.get(
                    f"{qdrant_url}/collections/{col_name}", headers=headers
                )
                if res.status_code == 404:
                    client.put(
                        f"{qdrant_url}/collections/{col_name}",
                        headers=headers,
                        json={"vectors": {"size": vector_size, "distance": "Cosine"}},
                    ).raise_for_status()

                # Upload points
                batch_size = 100
                for i in range(0, len(points), batch_size):
                    batch = points[i : i + batch_size]
                    client.put(
                        f"{qdrant_url}/collections/{col_name}/points",
                        headers=headers,
                        json={"points": batch},
                    ).raise_for_status()

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

    with db_session() as session:
        collection = session.query(Collection).filter_by(id=collection_id).first()
        if not collection:
            return False, "Collection not found."

        col_name = re.sub(r"[^a-zA-Z0-9_-]", "_", collection.title).lower()
        items = session.query(CollectionItem).filter_by(collection_id=collection_id).all()

        points = []
        for item in items:
            # Load chunk embeddings for this item
            chunks = (
                session.query(ChunkEmbedding)
                .filter_by(source_type=item.source_type, source_id=item.source_id)
                .all()
            )
            for chunk in chunks:
                if not chunk.chunk_vector:
                    continue
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{chunk.source_id}_{chunk.chunk_number}"))
                points.append(
                    {
                        "id": point_id,
                        "vector": chunk.chunk_vector,
                        "payload": {
                            "source_type": chunk.source_type,
                            "source_id": chunk.source_id,
                            "source_title": chunk.source_title,
                            "chunk_number": chunk.chunk_number,
                            "chunk_content": chunk.chunk_content,
                            "collection_id": collection_id,
                            "collection_title": collection.title,
                            "item_note": item.item_note or "",
                            "taxonomy_path": item.taxonomy_path or "",
                        },
                    }
                )

    if not points:
        return True, "Collection has no vector-indexed items. Sync skipped."

    headers = {}
    if qdrant_key:
        headers["api-key"] = qdrant_key

    try:
        with httpx.Client(timeout=10.0) as client:
            vector_size = len(points[0]["vector"])

            # Check if Qdrant collection exists
            res = client.get(
                f"{qdrant_url}/collections/{col_name}", headers=headers
            )
            if res.status_code == 404:
                client.put(
                    f"{qdrant_url}/collections/{col_name}",
                    headers=headers,
                    json={
                        "vectors": {
                            "size": vector_size,
                            "distance": "Cosine",
                        }
                    },
                ).raise_for_status()
            elif res.status_code != 200:
                save_sync_locally(col_name, points)
                return (
                    False,
                    f"Qdrant returned unexpected status {res.status_code}. Saved sync locally.",
                )

            # Upload points
            batch_size = 100
            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                client.put(
                    f"{qdrant_url}/collections/{col_name}/points",
                    headers=headers,
                    json={"points": batch},
                ).raise_for_status()

            # Flush any other offline queues
            flush_local_syncs(qdrant_url, headers)

        return True, f"Successfully synchronized {len(points)} points to Qdrant."
    except Exception as e:
        save_sync_locally(col_name, points)
        return False, f"Failed to sync with Qdrant: {e}. Saved sync locally."


# --- Collections View & Management Endpoints ---


@router.get("/collections", response_class=HTMLResponse)
def list_collections(request: Request) -> HTMLResponse:
    """Lists all created collections, showing page counts and ungrouped items."""
    from sqlalchemy import func

    collections_list = []
    ungrouped_pages = []

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        results = (
            session.query(Collection, func.count(CollectionItem.id).label("pages_count"))
            .outerjoin(CollectionItem, Collection.id == CollectionItem.collection_id)
            .group_by(Collection.id)
            .order_by(Collection.title.asc())
            .all()
        )

        for c, count in results:
            col_dict = {col.name: getattr(c, col.name) for col in c.__table__.columns}
            col_dict["pages_count"] = count
            collections_list.append(col_dict)

        # Filter out private collections for non-admin users
        if not is_admin:
            collections_list = [
                c for c in collections_list if c.get("visibility") != "private"
            ]

        try:
            general_id = get_general_collection_id()
            subq = session.query(CollectionItem.source_id).filter(CollectionItem.collection_id != general_id).subquery()
            rows = session.query(FetchedPage).filter(~FetchedPage.url.in_(subq)).order_by(FetchedPage.fetched_at.desc()).all()
            for r in rows:
                p_dict = {col.name: getattr(r, col.name) for col in r.__table__.columns}
                # Deserialize array fields to match Pydantic model expectations in Jinja template rendering
                for fld in ("links", "keywords", "tags"):
                    if p_dict.get(fld):
                        try:
                            p_dict[fld] = json.loads(p_dict[fld])
                        except Exception:
                            p_dict[fld] = []
                    else:
                        p_dict[fld] = []
                ungrouped_pages.append(HTMLPage(**p_dict))
        except Exception as e:
            print(f"Error fetching ungrouped pages: {e}")

        # Fetch all pages list for additions dropdown
        all_pages_list = []
        if is_admin:
            try:
                all_pages = session.query(FetchedPage).all()
                for r in all_pages:
                    p_dict = {col.name: getattr(r, col.name) for col in r.__table__.columns}
                    for fld in ("links", "keywords", "tags"):
                        if p_dict.get(fld):
                            try:
                                p_dict[fld] = json.loads(p_dict[fld])
                            except Exception:
                                p_dict[fld] = []
                        else:
                            p_dict[fld] = []
                    all_pages_list.append(HTMLPage(**p_dict))
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
    title: str = Form(...), visibility: str = Form("public")
) -> RedirectResponse:
    """Creates a new collection in the database."""
    title_clean = title.strip()
    if not title_clean:
        return RedirectResponse(url="/collections", status_code=303)

    try:
        with db_session() as session:
            new_col = Collection(
                title=title_clean,
                visibility=visibility,
                rag_system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
                taxonomy_system_prompt=DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                general_system_context="{}",
                created_at=datetime.now().isoformat(),
            )
            session.add(new_col)
    except Exception as e:
        print(f"Failed to create collection: {e}")

    return RedirectResponse(url="/collections", status_code=303)


@router.get("/collections/view/{collection_id}", response_class=HTMLResponse)
def view_collection(request: Request, collection_id: int) -> HTMLResponse:
    """Renders all pages within a specific collection."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        collection = session.query(Collection).filter_by(id=collection_id).first()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found.")

        if not is_admin and collection.visibility == "private":
            raise HTTPException(
                status_code=403, detail="Unauthorized: This is a private collection."
            )

        pages = []
        try:
            results = (
                session.query(FetchedPage, CollectionItem)
                .join(CollectionItem, FetchedPage.url == CollectionItem.source_id)
                .filter(CollectionItem.collection_id == collection_id)
                .order_by(CollectionItem.item_order.asc(), CollectionItem.id.desc())
                .all()
            )

            for page_obj, item in results:
                p_dict = {col.name: getattr(page_obj, col.name) for col in page_obj.__table__.columns}
                p_dict["item_note"] = item.item_note
                p_dict["taxonomy_path"] = item.taxonomy_path
                p_dict["item_order"] = item.item_order

                for fld in ("links", "keywords", "tags"):
                    if p_dict.get(fld):
                        try:
                            p_dict[fld] = json.loads(p_dict[fld])
                        except Exception:
                            p_dict[fld] = []
                    else:
                        p_dict[fld] = []

                # Find other collections this page belongs to
                coll_rows = (
                    session.query(Collection)
                    .join(CollectionItem, Collection.id == CollectionItem.collection_id)
                    .filter(CollectionItem.source_id == page_obj.url, Collection.id != 1)
                    .all()
                )
                if coll_rows:
                    p_dict["collection_title"] = ", ".join([c.title for c in coll_rows])
                    p_dict["collection_id"] = coll_rows[0].id
                else:
                    p_dict["collection_title"] = None
                    p_dict["collection_id"] = None

                pages.append(HTMLPage(**p_dict))
        except Exception as e:
            print(f"Failed to fetch collection pages: {e}")

        # Fetch all pages list for additions dropdown
        all_pages_list = []
        if is_admin:
            try:
                all_pages = session.query(FetchedPage).all()
                for page_obj in all_pages:
                    p_dict = {col.name: getattr(page_obj, col.name) for col in page_obj.__table__.columns}
                    for fld in ("links", "keywords", "tags"):
                        if p_dict.get(fld):
                            try:
                                p_dict[fld] = json.loads(p_dict[fld])
                            except Exception:
                                p_dict[fld] = []
                        else:
                            p_dict[fld] = []

                    coll_rows = (
                        session.query(Collection)
                        .join(CollectionItem, Collection.id == CollectionItem.collection_id)
                        .filter(CollectionItem.source_id == page_obj.url, Collection.id != 1)
                        .all()
                    )
                    if coll_rows:
                        p_dict["collection_title"] = ", ".join([c.title for c in coll_rows])
                        p_dict["collection_id"] = coll_rows[0].id
                    else:
                        p_dict["collection_title"] = None
                        p_dict["collection_id"] = None

                    all_pages_list.append(HTMLPage(**p_dict))
            except Exception:
                pass

        col_dict = {col.name: getattr(collection, col.name) for col in collection.__table__.columns}

    template = _jinja_env.get_template("view_collection.j2.html")
    return HTMLResponse(
        content=template.render(
            collection=col_dict,
            pages=pages,
            all_pages=all_pages_list,
            is_admin=is_admin,
        )
    )


@router.post(
    "/collections/view/{collection_id}/save-items", dependencies=[Depends(verify_auth)]
)
def save_collection_items(
    collection_id: int, urls_json: str = Form(...)
) -> JSONResponse:
    """Saves the exact set and ordered sequence of items inside a collection."""
    try:
        urls = json.loads(urls_json)

        with db_session() as session:
            # Clear existing items
            session.query(CollectionItem).filter_by(collection_id=collection_id).delete()

            # Insert items with reordered position
            for idx, url in enumerate(urls):
                is_video = session.query(YouTubeVideo).filter_by(url=url).first() is not None
                source_type = "videos" if is_video else "articles"

                session.add(
                    CollectionItem(
                        collection_id=collection_id,
                        source_type=source_type,
                        source_id=url,
                        item_note="",
                        taxonomy_path="",
                        item_order=idx,
                        added_at=datetime.now().isoformat(),
                    )
                )
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.post("/collections/delete", dependencies=[Depends(verify_auth)])
def delete_collection(id: int = Form(...)) -> RedirectResponse:
    """Deletes a collection and its items mappings. Retains actual fetched pages."""
    try:
        with db_session() as session:
            session.query(CollectionItem).filter_by(collection_id=id).delete()
            session.query(CollectionNote).filter_by(collection_id=id).delete()
            session.query(CollectionAction).filter_by(collection_id=id).delete()
            session.query(Collection).filter_by(id=id).delete()
    except Exception as e:
        print(f"Failed to delete collection {id}: {e}")

    return RedirectResponse(url="/collections", status_code=303)


@router.post(
    "/collections/add-items",
    dependencies=[Depends(verify_auth)],
    response_model=None,
)
def add_items_to_collection(
    collection_id: int = Form(...), urls_json: str = Form(...)
) -> RedirectResponse:
    """Appends multiple URLs to a specific collection (handling position order bounds)."""
    try:
        urls = json.loads(urls_json)
        with db_session() as session:
            # Find the max order index
            from sqlalchemy import func
            max_order = session.query(func.max(CollectionItem.item_order)).filter_by(collection_id=collection_id).scalar() or 0

            for url in urls:
                # Avoid duplicate insertion
                existing = session.query(CollectionItem).filter_by(collection_id=collection_id, source_id=url).first()
                if existing:
                    continue

                is_video = session.query(YouTubeVideo).filter_by(url=url).first() is not None
                source_type = "videos" if is_video else "articles"
                max_order += 1

                session.add(
                    CollectionItem(
                        collection_id=collection_id,
                        source_type=source_type,
                        source_id=url,
                        item_order=max_order,
                        added_at=datetime.now().isoformat(),
                    )
                )
    except Exception as e:
        print(f"Failed to add items to collection: {e}")

    return RedirectResponse(
        url=f"/collections/view/{collection_id}", status_code=303
    )


@router.post(
    "/collections/remove-items",
    dependencies=[Depends(verify_auth)],
    response_model=None,
)
def remove_items_from_collection(
    collection_id: int = Form(...), urls_json: str = Form(...)
) -> RedirectResponse:
    """Removes a list of page URLs from a collection."""
    try:
        urls = json.loads(urls_json)
        with db_session() as session:
            session.query(CollectionItem).filter(
                CollectionItem.collection_id == collection_id,
                CollectionItem.source_id.in_(urls)
            ).delete(synchronize_session=False)
    except Exception as e:
        print(f"Failed to remove items from collection: {e}")

    return RedirectResponse(
        url=f"/collections/view/{collection_id}", status_code=303
    )


@router.post(
    "/collections/clear-items",
    dependencies=[Depends(verify_auth)],
    response_model=None,
)
def clear_items_from_collection(
    collection_id: int = Form(...),
) -> RedirectResponse:
    """Removes all items from a collection."""
    try:
        with db_session() as session:
            session.query(CollectionItem).filter_by(collection_id=collection_id).delete()
    except Exception as e:
        print(f"Failed to clear collection items: {e}")

    return RedirectResponse(
        url=f"/collections/view/{collection_id}", status_code=303
    )


@router.post("/collections/edit/{collection_id}", dependencies=[Depends(verify_auth)])
def edit_collection(
    collection_id: int,
    title: str = Form(...),
    visibility: str = Form(...),
    rag_system_prompt: str = Form(""),
    taxonomy_system_prompt: str = Form(""),
    general_system_context: str = Form("{}"),
) -> RedirectResponse:
    """Edits the collection parameters (prompts, title, context variables)."""
    title_clean = title.strip()
    if not title_clean:
        return RedirectResponse(
            url=f"/collections/view/{collection_id}", status_code=303
        )

    # Validate JSON
    try:
        json.loads(general_system_context)
    except Exception:
        general_system_context = "{}"

    try:
        with db_session() as session:
            col = session.query(Collection).filter_by(id=collection_id).first()
            if col:
                col.title = title_clean
                col.visibility = visibility
                col.rag_system_prompt = rag_system_prompt
                col.taxonomy_system_prompt = taxonomy_system_prompt
                col.general_system_context = general_system_context
    except Exception as e:
        print(f"Failed to edit collection: {e}")

    return RedirectResponse(
        url=f"/collections/view/{collection_id}", status_code=303
    )


@router.post("/collections/action/sync-qdrant", dependencies=[Depends(verify_auth)])
def sync_qdrant_endpoint(collection_id: int = Form(...)) -> JSONResponse:
    """Invokes Qdrant sync process for a collection."""
    success, msg = sync_collection_to_qdrant(None, collection_id)
    if success:
        return JSONResponse(content={"status": "success", "message": msg})
    else:
        return JSONResponse(status_code=500, content={"status": "error", "message": msg})


@router.post(
    "/collections/action/ingest-suggested", dependencies=[Depends(verify_auth)]
)
def ingest_suggested_groups(
    request: Request, groups_json: str = Form(...)
) -> RedirectResponse:
    """Accepts classifications approved by the user, saving items into General Collection."""
    try:
        groups = json.loads(groups_json)
        general_id = get_general_collection_id()

        with db_session() as session:
            # Query maximum order position
            from sqlalchemy import func
            max_order = session.query(func.max(CollectionItem.item_order)).filter_by(collection_id=general_id).scalar() or 0

            for group in groups:
                url = group["url"]
                taxonomy_path = group["taxonomy_path"]
                action_note = group["action_note"]

                # Check if it already exists
                existing = session.query(CollectionItem).filter_by(collection_id=general_id, source_id=url).first()
                if existing:
                    existing.taxonomy_path = taxonomy_path
                    existing.item_note = f"# {group.get('title', '')}\n\n{action_note}"
                    continue

                is_video = session.query(YouTubeVideo).filter_by(url=url).first() is not None
                source_type = "videos" if is_video else "articles"
                max_order += 1

                session.add(
                    CollectionItem(
                        collection_id=general_id,
                        source_type=source_type,
                        source_id=url,
                        item_note=f"# {group.get('title', '')}\n\n{action_note}",
                        taxonomy_path=taxonomy_path,
                        item_order=max_order,
                        added_at=datetime.now().isoformat(),
                    )
                )

                session.add(
                    CollectionAction(
                        collection_id=general_id,
                        action_type="add_item",
                        source_type=source_type,
                        source_id=url,
                        note=action_note,
                        created_at=datetime.now().isoformat(),
                    )
                )
    except Exception as e:
        print(f"Failed to ingest suggested groups: {e}")

    return RedirectResponse(url="/collections", status_code=303)


# --- Streaming AI Taxonomy Classification ---


@router.post(
    "/collections/action/suggest-groupings", dependencies=[Depends(verify_auth)]
)
def suggest_ai_groupings(request: Request, limit: int = Form(10)) -> StreamingResponse:
    """Generator streaming endpoint categorizing ungrouped items using Ollama taxonomist agent."""
    general_id = get_general_collection_id()

    def generate_suggestions():
        yield """
    <div id="terminal-logs" style="background:#1e1e1e; color:#00ff00; font-family:monospace; padding:15px; border-radius:5px; height:250px; overflow-y:auto; font-size:12px; margin-bottom:15px; border:1px solid #333;">
        <div>[System] Launching Ollama Taxonomy agent...</div>
    </div>
    <script>
        const terminalLogs = document.getElementById('terminal-logs');
        function updateProgress(text, val) {
            const pb = document.getElementById('ingestion-progress-bar');
            const pt = document.getElementById('ingestion-progress-text');
            if(pb) pb.style.width = val + '%';
            if(pt) pt.innerText = text;
            addLog(text);
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
        with db_session() as session:
            # Query all pages
            pages = session.query(FetchedPage).all()
            total_pages = len(pages)
            yield f"<script>addLog({json.dumps(f'Found {total_pages} total pages to process.')});</script>\n"

            processed_count = 0
            suggestions = []

            for idx, page in enumerate(pages):
                if processed_count >= limit:
                    break

                url = page.url
                title = page.title or url
                desc = page.description or ""
                tags_json = page.tags or "[]"
                exclude = bool(page.exclude_from_general)

                if exclude:
                    log_msg = f"Excluding: {title} (exclude_from_general is set)"
                    yield f"<script>addLog({json.dumps(log_msg)});</script>\n"
                    continue

                # Check if it already exists in general_collection
                is_present = session.query(CollectionItem).filter_by(collection_id=general_id, source_id=url).first() is not None
                if is_present:
                    continue

                processed_count += 1
                yield f"<script>addLog({json.dumps(f'Processing {processed_count}/{limit}: {title[:35]}...')});</script>\n"

                # Ask agent for parameters
                try:
                    collection_general = session.query(Collection).filter_by(id=general_id).first()
                    system_instructions = compile_taxonomy_system_prompt(collection_general)
                except Exception:
                    system_instructions = (
                        "You are an expert taxonomist. Categorize the document into a virtual filetree system "
                        "representing the General Collection of all knowledge. "
                        "Output ONLY a valid JSON object matching the format: "
                        '{"taxonomy_path": "/Folder/Subfolder/Filename.md", "action_note": "A short, 1-sentence description of what this note contains."}'
                    )

                user_msg = (
                    f"URL: {url}\nTitle: {title}\nDescription: {desc}\nTags: {tags_json}"
                )

                taxonomy_path = f"/uncategorized/{title[:20].replace(' ', '_')}.md"
                action_note = "Imported to General Collection."

                yield f"<script>addLog({json.dumps('Querying Ollama taxonomy agent...')});</script>\n"
                try:
                    resp = client.chat(
                        model=config.ollama_model,
                        messages=[
                            {"role": "system", "content": system_instructions},
                            {"role": "user", "content": user_msg},
                        ],
                        think=getattr(config, "ollama_think", False),
                    )
                    reply = resp.message.content
                    # Parse JSON reply
                    parsed = json.loads(reply.strip())
                    taxonomy_path = parsed.get("taxonomy_path", taxonomy_path)
                    action_note = parsed.get("action_note", action_note)
                except Exception as ex:
                    yield f"<script>addLog({json.dumps(f'Agent warning: {ex}. Falling back to default.')});</script>\n"

                suggestions.append(
                    {
                        "url": url,
                        "title": title,
                        "taxonomy_path": taxonomy_path,
                        "action_note": action_note,
                    }
                )
                yield f"<script>addLog({json.dumps(f'Suggested categorisation: {taxonomy_path}')});</script>\n"

            percentage = 100
            yield f"<script>updateProgress({json.dumps('Processing complete!')}, {percentage});</script>\n"
            yield f"<script>window.renderSuggestions({json.dumps(suggestions)});</script>\n"

    return StreamingResponse(generate_suggestions(), media_type="text/html")


# --- Notes CRUD & Agent Chat Endpoints ---


def compile_taxonomy_system_prompt(collection) -> str:
    prompt = collection.taxonomy_system_prompt or DEFAULT_TAXONOMY_SYSTEM_PROMPT

    taxonomy_lines = []
    col_id = collection.id

    from ..models_orm import CollectionItem, CollectionNote

    with db_session() as session:
        items = session.query(CollectionItem).filter_by(collection_id=col_id).all()
        for item in items:
            path = (
                item.taxonomy_path or f"/uncategorized/{item.source_id[-20:]}"
            )
            taxonomy_lines.append(f"- [Item] {path} ({item.source_id})")

        notes = session.query(CollectionNote).filter_by(collection_id=col_id).all()
        for note in notes:
            path = note.taxonomy_path or f"/{note.title}"
            taxonomy_lines.append(f"- [Note] {path}")

    taxonomy_tree_str = (
        "\n".join(sorted(taxonomy_lines))
        if taxonomy_lines
        else "No items in this collection."
    )

    context_vars = {}
    try:
        context_vars = json.loads(collection.general_system_context or "{}")
    except Exception:
        pass

    context_vars["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    context_vars["taxonomy_tree_str"] = taxonomy_tree_str

    for k, v in context_vars.items():
        placeholder_2 = "{{" + k + "}}"
        val_str = str(v)
        prompt = prompt.replace(placeholder_2, val_str)

    return prompt


def compile_system_prompt(collection) -> str:
    prompt = (
        collection.rag_system_prompt
        or "You are a helpful knowledge assistant for this collection."
    )

    taxonomy_lines = []
    col_id = collection.id

    from ..models_orm import CollectionItem, CollectionNote

    with db_session() as session:
        items = session.query(CollectionItem).filter_by(collection_id=col_id).all()
        for item in items:
            path = (
                item.taxonomy_path or f"/uncategorized/{item.source_id[-20:]}"
            )
            taxonomy_lines.append(f"- [Item] {path} ({item.source_id})")

        notes = session.query(CollectionNote).filter_by(collection_id=col_id).all()
        for note in notes:
            path = note.taxonomy_path or f"/{note.title}"
            taxonomy_lines.append(f"- [Note] {path}")

    taxonomy_tree_str = (
        "\n".join(sorted(taxonomy_lines))
        if taxonomy_lines
        else "No items in this collection."
    )

    context_vars = {}
    try:
        context_vars = json.loads(collection.general_system_context or "{}")
    except Exception:
        pass

    context_vars["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    context_vars["taxonomy_tree_str"] = taxonomy_tree_str

    for k, v in context_vars.items():
        placeholder_2 = "{{" + k + "}}"
        val_str = str(v)
        prompt = prompt.replace(placeholder_2, val_str)

    return prompt


@router.post(
    "/collections/view/{collection_id}/notes/create",
    dependencies=[Depends(verify_auth)],
)
def create_collection_note(
    collection_id: int,
    title: str = Form("untitled_note.md"),
    taxonomy_path: str = Form("/untitled_note.md"),
) -> JSONResponse:
    # Ensure note title ends with .md
    if not title.lower().endswith(".md"):
        title += ".md"

    # Ensure taxonomy path starts with /
    if not taxonomy_path.startswith("/"):
        taxonomy_path = "/" + taxonomy_path

    # Adjust taxonomy path to include title if it does not
    if not taxonomy_path.endswith(title):
        taxonomy_path = taxonomy_path.rstrip("/") + "/" + title

    try:
        with db_session() as session:
            new_note = CollectionNote(
                collection_id=collection_id,
                title=title,
                content="",
                taxonomy_path=taxonomy_path,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
            session.add(new_note)
            session.flush()
            note_id = new_note.id

        return JSONResponse(
            content={
                "status": "success",
                "message": "Note created successfully.",
                "note_id": note_id,
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@router.post(
    "/collections/view/{collection_id}/notes/update",
    dependencies=[Depends(verify_auth)],
)
def update_collection_note(
    collection_id: int,
    note_id: int = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    taxonomy_path: str = Form(...),
) -> JSONResponse:
    if not title.lower().endswith(".md"):
        title += ".md"
    if not taxonomy_path.startswith("/"):
        taxonomy_path = "/" + taxonomy_path
    if not taxonomy_path.endswith(title):
        taxonomy_path = taxonomy_path.rstrip("/") + "/" + title

    try:
        with db_session() as session:
            note = session.query(CollectionNote).filter_by(id=note_id).first()
            if note:
                note.title = title
                note.content = content
                note.taxonomy_path = taxonomy_path
                note.updated_at = datetime.now().isoformat()
        return JSONResponse(
            content={"status": "success", "message": "Note updated successfully."}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@router.post(
    "/collections/view/{collection_id}/notes/delete",
    dependencies=[Depends(verify_auth)],
)
def delete_collection_note(
    collection_id: int, note_id: int = Form(...)
) -> JSONResponse:
    try:
        with db_session() as session:
            session.query(CollectionNote).filter_by(id=note_id).delete()
        return JSONResponse(
            content={"status": "success", "message": "Note deleted successfully."}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@router.post(
    "/collections/view/{collection_id}/items/update-note",
    dependencies=[Depends(verify_auth)],
)
def update_collection_item_note(
    collection_id: int,
    url: str = Form(...),
    item_note: str = Form(...),
    taxonomy_path: str = Form(...),
) -> JSONResponse:
    try:
        with db_session() as session:
            item = session.query(CollectionItem).filter_by(collection_id=collection_id, source_id=url).first()
            if not item:
                return JSONResponse(
                    status_code=404,
                    content={"status": "error", "message": "Collection item not found."},
                )
            item.item_note = item_note
            item.taxonomy_path = taxonomy_path
        return JSONResponse(
            content={
                "status": "success",
                "message": "Collection item note updated successfully.",
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@router.post(
    "/collections/view/{collection_id}/agent-chat", dependencies=[Depends(verify_auth)]
)
def collection_agent_chat(
    collection_id: int,
    message: str = Form(...),
    active_file_id: Optional[str] = Form(None),
    active_file_type: Optional[str] = Form(None),
    history_json: str = Form("[]"),
) -> JSONResponse:
    with db_session() as session:
        collection = session.query(Collection).filter_by(id=collection_id).first()
        if not collection:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Collection not found."},
            )
        system_prompt = compile_system_prompt(collection)

    try:
        history = json.loads(history_json)
    except Exception:
        history = []

    active_file_context = ""
    if active_file_id and active_file_type:
        with db_session() as session:
            if active_file_type == "note":
                try:
                    note = session.query(CollectionNote).filter_by(id=int(active_file_id)).first()
                    if note:
                        active_file_context = (
                            f"--- ACTIVE FILE --- \n"
                            f"Type: Markdown Note\n"
                            f"Title: {note.title}\n"
                            f"Taxonomy Path: {note.taxonomy_path}\n"
                            f"Content:\n{note.content}\n"
                            f"--------------------\n"
                        )
                except Exception:
                    pass
            elif active_file_type == "item":
                try:
                    item = session.query(CollectionItem).filter_by(collection_id=collection_id, source_id=active_file_id).first()
                    if item:
                        page_row = session.query(FetchedPage).filter_by(url=active_file_id).first()
                        title = page_row.title if page_row else active_file_id
                        desc = page_row.description if page_row else ""
                        active_file_context = (
                            f"--- ACTIVE FILE --- \n"
                            f"Type: Ingested Item ({item.source_type})\n"
                            f"Title: {title}\n"
                            f"Source URL: {active_file_id}\n"
                            f"Taxonomy Path: {item.taxonomy_path}\n"
                            f"Description/Summary:\n{desc}\n"
                            f"Item Note:\n{item.item_note}\n"
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
            model=config.ollama_model, messages=messages, think=getattr(config, "ollama_think", False)
        )
        agent_reply = response.message.content
        return JSONResponse(content={"status": "success", "reply": agent_reply})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ollama agent chat failed: {str(e)}",
            },
        )


@router.get("/collections/view/{collection_id}/editor", response_class=HTMLResponse)
def view_collection_editor(request: Request, collection_id: int) -> HTMLResponse:
    """Renders the split-pane collection notes workspace."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        collection = session.query(Collection).filter_by(id=collection_id).first()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found.")

        if not is_admin and collection.visibility == "private":
            raise HTTPException(
                status_code=403, detail="Unauthorized: This is a private collection."
            )

        items = []
        try:
            results = (
                session.query(FetchedPage, CollectionItem)
                .join(CollectionItem, FetchedPage.url == CollectionItem.source_id)
                .filter(CollectionItem.collection_id == collection_id)
                .order_by(CollectionItem.item_order.asc(), CollectionItem.id.desc())
                .all()
            )
            for page_obj, item in results:
                items.append(
                    {
                        "url": page_obj.url,
                        "title": page_obj.title,
                        "md_content": page_obj.md_content,
                        "description": page_obj.description,
                        "item_note": item.item_note,
                        "taxonomy_path": item.taxonomy_path,
                        "item_order": item.item_order,
                        "source_type": item.source_type,
                    }
                )
        except Exception as e:
            print(f"Failed to fetch collection editor items: {e}")

        notes = []
        try:
            note_rows = session.query(CollectionNote).filter_by(collection_id=collection_id).order_by(CollectionNote.title.asc()).all()
            for r in note_rows:
                notes.append({col.name: getattr(r, col.name) for col in r.__table__.columns})
        except Exception as e:
            print(f"Failed to fetch collection editor notes: {e}")

        col_dict = {col.name: getattr(collection, col.name) for col in collection.__table__.columns}

    template = _jinja_env.get_template("collection_editor.j2.html")
    return HTMLResponse(
        content=template.render(
            collection=col_dict,
            items=items,
            notes=notes,
            is_admin=is_admin,
            ollama_model=config.ollama_model,
        )
    )


@router.post("/admin/pages/toggle-exclude", dependencies=[Depends(verify_auth)])
def toggle_page_exclusion(
    url: str = Form(...), exclude: int = Form(0)
) -> RedirectResponse:
    """Toggles the exclude_from_general flag for an ingested page/video."""
    try:
        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=url).first()
            if page:
                page.exclude_from_general = exclude

            # If set to exclude (1), delete from General Collection collection_items
            if exclude == 1:
                general_id = get_general_collection_id()
                session.query(CollectionItem).filter_by(collection_id=general_id, source_id=url).delete()
                print(
                    f"Exclusion: Excluded {url} from General Collection and removed its collection item entry."
                )
    except Exception as e:
        print(f"Failed to toggle page exclusion: {e}")
    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)


@router.post("/admin/pages/update-collection", dependencies=[Depends(verify_auth)])
def update_page_collection(
    url: str = Form(...),
    collection_id: Optional[str] = Form(None),
    collection_ids: Optional[list[str]] = Form(None),
) -> RedirectResponse:
    """Assigns or updates the collection classification for an ingested page."""
    try:
        with db_session() as session:
            target_ids = []
            if collection_ids:
                for c_id in collection_ids:
                    if c_id.isdigit():
                        target_ids.append(int(c_id))
            elif collection_id and collection_id.isdigit():
                target_ids.append(int(collection_id))

            # Legacy single collection update
            page = session.query(FetchedPage).filter_by(url=url).first()
            if page:
                page.collection_id = target_ids[0] if target_ids else None

            # Junction table sync
            session.query(CollectionItem).filter_by(source_id=url).delete()
            is_video = session.query(YouTubeVideo).filter_by(url=url).first() is not None
            source_type = "videos" if is_video else "articles"

            for col_id in target_ids:
                from sqlalchemy import func
                max_order = session.query(func.max(CollectionItem.item_order)).filter_by(collection_id=col_id).scalar() or 0
                session.add(
                    CollectionItem(
                        collection_id=col_id,
                        source_type=source_type,
                        source_id=url,
                        item_note="",
                        taxonomy_path="",
                        item_order=max_order + 1,
                        added_at=datetime.now().isoformat(),
                    )
                )
    except Exception as e:
        print(f"Failed to update page collection: {e}")

    return RedirectResponse(url=f"/view/page?url={quote_plus(url)}", status_code=303)


@router.post("/admin/pages/remove-from-collection", dependencies=[Depends(verify_auth)])
def remove_page_from_collection(
    url: str = Form(...), redirect_to: str = Form("/collections")
) -> RedirectResponse:
    """Removes a page from its collection classification (sets collection_id to null)."""
    try:
        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=url).first()
            if page:
                page.collection_id = None
            session.query(CollectionItem).filter_by(source_id=url).delete()
    except Exception as e:
        print(f"Failed to remove page from collection: {e}")

    return RedirectResponse(url=redirect_to, status_code=303)


@router.post("/admin/collections/suggest", dependencies=[Depends(verify_auth)])
def suggest_collections() -> JSONResponse:
    """Queries Ollama to group ungrouped page titles into logical suggestions."""
    with db_session() as session:
        rows = (
            session.query(FetchedPage)
            .filter(FetchedPage.collection_id == None, FetchedPage.title != None)
            .all()
        )
        if not rows:
            return JSONResponse(
                content={"suggestions": [], "message": "No ungrouped pages available."}
            )

        title_to_url = {r.title: r.url for r in rows}
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
                {"role": "user", "content": user_content},
            ],
            think=getattr(config, "ollama_think", False),
        )
        raw_text = response.message.content.strip()

        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1] == "```":
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()

        suggestions_data = json.loads(raw_text)

        formatted_suggestions = []
        for sug in suggestions_data.get("suggestions", []):
            sug_title = sug.get("title", "Unnamed Suggestion")
            matches = sug.get("matches", [])

            sug_pages = []
            for t in matches:
                if t in title_to_url:
                    sug_pages.append({"url": title_to_url[t], "title": t})

            if sug_pages:
                formatted_suggestions.append(
                    {"title": sug_title, "pages": sug_pages}
                )

        return JSONResponse(content={"suggestions": formatted_suggestions})
    except Exception as e:
        print(f"Ollama collection suggestions failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate suggestions: {str(e)}"},
        )


@router.post(
    "/admin/collections/accept-suggestion", dependencies=[Depends(verify_auth)]
)
def accept_suggestion(
    title: str = Form(...), urls_json: str = Form(...)
) -> RedirectResponse:
    """Accepts an AI grouping suggestion: creates the collection and associates the matching pages."""
    title_clean = title.strip()
    if not title_clean:
        return RedirectResponse(url="/collections", status_code=303)

    try:
        with db_session() as session:
            new_col = Collection(
                title=title_clean,
                visibility="public",
                rag_system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
                taxonomy_system_prompt=DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                general_system_context="{}",
                created_at=datetime.now().isoformat(),
            )
            session.add(new_col)
            session.flush()
            collection_id = new_col.id

            urls = json.loads(urls_json)
            for url in urls:
                page = session.query(FetchedPage).filter_by(url=url).first()
                if page:
                    page.collection_id = collection_id

                is_video = (
                    session.query(YouTubeVideo).filter_by(url=url).first() is not None
                )
                source_type = "videos" if is_video else "articles"

                from sqlalchemy import func
                max_order = (
                    session.query(func.max(CollectionItem.item_order))
                    .filter_by(collection_id=collection_id)
                    .scalar()
                    or 0
                )
                session.add(
                    CollectionItem(
                        collection_id=collection_id,
                        source_type=source_type,
                        source_id=url,
                        item_note="",
                        taxonomy_path="",
                        item_order=max_order + 1,
                        added_at=datetime.now().isoformat(),
                    )
                )
            print(
                f"AI Suggestion: Created collection '{title_clean}' and assigned {len(urls)} pages."
            )
    except Exception as e:
        print(f"Failed to create collection from AI suggestion: {e}")

    return RedirectResponse(url="/collections", status_code=303)
