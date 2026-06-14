"""
FastAPI Router for displaying pages index and detail wiki profile views in kb-web.
"""

import json
from typing import Optional
from urllib.parse import unquote_plus, urlparse
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ..base import (
    config,
    _get_db,
    _jinja_env,
    COOKIE_NAME,
    verify_session_token,
)
from ..models import HTMLPage, extract_youtube_video_id
from ..utils import (
    get_url_basename,
    preprocess_markdown,
    get_similar_articles,
)

import markdown

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@router.get("/pages", response_class=HTMLResponse)
def view_all_pages(
    request: Request,
    q: Optional[str] = Query(None),
    view: str = Query("articles"),
    tag: Optional[str] = Query(None),
) -> HTMLResponse:
    """Lists historically captured records or grouped sites with a left-hand navigation menu."""
    db = _get_db()
    pages_list = []
    videos_list = []
    creators_counts = {}
    selected_creator = request.query_params.get("creator")

    has_yt_table = "youtube_videos" in db.table_names()

    if "fetched_pages" in db.table_names():
        if q:
            if has_yt_table:
                query = """
                    SELECT f.*, y.creator, y.video_id, y.duration, y.view_count, y.thumbnail_url
                    FROM fetched_pages f 
                    LEFT JOIN youtube_videos y ON f.url = y.url
                    WHERE f.title LIKE ? OR f.tags LIKE ?
                    ORDER BY f.ROWID DESC
                """
                rows = list(db.execute_returning_dicts(query, [f"%{q}%", f"%{q}%"]))
            else:
                rows = list(db.execute_returning_dicts(
                    "SELECT * FROM fetched_pages WHERE title LIKE ? OR tags LIKE ? ORDER BY ROWID DESC",
                    [f"%{q}%", f"%{q}%"],
                ))
        else:
            if has_yt_table:
                query = """
                    SELECT f.*, y.creator, y.video_id, y.duration, y.view_count, y.thumbnail_url
                    FROM fetched_pages f 
                    LEFT JOIN youtube_videos y ON f.url = y.url
                    ORDER BY f.ROWID DESC
                """
                rows = list(db.execute_returning_dicts(query))
            else:
                rows = list(db.execute_returning_dicts("SELECT * FROM fetched_pages ORDER BY ROWID DESC"))

        for row in rows:
            try:
                # Parse tags
                tags_list = []
                tags_json = row.get("tags")
                if tags_json:
                    try:
                        tags_list = json.loads(tags_json)
                        if not isinstance(tags_list, list):
                            tags_list = []
                    except Exception:
                        pass
                
                # Check tag filter
                if tag:
                    tag_lower = tag.strip().lower()
                    if not any(t.strip().lower() == tag_lower for t in tags_list):
                        continue

                video_id = row.get("video_id") or extract_youtube_video_id(row["url"])
                if video_id:
                    creator = row.get("creator") or "Unknown Creator"
                    creators_counts[creator] = creators_counts.get(creator, 0) + 1

                    if tag or view == "videos":
                        if not selected_creator or creator == selected_creator:
                            page_obj = HTMLPage(**row)
                            page_obj.creator = creator
                            page_obj.video_id = video_id
                            page_obj.duration = row.get("duration")
                            page_obj.view_count = row.get("view_count")
                            page_obj.thumbnail_url = row.get("thumbnail_url")
                            videos_list.append(page_obj)
                else:
                    if tag or view != "videos":
                        pages_list.append(HTMLPage(**row))
            except Exception as e:
                print(f"Database row validation error: {e}")
                continue

    # Fetch and compute sites
    sites_dict = {}
    if "fetched_pages" in db.table_names():
        rows_raw = db.execute_returning_dicts(
            "SELECT url, title, description, tags, fetched_at FROM fetched_pages"
        )
        for row in rows_raw:
            url = row["url"]
            if extract_youtube_video_id(url):
                continue
            basename = get_url_basename(url)
            if basename not in sites_dict:
                sites_dict[basename] = {
                    "name": basename,
                    "pages_count": 0,
                    "pages": [],
                }
            sites_dict[basename]["pages_count"] += 1
            sites_dict[basename]["pages"].append(row)

    sorted_sites = sorted(
        sites_dict.values(), key=lambda x: (-x["pages_count"], x["name"])
    )
    sorted_creators = sorted(creators_counts.items(), key=lambda x: (-x[1], x[0]))

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    template = _jinja_env.get_template("pages_list.j2.html")
    return HTMLResponse(
        content=template.render(
            pages=pages_list,
            videos=videos_list,
            creators=sorted_creators,
            selected_creator=selected_creator or "",
            selected_tag=tag or "",
            sites=sorted_sites,
            view=view,
            is_admin=is_admin,
            q=q or "",
        )
    )


@router.get("/view/page", response_class=HTMLResponse)
def view_saved_page(
    request: Request,
    url: str = Query(...),
    version_id: Optional[int] = Query(None),
    msg: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
) -> HTMLResponse:
    """Renders the AI-cleaned or raw markdown page view as rendered HTML."""
    db = _get_db()
    decoded_url = unquote_plus(url)
    page_obj = None

    if version_id:
        try:
            row = db["page_versions"].get(int(version_id))
            page_obj = HTMLPage(**row)
        except Exception:
            pass

    if not page_obj:
        try:
            row = db["fetched_pages"].get(decoded_url)
            page_obj = HTMLPage(**row)
        except Exception:
            return HTMLResponse(
                content="<h1>Wiki Article Profile Missing</h1>", status_code=404
            )

    # Fetch collection details if present
    collection_title = None
    if getattr(page_obj, "collection_id", None):
        try:
            col = db["collections"].get(page_obj.collection_id)
            collection_title = col.get("title")
        except Exception:
            pass
    # Set attributes dynamically
    page_obj.collection_title = collection_title

    # Retrieve all collections for management dropdown
    collections_list = []
    if "collections" in db.table_names():
        try:
            collections_list = list(db["collections"].rows)
        except Exception:
            pass

    video_metadata = None
    if "youtube_videos" in db.table_names():
        try:
            video_metadata = db["youtube_videos"].get(decoded_url)
        except Exception:
            pass

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    current_fetched_at = None
    try:
        current_row = db["fetched_pages"].get(decoded_url)
        current_fetched_at = current_row.get("fetched_at")
    except Exception:
        pass

    versions = []
    if "page_versions" in db.table_names():
        versions = list(
            db["page_versions"].rows_where("url = ? ORDER BY id ASC", [decoded_url])
        )

    similar_pages = get_similar_articles(db, decoded_url, config)

    # Filter and resolve links
    scraped_links = []
    if page_obj.links:
        from urllib.parse import urljoin
        for link in page_obj.links:
            if not link or link.startswith("#"):
                continue
            abs_link = urljoin(page_obj.url, link)
            link_parsed = urlparse(abs_link)
            if link_parsed.scheme in ("http", "https"):
                scraped_links.append(abs_link)
        scraped_links = list(dict.fromkeys(scraped_links))

    ingested_urls = set()
    if scraped_links and "fetched_pages" in db.table_names():
        placeholders = ", ".join(["?"] * len(scraped_links))
        rows = db.execute_returning_dicts(
            f"SELECT url FROM fetched_pages WHERE url IN ({placeholders})",
            scraped_links
        )
        ingested_urls = {r["url"] for r in rows}
        
    page_links_data = [
        {"url": link, "ingested": link in ingested_urls}
        for link in scraped_links
    ]

    rendered_wiki_html = markdown.markdown(
        preprocess_markdown(page_obj.description or ""), extensions=["fenced_code", "tables"]
    )
    rendered_md_html = markdown.markdown(
        preprocess_markdown(page_obj.md_content or ""), extensions=["fenced_code", "tables"]
    )
    video_id = extract_youtube_video_id(decoded_url)
    template = _jinja_env.get_template("view_page.j2.html")
    return HTMLResponse(
        content=template.render(
            page=page_obj,
            rendered_wiki_html=rendered_wiki_html,
            rendered_md_html=rendered_md_html,
            is_admin=is_admin,
            versions=versions,
            active_version_id=version_id,
            current_fetched_at=current_fetched_at,
            msg=msg,
            error=error,
            similar_pages=similar_pages,
            scraped_links=page_links_data,
            video_id=video_id,
            video_metadata=video_metadata,
            collections=collections_list,
        )
    )
