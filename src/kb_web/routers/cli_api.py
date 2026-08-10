import json
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from fastapi import APIRouter, Header, HTTPException, Depends, status, Form
from pydantic import BaseModel

from ..base import _get_db, _get_ollama_client, config
from ..gotify import post_to_gotify
from ..utils import (
    fetch_url,
    extract_wiki_content,
    extract_tags_content,
    serialize_page_for_db,
    save_youtube_metadata_helper,
    update_article_embedding,
    generate_gemma_embeddings_for_page,
    extract_first_url,
    extract_youtube_video_id,
    download_youtube_video
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cli", tags=["CLI API"])


def verify_cli_api_key(x_api_key: str = Header(...)) -> str:
    db = _get_db()
    if "cli_api_keys" not in db.table_names():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key configuration is missing on server."
        )
    try:
        # Check if the key exists
        row = db["cli_api_keys"].get(x_api_key)
        return x_api_key
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked CLI API Key."
        )


class RegistrationRequest(BaseModel):
    computer_name: str


@router.post("/register")
def register_cli_client(
    req: RegistrationRequest,
    api_key: str = Depends(verify_cli_api_key)
):
    db = _get_db()
    if "registered_clients" not in db.table_names():
        raise HTTPException(status_code=500, detail="Database table 'registered_clients' not initialized.")
    
    try:
        db["registered_clients"].insert({
            "computer_name": req.computer_name,
            "api_key": api_key,
            "registered_at": datetime.now().isoformat(),
            "status": "active"
        }, pk="computer_name", replace=True)
        db.conn.commit()
        return {"status": "success", "message": f"Client '{req.computer_name}' successfully registered."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/url")
def cli_import_url(
    url: str = Form(...),
    collection_id: Optional[str] = Form(None),
    new_collection_title: Optional[str] = Form(None),
    api_key: str = Depends(verify_cli_api_key)
):
    cleaned_url = extract_first_url(url)
    db = _get_db()
    client = _get_ollama_client()
    
    logger.info(f"CLI Ingestion started for URL: {cleaned_url}")
    try:
        page_data = fetch_url(cleaned_url)
    except Exception as e:
        return {"status": "error", "message": f"Fetch failed: {str(e)}"}
        
    try:
        wiki_entry = extract_wiki_content(page_data, config, client)
        page_data.description = wiki_entry
    except Exception as e:
        return {"status": "error", "message": f"Wiki generation failed: {str(e)}"}
        
    title = cleaned_url
    soup = BeautifulSoup(page_data.html_content, "html5lib")
    if soup.title:
        title = soup.title.string
    if not title:
        title = urlparse(cleaned_url).netloc or cleaned_url
        
    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        title = first_line.replace("#", "").strip()
    page_data.title = title
    
    try:
        tags = extract_tags_content(page_data, config, client)
        page_data.tags = tags
    except Exception as e:
        tags = []
        
    try:
        from ..config import DEFAULT_RAG_SYSTEM_PROMPT, DEFAULT_TAXONOMY_SYSTEM_PROMPT
        target_col_id = None
        if collection_id == "new_collection" and new_collection_title:
            col_row = {
                "title": new_collection_title,
                "visibility": "public",
                "rag_system_prompt": DEFAULT_RAG_SYSTEM_PROMPT,
                "taxonomy_system_prompt": DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                "general_system_context": "{}",
                "created_at": datetime.now().isoformat()
            }
            res = db["collections"].insert(col_row)
            db.conn.commit()
            target_col_id = res.last_pk
        elif collection_id:
            try:
                target_col_id = int(collection_id)
            except ValueError:
                pass
                
        if target_col_id:
            page_data.collection_id = target_col_id
            
        serialized, creator = serialize_page_for_db(page_data)
        if target_col_id:
            serialized["collection_id"] = target_col_id
            
        db["fetched_pages"].upsert(serialized, pk="url")
        db.conn.commit()
        
        if target_col_id:
            existing_items = list(db["collection_items"].rows_where(
                "collection_id = ? AND source_id = ?",
                [target_col_id, page_data.url]
            ))
            if not existing_items:
                is_video = bool(extract_youtube_video_id(page_data.url))
                source_type = "videos" if is_video else "articles"
                db["collection_items"].insert({
                    "collection_id": target_col_id,
                    "source_type": source_type,
                    "source_id": page_data.url,
                    "item_note": "",
                    "taxonomy_path": f"/uncategorized/{page_data.title[:20].replace(' ', '_')}.md" if page_data.title else f"/uncategorized/{target_col_id}.md",
                    "item_order": 0,
                    "added_at": datetime.now().isoformat()
                })
                db.conn.commit()
                
        if creator:
            save_youtube_metadata_helper(db, page_data.url, creator)
            db.conn.commit()
            
        update_article_embedding(db, page_data.url, config, client)
        db.conn.commit()
        
        generate_gemma_embeddings_for_page(db, page_data.url, config, client)
        db.conn.commit()
        
        try:
            view_url = f"/view/page?url={page_data.safe_url}"
            from ..server import _jinja_env
            post_to_gotify(config, _jinja_env, page_data, view_url)
        except Exception:
            pass
            
        return {
            "status": "success",
            "message": "Ingestion fully completed successfully.",
            "title": page_data.title,
            "url": page_data.url,
            "tags": page_data.tags
        }
    except Exception as e:
        return {"status": "error", "message": f"Database sync/embedding failed: {str(e)}"}


@router.get("/pages")
def list_pages(
    limit: int = 10,
    type: Optional[str] = None,
    api_key: str = Depends(verify_cli_api_key)
):
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return []
    
    if type == "videos":
        if "youtube_videos" in db.table_names():
            rows = list(db.execute_returning_dicts(
                "SELECT fp.* FROM fetched_pages fp JOIN youtube_videos yv ON fp.url = yv.url ORDER BY fp.fetched_at DESC LIMIT ?",
                [limit]
            ))
        else:
            rows = list(db.execute_returning_dicts(
                "SELECT * FROM fetched_pages WHERE url LIKE '%youtube.com%' OR url LIKE '%youtu.be%' ORDER BY fetched_at DESC LIMIT ?",
                [limit]
            ))
    elif type == "articles":
        if "youtube_videos" in db.table_names():
            rows = list(db.execute_returning_dicts(
                "SELECT fp.* FROM fetched_pages fp LEFT JOIN youtube_videos yv ON fp.url = yv.url WHERE yv.url IS NULL ORDER BY fp.fetched_at DESC LIMIT ?",
                [limit]
            ))
        else:
            rows = list(db.execute_returning_dicts(
                "SELECT * FROM fetched_pages WHERE url NOT LIKE '%youtube.com%' AND url NOT LIKE '%youtu.be%' ORDER BY fetched_at DESC LIMIT ?",
                [limit]
            ))
    else:
        rows = list(db.execute_returning_dicts(
            "SELECT * FROM fetched_pages ORDER BY fetched_at DESC LIMIT ?",
            [limit]
        ))
        
    res = []
    for r in rows:
        try:
            tags = json.loads(r.get("tags") or "[]")
        except Exception:
            tags = []
        res.append({
            "url": r.get("url"),
            "title": r.get("title"),
            "description": r.get("description"),
            "tags": tags,
            "fetched_at": r.get("fetched_at")
        })
    return res


@router.post("/pages/action")
def trigger_page_action(
    url: str = Form(...),
    action: str = Form(...),
    api_key: str = Depends(verify_cli_api_key)
):
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return {"status": "error", "message": "No pages in database."}
    
    try:
        page_row = db["fetched_pages"].get(url)
    except Exception:
        return {"status": "error", "message": f"Page with URL '{url}' not found."}
        
    client = _get_ollama_client()
    
    if action == "regenerate-wiki":
        from ..models import HTMLPage
        try:
            page_data = HTMLPage(
                url=page_row["url"],
                title=page_row["title"],
                html_content=page_row["html_content"],
                md_content=page_row["md_content"],
                links=[],
                html_content_hash="",
                md_content_hash="",
                fetched_at=page_row["fetched_at"]
            )
            wiki_entry = extract_wiki_content(page_data, config, client)
            db["fetched_pages"].update(url, {"description": wiki_entry})
            db.conn.commit()
            return {"status": "success", "message": "Wiki entry regenerated successfully.", "wiki": wiki_entry}
        except Exception as e:
            return {"status": "error", "message": f"Failed to regenerate wiki: {str(e)}"}
            
    elif action == "regenerate-tags":
        from ..models import HTMLPage
        try:
            page_data = HTMLPage(
                url=page_row["url"],
                title=page_row["title"],
                html_content=page_row["html_content"],
                md_content=page_row["md_content"],
                links=[],
                html_content_hash="",
                md_content_hash="",
                fetched_at=page_row["fetched_at"]
            )
            tags = extract_tags_content(page_data, config, client)
            db["fetched_pages"].update(url, {"tags": json.dumps(tags)})
            db.conn.commit()
            return {"status": "success", "message": "Tags regenerated successfully.", "tags": tags}
        except Exception as e:
            return {"status": "error", "message": f"Failed to regenerate tags: {str(e)}"}
            
    elif action == "download-video":
        video_id = extract_youtube_video_id(url)
        if not video_id:
            return {"status": "error", "message": "Not a valid YouTube URL."}
        try:
            local_path = download_youtube_video(video_id, config)
            if "youtube_videos" in db.table_names():
                db["youtube_videos"].update(url, {"local_path": local_path})
                db.conn.commit()
            return {"status": "success", "message": "Video downloaded successfully.", "local_path": local_path}
        except Exception as e:
            return {"status": "error", "message": f"Failed to download video: {str(e)}"}
            
    else:
        return {"status": "error", "message": f"Unknown action: {action}"}


@router.get("/collections")
def list_collections(api_key: str = Depends(verify_cli_api_key)):
    db = _get_db()
    if "collections" not in db.table_names():
        return []
    
    collections = list(db["collections"].rows)
    res = []
    for col in collections:
        col_id = col["id"]
        count = 0
        if "collection_items" in db.table_names():
            count = db["collection_items"].count_where("collection_id = ?", [col_id])
        res.append({
            "id": col_id,
            "title": col["title"],
            "visibility": col["visibility"],
            "item_count": count
        })
    return res


@router.post("/collections/item")
def manage_collection_item(
    action: str = Form(...),
    collection_id: int = Form(...),
    url: str = Form(...),
    api_key: str = Depends(verify_cli_api_key)
):
    db = _get_db()
    if "collections" not in db.table_names():
        return {"status": "error", "message": "Collections table not found."}
        
    try:
        col = db["collections"].get(collection_id)
    except Exception:
        return {"status": "error", "message": "Collection not found."}
        
    if action == "add":
        try:
            page_row = db["fetched_pages"].get(url)
        except Exception:
            return {"status": "error", "message": f"Page with URL '{url}' not found. Please import it first."}
            
        existing = list(db["collection_items"].rows_where(
            "collection_id = ? AND source_id = ?", [collection_id, url]
        ))
        if existing:
            return {"status": "success", "message": "Item already in collection."}
            
        is_video = bool(extract_youtube_video_id(url))
        source_type = "videos" if is_video else "articles"
        
        db["collection_items"].insert({
            "collection_id": collection_id,
            "source_type": source_type,
            "source_id": url,
            "item_note": "",
            "taxonomy_path": f"/uncategorized/{page_row.get('title', 'item')[:20].replace(' ', '_')}.md",
            "item_order": 0,
            "added_at": datetime.now().isoformat()
        })
        db.conn.commit()
        return {"status": "success", "message": "Item added to collection."}
        
    elif action == "remove":
        db["collection_items"].delete_where(
            "collection_id = ? AND source_id = ?", [collection_id, url]
        )
        db.conn.commit()
        return {"status": "success", "message": "Item removed from collection."}
    else:
        return {"status": "error", "message": f"Unknown action: {action}"}


@router.get("/tags")
def list_tags(api_key: str = Depends(verify_cli_api_key)):
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return []
    
    all_tags = set()
    for row in db["fetched_pages"].rows:
        try:
            tags = json.loads(row.get("tags") or "[]")
            for t in tags:
                all_tags.add(t)
        except Exception:
            pass
    return sorted(list(all_tags))


@router.post("/tags/operation")
def manage_tag(
    action: str = Form(...),
    tag: str = Form(...),
    url: str = Form(...),
    api_key: str = Depends(verify_cli_api_key)
):
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return {"status": "error", "message": "fetched_pages table not found."}
        
    try:
        page_row = db["fetched_pages"].get(url)
    except Exception:
        return {"status": "error", "message": "Page not found."}
        
    try:
        current_tags = json.loads(page_row.get("tags") or "[]")
    except Exception:
        current_tags = []
        
    if action == "add":
        if tag not in current_tags:
            current_tags.append(tag)
            db["fetched_pages"].update(url, {"tags": json.dumps(current_tags)})
            db.conn.commit()
        return {"status": "success", "message": f"Tag '{tag}' added to page.", "tags": current_tags}
    elif action == "remove":
        if tag in current_tags:
            current_tags.remove(tag)
            db["fetched_pages"].update(url, {"tags": json.dumps(current_tags)})
            db.conn.commit()
        return {"status": "success", "message": f"Tag '{tag}' removed from page.", "tags": current_tags}
    else:
        return {"status": "error", "message": f"Unknown action: {action}"}


@router.post("/agent/query")
def query_agent(
    query: str = Form(...),
    api_key: str = Depends(verify_cli_api_key)
):
    db = _get_db()
    client = _get_ollama_client()
    
    context_docs = []
    if "fetched_pages" in db.table_names():
        rows = list(db.execute_returning_dicts(
            "SELECT title, url, description, tags, md_content FROM fetched_pages WHERE title LIKE ? OR description LIKE ? OR tags LIKE ? OR md_content LIKE ? LIMIT 5",
            [f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"]
        ))
        for r in rows:
            try:
                tags = json.loads(r.get("tags") or "[]")
            except Exception:
                tags = []
            context_docs.append({
                "title": r.get("title") or r.get("url"),
                "url": r.get("url"),
                "tags": tags,
                "description": r.get("description") or "",
                "preview": (r.get("md_content") or "")[:1500]
            })
            
    if context_docs:
        context_str = ""
        for i, doc in enumerate(context_docs):
            context_str += f"--- Document {i+1} ---\n"
            context_str += f"Title: {doc['title']}\n"
            context_str += f"URL: {doc['url']}\n"
            context_str += f"Tags: {', '.join(doc['tags'])}\n"
            context_str += f"Summary: {doc['description']}\n"
            context_str += f"Content Preview:\n{doc['preview']}\n"
            context_str += "---------------------\n\n"
    else:
        context_str = "No matching context documents found in the Knowledge Base."
        
    system_prompt = (
        "You are an agent representing the Knowledge Base Web application. "
        "You are equipped with search tools to retrieve matching document contexts from the knowledge base. "
        "Below is the retrieved context matching the user's query.\n\n"
        f"=== RETRIEVED CONTEXT ===\n{context_str}\n\n"
        "Answer the user's query accurately using the retrieved context. If the context is empty or "
        "insufficient to answer the query, tell the user politely and answer to the best of your general knowledge."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]
    
    try:
        response = client.chat(
            model=config.ollama_model,
            messages=messages,
            think=config.ollama_think
        )
        reply = response.message.content
        
        references = [{
            "title": d["title"],
            "url": d["url"],
            "tags": d["tags"]
        } for d in context_docs]
        
        return {
            "status": "success",
            "query": query,
            "reply": reply,
            "references": references
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama query failed: {str(e)}")


@router.get("/logs")
def get_cli_logs(
    limit: int = 100,
    api_key: str = Depends(verify_cli_api_key)
):
    db = _get_db()
    if "system_logs" not in db.table_names():
        return []
    try:
        rows = list(db.execute_returning_dicts(
            "SELECT * FROM system_logs ORDER BY rowid DESC LIMIT ?", [limit]
        ))
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error reading logs: {str(e)}")

