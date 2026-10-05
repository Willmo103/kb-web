"""FastAPI Router for administrative batch deletion and content immutability operations.

Supports batch deletion of Obsidian notes, virtual domain sites, videos, and articles,
along with content freeze/immutability toggles.
"""

import os
from pathlib import Path
from typing import Optional, List, Union, Dict, Any
from urllib.parse import unquote_plus, urlparse

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import or_

from ..base import db_session, config, verify_auth
from ..models import extract_youtube_video_id
from ..models_orm import (
    FetchedPage,
    YouTubeVideo,
    Note,
    CollectionItem,
    CollectionAction,
    PageVersion,
    ArticleEmbedding,
    TitleEmbedding,
    VideoEmbedding,
    ChunkEmbedding,
    Link,
    TaxonomyItem,
    SiteWiki,
)

router = APIRouter(tags=["Admin Batch Operations"])


class BatchDeleteRequest(BaseModel):
    entity_type: str  # "notes", "pages", "videos", "sites"
    ids: Optional[List[Union[str, int]]] = None
    folder_prefix: Optional[str] = None
    vault_name: Optional[str] = None
    delete_media: Optional[bool] = False


class BatchDeleteNotesRequest(BaseModel):
    note_ids: Optional[List[int]] = None
    folder_prefix: Optional[str] = None
    vault_name: Optional[str] = None


class BatchDeleteVideosRequest(BaseModel):
    video_ids: Optional[List[str]] = None
    urls: Optional[List[str]] = None
    delete_media: Optional[bool] = False


class BatchDeletePagesRequest(BaseModel):
    urls: List[str]


def _cascade_delete_page_urls(session, urls: List[str]) -> int:
    """Helper to cleanly cascade-delete a list of page URLs and all dependent records."""
    if not urls:
        return 0

    deleted_count = 0
    for u in urls:
        session.query(ArticleEmbedding).filter_by(url=u).delete()
        session.query(TitleEmbedding).filter_by(url=u).delete()
        session.query(VideoEmbedding).filter_by(url=u).delete()
        session.query(ChunkEmbedding).filter_by(source_id=u).delete()
        session.query(CollectionItem).filter_by(source_id=u).delete()
        session.query(CollectionAction).filter_by(source_id=u).delete()
        session.query(TaxonomyItem).filter(
            or_(TaxonomyItem.item_id == u, TaxonomyItem.item_id == u.split("/")[-1])
        ).delete()

        vid_id = extract_youtube_video_id(u)
        if vid_id:
            session.query(YouTubeVideo).filter(
                or_(YouTubeVideo.url == u, YouTubeVideo.video_id == vid_id)
            ).delete()
        else:
            session.query(YouTubeVideo).filter_by(url=u).delete()

        session.query(PageVersion).filter_by(url=u).delete()
        session.query(Link).filter_by(url=u).delete()
        c = session.query(FetchedPage).filter_by(url=u).delete()
        deleted_count += c

    return deleted_count


# --- 1. Batch Notes Deletion ---

@router.delete("/api/notes/batch", dependencies=[Depends(verify_auth)])
def batch_delete_notes(payload: BatchDeleteNotesRequest) -> Dict[str, Any]:
    """Batch deletes Obsidian notes by IDs or folder prefix, cascading embeddings and mirrored pages."""
    deleted_ids = []
    deleted_urls = []

    with db_session() as session:
        query = session.query(Note)
        if payload.note_ids:
            query = query.filter(Note.id.in_(payload.note_ids))
        elif payload.vault_name or payload.folder_prefix:
            if payload.vault_name:
                query = query.filter(Note.vault_name == payload.vault_name)
            if payload.folder_prefix:
                prefix = payload.folder_prefix.strip("/")
                query = query.filter(
                    or_(
                        Note.folder_path == prefix,
                        Note.folder_path.like(f"{prefix}/%"),
                    )
                )
        else:
            raise HTTPException(status_code=400, detail="Must provide note_ids, folder_prefix, or vault_name.")

        notes_to_delete = query.all()
        for note in notes_to_delete:
            deleted_ids.append(note.id)
            if note.url:
                deleted_urls.append(note.url)
            session.delete(note)

        # Clean up mirrored pages, embeddings, and taxonomy records
        for u in deleted_urls:
            session.query(ChunkEmbedding).filter_by(source_id=u).delete()
            session.query(TaxonomyItem).filter_by(item_id=u).delete()
            session.query(FetchedPage).filter_by(url=u).delete()

        for n_id in deleted_ids:
            session.query(TaxonomyItem).filter(
                TaxonomyItem.item_type == "note",
                TaxonomyItem.item_id == str(n_id),
            ).delete()

        session.commit()

    return {
        "status": "success",
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "deleted_urls": deleted_urls,
    }


# --- 2. Batch Site & Pages Deletion ---

@router.delete("/api/sites/{domain:path}/all", dependencies=[Depends(verify_auth)])
def batch_delete_site(domain: str) -> Dict[str, Any]:
    """Deletes a virtual domain site and all its ingested pages, embeddings, and versions."""
    clean_domain = unquote_plus(domain).strip().lower()
    if clean_domain.startswith("http://") or clean_domain.startswith("https://"):
        clean_domain = urlparse(clean_domain).netloc or clean_domain

    with db_session() as session:
        # Find all pages belonging to domain
        pages = session.query(FetchedPage).filter(
            or_(
                FetchedPage.url.like(f"http://{clean_domain}%"),
                FetchedPage.url.like(f"https://{clean_domain}%"),
                FetchedPage.url.like(f"%://{clean_domain}%"),
            )
        ).all()

        urls = [p.url for p in pages]
        deleted_count = _cascade_delete_page_urls(session, urls)

        # Delete site wiki documentation if present
        session.query(SiteWiki).filter(
            or_(SiteWiki.site == clean_domain, SiteWiki.site.ilike(f"%{clean_domain}%"))
        ).delete()

        session.commit()

    return {
        "status": "success",
        "domain": clean_domain,
        "deleted_pages_count": deleted_count,
    }


# --- 3. Batch Videos Deletion ---

@router.delete("/api/videos/batch", dependencies=[Depends(verify_auth)])
def batch_delete_videos(payload: BatchDeleteVideosRequest) -> Dict[str, Any]:
    """Batch deletes videos and embeddings, with optional removal of downloaded local media files."""
    deleted_video_ids = []
    urls_to_remove = []

    with db_session() as session:
        query = session.query(YouTubeVideo)
        if payload.video_ids:
            query = query.filter(YouTubeVideo.video_id.in_(payload.video_ids))
        elif payload.urls:
            clean_urls = [unquote_plus(u) for u in payload.urls]
            query = query.filter(YouTubeVideo.url.in_(clean_urls))
        else:
            raise HTTPException(status_code=400, detail="Must provide either video_ids or urls.")

        videos = query.all()
        for vid in videos:
            deleted_video_ids.append(vid.video_id)
            if vid.url:
                urls_to_remove.append(vid.url)

            # Delete local video files from disk if requested
            if payload.delete_media:
                if vid.local_path and os.path.exists(vid.local_path):
                    try:
                        os.remove(vid.local_path)
                    except Exception as e:
                        print(f"Warning: Failed to delete media file {vid.local_path}: {e}")

                # Also check default media folder ~/.kb/media/videos/{video_id}.*
                media_dir = config.configs_dir.parent / "media" / "videos"
                if media_dir.exists():
                    for f in media_dir.glob(f"{vid.video_id}.*"):
                        try:
                            f.unlink()
                        except Exception:
                            pass

        deleted_count = _cascade_delete_page_urls(session, urls_to_remove)
        session.commit()

    return {
        "status": "success",
        "deleted_videos_count": len(deleted_video_ids),
        "deleted_video_ids": deleted_video_ids,
        "deleted_pages_count": deleted_count,
    }


# --- 4. Batch Pages Deletion ---

@router.delete("/api/pages/batch", dependencies=[Depends(verify_auth)])
def batch_delete_pages(payload: BatchDeletePagesRequest) -> Dict[str, Any]:
    """Batch deletes a list of ingested page URLs and dependent embeddings."""
    clean_urls = [unquote_plus(u) for u in payload.urls]
    with db_session() as session:
        deleted_count = _cascade_delete_page_urls(session, clean_urls)
        session.commit()

    return {
        "status": "success",
        "deleted_count": deleted_count,
        "urls": clean_urls,
    }


# --- 5. Unified Admin Batch-Delete Endpoint ---

@router.post("/api/admin/batch-delete", dependencies=[Depends(verify_auth)])
def admin_batch_delete(payload: BatchDeleteRequest) -> Dict[str, Any]:
    """Unified admin batch deletion endpoint covering notes, sites, videos, and pages."""
    etype = payload.entity_type.lower().strip()

    if etype in ("notes", "note"):
        note_ids = [int(i) for i in payload.ids] if payload.ids else None
        req = BatchDeleteNotesRequest(
            note_ids=note_ids,
            folder_prefix=payload.folder_prefix,
            vault_name=payload.vault_name,
        )
        return batch_delete_notes(req)

    elif etype in ("sites", "site"):
        domain = payload.folder_prefix or (payload.ids[0] if payload.ids else "")
        if not domain:
            raise HTTPException(status_code=400, detail="Domain required for site batch deletion.")
        return batch_delete_site(str(domain))

    elif etype in ("videos", "video"):
        video_ids = [str(i) for i in payload.ids] if payload.ids else None
        req = BatchDeleteVideosRequest(video_ids=video_ids, delete_media=bool(payload.delete_media))
        return batch_delete_videos(req)

    elif etype in ("pages", "articles", "page", "article"):
        if not payload.ids:
            raise HTTPException(status_code=400, detail="Page URLs required for batch deletion.")
        req = BatchDeletePagesRequest(urls=[str(i) for i in payload.ids])
        return batch_delete_pages(req)

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported entity_type '{payload.entity_type}'. Must be 'notes', 'sites', 'videos', or 'pages'.",
        )


# --- 6. Video Freeze Toggle Endpoint ---

@router.post("/api/videos/{video_id}/freeze", dependencies=[Depends(verify_auth)])
def toggle_freeze_video(video_id: str) -> Dict[str, Any]:
    """Toggles freeze/immutable state of a video and its mirrored page."""
    with db_session() as session:
        vid = session.query(YouTubeVideo).filter_by(video_id=video_id).first()
        if not vid:
            raise HTTPException(status_code=404, detail="Video not found")

        vid.is_frozen = 0 if getattr(vid, "is_frozen", 0) else 1
        new_state = vid.is_frozen

        page = session.query(FetchedPage).filter_by(url=vid.url).first()
        if page:
            page.is_frozen = new_state

        session.commit()

    return {"status": "success", "video_id": video_id, "is_frozen": new_state}


# --- 7. Batch Freeze & Immutability Endpoint ---

class BatchFreezeRequest(BaseModel):
    entity_type: str  # "notes", "pages", "videos"
    ids: List[Union[str, int]]
    freeze: int = 1  # 1 to freeze, 0 to unfreeze


@router.post("/api/admin/batch-freeze", dependencies=[Depends(verify_auth)])
def admin_batch_freeze(payload: BatchFreezeRequest) -> Dict[str, Any]:
    """Batch freeze or unfreeze notes, pages, or videos."""
    etype = payload.entity_type.lower().strip()
    freeze_val = 1 if payload.freeze else 0
    updated_count = 0

    with db_session() as session:
        if etype in ("notes", "note"):
            note_ids = [int(i) for i in payload.ids]
            notes = session.query(Note).filter(Note.id.in_(note_ids)).all()
            for n in notes:
                n.is_frozen = freeze_val
                if n.url:
                    page = session.query(FetchedPage).filter_by(url=n.url).first()
                    if page:
                        page.is_frozen = freeze_val
                updated_count += 1

        elif etype in ("pages", "page", "articles", "article"):
            clean_urls = [unquote_plus(str(u)) for u in payload.ids]
            pages = session.query(FetchedPage).filter(FetchedPage.url.in_(clean_urls)).all()
            for p in pages:
                p.is_frozen = freeze_val
                if p.url and p.url.startswith("note://"):
                    note = session.query(Note).filter_by(url=p.url).first()
                    if note:
                        note.is_frozen = freeze_val
                vid_id = extract_youtube_video_id(p.url)
                if vid_id:
                    v = session.query(YouTubeVideo).filter_by(video_id=vid_id).first()
                    if v:
                        v.is_frozen = freeze_val
                updated_count += 1

        elif etype in ("videos", "video"):
            v_ids = [str(i) for i in payload.ids]
            vids = session.query(YouTubeVideo).filter(YouTubeVideo.video_id.in_(v_ids)).all()
            for v in vids:
                v.is_frozen = freeze_val
                if v.url:
                    page = session.query(FetchedPage).filter_by(url=v.url).first()
                    if page:
                        page.is_frozen = freeze_val
                updated_count += 1

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported entity_type '{payload.entity_type}'. Must be 'notes', 'pages', or 'videos'.",
            )

        session.commit()

    return {
        "status": "success",
        "entity_type": etype,
        "is_frozen": freeze_val,
        "updated_count": updated_count,
    }

