"""
FastAPI REST API Router providing standardized programmatic JSON endpoints for kb-web.

Supports paginated article cards, full article details, paginated video libraries,
structured video transcripts with timestamp segments, virtual domain sites, and tags.
"""

import json
import math
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy import or_, func, desc, asc

from ..base import db_session, config
from ..models import extract_youtube_video_id
from ..models_orm import FetchedPage, YouTubeVideo, Collection, CollectionItem, PageVersion, PageCardView
from ..utils import get_url_basename

router = APIRouter(prefix="/api", tags=["REST API"])


def _parse_tags(tags_json: Optional[str]) -> List[str]:
    """Safely decodes JSON tags string into a Python list of strings."""
    if not tags_json:
        return []
    try:
        parsed = json.loads(tags_json)
        if isinstance(parsed, list):
            return [str(t).strip() for t in parsed if t]
    except Exception:
        pass
    return []


def _parse_json_field(val: Optional[str]) -> Any:
    if not val:
        return []
    try:
        return json.loads(val)
    except Exception:
        return []


def _timestamp_to_seconds(ts: str) -> int:
    """Converts a timestamp string like '01:23' or '01:02:03' to integer seconds."""
    parts = ts.strip("[]() ").split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        pass
    return 0


# --- 1. Articles Endpoints ---

@router.get("/articles")
def list_articles(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(24, ge=1, le=100, description="Items per page"),
    q: Optional[str] = Query(None, description="Search term for title, tags, or summary"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    creator: Optional[str] = Query(None, description="Filter by creator"),
    sort: str = Query("desc", pattern="^(asc|desc)$", description="Sort order by fetched_at"),
) -> Dict[str, Any]:
    """Returns a paginated list of lightweight article cards without heavy HTML/markdown."""
    with db_session() as session:
        # Base query from pre-aggregated view PageCardView
        query = session.query(PageCardView).filter(PageCardView.video_id.is_(None))

        if q:
            term = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    PageCardView.title.ilike(term),
                    PageCardView.tags.ilike(term),
                    PageCardView.description.ilike(term),
                )
            )

        if tag:
            query = query.filter(PageCardView.tags.ilike(f"%{tag.strip()}%"))

        if creator:
            query = query.filter(PageCardView.creator == creator)

        # Count total matching
        total = query.count()

        # Sorting
        if sort == "asc":
            query = query.order_by(asc(PageCardView.fetched_at))
        else:
            query = query.order_by(desc(PageCardView.fetched_at))

        # Pagination
        offset = (page - 1) * limit
        rows = query.offset(offset).limit(limit).all()

        items = []
        for r in rows:
            tags = _parse_tags(r.tags)
            if tag:
                # Precise tag check
                tag_lower = tag.strip().lower()
                if not any(t.lower() == tag_lower for t in tags):
                    continue

            parsed_url = urlparse(r.url)
            items.append({
                "url": r.url,
                "title": r.title or r.url,
                "description": r.description or "",
                "tags": tags,
                "domain": parsed_url.hostname or "Source",
                "fetched_at": r.fetched_at or "",
                "collection_id": r.collection_first_id or r.collection_id,
                "collection_title": r.collection_title or None,
            })

        total_pages = math.ceil(total / limit) if limit > 0 else 1

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": (page * limit) < total,
            "has_prev": page > 1,
        }


@router.get("/articles/detail")
def get_article_detail(
    url: str = Query(..., description="Exact URL of the article to fetch")
) -> Dict[str, Any]:
    """Retrieves full article details including cleaned wiki entry, markdown, tags, and collections."""
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if not page:
            raise HTTPException(status_code=404, detail="Article not found.")

        # Associated collections
        coll_rows = (
            session.query(Collection.id, Collection.title)
            .join(CollectionItem, Collection.id == CollectionItem.collection_id)
            .filter(CollectionItem.source_id == url, Collection.id != 1)
            .all()
        )
        collections = [{"id": c[0], "title": c[1]} for c in coll_rows]

        # Version count
        versions_count = session.query(PageVersion).filter_by(url=url).count()

        return {
            "url": page.url,
            "title": page.title or page.url,
            "description": page.description or "",
            "md_content": page.md_content or "",
            "tags": _parse_tags(page.tags),
            "links": _parse_json_field(page.links),
            "keywords": _parse_json_field(page.keywords),
            "fetched_at": page.fetched_at or "",
            "html_content_hash": page.html_content_hash,
            "md_content_hash": page.md_content_hash,
            "collections": collections,
            "versions_count": versions_count,
        }


# --- 2. Videos Endpoints ---

@router.get("/videos")
def list_videos(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(24, ge=1, le=100, description="Items per page"),
    creator: Optional[str] = Query(None, description="Filter by YouTube creator"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    q: Optional[str] = Query(None, description="Search term for title or creator"),
    sort: str = Query("desc", pattern="^(asc|desc)$", description="Sort order by fetched_at"),
) -> Dict[str, Any]:
    """Returns a paginated list of ingested YouTube video profiles and transcripts."""
    with db_session() as session:
        query = session.query(PageCardView).filter(PageCardView.video_id.isnot(None))

        if creator:
            query = query.filter(PageCardView.creator == creator)

        if tag:
            query = query.filter(PageCardView.tags.ilike(f"%{tag.strip()}%"))

        if q:
            term = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    PageCardView.title.ilike(term),
                    PageCardView.creator.ilike(term),
                    PageCardView.tags.ilike(term),
                )
            )

        total = query.count()

        # Sort
        if sort == "asc":
            query = query.order_by(asc(PageCardView.fetched_at))
        else:
            query = query.order_by(desc(PageCardView.fetched_at))

        offset = (page - 1) * limit
        rows = query.offset(offset).limit(limit).all()

        items = []
        for r in rows:
            tags = _parse_tags(r.tags)
            items.append({
                "url": r.url,
                "video_id": r.video_id,
                "title": r.title or r.url,
                "creator": r.creator or "YouTube",
                "duration": r.duration,
                "view_count": r.view_count,
                "thumbnail_url": r.thumbnail_url or (f"https://img.youtube.com/vi/{r.video_id}/mqdefault.jpg" if r.video_id else None),
                "tags": tags,
                "fetched_at": r.fetched_at or "",
                "collection_id": r.collection_first_id or r.collection_id,
                "collection_title": r.collection_title or None,
            })

        # Creator aggregation list
        creator_counts_raw = (
            session.query(PageCardView.creator, func.count(PageCardView.url))
            .filter(PageCardView.video_id.isnot(None))
            .group_by(PageCardView.creator)
            .order_by(func.count(PageCardView.url).desc())
            .all()
        )
        creators = [{"name": c[0] or "Unknown Creator", "count": c[1]} for c in creator_counts_raw if c[0]]

        total_pages = math.ceil(total / limit) if limit > 0 else 1

        return {
            "items": items,
            "creators": creators,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": (page * limit) < total,
            "has_prev": page > 1,
        }


@router.get("/videos/transcript")
def get_video_transcript(
    url: Optional[str] = Query(None, description="YouTube URL"),
    video_id: Optional[str] = Query(None, description="YouTube Video ID"),
) -> Dict[str, Any]:
    """Returns structured timestamped transcript segments and markdown summary for a video."""
    if not url and not video_id:
        raise HTTPException(status_code=400, detail="Either 'url' or 'video_id' parameter must be provided.")

    with db_session() as session:
        page = None
        yt_record = None

        if video_id:
            yt_record = session.query(YouTubeVideo).filter_by(video_id=video_id).first()
            if yt_record:
                page = session.query(FetchedPage).filter_by(url=yt_record.url).first()

        if not page and url:
            page = session.query(FetchedPage).filter_by(url=url).first()
            if not yt_record:
                yt_record = session.query(YouTubeVideo).filter_by(url=url).first()

        if not page:
            raise HTTPException(status_code=404, detail="Video record not found.")

        resolved_video_id = (
            (yt_record.video_id if yt_record else None)
            or extract_youtube_video_id(page.url)
        )

        md = page.md_content or ""
        transcript_raw = ""
        if "## Transcript" in md:
            transcript_raw = md.split("## Transcript", 1)[1].strip()
        elif "Transcript" in md:
            transcript_raw = md.split("Transcript", 1)[1].strip()

        # Parse timestamp segments
        # Matches patterns like "[01:23] Text..." or "01:23 Text..."
        segment_pattern = re.compile(r"(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?)\s*(.*)")
        segments = []
        for line in transcript_raw.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            match = segment_pattern.match(line_str)
            if match:
                ts = match.group(1)
                text_content = match.group(2).strip()
                segments.append({
                    "timestamp": ts,
                    "seconds": _timestamp_to_seconds(ts),
                    "text": text_content,
                })

        return {
            "video_id": resolved_video_id,
            "url": page.url,
            "title": page.title or page.url,
            "creator": (yt_record.creator if yt_record else None) or "YouTube",
            "duration": yt_record.duration if yt_record else None,
            "view_count": yt_record.view_count if yt_record else None,
            "thumbnail_url": (
                (yt_record.thumbnail_url if yt_record else None)
                or (f"https://img.youtube.com/vi/{resolved_video_id}/mqdefault.jpg" if resolved_video_id else None)
            ),
            "summary": page.description or "",
            "raw_transcript": transcript_raw,
            "segments": segments,
        }


# --- 3. Sites Endpoints ---

@router.get("/sites")
def list_sites(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(24, ge=1, le=100, description="Items per page"),
    q: Optional[str] = Query(None, description="Search term for domain"),
) -> Dict[str, Any]:
    """Returns aggregated virtual domain portals with page counts without loading raw HTML."""
    with db_session() as session:
        # Fetch only url and title columns to prevent heavy text loading
        pages_tuples = session.query(FetchedPage.url, FetchedPage.title).all()

        sites_dict: Dict[str, Dict[str, Any]] = {}
        for url, title in pages_tuples:
            if extract_youtube_video_id(url):
                continue
            basename = get_url_basename(url)
            if not basename:
                continue
            if basename not in sites_dict:
                sites_dict[basename] = {
                    "name": basename,
                    "pages_count": 0,
                    "sample_pages": [],
                }
            sites_dict[basename]["pages_count"] += 1
            if len(sites_dict[basename]["sample_pages"]) < 5:
                sites_dict[basename]["sample_pages"].append({
                    "url": url,
                    "title": title or url,
                })

        all_sites = list(sites_dict.values())

        if q:
            q_lower = q.strip().lower()
            all_sites = [s for s in all_sites if q_lower in s["name"].lower()]

        # Sort by page count descending, then alphabetically
        all_sites.sort(key=lambda x: (-x["pages_count"], x["name"]))

        total = len(all_sites)
        offset = (page - 1) * limit
        paged_sites = all_sites[offset : offset + limit]
        total_pages = math.ceil(total / limit) if limit > 0 else 1

        return {
            "items": paged_sites,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": (page * limit) < total,
            "has_prev": page > 1,
        }


# --- 4. Tags Endpoints ---

@router.get("/tags")
def list_tags() -> Dict[str, Any]:
    """Returns a list of all unique tags in the system alongside item counts."""
    with db_session() as session:
        rows = session.query(FetchedPage.tags).filter(FetchedPage.tags.isnot(None)).all()
        tag_counts: Dict[str, int] = {}
        for (tags_json,) in rows:
            for tag in _parse_tags(tags_json):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        sorted_tags = sorted(
            [{"tag": k, "count": v} for k, v in tag_counts.items()],
            key=lambda x: (-x["count"], x["tag"]),
        )

        return {
            "total": len(sorted_tags),
            "tags": sorted_tags,
        }
