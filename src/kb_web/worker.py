"""
Autonomous Background Server Worker Engine for kb-web.

Monitors the database for newly imported pages lacking wiki descriptions or tags,
curating them one at a time with graceful error handling and zero data loss.
Provides extensible task hooks for synthetic QA generation, RAG evaluation,
and autonomous link discovery.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from sqlalchemy import or_
from starlette.concurrency import run_in_threadpool

from .base import config, db_session, _get_ollama_client
from .models import HTMLPage
from .models_orm import FetchedPage
from .pipeline import record_notification
from .utils import (
    extract_wiki_content,
    extract_tags_content,
    update_article_embedding,
    generate_gemma_embeddings_for_page,
)

logger = logging.getLogger("kb_web.worker")


class AutonomousWorker:
    """Resilient periodic background worker for autonomous wiki curation, tagging, and maintenance."""

    def __init__(self) -> None:
        self.enabled: bool = (
            os.getenv("KB_AUTONOMOUS_WORKER_ENABLED", "true").strip().lower()
            in ("true", "1", "yes")
        )
        try:
            self.interval_minutes: int = int(
                os.getenv("KB_AUTONOMOUS_WORKER_INTERVAL_MINUTES", "5")
            )
        except ValueError:
            self.interval_minutes = 5

        self._is_running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        self._stop_event: asyncio.Event = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None

        self.last_run: Optional[str] = None
        self.next_run: Optional[str] = None
        self.total_cycles: int = 0
        self.wikis_curated_total: int = 0
        self.tags_curated_total: int = 0
        self.last_error: Optional[str] = None
        self.last_activity: str = "Worker initialized"

    def get_status(self) -> Dict[str, Any]:
        """Returns the current worker health, operational status, and metrics."""
        return {
            "enabled": self.enabled,
            "is_running": self._is_running,
            "interval_minutes": self.interval_minutes,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "total_cycles": self.total_cycles,
            "wikis_curated_total": self.wikis_curated_total,
            "tags_curated_total": self.tags_curated_total,
            "last_error": self.last_error,
            "last_activity": self.last_activity,
        }

    async def run_cycle(self) -> Dict[str, Any]:
        """Executes one autonomous maintenance cycle, curating one wiki and one set of tags."""
        if self._lock.locked():
            logger.info("[AUTONOMOUS WORKER] Cycle already in progress, skipping duplicate invocation.")
            return {"status": "skipped", "reason": "already_running"}

        async with self._lock:
            self._is_running = True
            now_iso = datetime.now().isoformat()
            self.last_run = now_iso
            self.total_cycles += 1
            cycle_id = f"worker_{uuid.uuid4().hex[:6]}"
            logger.info(f"[AUTONOMOUS WORKER] Starting maintenance cycle #{self.total_cycles} ({cycle_id})")

            curated_wiki_url: Optional[str] = None
            curated_tags_url: Optional[str] = None
            cycle_errors = []

            # -------------------------------------------------------------
            # STAGE 1: Wiki Generation for un-processed items (one at a time)
            # -------------------------------------------------------------
            target_page_wiki = None
            with db_session() as session:
                row = (
                    session.query(FetchedPage)
                    .filter(
                        or_(
                            FetchedPage.description.is_(None),
                            FetchedPage.description == "",
                            FetchedPage.description.ilike("%AI Processing skipped%"),
                        )
                    )
                    .order_by(FetchedPage.fetched_at.asc())
                    .first()
                )
                if row:
                    target_page_wiki = self._row_to_page_dict(row)

            if target_page_wiki:
                url = target_page_wiki["url"]
                title = target_page_wiki.get("title") or url
                logger.info(f"[AUTONOMOUS WORKER] Processing missing wiki for: {url}")
                self.last_activity = f"Generating wiki for {title[:40]}"

                try:
                    page_obj = HTMLPage(**target_page_wiki)
                    client = _get_ollama_client()
                    wiki_entry = await run_in_threadpool(
                        extract_wiki_content, page_obj, config, client
                    )

                    if wiki_entry and wiki_entry.strip():
                        extracted_title = title
                        if wiki_entry.strip().startswith("#"):
                            first_line = wiki_entry.strip().split("\n")[0]
                            cleaned_header = first_line.replace("#", "").strip()
                            if cleaned_header:
                                extracted_title = cleaned_header

                        with db_session() as session:
                            rec = session.query(FetchedPage).filter_by(url=url).first()
                            if rec:
                                rec.description = wiki_entry
                                rec.title = extracted_title
                                session.commit()

                        # Update embeddings in background
                        try:
                            await run_in_threadpool(
                                update_article_embedding, None, url, config, client
                            )
                            await run_in_threadpool(
                                generate_gemma_embeddings_for_page, None, url, config, client
                            )
                        except Exception as emb_err:
                            logger.warning(f"[AUTONOMOUS WORKER] Embedding indexing warning for {url}: {emb_err}")

                        self.wikis_curated_total += 1
                        curated_wiki_url = url
                        record_notification(
                            stage="worker",
                            status="success",
                            message=f"Autonomous worker generated wiki summary for: {extracted_title}",
                            url=url,
                            title=extracted_title,
                            task_id=cycle_id,
                        )
                        logger.info(f"[AUTONOMOUS WORKER] Successfully generated wiki for: {url}")
                except Exception as e:
                    err_msg = f"Autonomous wiki generation failed for {url}: {e}"
                    logger.warning(err_msg)
                    self.last_error = str(e)
                    cycle_errors.append(err_msg)
                    record_notification(
                        stage="worker",
                        status="warning",
                        message=f"Autonomous wiki generation failed for {title}: {e}. Retrying next cycle.",
                        url=url,
                        title=title,
                        task_id=cycle_id,
                    )

            # -------------------------------------------------------------
            # STAGE 2: Tag Extraction for untagged items (one at a time)
            # -------------------------------------------------------------
            target_page_tags = None
            with db_session() as session:
                row = (
                    session.query(FetchedPage)
                    .filter(
                        or_(
                            FetchedPage.tags.is_(None),
                            FetchedPage.tags == "",
                            FetchedPage.tags == "[]",
                        )
                    )
                    .order_by(FetchedPage.fetched_at.asc())
                    .first()
                )
                if row:
                    target_page_tags = self._row_to_page_dict(row)

            if target_page_tags:
                url = target_page_tags["url"]
                title = target_page_tags.get("title") or url
                logger.info(f"[AUTONOMOUS WORKER] Processing missing tags for: {url}")
                self.last_activity = f"Extracting tags for {title[:40]}"

                try:
                    page_obj = HTMLPage(**target_page_tags)
                    client = _get_ollama_client()
                    tags = await run_in_threadpool(
                        extract_tags_content, page_obj, config, client
                    )

                    if tags:
                        with db_session() as session:
                            rec = session.query(FetchedPage).filter_by(url=url).first()
                            if rec:
                                rec.tags = json.dumps(tags)
                                session.commit()

                        self.tags_curated_total += 1
                        curated_tags_url = url
                        tag_preview = ", ".join(tags[:4])
                        record_notification(
                            stage="worker",
                            status="success",
                            message=f"Autonomous worker assigned tags for {title}: {tag_preview}",
                            url=url,
                            title=title,
                            task_id=cycle_id,
                        )
                        logger.info(f"[AUTONOMOUS WORKER] Successfully extracted tags for: {url} ({tags})")
                except Exception as e:
                    err_msg = f"Autonomous tag extraction failed for {url}: {e}"
                    logger.warning(err_msg)
                    self.last_error = str(e)
                    cycle_errors.append(err_msg)
                    record_notification(
                        stage="worker",
                        status="warning",
                        message=f"Autonomous tag extraction failed for {title}: {e}. Retrying next cycle.",
                        url=url,
                        title=title,
                        task_id=cycle_id,
                    )

            # -------------------------------------------------------------
            # STAGE 3: Extensible Hooks (Synthetic QA, RAG Eval, Link Crawling)
            # -------------------------------------------------------------
            await self._run_extensible_hooks(cycle_id)

            # Update final cycle state
            self._is_running = False
            next_time = datetime.now() + timedelta(minutes=self.interval_minutes)
            self.next_run = next_time.isoformat()
            if curated_wiki_url or curated_tags_url:
                self.last_activity = f"Curated: wiki={bool(curated_wiki_url)}, tags={bool(curated_tags_url)}"
            else:
                self.last_activity = "Idle (all library items up-to-date)"

            return {
                "status": "completed",
                "cycle_id": cycle_id,
                "curated_wiki_url": curated_wiki_url,
                "curated_tags_url": curated_tags_url,
                "errors": cycle_errors,
                "next_run": self.next_run,
            }

    async def _run_extensible_hooks(self, cycle_id: str) -> None:
        """Extensible extension points for future autonomous capabilities."""
        # Hook A: Synthetic QA questions generation (foundation)
        await self._hook_synthetic_qa(cycle_id)

        # Hook B: RAG answer quality evaluation (foundation)
        await self._hook_rag_evaluation(cycle_id)

        # Hook C: Autonomous link discovery & queueing (foundation)
        await self._hook_link_crawler(cycle_id)

    async def _hook_synthetic_qa(self, cycle_id: str) -> None:
        """Extensible hook: generates evaluation QA pairs for indexed articles."""
        pass  # Foundation for upcoming QA index generation

    async def _hook_rag_evaluation(self, cycle_id: str) -> None:
        """Extensible hook: tests retrieval precision and scores response accuracy."""
        pass  # Foundation for automated RAG benchmark testing

    async def _hook_link_crawler(self, cycle_id: str) -> None:
        """Extensible hook: autonomously discovers referenced outbound links."""
        pass  # Foundation for autonomous deep crawl

    def _row_to_page_dict(self, row: FetchedPage) -> Dict[str, Any]:
        """Converts an ORM row to an HTMLPage-compatible dictionary."""
        p_dict = {col.name: getattr(row, col.name) for col in row.__table__.columns}
        for fld in ("links", "keywords", "tags"):
            val = p_dict.get(fld)
            if val:
                try:
                    p_dict[fld] = json.loads(val) if isinstance(val, str) else val
                except Exception:
                    p_dict[fld] = []
            else:
                p_dict[fld] = []
        return p_dict

    async def _worker_loop(self) -> None:
        """Continuous background execution loop with configurable interval."""
        logger.info(
            f"[AUTONOMOUS WORKER] Background loop active (interval={self.interval_minutes}m, enabled={self.enabled})"
        )
        # Calculate initial next_run
        self.next_run = (datetime.now() + timedelta(minutes=self.interval_minutes)).isoformat()

        # Initial startup delay (15 seconds) so web server boots smoothly
        try:
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            return

        while not self._stop_event.is_set():
            if self.enabled:
                try:
                    await self.run_cycle()
                except Exception as e:
                    logger.error(f"[AUTONOMOUS WORKER] Unexpected error in worker loop: {e}", exc_info=True)
                    self.last_error = str(e)

            # Sleep in 5-second increments to allow instant responsive shutdown
            wait_seconds = max(30, self.interval_minutes * 60)
            self.next_run = (datetime.now() + timedelta(seconds=wait_seconds)).isoformat()
            slept = 0
            while slept < wait_seconds and not self._stop_event.is_set():
                try:
                    await asyncio.sleep(min(5, wait_seconds - slept))
                    slept += 5
                except asyncio.CancelledError:
                    return

    def start(self) -> None:
        """Starts the autonomous worker task loop if not already running."""
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._worker_loop())
        logger.info("[AUTONOMOUS WORKER] Started worker loop task.")

    def stop(self) -> None:
        """Stops the autonomous worker task loop cleanly."""
        self._stop_event.set()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            logger.info("[AUTONOMOUS WORKER] Stopped worker loop task.")


# Global singleton instance
autonomous_worker = AutonomousWorker()
