"""
FastAPI Router for displaying pages index and detail wiki profile views in kb-web.
"""

import json
import time
import os
from typing import Optional
from urllib.parse import unquote_plus, urlparse, urljoin
from fastapi import APIRouter, Query, Request, BackgroundTasks, Form, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import or_

from ..base import (
    config,
    _jinja_env,
    COOKIE_NAME,
    verify_session_token,
    verify_auth,
    db_session,
)
from ..models import HTMLPage, extract_youtube_video_id
from ..models_orm import FetchedPage, YouTubeVideo, Collection, CollectionItem, PageVersion
from ..utils import (
    get_url_basename,
    preprocess_markdown,
    get_similar_articles,
    download_youtube_video,
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
    pages_list = []
    videos_list = []
    creators_counts = {}
    selected_creator = request.query_params.get("creator")

    with db_session() as session:
        # Fetch pages joined with YouTube videos
        query = (
            session.query(
                FetchedPage,
                YouTubeVideo.creator,
                YouTubeVideo.video_id,
                YouTubeVideo.duration,
                YouTubeVideo.view_count,
                YouTubeVideo.thumbnail_url,
            )
            .outerjoin(YouTubeVideo, FetchedPage.url == YouTubeVideo.url)
        )

        if q:
            query = query.filter(
                or_(
                    FetchedPage.title.like(f"%{q}%"),
                    FetchedPage.tags.like(f"%{q}%"),
                )
            )

        query = query.order_by(FetchedPage.fetched_at.desc())
        rows = query.all()

        for page_obj, creator, video_id, duration, view_count, thumbnail_url in rows:
            try:
                # Parse tags
                tags_list = []
                tags_json = page_obj.tags
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

                # Fetch collection details
                coll_title = None
                coll_id = None
                coll_rows = (
                    session.query(Collection)
                    .join(CollectionItem, Collection.id == CollectionItem.collection_id)
                    .filter(CollectionItem.source_id == page_obj.url, Collection.id != 1)
                    .all()
                )
                if coll_rows:
                    coll_title = ", ".join([c.title for c in coll_rows])
                    coll_id = coll_rows[0].id

                # Build dictionary for HTMLPage matching models expectations
                p_dict = {col.name: getattr(page_obj, col.name) for col in page_obj.__table__.columns}
                # Ensure JSON strings are converted back to list/dict for Pydantic/Jinja
                for fld in ("links", "keywords", "tags"):
                    if p_dict.get(fld):
                        try:
                            p_dict[fld] = json.loads(p_dict[fld])
                        except Exception:
                            p_dict[fld] = []
                    else:
                        p_dict[fld] = []

                actual_video_id = video_id or extract_youtube_video_id(page_obj.url)
                if actual_video_id:
                    actual_creator = creator or "Unknown Creator"
                    creators_counts[actual_creator] = creators_counts.get(actual_creator, 0) + 1

                    if tag or view == "videos":
                        if not selected_creator or actual_creator == selected_creator:
                            html_page = HTMLPage(**p_dict)
                            html_page.creator = actual_creator
                            html_page.video_id = actual_video_id
                            html_page.duration = duration
                            html_page.view_count = view_count
                            html_page.thumbnail_url = thumbnail_url
                            html_page.collection_title = coll_title
                            html_page.collection_id = coll_id
                            videos_list.append(html_page)
                else:
                    if tag or view != "videos":
                        html_page = HTMLPage(**p_dict)
                        html_page.collection_title = coll_title
                        html_page.collection_id = coll_id
                        pages_list.append(html_page)
            except Exception as e:
                print(f"Database row validation error: {e}")
                continue

        # Fetch and compute sites
        sites_dict = {}
        all_pages = session.query(FetchedPage).all()
        for page_obj in all_pages:
            url = page_obj.url
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
            p_dict = {col.name: getattr(page_obj, col.name) for col in page_obj.__table__.columns}
            sites_dict[basename]["pages"].append(p_dict)

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
    decoded_url = unquote_plus(url)
    page_obj = None

    with db_session() as session:
        if version_id:
            try:
                row = session.query(PageVersion).filter_by(id=int(version_id)).first()
                if row:
                    p_dict = {col.name: getattr(row, col.name) for col in row.__table__.columns}
                    for fld in ("links", "keywords", "tags"):
                        if p_dict.get(fld):
                            try:
                                p_dict[fld] = json.loads(p_dict[fld])
                            except Exception:
                                p_dict[fld] = []
                        else:
                            p_dict[fld] = []
                    page_obj = HTMLPage(**p_dict)
            except Exception:
                pass

        if not page_obj:
            try:
                row = session.query(FetchedPage).filter_by(url=decoded_url).first()
                if row:
                    p_dict = {col.name: getattr(row, col.name) for col in row.__table__.columns}
                    for fld in ("links", "keywords", "tags"):
                        if p_dict.get(fld):
                            try:
                                p_dict[fld] = json.loads(p_dict[fld])
                            except Exception:
                                p_dict[fld] = []
                        else:
                            p_dict[fld] = []
                    page_obj = HTMLPage(**p_dict)
            except Exception:
                pass

        if not page_obj:
            return HTMLResponse(
                content="<h1>Wiki Article Profile Missing</h1>", status_code=404
            )

        # Fetch collection details if present (using many-to-many relationship)
        collection_title = None
        assigned_collection_ids = []
        assigned_collections = []
        try:
            coll_rows = (
                session.query(Collection)
                .join(CollectionItem, Collection.id == CollectionItem.collection_id)
                .filter(CollectionItem.source_id == decoded_url)
                .all()
            )
            if coll_rows:
                non_general = [c for c in coll_rows if c.id != 1]
                if non_general:
                    collection_title = ", ".join([c.title for c in non_general])
                    page_obj.collection_id = non_general[0].id
                assigned_collection_ids = [c.id for c in coll_rows]
                assigned_collections = [{"id": c.id, "title": c.title} for c in non_general]
        except Exception as e:
            print(f"Failed to fetch assigned collections: {e}")

        page_obj.collection_title = collection_title or None

        # Retrieve all collections for management dropdown
        collections_list = []
        try:
            collections_list = [
                {col.name: getattr(c, col.name) for col in c.__table__.columns}
                for c in session.query(Collection).all()
            ]
        except Exception:
            pass

        video_metadata = None
        is_offline = False
        local_video_url = None
        video_id = extract_youtube_video_id(decoded_url)
        if video_id:
            try:
                yt_row = session.query(YouTubeVideo).filter_by(url=decoded_url).first()
                if yt_row:
                    video_metadata = {col.name: getattr(yt_row, col.name) for col in yt_row.__table__.columns}
            except Exception:
                pass

            db_path = video_metadata.get("local_path") if video_metadata else None
            media_dir = config.configs_dir.parent / "media" / "videos"
            default_local_path = media_dir / f"{video_id}.mp4"
            has_file = False
            filename = None

            if db_path and os.path.exists(db_path):
                has_file = True
                filename = os.path.basename(db_path)
            elif default_local_path.exists():
                has_file = True
                filename = f"{video_id}.mp4"
            elif media_dir.exists():
                matching = list(media_dir.glob(f"*{video_id}*"))
                if matching:
                    has_file = True
                    filename = matching[0].name

            if has_file and filename:
                is_offline = True
                local_video_url = f"/media/videos/{filename}"

        current_fetched_at = None
        try:
            current_row = session.query(FetchedPage).filter_by(url=decoded_url).first()
            if current_row:
                current_fetched_at = current_row.fetched_at
        except Exception:
            pass

        versions = []
        try:
            version_rows = session.query(PageVersion).filter_by(url=decoded_url).order_by(PageVersion.id.asc()).all()
            versions = [{col.name: getattr(r, col.name) for col in r.__table__.columns} for r in version_rows]
        except Exception:
            pass

        similar_pages = get_similar_articles(None, decoded_url, config)

        # Filter and resolve links
        scraped_links = []
        if page_obj.links:
            for link in page_obj.links:
                if not link or link.startswith("#"):
                    continue
                abs_link = urljoin(page_obj.url, link)
                link_parsed = urlparse(abs_link)
                if link_parsed.scheme in ("http", "https"):
                    scraped_links.append(abs_link)
            scraped_links = list(dict.fromkeys(scraped_links))

        ingested_urls = set()
        if scraped_links:
            rows = session.query(FetchedPage.url).filter(FetchedPage.url.in_(scraped_links)).all()
            ingested_urls = {r[0] for r in rows}

        page_links_data = [
            {"url": link, "ingested": link in ingested_urls} for link in scraped_links
        ]

    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    rendered_wiki_html = markdown.markdown(
        preprocess_markdown(page_obj.description or ""),
        extensions=["fenced_code", "tables"],
    )
    rendered_md_html = markdown.markdown(
        preprocess_markdown(page_obj.md_content or ""),
        extensions=["fenced_code", "tables"],
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
            is_offline=is_offline,
            local_video_url=local_video_url,
            assigned_collections=assigned_collections,
            assigned_collection_ids=assigned_collection_ids,
        )
    )


def run_recursive_crawl(base_url: str, depth: int, interval: int, config_obj):
    """
    Crawls recursively from a base URL up to a given depth, waiting `interval` seconds between fetches.
    Only crawls URLs that have the same netloc domain as the base URL.
    """
    import logging
    import ollama

    logger = logging.getLogger("kb_web")
    client = ollama.Client(host=config_obj.ollama_host)

    from ..utils import ingest_url_sync

    # Normalize base netloc domain to ignore www. differences
    base_netloc = urlparse(base_url).netloc
    base_domain = base_netloc.lower()
    if base_domain.startswith("www."):
        base_domain = base_domain[4:]

    queue = [(base_url, 0)]
    visited = set()

    logger.info(
        f"[CRAWLER] Starting recursive crawl from: {base_url} (depth={depth}, interval={interval}s, normalized domain={base_domain})"
    )

    count = 0
    max_pages = 50  # safeguard

    while queue and count < max_pages:
        current_url, current_depth = queue.pop(0)

        if current_url in visited:
            continue
        visited.add(current_url)

        # Check if already ingested in database
        already_ingested = False
        with db_session() as session:
            already_ingested = session.query(FetchedPage).filter_by(url=current_url).first() is not None

        logger.info(
            f"[CRAWLER] Processing target: {current_url} at depth {current_depth}"
        )

        try:
            if not already_ingested:
                ingest_url_sync(None, current_url, config_obj, client)
                count += 1
                logger.info(f"[CRAWLER] Ingested successfully: {current_url}")
                # Sleep between requests to respect crawl interval
                time.sleep(interval)
            else:
                logger.info(
                    f"[CRAWLER] Skipping ingestion: {current_url} (already exists in database)"
                )
        except Exception as e:
            logger.error(
                f"[CRAWLER] Ingestion failure for {current_url}: {str(e)}",
                exc_info=True,
            )
            continue

        # Fetch page links to continue crawling if depth is not exceeded
        if current_depth < depth:
            try:
                with db_session() as session:
                    row = session.query(FetchedPage).filter_by(url=current_url).first()
                    links_json = row.links if row else "[]"
                links = json.loads(links_json)
                logger.info(
                    f"[CRAWLER] Parsing links for {current_url}. Found {len(links)} links."
                )
                for link in links:
                    if not link or link.startswith("#"):
                        continue
                    abs_link = urljoin(current_url, link)
                    parsed_link = urlparse(abs_link)

                    # Normalize child link netloc domain to ignore www. differences
                    link_domain = parsed_link.netloc.lower()
                    if link_domain.startswith("www."):
                        link_domain = link_domain[4:]

                    if (
                        parsed_link.scheme in ("http", "https")
                        and link_domain == base_domain
                    ):
                        if abs_link not in visited:
                            queue.append((abs_link, current_depth + 1))
            except Exception as e:
                logger.error(
                    f"[CRAWLER] Failed parsing links for {current_url}: {str(e)}",
                    exc_info=True,
                )

    logger.info(
        f"[CRAWLER] Recursive crawl finished. Total new pages ingested: {count}"
    )


@router.post("/api/crawl/start", dependencies=[Depends(verify_auth)])
def start_site_crawl(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    depth: int = Form(3),
    interval: int = Form(5),
) -> dict:
    """Spawns a recursive crawler task in the background."""
    background_tasks.add_task(run_recursive_crawl, url, depth, interval, config)
    return {"status": "success", "message": f"Crawler started in background for: {url}"}


def background_video_downloader(video_id: str, url: str, config_obj):
    try:
        local_path = download_youtube_video(video_id, config_obj)
        # Update youtube_videos table with the local path
        with db_session() as session:
            yt = session.query(YouTubeVideo).filter_by(url=url).first()
            if yt:
                yt.local_path = local_path
            else:
                session.add(YouTubeVideo(url=url, video_id=video_id, local_path=local_path))
        print(f"[DOWNLOAD] Video {video_id} successfully saved offline at {local_path}")
    except Exception as e:
        print(f"[DOWNLOAD] Error downloading video {video_id}: {e}")


@router.post("/api/youtube/download", dependencies=[Depends(verify_auth)])
def start_video_download(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
) -> dict:
    """Spawns a background task to download a YouTube video offline."""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return {"status": "error", "message": "Invalid YouTube URL or video ID."}

    background_tasks.add_task(background_video_downloader, video_id, url, config)
    return {
        "status": "success",
        "message": f"Downloading video {video_id} in background.",
    }
