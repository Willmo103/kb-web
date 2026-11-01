"""
Resilient, isolated asynchronous background ingestion pipeline for kb-web.

Processes web pages and YouTube videos in distinct, decoupled, re-runnable stages:
1. Immediate Fetch & Instant Database Persistence (Zero Data Loss)
2. Isolated AI Wiki Synthesis (with generous 1200s timeout)
3. Isolated AI Tag Extraction
3b. Isolated AI Topic & Sub-Topic Assignment & Allowed Topics Check (Issue #128)
4. Isolated Vector & Chunk Embedding Indexing
4b. Isolated Context Mesh Atomic Fact Extraction (Decoupled from Wiki retries, Issue #124)
5. Optional Offline Video Download

Tracks each step's status in the IngestionNotification database table
and notifies connected clients in real-time.
"""

from datetime import datetime, timezone
import json
import logging
import traceback
from typing import List, Optional
from urllib.parse import quote_plus, urlparse
import uuid

from bs4 import BeautifulSoup
from fastapi.concurrency import run_in_threadpool

from .base import _get_ollama_client, config, db_session
from .config import DEFAULT_RAG_SYSTEM_PROMPT, DEFAULT_TAXONOMY_SYSTEM_PROMPT
from .models_orm import (
    Collection,
    CollectionItem,
    ContextStatementORM,
    FetchedPage,
    IngestionNotification,
    PageVersion,
    WorkerJobExecution,
    YouTubeVideo,
)
from .utils import (
    download_youtube_video,
    extract_first_url,
    extract_tags_content,
    extract_wiki_content,
    extract_youtube_video_id,
    fetch_url,
    generate_gemma_embeddings_for_page,
    save_youtube_metadata_helper,
    serialize_page_for_db,
    update_article_embedding,
)

logger = logging.getLogger("kb_web")


def record_notification(
    stage: str,
    status: str,
    message: str,
    url: str = "",
    title: str = "",
    task_id: str = "",
    details: str = "",
) -> None:
    """Persists an ingestion event record into ingestion_notifications."""
    try:
        now_str = datetime.now().isoformat()
        with db_session() as session:
            notif = IngestionNotification(
                task_id=task_id,
                url=url,
                title=title[:255] if title else (url[:255] if url else "Unknown Target"),
                stage=stage,
                status=status,
                message=message,
                details=details[:2000] if details else "",
                created_at=now_str,
                read=0,
            )
            session.add(notif)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to record ingestion notification: {e}")


def _log_pipeline_job_execution(
    job_id: str,
    target_id: str,
    status: str,
    items_count: int = 0,
    error_message: Optional[str] = None,
) -> None:
    """Record stage execution in WorkerJobExecution so the background worker does not duplicate work."""
    try:
        with db_session() as session:
            rec = WorkerJobExecution(
                job_id=job_id,
                target_id=str(target_id).strip(),
                status=status,
                items_count=items_count,
                error_message=str(error_message) if error_message else None,
                executed_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(rec)
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to record WorkerJobExecution for {job_id} on {target_id}: {e}")


async def run_ingest_pipeline_background(
    raw_url: str,
    collection_id: Optional[str] = None,
    new_collection_title: Optional[str] = None,
    download_video: Optional[str] = None,
    task_id: Optional[str] = None,
) -> dict:
    """Executes the complete ingestion lifecycle in resilient, isolated background stages."""
    import sys
    from . import utils
    admin_mod = sys.modules.get("kb_web.routers.admin")

    if fetch_url is not utils.fetch_url:
        _fetch = fetch_url
    elif admin_mod and getattr(admin_mod, "fetch_url", None) is not utils.fetch_url:
        _fetch = getattr(admin_mod, "fetch_url")
    else:
        _fetch = fetch_url

    if extract_wiki_content is not utils.extract_wiki_content:
        _extract_wiki = extract_wiki_content
    elif admin_mod and getattr(admin_mod, "extract_wiki_content", None) is not utils.extract_wiki_content:
        _extract_wiki = getattr(admin_mod, "extract_wiki_content")
    else:
        _extract_wiki = extract_wiki_content

    if extract_tags_content is not utils.extract_tags_content:
        _extract_tags = extract_tags_content
    elif admin_mod and getattr(admin_mod, "extract_tags_content", None) is not utils.extract_tags_content:
        _extract_tags = getattr(admin_mod, "extract_tags_content")
    else:
        _extract_tags = extract_tags_content

    if update_article_embedding is not utils.update_article_embedding:
        _update_embedding = update_article_embedding
    elif admin_mod and getattr(admin_mod, "update_article_embedding", None) is not utils.update_article_embedding:
        _update_embedding = getattr(admin_mod, "update_article_embedding")
    else:
        _update_embedding = update_article_embedding

    if generate_gemma_embeddings_for_page is not utils.generate_gemma_embeddings_for_page:
        _generate_embeddings = generate_gemma_embeddings_for_page
    elif admin_mod and getattr(admin_mod, "generate_gemma_embeddings_for_page", None) is not utils.generate_gemma_embeddings_for_page:
        _generate_embeddings = getattr(admin_mod, "generate_gemma_embeddings_for_page")
    else:
        _generate_embeddings = generate_gemma_embeddings_for_page

    cleaned_url = extract_first_url(raw_url)
    if not task_id:
        task_id = f"task_{uuid.uuid4().hex[:8]}"

    logger.info(
        f"[ASYNC PIPELINE] Starting background ingestion for: {cleaned_url} (task: {task_id})"
    )
    record_notification(
        stage="fetch",
        status="started",
        message=f"Starting ingestion for: {cleaned_url}",
        url=cleaned_url,
        task_id=task_id,
    )

    # -------------------------------------------------------------------------
    # STAGE 1: Fetch & Instant Persistence (Guaranteed Zero Data Loss)
    # -------------------------------------------------------------------------
    page_data = None
    try:
        page_data = await run_in_threadpool(_fetch, cleaned_url)
        logger.info(f"[ASYNC PIPELINE] Successfully fetched raw content for: {cleaned_url}")
    except Exception as e:
        err_msg = f"Fetch failed for {cleaned_url}: {str(e)}"
        logger.error(err_msg, exc_info=True)
        record_notification(
            stage="fetch",
            status="failed",
            message=err_msg,
            url=cleaned_url,
            task_id=task_id,
            details=traceback.format_exc(),
        )
        return {"status": "failed", "stage": "fetch", "error": str(e), "url": cleaned_url}

    # Extract initial title from HTML if not present
    title = page_data.title or cleaned_url
    if not page_data.title or page_data.title == cleaned_url:
        try:
            soup = BeautifulSoup(page_data.html_content, "html5lib")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        except Exception:
            pass
        if not title:
            title = urlparse(cleaned_url).netloc or cleaned_url
        page_data.title = title

    # Resolve Collections association
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

    # Check for content change and archive historical version if necessary
    is_content_unchanged = False
    existing_has_tags = False
    existing_has_topic = False
    existing_has_facts = False

    with db_session() as session:
        existing = session.query(FetchedPage).filter_by(url=cleaned_url).first()
        if (
            existing
            and existing.md_content_hash == page_data.md_content_hash
            and existing.description
        ):
            is_content_unchanged = True

        if existing:
            existing_has_tags = bool(existing.tags and existing.tags not in ("", "[]"))
            existing_has_topic = bool(existing.topic and existing.topic_status in ("approved", "pending"))

        existing_has_facts = (
            session.query(ContextStatementORM).filter_by(source_uri=cleaned_url).count() > 0
        )

        if existing and existing.md_content_hash != page_data.md_content_hash:
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

        # Save or update FetchedPage immediately
        if existing:
            for k, v in serialized.items():
                setattr(existing, k, v)
        else:
            session.add(FetchedPage(**serialized))

        # Associate with collection if specified
        if resolved_col_id:
            existing_item = (
                session.query(CollectionItem)
                .filter_by(collection_id=resolved_col_id, source_id=cleaned_url)
                .first()
            )
            if not existing_item:
                is_video = extract_youtube_video_id(cleaned_url) is not None
                source_type = "videos" if is_video else "articles"
                from sqlalchemy import func

                max_order = (
                    session.query(func.max(CollectionItem.item_order))
                    .filter_by(collection_id=resolved_col_id)
                    .scalar()
                    or 0
                )
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

        session.commit()

    # Save initial YouTube metadata if video
    video_id = extract_youtube_video_id(cleaned_url)
    if video_id:
        try:
            await run_in_threadpool(
                save_youtube_metadata_helper, None, cleaned_url, creator
            )
        except Exception as e:
            logger.warning(f"Initial YouTube metadata save warning: {e}")

    record_notification(
        stage="fetch",
        status="success",
        message=f"Fetched and saved: {title}",
        url=cleaned_url,
        title=title,
        task_id=task_id,
    )
    logger.info(f"[ASYNC PIPELINE] Saved initial page record for: {cleaned_url}")

    # -------------------------------------------------------------------------
    # STAGE 2: AI Wiki Digest Synthesis (Isolated with 1200s timeout)
    # -------------------------------------------------------------------------
    client = _get_ollama_client(timeout=1200.0)
    wiki_success = False

    if is_content_unchanged:
        wiki_success = True
        logger.info(
            f"[ASYNC PIPELINE] Content unchanged (hash match). Skipping AI wiki extraction for: {cleaned_url}"
        )
        record_notification(
            stage="wiki",
            status="info",
            message=f"Content unchanged. Retained existing wiki digest for: {title}",
            url=cleaned_url,
            title=title,
            task_id=task_id,
        )
    else:
        record_notification(
            stage="wiki",
            status="started",
            message=f"Synthesizing wiki entry with AI for: {title}",
            url=cleaned_url,
            title=title,
            task_id=task_id,
        )

        try:
            wiki_entry = await run_in_threadpool(
                _extract_wiki, page_data, config, client
            )
            if wiki_entry and wiki_entry.strip():
                page_data.description = wiki_entry
                extracted_title = title
                if wiki_entry.strip().startswith("#"):
                    first_line = wiki_entry.strip().split("\n")[0]
                    cleaned_header = first_line.replace("#", "").strip()
                    if cleaned_header:
                        extracted_title = cleaned_header
                        page_data.title = extracted_title

                with db_session() as session:
                    page_rec = session.query(FetchedPage).filter_by(url=cleaned_url).first()
                    if page_rec:
                        page_rec.description = wiki_entry
                        page_rec.title = extracted_title
                        session.commit()

                title = extracted_title
                wiki_success = True
                _log_pipeline_job_execution("wiki_curation", cleaned_url, "success", items_count=1)
                record_notification(
                    stage="wiki",
                    status="success",
                    message=f"Wiki digest generated: {title}",
                    url=cleaned_url,
                    title=title,
                    task_id=task_id,
                )
                logger.info(f"[ASYNC PIPELINE] Wiki generated for: {cleaned_url}")
        except Exception as e:
            err_msg = f"AI Wiki generation failed: {str(e)}"
            logger.error(err_msg, exc_info=True)
            record_notification(
                stage="wiki",
                status="failed",
                message=f"Wiki generation failed for {title}: {str(e)}. Raw content preserved.",
                url=cleaned_url,
                title=title,
                task_id=task_id,
                details=str(e),
            )

    # -------------------------------------------------------------------------
    # STAGE 3: AI Tag Extraction (Isolated)
    # -------------------------------------------------------------------------
    tags: List[str] = list(page_data.tags or []) if page_data else []
    if is_content_unchanged and existing_has_tags:
        logger.info(
            f"[ASYNC PIPELINE] Content unchanged. Skipping tag extraction for: {cleaned_url}"
        )
    else:
        record_notification(
            stage="tags",
            status="started",
            message=f"Extracting tags for: {title}",
            url=cleaned_url,
            title=title,
            task_id=task_id,
        )
        try:
            extracted_tags = await run_in_threadpool(_extract_tags, page_data, config, client)
            if extracted_tags:
                tags = extracted_tags
                page_data.tags = tags
                with db_session() as session:
                    page_rec = session.query(FetchedPage).filter_by(url=cleaned_url).first()
                    if page_rec:
                        page_rec.tags = json.dumps(tags)
                        session.commit()

                _log_pipeline_job_execution("tag_curation", cleaned_url, "success", items_count=len(tags))
                tag_preview = ", ".join(tags[:4]) if tags else ""
                record_notification(
                    stage="tags",
                    status="success",
                    message=f"Tags extracted for {title}: {tag_preview}",
                    url=cleaned_url,
                    title=title,
                    task_id=task_id,
                )
                logger.info(f"[ASYNC PIPELINE] Tags generated for: {cleaned_url} ({tags})")
        except Exception as e:
            logger.warning(f"Tag extraction warning for {cleaned_url}: {e}")
            record_notification(
                stage="tags",
                status="warning",
                message=f"Tag generation skipped for {title}: {str(e)}",
                url=cleaned_url,
                title=title,
                task_id=task_id,
            )

    # -------------------------------------------------------------------------
    # STAGE 3b: AI Topic & Sub-Topic Assignment & Allowed Topics Check (Issue #128)
    # -------------------------------------------------------------------------
    if is_content_unchanged and existing_has_topic:
        logger.info(f"[ASYNC PIPELINE] Topic already assigned for unchanged content: {cleaned_url}")
    else:
        try:
            from .taxonomy.engine import assign_topic_and_subtopic

            md_for_topic = (
                (page_data.description if page_data and page_data.description else None)
                or (page_data.md_content if page_data else "")
                or ""
            )
            topic_res = await run_in_threadpool(
                assign_topic_and_subtopic,
                cleaned_url,
                title,
                md_for_topic,
                tags,
                config,
                client,
            )
            _log_pipeline_job_execution("topic_assignment", cleaned_url, "success", items_count=1)
            record_notification(
                stage="topic",
                status="success",
                message=(
                    f"Assigned Topic '{topic_res.get('topic')}' & Sub-Topic "
                    f"'{topic_res.get('sub_topic')}' ({topic_res.get('topic_status')}) for: {title}"
                ),
                url=cleaned_url,
                title=title,
                task_id=task_id,
            )
            logger.info(
                f"[ASYNC PIPELINE] Assigned topic={topic_res.get('topic')} "
                f"sub_topic={topic_res.get('sub_topic')} for: {cleaned_url}"
            )
        except Exception as e:
            logger.warning(f"Topic & sub-topic assignment warning for {cleaned_url}: {e}")

    # -------------------------------------------------------------------------
    # STAGE 4: Vector & Chunk Embeddings Indexing (Isolated)
    # -------------------------------------------------------------------------
    record_notification(
        stage="vector",
        status="started",
        message=f"Indexing vector embeddings for: {title}",
        url=cleaned_url,
        title=title,
        task_id=task_id,
    )
    try:
        await run_in_threadpool(
            _update_embedding, None, cleaned_url, config, client
        )
        await run_in_threadpool(
            _generate_embeddings, None, cleaned_url, config, client
        )
        _log_pipeline_job_execution("embedding_refresh", cleaned_url, "success", items_count=1)
        record_notification(
            stage="vector",
            status="success",
            message=f"Vector embeddings indexed: {title}",
            url=cleaned_url,
            title=title,
            task_id=task_id,
        )
        logger.info(f"[ASYNC PIPELINE] Vector embeddings generated for: {cleaned_url}")
    except Exception as e:
        logger.warning(f"Vector embedding warning for {cleaned_url}: {e}")
        record_notification(
            stage="vector",
            status="warning",
            message=f"Vector embeddings warning for {title}: {str(e)}",
            url=cleaned_url,
            title=title,
            task_id=task_id,
        )

    # -------------------------------------------------------------------------
    # STAGE 4b: Context Mesh Atomic Fact Extraction (Decoupled - Issue #124)
    # -------------------------------------------------------------------------
    if is_content_unchanged and existing_has_facts:
        logger.info(
            f"[ASYNC PIPELINE] Existing facts present for unchanged page {cleaned_url}. Skipping Stage 4b."
        )
    else:
        try:
            from .context_mesh.pipeline import FactExtractionPipeline

            fact_pipeline = FactExtractionPipeline(config=config, client=client)
            tags_list = tags if tags else []
            md_text = (
                (page_data.description if page_data and page_data.description else None)
                or (page_data.md_content if page_data else "")
                or ""
            )
            stmts = await run_in_threadpool(
                fact_pipeline.extract_from_page,
                cleaned_url,
                title,
                md_text,
                tags_list,
                False,
            )
            _log_pipeline_job_execution(
                "fact_extraction",
                cleaned_url,
                "success" if stmts else "skipped",
                items_count=len(stmts) if stmts else 0,
            )
            if stmts:
                record_notification(
                    stage="context_mesh",
                    status="success",
                    message=f"Extracted {len(stmts)} atomic context statements for: {title}",
                    url=cleaned_url,
                    title=title,
                    task_id=task_id,
                )
                logger.info(f"[ASYNC PIPELINE] Context statements extracted ({len(stmts)}) for: {cleaned_url}")
        except Exception as e:
            logger.warning(f"Context mesh extraction warning for {cleaned_url}: {e}")
            _log_pipeline_job_execution(
                "fact_extraction",
                cleaned_url,
                "failed",
                items_count=0,
                error_message=str(e),
            )

    # -------------------------------------------------------------------------
    # STAGE 5: Offline Video Download (Isolated, if requested)
    # -------------------------------------------------------------------------
    if download_video == "yes" and video_id:
        record_notification(
            stage="video",
            status="started",
            message=f"Downloading offline video for: {title}",
            url=cleaned_url,
            title=title,
            task_id=task_id,
        )
        try:
            local_path = await run_in_threadpool(
                download_youtube_video, video_id, config
            )
            with db_session() as session:
                yt_rec = session.query(YouTubeVideo).filter_by(url=cleaned_url).first()
                if yt_rec:
                    yt_rec.local_path = local_path
                    session.commit()
            record_notification(
                stage="video",
                status="success",
                message=f"Downloaded offline video for: {title}",
                url=cleaned_url,
                title=title,
                task_id=task_id,
            )
            logger.info(f"[ASYNC PIPELINE] Video downloaded offline: {local_path}")
        except Exception as e:
            logger.warning(f"Video download failed for {cleaned_url}: {e}")
            record_notification(
                stage="video",
                status="warning",
                message=f"Offline video download warning for {title}: {str(e)}",
                url=cleaned_url,
                title=title,
                task_id=task_id,
            )

    logger.info(f"[ASYNC PIPELINE] Pipeline completed for: {cleaned_url}")
    return {
        "status": "success",
        "url": cleaned_url,
        "title": title,
        "wiki_success": wiki_success,
    }
