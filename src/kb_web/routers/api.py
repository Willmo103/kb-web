"""
FastAPI Router for extension/external programmatic imports.
"""

import hashlib
from urllib.parse import urlparse, urljoin
from fastapi import APIRouter, Depends, HTTPException, Request
from html2text import HTML2Text
from bs4 import BeautifulSoup  # type: ignore

from ..base import (
    config,
    _jinja_env,
    _get_ollama_client,
    verify_api_key,
    db_session,
)
from ..models import HTMLPage, HTMLImportPayload, extract_youtube_video_id
from ..models_orm import FetchedPage, PageVersion
from ..utils import (
    extract_wiki_content,
    extract_tags_content,
    save_youtube_metadata_helper,
    update_article_embedding,
    serialize_page_for_db,
    fetch_youtube_video_page,
    generate_gemma_embeddings_for_page,
)
from ..gotify import post_to_gotify

router = APIRouter()


@router.post(
    "/api/import/html", dependencies=[Depends(verify_api_key)], response_model=None
)
def handle_html_import(payload: HTMLImportPayload, request: Request) -> dict:
    """Accepts raw HTML posts directly from browser extensions and processes them."""
    try:
        url = payload.url
        html_content = payload.html_content
        video_id = extract_youtube_video_id(url)

        page_data = None
        if video_id:
            try:
                page_data = fetch_youtube_video_page(url, video_id)
                if (
                    not page_data.title
                    or page_data.title == f"YouTube Video {video_id}"
                ):
                    if payload.title:
                        page_data.title = payload.title
            except Exception as e:
                print(
                    f"Failed to fetch YouTube page content, falling back to raw payload: {e}"
                )
                page_data = None

        if not page_data:
            h = HTML2Text()
            h.ignore_links = True
            md_content = h.handle(html_content)

            soup = BeautifulSoup(html_content, "html5lib")
            links = [a.get("href") for a in soup.find_all("a", href=True)]
            links = [
                urljoin(url, link) if link.startswith("/") else link for link in links
            ]

            title = payload.title
            if not title and soup.title:
                title = soup.title.string
            if not title:
                title = urlparse(url).netloc or url

            page_data = HTMLPage(
                url=url,
                title=title,
                html_content=html_content,
                md_content=md_content,
                links=links,
                html_content_hash=hashlib.sha256(
                    html_content.encode("utf-8")
                ).hexdigest(),
                md_content_hash=hashlib.sha256(md_content.encode("utf-8")).hexdigest(),
                fetched_at=datetime_now_str(),
                description="",
                keywords=[],
                tags=[],
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse page HTML: {e}")

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"

    try:
        with db_session() as session:
            existing = session.query(FetchedPage).filter_by(url=url).first()
            if existing:
                if existing.html_content_hash == page_data.html_content_hash:
                    return {
                        "status": "success",
                        "message": "Content unchanged. Skipping ingestion.",
                        "url": url,
                        "view_url": view_url,
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
    except Exception:
        pass

    client = _get_ollama_client()
    wiki_entry = extract_wiki_content(page_data, config, client)
    page_data.description = wiki_entry

    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        page_data.title = first_line.replace("#", "").strip()

    tags = extract_tags_content(page_data, config, client)
    page_data.tags = tags

    serialized, creator = serialize_page_for_db(page_data)
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=page_data.url).first()
        if page:
            for k, v in serialized.items():
                setattr(page, k, v)
        else:
            session.add(FetchedPage(**serialized))

    save_youtube_metadata_helper(None, page_data.url, creator)
    update_article_embedding(None, page_data.url, config, client)
    generate_gemma_embeddings_for_page(None, page_data.url, config, client)

    post_to_gotify(config, _jinja_env, page_data, view_url)

    return {"status": "success", "url": url, "view_url": view_url}


@router.post(
    "/api/import/page", dependencies=[Depends(verify_api_key)], response_model=None
)
def handle_page_import(payload: HTMLPage, request: Request) -> dict:
    """Accepts full HTMLPage Pydantic payloads (e.g. from kb-rss) and processes/saves them."""
    video_id = extract_youtube_video_id(payload.url)
    if video_id:
        try:
            yt_page = fetch_youtube_video_page(payload.url, video_id)
            payload.html_content = yt_page.html_content
            payload.md_content = yt_page.md_content
            payload.title = yt_page.title or payload.title
            payload.creator = yt_page.creator
        except Exception as e:
            print(
                f"Failed to fetch YouTube page content for import/page, falling back: {e}"
            )

    if not payload.title:
        title = payload.url
        soup = BeautifulSoup(payload.html_content, "html5lib")
        if soup.title:
            title = soup.title.string
        if not title:
            title = urlparse(payload.url).netloc or payload.url
        payload.title = title

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={payload.safe_url}"

    try:
        with db_session() as session:
            existing = session.query(FetchedPage).filter_by(url=payload.url).first()
            if existing:
                if existing.html_content_hash == payload.html_content_hash:
                    return {
                        "status": "success",
                        "message": "Content unchanged. Skipping ingestion.",
                        "url": payload.url,
                        "view_url": view_url,
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
    except Exception:
        pass

    client = _get_ollama_client()
    if not payload.description:
        wiki_entry = extract_wiki_content(payload, config, client)
        payload.description = wiki_entry

        if wiki_entry.strip().startswith("#"):
            first_line = wiki_entry.strip().split("\n")[0]
            payload.title = first_line.replace("#", "").strip()

    if not payload.tags:
        payload.tags = extract_tags_content(payload, config, client)

    serialized, creator = serialize_page_for_db(payload)
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=payload.url).first()
        if page:
            for k, v in serialized.items():
                setattr(page, k, v)
        else:
            session.add(FetchedPage(**serialized))

    save_youtube_metadata_helper(None, payload.url, creator)
    update_article_embedding(None, payload.url, config, client)
    generate_gemma_embeddings_for_page(None, payload.url, config, client)

    post_to_gotify(config, _jinja_env, payload, view_url)

    return {"status": "success", "url": payload.url, "view_url": view_url}


def datetime_now_str() -> str:
    from datetime import datetime

    return datetime.now().isoformat()
