"""State-Driven Job Queue Processor Daemon and Pipeline Registry for kb-web.

Manages background ingestion pipelines via the `sources` queue table and `_processor_xref`
registry, supporting state-driven execution, pipeline progression, retry tracking,
and Gotify alerting.
"""

import importlib
import json
import logging
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from sqlalchemy.orm import Session
from sqlalchemy import select

from .base import config as default_config, db_session, _get_ollama_client
from .models_orm import Source, ProcessorXref, FetchedPage, YouTubeVideo, ChunkEmbedding
from .gotify import post_error_to_gotify
from .models import HTMLPage, extract_youtube_video_id
from .utils import (
    fetch_url,
    fetch_youtube_video_page,
    extract_wiki_content,
    extract_tags_content,
    save_youtube_metadata_helper,
    generate_gemma_embeddings_for_page,
    serialize_page_for_db,
)

logger = logging.getLogger("kb_web.queue_processor")

_CALLBACK_CACHE: Dict[str, Callable] = {}


def resolve_callback(callback_path: str) -> Callable:
    """Dynamically resolves an importable string path (e.g. 'module.sub:func') to a callable."""
    if callback_path in _CALLBACK_CACHE:
        return _CALLBACK_CACHE[callback_path]

    if ":" in callback_path:
        mod_name, func_name = callback_path.split(":", 1)
    elif "." in callback_path:
        mod_name, func_name = callback_path.rsplit(".", 1)
    else:
        raise ValueError(f"Invalid callback path format: {callback_path}")

    mod = importlib.import_module(mod_name)
    func = getattr(mod, func_name)
    if not callable(func):
        raise TypeError(f"Resolved object {callback_path} is not callable")

    _CALLBACK_CACHE[callback_path] = func
    return func


# ---------------------------------------------------------------------------
# Pipeline Callback Handlers
# ---------------------------------------------------------------------------

def process_fetch(source: Source, session: Session) -> None:
    """Stage 'pre': Fetches raw webpage HTML and converts to clean markdown."""
    if not source.url:
        raise ValueError(f"Source {source.id} has no URL to fetch")

    logger.info(f"[Fetcher] Processing URL for source {source.id}: {source.url}")
    page_data = fetch_url(source.url)

    metadata = {}
    if source.metadata_json:
        try:
            metadata = json.loads(source.metadata_json)
        except Exception:
            pass

    col_id = metadata.get("collection_id")

    existing_page = session.query(FetchedPage).filter_by(url=source.url).first()
    if existing_page:
        existing_page.title = page_data.title
        existing_page.html_content = page_data.html_content
        existing_page.md_content = page_data.md_content
        existing_page.links = json.dumps(page_data.links)
        existing_page.html_content_hash = page_data.html_content_hash
        existing_page.md_content_hash = page_data.md_content_hash
        existing_page.fetched_at = datetime.now().isoformat()
        existing_page.source_id = source.id
        if col_id is not None:
            existing_page.collection_id = col_id
    else:
        new_page = FetchedPage(
            url=source.url,
            title=page_data.title,
            html_content=page_data.html_content,
            md_content=page_data.md_content,
            links=json.dumps(page_data.links),
            html_content_hash=page_data.html_content_hash,
            md_content_hash=page_data.md_content_hash,
            fetched_at=datetime.now().isoformat(),
            collection_id=col_id,
            source_id=source.id,
        )
        session.add(new_page)

    source.file_hash = page_data.md_content_hash


def process_summary(source: Source, session: Session) -> None:
    """Stage 'process': Generates structured wiki summary via LLM."""
    page = session.query(FetchedPage).filter(
        (FetchedPage.source_id == source.id) | (FetchedPage.url == source.url)
    ).first()

    if not page:
        raise ValueError(f"No FetchedPage found for source {source.id}")

    logger.info(f"[WikiSummary] Generating summary for {page.url} (source {source.id})")
    html_page = HTMLPage(
        url=page.url,
        title=page.title or "",
        html_content=page.html_content or "",
        md_content=page.md_content or "",
        links=json.loads(page.links) if page.links else [],
        html_content_hash=page.html_content_hash or "",
        md_content_hash=page.md_content_hash or "",
        fetched_at=page.fetched_at or "",
    )

    summary = extract_wiki_content(html_page, config=default_config)
    page.description = summary


def process_tags(source: Source, session: Session) -> None:
    """Stage 'process': Extracts semantic categorization tags via LLM."""
    page = session.query(FetchedPage).filter(
        (FetchedPage.source_id == source.id) | (FetchedPage.url == source.url)
    ).first()

    if not page:
        raise ValueError(f"No FetchedPage found for source {source.id}")

    logger.info(f"[Tagger] Extracting tags for {page.url} (source {source.id})")
    html_page = HTMLPage(
        url=page.url,
        title=page.title or "",
        html_content=page.html_content or "",
        md_content=page.md_content or "",
        description=page.description or "",
    )

    tags = extract_tags_content(html_page, config=default_config)
    page.tags = json.dumps(tags)


def process_embeddings(source: Source, session: Session) -> None:
    """Stage 'post': Generates vector embeddings and chunk index."""
    page = session.query(FetchedPage).filter(
        (FetchedPage.source_id == source.id) | (FetchedPage.url == source.url)
    ).first()

    if not page:
        raise ValueError(f"No FetchedPage found for source {source.id}")

    logger.info(f"[Embeddings] Generating embeddings for {page.url} (source {source.id})")
    generate_gemma_embeddings_for_page(None, page.url, config=default_config)

    # Associate created chunks with source.id
    session.query(ChunkEmbedding).filter_by(source_id=page.url).update({"source_uuid": source.id})


def process_youtube_metadata(source: Source, session: Session) -> None:
    """Stage 'pre': Extracts YouTube video metadata and transcript."""
    if not source.url:
        raise ValueError(f"Source {source.id} has no YouTube URL")

    video_id = extract_youtube_video_id(source.url)
    if not video_id:
        raise ValueError(f"Source URL {source.url} is not a valid YouTube link")

    logger.info(f"[YouTubeMetadata] Fetching metadata for {source.url} (source {source.id})")
    page_data = fetch_youtube_video_page(source.url, video_id)

    metadata = {}
    if source.metadata_json:
        try:
            metadata = json.loads(source.metadata_json)
        except Exception:
            pass

    col_id = metadata.get("collection_id")

    existing_page = session.query(FetchedPage).filter_by(url=source.url).first()
    if existing_page:
        existing_page.title = page_data.title
        existing_page.html_content = page_data.html_content
        existing_page.md_content = page_data.md_content
        existing_page.links = json.dumps(page_data.links)
        existing_page.html_content_hash = page_data.html_content_hash
        existing_page.md_content_hash = page_data.md_content_hash
        existing_page.fetched_at = datetime.now().isoformat()
        existing_page.source_id = source.id
        if col_id is not None:
            existing_page.collection_id = col_id
    else:
        new_page = FetchedPage(
            url=source.url,
            title=page_data.title,
            html_content=page_data.html_content,
            md_content=page_data.md_content,
            links=json.dumps(page_data.links),
            html_content_hash=page_data.html_content_hash,
            md_content_hash=page_data.md_content_hash,
            fetched_at=datetime.now().isoformat(),
            collection_id=col_id,
            source_id=source.id,
        )
        session.add(new_page)

    save_youtube_metadata_helper(None, source.url, force_fetch=True)

    # Link source_id on YouTubeVideo
    yt_vid = session.query(YouTubeVideo).filter_by(url=source.url).first()
    if yt_vid:
        yt_vid.source_id = source.id

    source.file_hash = page_data.md_content_hash


def process_youtube_wiki(source: Source, session: Session) -> None:
    """Stage 'process': Generates YouTube video wiki summary from transcript."""
    process_summary(source, session)


def process_docling_file(source: Source, session: Session) -> None:
    """Stage 'process': Parses local document file (PDF, DOCX, etc.) into markdown."""
    file_path = source.path or source.url
    if not file_path:
        raise ValueError(f"Source {source.id} has no file path to parse")

    logger.info(f"[DoclingParser] Parsing document at {file_path} for source {source.id}")
    content = ""
    title = file_path

    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(file_path)
        content = result.document.export_to_markdown()
    except Exception as e:
        logger.warning(f"Docling conversion unavailable or failed: {e}. Falling back to text reader.")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as read_err:
            raise RuntimeError(f"Failed to read file {file_path}: {read_err}") from read_err

    url_key = f"file://{file_path}"
    existing_page = session.query(FetchedPage).filter_by(url=url_key).first()
    if existing_page:
        existing_page.title = title
        existing_page.md_content = content
        existing_page.fetched_at = datetime.now().isoformat()
        existing_page.source_id = source.id
    else:
        new_page = FetchedPage(
            url=url_key,
            title=title,
            md_content=content,
            fetched_at=datetime.now().isoformat(),
            source_id=source.id,
        )
        session.add(new_page)


# ---------------------------------------------------------------------------
# Enqueue API
# ---------------------------------------------------------------------------

def enqueue_source(
    url_or_path: str,
    source_type: str = "html",
    collection_id: Optional[int] = None,
    custom_instructions: Optional[str] = None,
    initial_processor_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Enqueues a new item into the sources table for background pipeline execution."""
    source_id = str(uuid.uuid4())
    meta = metadata.copy() if metadata else {}
    if collection_id is not None:
        meta["collection_id"] = collection_id
    if custom_instructions:
        meta["custom_instructions"] = custom_instructions

    if initial_processor_id is None:
        if source_type == "youtube":
            initial_processor_id = 5  # youtube_metadata
        elif source_type in ("file", "docling"):
            initial_processor_id = 7  # docling_parser
        else:
            initial_processor_id = 1  # fetcher

    is_url = url_or_path.startswith("http://") or url_or_path.startswith("https://")
    url_val = url_or_path if is_url else None
    path_val = url_or_path if not is_url else None

    with db_session() as session:
        new_source = Source(
            id=source_id,
            url=url_val,
            type=source_type,
            processor_id=initial_processor_id,
            path=path_val,
            status="pending",
            retry_count=0,
            timestamp=datetime.now().isoformat(),
            metadata_json=json.dumps(meta) if meta else None,
        )
        session.add(new_source)
        session.commit()

    logger.info(f"Enqueued source {source_id} (type={source_type}, processor={initial_processor_id})")
    return source_id


# ---------------------------------------------------------------------------
# IngestionWorker Daemon
# ---------------------------------------------------------------------------

class IngestionWorker:
    """Background daemon thread polling the sources table and executing pipelines."""

    def __init__(
        self,
        poll_interval: float = 2.0,
        max_retries: int = 3,
        config=None,
    ):
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.config = config or default_config
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts the background worker thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="IngestionWorkerThread",
        )
        self._thread.start()
        logger.info("IngestionWorker background daemon started.")

    def stop(self, timeout: float = 5.0) -> None:
        """Stops the background worker thread gracefully."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("IngestionWorker background daemon stopped.")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = self.process_next_job()
                if not processed:
                    self._stop_event.wait(self.poll_interval)
            except Exception as e:
                logger.error(f"Unexpected error in IngestionWorker loop: {e}", exc_info=True)
                self._stop_event.wait(self.poll_interval)

    def process_next_job(self, source_id: Optional[str] = None) -> bool:
        """Pulls and executes the next pending source job, or a specific source_id if provided.

        Returns True if a job was found and processed, False if queue is empty.
        """
        with db_session() as session:
            # 1. Acquire next pending job
            query = session.query(Source).filter(Source.status == "pending")
            if source_id:
                query = query.filter(Source.id == source_id)
            else:
                query = query.order_by(Source.timestamp.asc())

            source = query.first()
            if not source:
                return False

            source.status = "processing"
            session.commit()

            # 2. Lookup processor definition
            processor = (
                session.query(ProcessorXref)
                .filter(ProcessorXref.id == source.processor_id)
                .first()
            )

            if not processor or not processor.is_active:
                err_msg = f"Processor {source.processor_id} not found or inactive"
                logger.error(f"Source {source.id}: {err_msg}")
                source.status = "failed"
                source.error_log = err_msg
                session.commit()
                return True

            logger.info(
                f"Executing stage '{processor.stage}' (service: '{processor.service_name}') for source {source.id}"
            )

            # 3. Execute callback
            try:
                callback = resolve_callback(processor.callback_path)
                callback(source, session)
                session.flush()

                # 4. Advance pipeline stage
                if processor.next_processor_id:
                    source.processor_id = processor.next_processor_id
                    source.status = "pending"
                else:
                    source.status = "completed"
                    source.error_log = None

                session.commit()
                logger.info(
                    f"Successfully completed stage '{processor.service_name}' for source {source.id}. Next status: {source.status}"
                )

            except Exception as exc:
                session.rollback()
                tb = traceback.format_exc()
                logger.error(f"Pipeline error on source {source.id} (processor: {processor.service_name}): {exc}")

                # Re-query source in fresh state
                source = session.query(Source).filter_by(id=source.id).first()
                if source:
                    source.retry_count = (source.retry_count or 0) + 1
                    source.error_log = f"{type(exc).__name__}: {str(exc)}\n{tb}"

                    if source.retry_count >= self.max_retries:
                        source.status = "failed"
                        logger.error(f"Source {source.id} exceeded max retries ({self.max_retries}). Marked as failed.")
                        try:
                            post_error_to_gotify(self.config, exc, tb)
                        except Exception as gotify_err:
                            logger.error(f"Failed sending Gotify alert on source failure: {gotify_err}")
                    else:
                        source.status = "pending"

                    session.commit()

            return True


# ---------------------------------------------------------------------------
# Global Worker Singleton
# ---------------------------------------------------------------------------

_global_worker: Optional[IngestionWorker] = None
_worker_lock = threading.Lock()


def get_worker() -> IngestionWorker:
    """Returns or instantiates the global IngestionWorker singleton."""
    global _global_worker
    if _global_worker is None:
        with _worker_lock:
            if _global_worker is None:
                _global_worker = IngestionWorker()
    return _global_worker


def start_worker() -> None:
    """Starts the global IngestionWorker daemon."""
    worker = get_worker()
    if not worker.is_running:
        worker.start()


def stop_worker() -> None:
    """Stops the global IngestionWorker daemon."""
    global _global_worker
    if _global_worker is not None and _global_worker.is_running:
        _global_worker.stop()
