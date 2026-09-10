import json
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from fastapi import APIRouter, Header, HTTPException, Depends, status, Form
from pydantic import BaseModel
from sqlalchemy import or_

from ..base import _get_ollama_client, config, db_session, verify_api_key
from ..gotify import post_to_gotify
from ..models_orm import CliApiKey, RegisteredClient, FetchedPage, PageVersion, Collection, CollectionItem, YouTubeVideo, ArticleEmbedding, TitleEmbedding
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
    download_youtube_video,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cli", tags=["CLI API"])


def verify_cli_api_key(x_api_key: str = Header(...)) -> str:
    with db_session() as session:
        key_exists = session.query(CliApiKey).filter_by(key=x_api_key).first() is not None

    if not key_exists:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked CLI API Key.",
        )
    return x_api_key


class RegistrationRequest(BaseModel):
    computer_name: str


@router.post("/register")
def register_cli_client(
    req: RegistrationRequest, api_key: str = Depends(verify_cli_api_key)
):
    try:
        with db_session() as session:
            client = session.query(RegisteredClient).filter_by(computer_name=req.computer_name).first()
            if client:
                client.api_key = api_key
                client.registered_at = datetime.now().isoformat()
                client.status = "active"
            else:
                session.add(
                    RegisteredClient(
                        computer_name=req.computer_name,
                        api_key=api_key,
                        registered_at=datetime.now().isoformat(),
                        status="active",
                    )
                )
        return {
            "status": "success",
            "message": f"Client '{req.computer_name}' successfully registered.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/url")
def cli_import_url(
    url: str = Form(...),
    collection_id: Optional[str] = Form(None),
    new_collection_title: Optional[str] = Form(None),
    download_video: Optional[str] = Form(None),
    api_key: str = Depends(verify_cli_api_key),
):
    cleaned_url = extract_first_url(url)
    logger.info(f"CLI Ingestion starting for: {cleaned_url}")

    try:
        page_data = fetch_url(cleaned_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fetch failed: {str(e)}")

    with db_session() as session:
        existing = session.query(FetchedPage).filter_by(url=cleaned_url).first()
        if existing:
            if existing.md_content_hash == page_data.md_content_hash:
                return {
                    "status": "success",
                    "message": "Content unchanged. Skipping ingestion.",
                    "url": cleaned_url,
                }
            else:
                session.add(
                    PageVersion(
                        url=existing.url,
                        title=existing.title,
                        html_content=existing.html_content,
                        md_content=existing.md_content,
                        links=existing.links,
                        html_content_hash=existing.html_content_hash,
                        md_content_hash=existing.md_content_hash,
                        fetched_at=existing.fetched_at,
                        description=existing.description,
                        keywords=existing.keywords,
                        tags=existing.tags,
                    )
                )

    client = _get_ollama_client()
    try:
        wiki_entry = extract_wiki_content(page_data, config, client)
        page_data.description = wiki_entry
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"LLM Summary Extraction failed: {str(e)}"
        )

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
        page_data.tags = extract_tags_content(page_data, config, client)
    except Exception:
        pass

    resolved_col_id = None
    with db_session() as session:
        if new_collection_title and new_collection_title.strip():
            col_title = new_collection_title.strip()
            col = session.query(Collection).filter_by(title=col_title).first()
            if not col:
                col = Collection(
                    title=col_title,
                    visibility="public",
                    rag_system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
                    taxonomy_system_prompt=DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                    general_system_context="{}",
                    created_at=datetime.now().isoformat(),
                )
                session.add(col)
                session.flush()
            resolved_col_id = col.id
        elif collection_id and collection_id.isdigit():
            resolved_col_id = int(collection_id)

    page_data.collection_id = resolved_col_id
    serialized, creator = serialize_page_for_db(page_data)

    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=cleaned_url).first()
        if page:
            for k, v in serialized.items():
                setattr(page, k, v)
        else:
            session.add(FetchedPage(**serialized))

        # Associate to Collection
        if resolved_col_id:
            existing_item = session.query(CollectionItem).filter_by(collection_id=resolved_col_id, source_id=cleaned_url).first()
            if not existing_item:
                is_video = extract_youtube_video_id(cleaned_url) is not None
                source_type = "videos" if is_video else "articles"
                from sqlalchemy import func
                max_order = session.query(func.max(CollectionItem.item_order)).filter_by(collection_id=resolved_col_id).scalar() or 0
                session.add(
                    CollectionItem(
                        collection_id=resolved_col_id,
                        source_type=source_type,
                        source_id=cleaned_url,
                        item_note="",
                        taxonomy_path="",
                        item_order=max_order + 1,
                        added_at=datetime.now().isoformat(),
                    )
                )

    save_youtube_metadata_helper(None, page_data.url, creator)
    update_article_embedding(None, page_data.url, config, client)
    generate_gemma_embeddings_for_page(None, page_data.url, config, client)

    video_id = extract_youtube_video_id(cleaned_url)
    if download_video == "true" and video_id:
        try:
            local_path = download_youtube_video(video_id, config)
            with db_session() as session:
                yt = session.query(YouTubeVideo).filter_by(url=page_data.url).first()
                if yt:
                    yt.local_path = local_path
                else:
                    session.add(YouTubeVideo(url=page_data.url, video_id=video_id, local_path=local_path))
        except Exception as e:
            logger.error(f"Background downloader failed: {e}")

    # Post notification
    try:
        view_url = f"/view/page?url={page_data.safe_url}"
        post_to_gotify(config, None, page_data, view_url)
    except Exception:
        pass

    return {
        "status": "success",
        "url": cleaned_url,
        "message": "URL successfully ingested via CLI API.",
    }


@router.post("/query-similar")
def cli_query_similar(
    query: str = Form(...),
    collection_id: Optional[int] = Form(None),
    limit: int = Form(5),
    api_key: str = Depends(verify_api_key),
):
    emb_model = "embeddinggemma"
    try:
        client = _get_ollama_client()
        resp = client.embeddings(model=emb_model, prompt=f"search_query: {query}")
        vector = resp["embedding"]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Ollama embedding query failed: {str(e)}"
        )

    # Perform similarity search
    from ..utils import get_similar_articles
    with db_session() as session:
        # Fallback or PgVector search
        # If SQLite, fallback to custom cosine query
        pass

    results = get_similar_articles(None, None, config, query_vector=vector, limit=limit, collection_id=collection_id)
    return {"status": "success", "results": results}


@router.post("/update/describe")
def cli_update_describe(
    url: str = Form(...),
    api_key: str = Depends(verify_api_key),
):
    client = _get_ollama_client()
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if not page:
            raise HTTPException(status_code=404, detail="Page not found.")

        p_dict = {col.name: getattr(page, col.name) for col in page.__table__.columns}
        for fld in ("links", "keywords", "tags"):
            if p_dict.get(fld):
                try:
                    p_dict[fld] = json.loads(p_dict[fld])
                except Exception:
                    p_dict[fld] = []
            else:
                p_dict[fld] = []
        page_obj = HTMLPage(**p_dict)

        wiki_entry = extract_wiki_content(page_obj, config, client)
        page.description = wiki_entry

    update_article_embedding(None, url, config, client)
    return {"status": "success", "description": wiki_entry}


@router.post("/update/tags")
def cli_update_tags(
    url: str = Form(...),
    api_key: str = Depends(verify_api_key),
):
    client = _get_ollama_client()
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if not page:
            raise HTTPException(status_code=404, detail="Page not found.")

        p_dict = {col.name: getattr(page, col.name) for col in page.__table__.columns}
        for fld in ("links", "keywords", "tags"):
            if p_dict.get(fld):
                try:
                    p_dict[fld] = json.loads(p_dict[fld])
                except Exception:
                    p_dict[fld] = []
            else:
                p_dict[fld] = []
        page_obj = HTMLPage(**p_dict)

        tags = extract_tags_content(page_obj, config, client)
        page.tags = json.dumps(tags)

    update_article_embedding(None, url, config, client)
    return {"status": "success", "tags": tags}


@router.post("/update/video-path")
def cli_update_video_path(
    url: str = Form(...),
    local_path: str = Form(...),
    api_key: str = Depends(verify_api_key),
):
    with db_session() as session:
        yt = session.query(YouTubeVideo).filter_by(url=url).first()
        if yt:
            yt.local_path = local_path
        else:
            session.add(YouTubeVideo(url=url, local_path=local_path))
    return {"status": "success"}


@router.get("/collections")
def cli_list_collections(api_key: str = Depends(verify_cli_api_key)):
    res = []
    with db_session() as session:
        collections = session.query(Collection).all()
        for col in collections:
            count = session.query(CollectionItem).filter_by(collection_id=col.id).count()
            res.append(
                {
                    "id": col.id,
                    "title": col.title,
                    "visibility": col.visibility,
                    "item_count": count,
                }
            )
    return res


@router.post("/collections/item")
def manage_collection_item(
    action: str = Form(...),
    collection_id: int = Form(...),
    url: str = Form(...),
    api_key: str = Depends(verify_cli_api_key),
):
    with db_session() as session:
        col = session.query(Collection).filter_by(id=collection_id).first()
        if not col:
            return {"status": "error", "message": "Collection not found."}

        page = session.query(FetchedPage).filter_by(url=url).first()
        if not page:
            return {"status": "error", "message": f"Page with URL '{url}' not found. Please import it first."}

        if action == "add":
            existing = session.query(CollectionItem).filter_by(collection_id=collection_id, source_id=url).first()
            if existing:
                return {"status": "success", "message": "Item already in collection."}

            is_video = session.query(YouTubeVideo).filter_by(url=url).first() is not None
            source_type = "videos" if is_video else "articles"
            from sqlalchemy import func
            max_order = session.query(func.max(CollectionItem.item_order)).filter_by(collection_id=collection_id).scalar() or 0

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
            return {"status": "success", "message": "Item added to collection."}

        elif action == "remove":
            session.query(CollectionItem).filter_by(collection_id=collection_id, source_id=url).delete()
            return {"status": "success", "message": "Item removed from collection."}
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}


@router.get("/pages")
def cli_list_pages(api_key: str = Depends(verify_cli_api_key)):
    res = []
    with db_session() as session:
        pages = session.query(FetchedPage).all()
        for page in pages:
            res.append(
                {
                    "url": page.url,
                    "title": page.title,
                    "fetched_at": page.fetched_at,
                }
            )
    return res


@router.get("/tags")
def cli_list_tags(api_key: str = Depends(verify_cli_api_key)):
    with db_session() as session:
        all_tags = set()
        pages = session.query(FetchedPage).all()
        for page in pages:
            if page.tags:
                try:
                    tags = json.loads(page.tags)
                    for t in tags:
                        all_tags.add(t)
                except Exception:
                    pass
        return sorted(list(all_tags))


@router.post("/tags/operation")
def cli_manage_tag(
    action: str = Form(...),
    tag: str = Form(...),
    url: str = Form(...),
    api_key: str = Depends(verify_cli_api_key),
):
    tag_clean = tag.strip().lower()
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if not page:
            return {"status": "error", "message": "Page not found."}

        current_tags = []
        if page.tags:
            try:
                current_tags = json.loads(page.tags)
            except Exception:
                pass

        if action == "add":
            if tag_clean not in current_tags:
                current_tags.append(tag_clean)
                page.tags = json.dumps(current_tags)
            update_article_embedding(None, url, config, _get_ollama_client())
            return {"status": "success", "message": f"Tag '{tag}' added to page.", "tags": current_tags}
        elif action == "remove":
            if tag_clean in current_tags:
                current_tags.remove(tag_clean)
                page.tags = json.dumps(current_tags)
            update_article_embedding(None, url, config, _get_ollama_client())
            return {"status": "success", "message": f"Tag '{tag}' removed from page.", "tags": current_tags}
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}


@router.post("/search")
def cli_search(
    query: str = Form(...),
    limit: int = Form(5),
    api_key: str = Depends(verify_api_key),
):
    res = []
    with db_session() as session:
        # DB-independent search query using ILIKE / LIKE
        rows = (
            session.query(FetchedPage)
            .filter(
                or_(
                    FetchedPage.title.like(f"%{query}%"),
                    FetchedPage.description.like(f"%{query}%"),
                    FetchedPage.tags.like(f"%{query}%"),
                )
            )
            .limit(limit)
            .all()
        )
        for r in rows:
            res.append(
                {
                    "url": r.url,
                    "title": r.title,
                    "description": r.description,
                    "tags": r.tags,
                }
            )
    return {"status": "success", "results": res}


@router.post("/chat")
def cli_chat(
    query: str = Form(...),
    limit: int = Form(5),
    api_key: str = Depends(verify_api_key),
):
    emb_model = "embeddinggemma"
    try:
        client = _get_ollama_client()
        resp = client.embeddings(model=emb_model, prompt=f"search_query: {query}")
        vector = resp["embedding"]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Ollama embedding query failed: {str(e)}"
        )

    from ..utils import get_similar_articles
    context_docs = get_similar_articles(None, None, config, query_vector=vector, limit=limit)

    context_str = ""
    for idx, doc in enumerate(context_docs):
        context_str += f"[{idx+1}] Title: {doc['title']}\nURL: {doc['url']}\nContent/Summary:\n{doc['description']}\n\n"

    system_prompt = (
        "You are an expert AI search assistant answering queries from the user's private knowledge base.\n"
        f"=== RETRIEVED CONTEXT ===\n{context_str}\n\n"
        "Answer the user's query accurately using the retrieved context. If the context is empty or "
        "insufficient to answer the query, tell the user politely and answer to the best of your general knowledge."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    try:
        response = client.chat(
            model=config.ollama_model, messages=messages, think=getattr(config, "ollama_think", False)
        )
        reply = response.message.content

        references = [
            {"title": d["title"], "url": d["url"], "tags": d["tags"]}
            for d in context_docs
        ]

        return {
            "status": "success",
            "query": query,
            "reply": reply,
            "references": references,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/query")
def query_agent(
    query: str = Form(...),
    api_key: str = Depends(verify_cli_api_key)
):
    client = _get_ollama_client()
    with db_session() as session:
        # DB-independent query using ILIKE / LIKE
        rows = (
            session.query(FetchedPage)
            .filter(
                or_(
                    FetchedPage.title.like(f"%{query}%"),
                    FetchedPage.description.like(f"%{query}%"),
                    FetchedPage.tags.like(f"%{query}%"),
                    FetchedPage.md_content.like(f"%{query}%"),
                )
            )
            .limit(5)
            .all()
        )
        context_docs = []
        for r in rows:
            try:
                tags = json.loads(r.tags) if r.tags else []
            except Exception:
                tags = []
            context_docs.append({
                "title": r.title or r.url,
                "url": r.url,
                "tags": tags,
                "description": r.description or "",
                "preview": (r.md_content or "")[:1500]
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
            think=getattr(config, "ollama_think", False)
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
    with db_session() as session:
        from ..models_orm import SystemLog
        rows = (
            session.query(SystemLog)
            .order_by(SystemLog.id.desc())
            .limit(limit)
            .all()
        )
        res = []
        for r in rows:
            res.append({
                "id": r.id,
                "timestamp": r.timestamp,
                "level": r.level,
                "module": r.module,
                "message": r.message,
                "traceback": r.traceback
            })
        return res
