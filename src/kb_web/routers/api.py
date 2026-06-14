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
    _get_db,
    _get_ollama_client,
    verify_api_key,
)
from ..models import HTMLPage, HTMLImportPayload
from ..utils import (
    extract_wiki_content,
    extract_tags_content,
    save_youtube_metadata_helper,
    update_article_embedding,
    serialize_page_for_db,
)
from ..gotify import post_to_gotify

router = APIRouter()


@router.post(
    "/api/import/html", dependencies=[Depends(verify_api_key)], response_model=None
)
def handle_html_import(payload: HTMLImportPayload, request: Request) -> dict:
    """Accepts raw HTML posts directly from browser extensions and processes them."""
    db = _get_db()
    try:
        html_content = payload.html_content
        url = payload.url

        h = HTML2Text()
        h.ignore_links = True
        md_content = h.handle(html_content)

        soup = BeautifulSoup(html_content, "html5lib")
        links = [a.get("href") for a in soup.find_all("a", href=True)]
        links = [urljoin(url, link) if link.startswith("/") else link for link in links]

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
            html_content_hash=hashlib.sha256(html_content.encode("utf-8")).hexdigest(),
            md_content_hash=hashlib.sha256(md_content.encode("utf-8")).hexdigest(),
            fetched_at=datetime_now_str(),
            description="",
            keywords=[],
            tags=[],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse page HTML: {e}")

    client = _get_ollama_client()
    wiki_entry = extract_wiki_content(page_data, config, client)
    page_data.description = wiki_entry

    if wiki_entry.strip().startswith("#"):
        first_line = wiki_entry.strip().split("\n")[0]
        title = first_line.replace("#", "").strip()

    page_data.title = title
    tags = extract_tags_content(page_data, config, client)
    page_data.tags = tags

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={page_data.safe_url}"

    serialized, creator = serialize_page_for_db(page_data)
    db["fetched_pages"].upsert(serialized, pk="url")
    save_youtube_metadata_helper(db, page_data.url, creator)
    update_article_embedding(db, page_data.url, config, client)
    post_to_gotify(config, _jinja_env, page_data, view_url)

    return {"status": "success", "url": url, "view_url": view_url}


@router.post(
    "/api/import/page", dependencies=[Depends(verify_api_key)], response_model=None
)
def handle_page_import(payload: HTMLPage, request: Request) -> dict:
    """Accepts full HTMLPage Pydantic payloads (e.g. from kb-rss) and processes/saves them."""
    db = _get_db()

    if not payload.title:
        title = payload.url
        soup = BeautifulSoup(payload.html_content, "html5lib")
        if soup.title:
            title = soup.title.string
        if not title:
            title = urlparse(payload.url).netloc or payload.url
        payload.title = title

    client = _get_ollama_client()
    if not payload.description:
        wiki_entry = extract_wiki_content(payload, config, client)
        payload.description = wiki_entry

        if wiki_entry.strip().startswith("#"):
            first_line = wiki_entry.strip().split("\n")[0]
            payload.title = first_line.replace("#", "").strip()

    if not payload.tags:
        payload.tags = extract_tags_content(payload, config, client)

    base_url = str(request.base_url).rstrip("/")
    view_url = f"{base_url}/view/page?url={payload.safe_url}"

    serialized, creator = serialize_page_for_db(payload)
    db["fetched_pages"].upsert(serialized, pk="url")
    save_youtube_metadata_helper(db, payload.url, creator)
    update_article_embedding(db, payload.url, config, client)
    post_to_gotify(config, _jinja_env, payload, view_url)

    return {"status": "success", "url": payload.url, "view_url": view_url}


def datetime_now_str() -> str:
    from datetime import datetime
    return datetime.now().isoformat()
