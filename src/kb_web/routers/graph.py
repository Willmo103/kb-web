"""
FastAPI Router for embedding neighbors similarity graph rendering.
"""

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..base import (
    config,
    _jinja_env,
    _get_db,
    COOKIE_NAME,
    verify_session_token,
)
from ..utils import get_url_basename, cosine_similarity

router = APIRouter()


@router.get("/graph", response_class=HTMLResponse)
def get_graph_view(request: Request) -> HTMLResponse:
    """Serves the interactive similarity graph visualizer page."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    template = _jinja_env.get_template("similarity_graph.j2.html")
    return HTMLResponse(content=template.render(is_admin=is_admin))


@router.get("/api/graph-data")
def get_graph_data(request: Request) -> JSONResponse:
    """Returns nodes and links representing pages, tags, sites, and creators."""
    db = _get_db()
    nodes = []
    links = []

    if "fetched_pages" not in db.table_names():
        return JSONResponse(content={"nodes": [], "links": []})

    # Fetch all pages
    pages = list(db["fetched_pages"].rows)
    page_urls = {p["url"] for p in pages}

    # Fetch all embeddings
    embeddings = {}
    if "article_embeddings" in db.table_names():
        try:
            for r in db["article_embeddings"].rows:
                # Only include embeddings of pages that actually exist in the database
                if r["url"] in page_urls:
                    embeddings[r["url"]] = json.loads(r["embedding"])
        except Exception as e:
            print(f"Error loading embeddings for graph: {e}")

    # Fetch video creators
    video_creators = {}
    if "youtube_videos" in db.table_names():
        try:
            for r in db["youtube_videos"].rows:
                if r["url"] in page_urls:
                    video_creators[r["url"]] = r.get("creator") or "Unknown Creator"
        except Exception:
            pass

    tags_seen = set()
    sites_seen = set()
    creators_seen = set()

    for p in pages:
        url = p["url"]
        title = p.get("title") or url
        nodes.append({
            "id": url,
            "label": title,
            "type": "page"
        })

        # Link Page -> Site (excluding virtual cron URLs)
        if not url.startswith("cron://"):
            site = get_url_basename(url)
            site_id = f"site:{site}"
            if site not in sites_seen:
                sites_seen.add(site)
                nodes.append({
                    "id": site_id,
                    "label": site,
                    "type": "site"
                })
            links.append({
                "source": url,
                "target": site_id,
                "type": "page-site"
            })

        # Link Page -> Creator (if YouTube video)
        creator = video_creators.get(url)
        if creator:
            creator_id = f"creator:{creator}"
            if creator not in creators_seen:
                creators_seen.add(creator)
                nodes.append({
                    "id": creator_id,
                    "label": creator,
                    "type": "creator"
                })
            links.append({
                "source": url,
                "target": creator_id,
                "type": "page-creator"
            })

        # Link Page -> Tags
        tags_json = p.get("tags")
        if tags_json:
            try:
                tags = json.loads(tags_json)
                for t in tags:
                    tag_id = f"tag:{t}"
                    if t not in tags_seen:
                        tags_seen.add(t)
                        nodes.append({
                            "id": tag_id,
                            "label": t,
                            "type": "tag"
                        })
                    links.append({
                        "source": url,
                        "target": tag_id,
                        "type": "page-tag"
                    })
            except Exception:
                pass

    # Compute similarity-based page-to-page links
    url_list = list(embeddings.keys())
    threshold = getattr(config, "similarity_threshold", 0.8)
    for i in range(len(url_list)):
        for j in range(i + 1, len(url_list)):
            u1 = url_list[i]
            u2 = url_list[j]
            sim = cosine_similarity(embeddings[u1], embeddings[u2])
            if sim >= threshold:
                links.append({
                    "source": u1,
                    "target": u2,
                    "type": "similarity",
                    "weight": round(sim, 2)
                })

    return JSONResponse(content={"nodes": nodes, "links": links})
