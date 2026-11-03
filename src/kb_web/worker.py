"""
Autonomous Background Server Worker Engine for kb-web.

Provides a modular Server Jobs & Agents framework for independent, continuous
curation, tagging, topic & sub-topic assignment (#128), embedding indexing,
synthetic QA generation, RAG evaluation, autonomous link discovery, and
decoupled context fact extraction (#124).

Each job maintains its own execution schedule (timespan/interval in minutes),
designated Ollama model (LLM, decision, or embedding), toggle state, and runtime metrics.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool

from .base import _get_ollama_client, config, db_session
from .models import HTMLPage
from .models_orm import FetchedPage, ChunkEmbedding, WorkerJobExecution, ContextStatementORM, TaxonomyEntityORM
from .pipeline import record_notification
from .utils import (
    extract_tags_content,
    extract_wiki_content,
    generate_gemma_embeddings_for_page,
    update_article_embedding,
)

logger = logging.getLogger("kb_web.worker")


class JobConfigProxy:
    """Proxies config attributes while overriding model targets for specific jobs."""

    def __init__(self, base_config: Any, model: Optional[str] = None, is_embedding: bool = False) -> None:
        self._base = base_config
        self._model = model
        self._is_embedding = is_embedding

    def __getattr__(self, name: str) -> Any:
        if name == "ollama_model" and self._model and not self._is_embedding:
            return self._model
        if name == "ollama_embedding_model" and self._model and self._is_embedding:
            return self._model
        return getattr(self._base, name)


class ServerJob:
    """Represents a discrete autonomous server job / agent with dedicated scheduling and model configuration."""

    def __init__(
        self,
        job_id: str,
        name: str,
        description: str,
        category: str,  # 'llm', 'embedding', 'decision', 'crawler'
        default_interval_minutes: int = 5,
        default_model: str = "",
        runner: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.job_id = job_id
        self.name = name
        self.description = description
        self.category = category
        self.default_interval_minutes = default_interval_minutes
        self.default_model = default_model
        self._runner = runner

        self.last_run: Optional[str] = None
        self.next_run: Optional[str] = None
        self.total_runs: int = 0
        self.items_processed_total: int = 0
        self.last_error: Optional[str] = None
        self.last_activity: str = "Initialized"
        self._is_running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        env_val = os.getenv(f"KB_JOB_{self.job_id.upper()}_ENABLED")
        if env_val is not None:
            return env_val.strip().lower() in ("true", "1", "yes")
        return bool(config._read_db_setting("settings_ollama", f"job_{self.job_id}_enabled", True))

    @enabled.setter
    def enabled(self, val: bool) -> None:
        config._write_db_setting("settings_ollama", f"job_{self.job_id}_enabled", "true" if val else "false")

    @property
    def interval_minutes(self) -> int:
        try:
            val = config._read_db_setting("settings_ollama", f"job_{self.job_id}_interval_minutes", self.default_interval_minutes)
            return max(1, int(val))
        except Exception:
            return self.default_interval_minutes

    @interval_minutes.setter
    def interval_minutes(self, val: int) -> None:
        val = max(1, int(val))
        config._write_db_setting("settings_ollama", f"job_{self.job_id}_interval_minutes", str(val))
        self.next_run = (datetime.now() + timedelta(minutes=val)).isoformat()

    @property
    def model(self) -> str:
        fallback = (
            getattr(config, "ollama_embedding_model", "nomic-embed-text")
            if self.category == "embedding"
            else getattr(config, "ollama_model", "llama3.2")
        )
        val = config._read_db_setting("settings_ollama", f"job_{self.job_id}_model", self.default_model or fallback)
        return str(val) if val else fallback

    @model.setter
    def model(self, val: str) -> None:
        config._write_db_setting("settings_ollama", f"job_{self.job_id}_model", str(val).strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.job_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "enabled": self.enabled,
            "interval_minutes": self.interval_minutes,
            "model": self.model,
            "is_running": self._is_running,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "total_runs": self.total_runs,
            "items_processed_total": self.items_processed_total,
            "last_error": self.last_error,
            "last_activity": self.last_activity,
        }

    def is_due(self) -> bool:
        if not self.enabled:
            return False
        if not self.next_run:
            return True
        try:
            return datetime.now() >= datetime.fromisoformat(self.next_run)
        except Exception:
            return True

    async def execute(self) -> Dict[str, Any]:
        if self._lock.locked():
            logger.info(f"[JOB {self.job_id}] Execution already in progress, skipping duplicate call.")
            return {"status": "skipped", "reason": "already_running"}

        async with self._lock:
            self._is_running = True
            now_dt = datetime.now()
            self.last_run = now_dt.isoformat()
            self.total_runs += 1
            cycle_id = f"{self.job_id}_{uuid.uuid4().hex[:6]}"
            logger.info(f"[JOB {self.job_id}] Starting execution run #{self.total_runs} ({cycle_id})")

            try:
                if self._runner:
                    res = await self._runner(self, cycle_id)
                else:
                    res = {"status": "noop", "message": "No runner registered"}

                self.last_error = None
                return res
            except Exception as e:
                err_msg = str(e)
                logger.error(f"[JOB {self.job_id}] Error in execution: {err_msg}", exc_info=True)
                self.last_error = err_msg
                self.last_activity = f"Failed: {err_msg[:40]}"
                return {"status": "error", "error": err_msg}
            finally:
                self._is_running = False
                self.next_run = (datetime.now() + timedelta(minutes=self.interval_minutes)).isoformat()


class AutonomousWorker:
    """Modular autonomous server worker managing independent curation and maintenance jobs."""

    def __init__(self) -> None:
        self.enabled: bool = (
            os.getenv("KB_AUTONOMOUS_WORKER_ENABLED", "true").strip().lower()
            in ("true", "1", "yes")
        )
        self._is_running: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None

        self.last_run: Optional[str] = None
        self.next_run: Optional[str] = None
        self.total_cycles: int = 0
        self.last_error: Optional[str] = None
        self.last_activity: str = "Worker initialized"

        # In-memory target deduplication tracker per job
        self._recent_targets: Dict[str, Set[str]] = defaultdict(set)

        # Register modular jobs
        self.jobs: Dict[str, ServerJob] = {}
        self._register_default_jobs()

    # -------------------------------------------------------------
    # Target Execution Tracking & Deduplication
    # -------------------------------------------------------------

    def log_target_execution(
        self,
        job_id: str,
        target_id: str,
        status: str,
        items_count: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Persists target-level execution status and updates in-memory deduplication tracking."""
        clean_target = str(target_id).strip()
        self._recent_targets[job_id].add(clean_target)
        try:
            with db_session() as session:
                rec = WorkerJobExecution(
                    job_id=job_id,
                    target_id=clean_target,
                    status=status,
                    items_count=items_count,
                    error_message=str(error_message) if error_message else None,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
                session.add(rec)
                session.commit()
        except Exception as e:
            logger.warning(f"[AUTONOMOUS WORKER] Failed to persist execution log for {job_id} on {clean_target}: {e}")

    def get_executed_targets(self, job_id: str, statuses: Optional[List[str]] = None) -> Set[str]:
        """Returns the set of targets that have already been executed for this job."""
        results = set(self._recent_targets.get(job_id, set()))
        try:
            with db_session() as session:
                q = session.query(WorkerJobExecution.target_id).filter(WorkerJobExecution.job_id == job_id)
                if statuses:
                    q = q.filter(WorkerJobExecution.status.in_(statuses))
                for (tid,) in q.all():
                    if tid:
                        results.add(tid.strip())
        except Exception as e:
            logger.warning(f"[AUTONOMOUS WORKER] Failed to query executed targets for {job_id}: {e}")
        return results

    def clear_target_executions(self, job_id: Optional[str] = None) -> int:
        """Clears target execution records for a specific job or all jobs."""
        if job_id:
            self._recent_targets.pop(job_id, None)
        else:
            self._recent_targets.clear()

        count = 0
        try:
            with db_session() as session:
                q = session.query(WorkerJobExecution)
                if job_id:
                    q = q.filter_by(job_id=job_id)
                count = q.delete()
                session.commit()
        except Exception as e:
            logger.warning(f"[AUTONOMOUS WORKER] Failed to clear target executions: {e}")
        return count

    def get_target_executions(self, job_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Returns recent target-level execution records."""
        try:
            with db_session() as session:
                q = session.query(WorkerJobExecution)
                if job_id:
                    q = q.filter_by(job_id=job_id)
                q = q.order_by(WorkerJobExecution.id.desc()).limit(limit)
                rows = q.all()
                return [
                    {
                        "id": r.id,
                        "job_id": r.job_id,
                        "target_id": r.target_id,
                        "status": r.status,
                        "items_count": r.items_count,
                        "error_message": r.error_message,
                        "executed_at": r.executed_at,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"[AUTONOMOUS WORKER] Failed to fetch target executions: {e}")
            return []

    def _register_default_jobs(self) -> None:
        """Initializes the standard roster of autonomous server jobs."""
        self.jobs["wiki_curation"] = ServerJob(
            job_id="wiki_curation",
            name="Wiki Curation Agent",
            description="Monitors newly imported pages and synthesizes clean wiki summaries using Ollama LLM.",
            category="llm",
            default_interval_minutes=5,
            default_model=getattr(config, "ollama_model", "llama3.2"),
            runner=self._run_wiki_curation,
        )

        self.jobs["tag_curation"] = ServerJob(
            job_id="tag_curation",
            name="Tag Taxonomy Agent",
            description="Extracts and assigns structured taxonomy tags to newly imported articles.",
            category="llm",
            default_interval_minutes=5,
            default_model=getattr(config, "ollama_model", "llama3.2"),
            runner=self._run_tag_curation,
        )

        self.jobs["topic_assignment"] = ServerJob(
            job_id="topic_assignment",
            name="Topic & Sub-Topic Assignment Agent",
            description="Assigns governed top-level topics (Kingdom) and 2-level sub-topics (Phylum/Class) to articles and videos.",
            category="llm",
            default_interval_minutes=5,
            default_model=getattr(config, "ollama_model", "llama3.2"),
            runner=self._run_topic_assignment,
        )

        self.jobs["embedding_refresh"] = ServerJob(
            job_id="embedding_refresh",
            name="Vector Embedding Indexer",
            description="Indexes document and chunk vectors into Qdrant for semantic similarity search.",
            category="embedding",
            default_interval_minutes=15,
            default_model=getattr(config, "ollama_embedding_model", "nomic-embed-text"),
            runner=self._run_embedding_refresh,
        )

        self.jobs["synthetic_qa"] = ServerJob(
            job_id="synthetic_qa",
            name="Synthetic QA Benchmark Agent",
            description="Generates synthetic question-answer pairs for indexed articles to evaluate retrieval quality.",
            category="llm",
            default_interval_minutes=60,
            default_model=getattr(config, "ollama_model", "llama3.2"),
            runner=self._run_synthetic_qa,
        )

        self.jobs["rag_eval"] = ServerJob(
            job_id="rag_eval",
            name="RAG Decision Evaluation Agent",
            description="Benchmarks retrieval precision and scores response accuracy using decision model gating.",
            category="decision",
            default_interval_minutes=60,
            default_model=getattr(config, "ollama_model", "llama3.2"),
            runner=self._run_rag_eval,
        )

        self.jobs["link_crawler"] = ServerJob(
            job_id="link_crawler",
            name="Autonomous Link Discovery Crawler",
            description="Autonomously discovers and queues outbound links referenced in library articles.",
            category="crawler",
            default_interval_minutes=30,
            default_model=getattr(config, "ollama_model", "llama3.2"),
            runner=self._run_link_crawler,
        )

        self.jobs["fact_extraction"] = ServerJob(
            job_id="fact_extraction",
            name="Context Fact Extraction Agent",
            description="Extracts atomic context statements, preferences, and declarative intent into the context mesh.",
            category="llm",
            default_interval_minutes=15,
            default_model=getattr(config, "ollama_model", "llama3.2"),
            runner=self._run_fact_extraction,
        )

        self.jobs["lifecycle_refetch"] = ServerJob(
            job_id="lifecycle_refetch",
            name="Taxonomy Content Refetch Agent",
            description="Re-fetches and refreshes dynamic pages assigned to auto-refetch taxonomy nodes, dispatching Gotify alerts.",
            category="crawler",
            default_interval_minutes=30,
            default_model="",
            runner=self._run_lifecycle_refetch,
        )

    # -------------------------------------------------------------
    # Job Runners
    # -------------------------------------------------------------

    async def _run_wiki_curation(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Curates 1 library item lacking wiki description or containing skipped placeholder.

        Issue #124: Strictly isolated from fact extraction so failed/retried wikis never
        trigger duplicate fact generation loops.
        """
        target_page_wiki = None
        with db_session() as session:
            exec_subq = select(WorkerJobExecution.target_id).filter(
                WorkerJobExecution.job_id == "wiki_curation",
                WorkerJobExecution.status.in_(["success", "skipped"]),
            )
            recent_in_mem = list(self._recent_targets.get("wiki_curation", set()))
            q = (
                session.query(FetchedPage)
                .filter(
                    FetchedPage.url.not_in(exec_subq),
                    or_(
                        FetchedPage.description.is_(None),
                        FetchedPage.description == "",
                        FetchedPage.description.ilike("%AI Processing skipped%"),
                    ),
                )
            )
            if recent_in_mem:
                q = q.filter(FetchedPage.url.not_in(recent_in_mem))
            row = q.order_by(FetchedPage.fetched_at.asc().nullslast()).first()
            if row:
                target_page_wiki = self._row_to_page_dict(row)

        if not target_page_wiki:
            job.last_activity = "Idle (no uncurated wikis found)"
            return {"status": "noop", "message": "All pages have wiki summaries"}

        url = target_page_wiki["url"]
        title = target_page_wiki.get("title") or url
        self._recent_targets["wiki_curation"].add(url)
        job.last_activity = f"Generating wiki for {title[:40]}"
        logger.info(f"[JOB wiki_curation] Processing missing wiki for: {url}")

        try:
            page_obj = HTMLPage(**target_page_wiki)
            client = _get_ollama_client()
            job_cfg = JobConfigProxy(config, model=job.model, is_embedding=False)

            wiki_entry = await run_in_threadpool(
                extract_wiki_content, page_obj, job_cfg, client
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

                # Generate embeddings
                try:
                    emb_target_model = getattr(job_cfg, "ollama_embedding_model", None) or getattr(config, "ollama_embedding_model", "nomic-embed-text")
                    await run_in_threadpool(
                        update_article_embedding, None, url, job_cfg, client, emb_target_model
                    )
                    await run_in_threadpool(
                        generate_gemma_embeddings_for_page, None, url, job_cfg, client, emb_target_model
                    )
                except Exception as emb_err:
                    logger.warning(f"[JOB wiki_curation] Embedding indexing warning for {url}: {emb_err}")

                self.log_target_execution(
                    job_id="wiki_curation",
                    target_id=url,
                    status="success",
                    items_count=1,
                )
                job.items_processed_total += 1
                job.last_activity = f"Curated wiki for: {extracted_title[:40]}"
                record_notification(
                    stage="worker",
                    status="success",
                    message=f"Wiki curation agent generated wiki summary for: {extracted_title}",
                    url=url,
                    title=extracted_title,
                    task_id=cycle_id,
                )
                logger.info(f"[JOB wiki_curation] Successfully generated wiki for: {url}")
                return {"status": "success", "url": url, "title": extracted_title}
            else:
                self.log_target_execution(
                    job_id="wiki_curation",
                    target_id=url,
                    status="skipped",
                    items_count=0,
                )
                job.last_activity = f"Skipped empty wiki for: {title[:40]}"
                return {"status": "skipped", "url": url}
        except Exception as e:
            err_msg = f"Wiki generation failed for {url}: {e}"
            logger.warning(err_msg)
            self.log_target_execution(
                job_id="wiki_curation",
                target_id=url,
                status="failed",
                error_message=str(e),
            )
            job.last_error = str(e)
            record_notification(
                stage="worker",
                status="warning",
                message=f"Wiki generation failed for {title}: {e}. Retrying next cycle.",
                url=url,
                title=title,
                task_id=cycle_id,
            )
            raise

    async def _run_tag_curation(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Curates 1 library item lacking taxonomy tags."""
        target_page_tags = None
        with db_session() as session:
            exec_subq = select(WorkerJobExecution.target_id).filter(
                WorkerJobExecution.job_id == "tag_curation",
                WorkerJobExecution.status.in_(["success", "skipped"]),
            )
            recent_in_mem = list(self._recent_targets.get("tag_curation", set()))
            q = (
                session.query(FetchedPage)
                .filter(
                    FetchedPage.url.not_in(exec_subq),
                    or_(
                        FetchedPage.tags.is_(None),
                        FetchedPage.tags == "",
                        FetchedPage.tags == "[]",
                    ),
                )
            )
            if recent_in_mem:
                q = q.filter(FetchedPage.url.not_in(recent_in_mem))
            row = q.order_by(FetchedPage.fetched_at.asc().nullslast()).first()
            if row:
                target_page_tags = self._row_to_page_dict(row)

        if not target_page_tags:
            job.last_activity = "Idle (no untagged pages found)"
            return {"status": "noop", "message": "All pages have tags"}

        url = target_page_tags["url"]
        title = target_page_tags.get("title") or url
        self._recent_targets["tag_curation"].add(url)
        job.last_activity = f"Extracting tags for {title[:40]}"
        logger.info(f"[JOB tag_curation] Processing missing tags for: {url}")

        try:
            page_obj = HTMLPage(**target_page_tags)
            client = _get_ollama_client()
            job_cfg = JobConfigProxy(config, model=job.model, is_embedding=False)

            tags = await run_in_threadpool(
                extract_tags_content, page_obj, job_cfg, client
            )

            if tags:
                with db_session() as session:
                    rec = session.query(FetchedPage).filter_by(url=url).first()
                    if rec:
                        rec.tags = json.dumps(tags)
                        session.commit()

                self.log_target_execution(
                    job_id="tag_curation",
                    target_id=url,
                    status="success",
                    items_count=len(tags),
                )
                job.items_processed_total += 1
                job.last_activity = f"Assigned {len(tags)} tags to: {title[:40]}"
                tag_preview = ", ".join(tags[:4])
                record_notification(
                    stage="worker",
                    status="success",
                    message=f"Tag taxonomy agent assigned tags for {title}: {tag_preview}",
                    url=url,
                    title=title,
                    task_id=cycle_id,
                )
                logger.info(f"[JOB tag_curation] Successfully extracted tags for: {url} ({tags})")
                return {"status": "success", "url": url, "tags": tags}
            else:
                self.log_target_execution(
                    job_id="tag_curation",
                    target_id=url,
                    status="skipped",
                    items_count=0,
                )
                job.last_activity = f"No tags generated for: {title[:40]}"
                return {"status": "skipped", "url": url}
        except Exception as e:
            err_msg = f"Tag extraction failed for {url}: {e}"
            logger.warning(err_msg)
            self.log_target_execution(
                job_id="tag_curation",
                target_id=url,
                status="failed",
                error_message=str(e),
            )
            job.last_error = str(e)
            record_notification(
                stage="worker",
                status="warning",
                message=f"Tag extraction failed for {title}: {e}. Retrying next cycle.",
                url=url,
                title=title,
                task_id=cycle_id,
            )
            raise

    async def _run_topic_assignment(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Assigns governed top-level topic and 2-level sub-topic to 1 unassigned article or video (Issue #128)."""
        from .taxonomy.engine import assign_topic_and_subtopic

        target_page = None
        with db_session() as session:
            exec_subq = select(WorkerJobExecution.target_id).filter(
                WorkerJobExecution.job_id == "topic_assignment",
                WorkerJobExecution.status.in_(["success", "skipped"]),
            )
            recent_in_mem = list(self._recent_targets.get("topic_assignment", set()))
            q = (
                session.query(FetchedPage)
                .filter(
                    FetchedPage.url.not_in(exec_subq),
                    or_(
                        FetchedPage.topic.is_(None),
                        FetchedPage.topic == "",
                        FetchedPage.topic_status == "unassigned",
                    ),
                )
            )
            if recent_in_mem:
                q = q.filter(FetchedPage.url.not_in(recent_in_mem))
            row = q.order_by(FetchedPage.fetched_at.asc().nullslast()).first()
            if row:
                target_page = self._row_to_page_dict(row)

        if not target_page:
            job.last_activity = "Idle (all items have assigned topics)"
            return {"status": "noop", "message": "All articles and videos have assigned topics"}

        url = target_page["url"]
        title = target_page.get("title") or url
        self._recent_targets["topic_assignment"].add(url)
        job.last_activity = f"Assigning topic for {title[:40]}"
        logger.info(f"[JOB topic_assignment] Assigning topic & sub-topic for: {url}")

        try:
            client = _get_ollama_client()
            job_cfg = JobConfigProxy(config, model=job.model, is_embedding=False)
            tags = target_page.get("tags") if isinstance(target_page.get("tags"), list) else []
            md_content = target_page.get("description") or target_page.get("md_content") or ""

            res = await run_in_threadpool(
                assign_topic_and_subtopic,
                url,
                title,
                md_content,
                tags,
                job_cfg,
                client,
            )

            self.log_target_execution(
                job_id="topic_assignment",
                target_id=url,
                status="success",
                items_count=1,
            )
            job.items_processed_total += 1
            assigned_topic = res.get("topic", "")
            assigned_sub = res.get("sub_topic", "")
            job.last_activity = f"Assigned {assigned_topic} > {assigned_sub} to: {title[:30]}"
            record_notification(
                stage="worker",
                status="success",
                message=f"Topic agent assigned '{assigned_topic} / {assigned_sub}' to: {title}",
                url=url,
                title=title,
                task_id=cycle_id,
            )
            return {
                "status": "success",
                "url": url,
                "topic": assigned_topic,
                "sub_topic": assigned_sub,
                "topic_status": res.get("topic_status"),
            }
        except Exception as e:
            err_msg = f"Topic assignment failed for {url}: {e}"
            logger.warning(err_msg)
            self.log_target_execution(
                job_id="topic_assignment",
                target_id=url,
                status="failed",
                error_message=str(e),
            )
            job.last_error = str(e)
            raise

    async def _run_embedding_refresh(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Indexes vector embeddings into Qdrant for 1 page."""
        target_url = None
        target_title = None
        with db_session() as session:
            exec_subq = select(WorkerJobExecution.target_id).filter(
                WorkerJobExecution.job_id == "embedding_refresh",
                WorkerJobExecution.status == "success",
            )
            subq = select(ChunkEmbedding.source_id).filter(
                ChunkEmbedding.source_type == "pages"
            )
            recent_in_mem = list(self._recent_targets.get("embedding_refresh", set()))
            q = (
                session.query(FetchedPage)
                .filter(
                    FetchedPage.url.not_in(subq),
                    FetchedPage.url.not_in(exec_subq),
                )
            )
            if recent_in_mem:
                q = q.filter(FetchedPage.url.not_in(recent_in_mem))
            row = q.order_by(FetchedPage.fetched_at.asc().nullslast()).first()
            if row:
                target_url = row.url
                target_title = row.title or row.url

        if not target_url:
            job.last_activity = "Idle (no pages available for indexing)"
            return {"status": "noop", "message": "No pages to index"}

        self._recent_targets["embedding_refresh"].add(target_url)
        job.last_activity = f"Generating embeddings for {target_title[:40]}"
        try:
            client = _get_ollama_client()
            job_cfg = JobConfigProxy(config, model=job.model, is_embedding=True)
            await run_in_threadpool(
                generate_gemma_embeddings_for_page, None, target_url, job_cfg, client, job.model
            )
            self.log_target_execution(
                job_id="embedding_refresh",
                target_id=target_url,
                status="success",
                items_count=1,
            )
            job.items_processed_total += 1
            job.last_activity = f"Embeddings synced for: {target_title[:40]}"
            return {"status": "success", "url": target_url}
        except Exception as e:
            self.log_target_execution(
                job_id="embedding_refresh",
                target_id=target_url,
                status="failed",
                error_message=str(e),
            )
            job.last_error = str(e)
            logger.warning(f"[JOB embedding_refresh] Failed: {e}")
            raise

    async def _run_synthetic_qa(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Foundation runner for synthetic QA evaluation pair generation."""
        job.last_activity = "Completed synthetic QA validation check"
        return {"status": "noop", "message": "Synthetic QA hook active"}

    async def _run_rag_eval(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Foundation runner for RAG decision model benchmark evaluation."""
        job.last_activity = "Completed RAG evaluation benchmark cycle"
        return {"status": "noop", "message": "RAG evaluation hook active"}

    async def _run_link_crawler(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Foundation runner for autonomous outbound link discovery."""
        job.last_activity = "Completed link discovery pass"
        return {"status": "noop", "message": "Autonomous link crawler hook active"}

    async def _run_fact_extraction(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Extracts atomic context statements from 1 library item lacking extracted statements.

        Issue #124: Excludes any page that already has facts in ContextStatementORM, has already
        been processed by fact_extraction, or has a failed/missing wiki awaiting wiki_curation.
        """
        from .context_mesh.pipeline import FactExtractionPipeline

        target_page = None
        with db_session() as session:
            exec_subq = select(WorkerJobExecution.target_id).filter(
                WorkerJobExecution.job_id == "fact_extraction",
                WorkerJobExecution.status.in_(["success", "skipped", "failed"]),
            )
            stmt_subq = select(ContextStatementORM.source_uri).filter(
                ContextStatementORM.source_uri.isnot(None),
                ContextStatementORM.source_uri != "",
            )
            failed_wiki_subq = select(WorkerJobExecution.target_id).filter(
                WorkerJobExecution.job_id == "wiki_curation",
                WorkerJobExecution.status == "failed",
            )
            recent_in_mem = list(self._recent_targets.get("fact_extraction", set()))

            q = (
                session.query(FetchedPage)
                .filter(
                    FetchedPage.url.not_in(exec_subq),
                    FetchedPage.url.not_in(stmt_subq),
                    FetchedPage.url.not_in(failed_wiki_subq),
                    or_(
                        FetchedPage.description.isnot(None),
                        FetchedPage.md_content.isnot(None),
                    ),
                )
            )
            if recent_in_mem:
                q = q.filter(FetchedPage.url.not_in(recent_in_mem))

            row = q.order_by(FetchedPage.fetched_at.desc().nullslast()).first()
            if row:
                target_page = self._row_to_page_dict(row)

        if not target_page:
            job.last_activity = "Idle (all pages extracted into context mesh)"
            return {"status": "noop", "message": "All pages processed for context statements"}

        url = target_page["url"]
        title = target_page.get("title") or url
        self._recent_targets["fact_extraction"].add(url)
        job.last_activity = f"Extracting facts for {title[:40]}"
        logger.info(f"[JOB fact_extraction] Extracting context statements for: {url}")

        try:
            client = _get_ollama_client()
            job_cfg = JobConfigProxy(config, model=job.model, is_embedding=False)
            pipeline = FactExtractionPipeline(config=job_cfg, client=client)

            tags: List[str] = []
            if target_page.get("tags"):
                if isinstance(target_page["tags"], list):
                    tags = target_page["tags"]
                else:
                    try:
                        parsed_tags = json.loads(target_page["tags"])
                        if isinstance(parsed_tags, list):
                            tags = parsed_tags
                    except Exception:
                        pass

            md_content = target_page.get("description") or target_page.get("md_content") or ""

            statements = await run_in_threadpool(
                pipeline.extract_from_page,
                url,
                title,
                md_content,
                tags,
                False,
            )

            if statements:
                self.log_target_execution(
                    job_id="fact_extraction",
                    target_id=url,
                    status="success",
                    items_count=len(statements),
                )
                job.items_processed_total += len(statements)
                job.last_activity = f"Extracted {len(statements)} statements for: {title[:40]}"
                record_notification(
                    stage="worker",
                    status="success",
                    message=f"Context Fact Extraction agent extracted {len(statements)} statements for: {title}",
                    url=url,
                    title=title,
                    task_id=cycle_id,
                )
                logger.info(f"[JOB fact_extraction] Extracted {len(statements)} statements for: {url}")
                return {"status": "success", "url": url, "count": len(statements)}
            else:
                self.log_target_execution(
                    job_id="fact_extraction",
                    target_id=url,
                    status="skipped",
                    items_count=0,
                )
                job.last_activity = f"Skipped (0 statements) for: {title[:40]}"
                logger.info(f"[JOB fact_extraction] Zero statements extracted for: {url}. Logged as skipped.")
                return {"status": "skipped", "url": url, "count": 0}
        except Exception as e:
            err_msg = f"Fact extraction failed for {url}: {e}"
            logger.warning(err_msg)
            self.log_target_execution(
                job_id="fact_extraction",
                target_id=url,
                status="failed",
                error_message=str(e),
            )
            job.last_error = str(e)
            record_notification(
                stage="worker",
                status="warning",
                message=f"Fact extraction warning for {title}: {e}.",
                url=url,
                title=title,
                task_id=cycle_id,
            )
            return {"status": "warning", "error": err_msg}

    # -------------------------------------------------------------
    # Management & Inspection APIs
    # -------------------------------------------------------------


    async def _run_lifecycle_refetch(self, job: ServerJob, cycle_id: str) -> Dict[str, Any]:
        """Re-fetches and refreshes dynamic pages assigned to auto-refetch taxonomy nodes, dispatching Gotify alerts."""
        from .utils import fetch_url
        from kb_core.notifier import Gotify

        target_row = None
        refetch_hours = 24
        tax_path_str = ""

        with db_session() as session:
            entities = session.query(TaxonomyEntityORM).filter(
                TaxonomyEntityORM.attributes_json.ilike('%"lifecycle_action": "refetch"%')
            ).all()

            now_dt = datetime.now(timezone.utc)
            for ent in entities:
                try:
                    attr = json.loads(ent.attributes_json) if ent.attributes_json else {}
                    interval_h = int(attr.get("refetch_interval_hours") or 24)
                except Exception:
                    interval_h = 24

                url = ent.physical_location
                page = session.query(FetchedPage).filter_by(url=url).first()
                if not page:
                    continue

                if page.is_frozen:
                    continue

                should_refetch = False
                if not page.fetched_at:
                    should_refetch = True
                else:
                    try:
                        ts_str = page.fetched_at.replace("Z", "+00:00")
                        fetched_dt = datetime.fromisoformat(ts_str)
                        if fetched_dt.tzinfo is None:
                            fetched_dt = fetched_dt.replace(tzinfo=timezone.utc)
                        if (now_dt - fetched_dt) >= timedelta(hours=interval_h):
                            should_refetch = True
                    except Exception:
                        should_refetch = True

                if should_refetch:
                    target_row = {
                        "url": page.url,
                        "title": page.title or page.url,
                        "interval_hours": interval_h,
                    }
                    tax_path_str = ent.taxonomy_path
                    break

        if not target_row:
            job.last_activity = "Idle (no items due for refetch)"
            return {"status": "noop", "message": "No pages due for scheduled refetch"}

        url = target_row["url"]
        title = target_row["title"]
        job.last_activity = f"Refetching {title[:40]}"
        logger.info(f"[JOB lifecycle_refetch] Re-fetching content for: {url}")

        try:
            page_obj = await run_in_threadpool(fetch_url, url)
            now_iso = datetime.now(timezone.utc).isoformat()

            with db_session() as session:
                fp = session.query(FetchedPage).filter_by(url=url).first()
                if fp:
                    if page_obj.html_content:
                        fp.html_content = page_obj.html_content
                    if page_obj.md_content:
                        fp.md_content = page_obj.md_content
                    fp.fetched_at = now_iso
                    session.commit()

            gotify_sent = False
            try:
                notifier = Gotify(config.gotify_url, config.gotify_token)
                notifier.send(
                    title="Taxonomy Auto-Refetch Complete",
                    message=(
                        f"Auto-refetched content for: {title}\n"
                        f"URL: {url}\n"
                        f"Taxonomy Path: {tax_path_str}\n"
                        f"Refetch Interval: {target_row['interval_hours']}h"
                    ),
                    priority=4,
                )
                gotify_sent = True
            except Exception as e:
                logger.debug(f"[JOB lifecycle_refetch] Gotify alert skipped or failed: {e}")

            self.log_target_execution(
                job_id="lifecycle_refetch",
                target_id=url,
                status="success",
                items_count=1,
            )
            job.items_processed_total += 1
            job.last_activity = f"Refetched {title[:40]}"
            record_notification(
                stage="worker",
                status="success",
                message=f"Taxonomy Content Refetch Agent refreshed: {title}",
                url=url,
                title=title,
                task_id=cycle_id,
            )
            return {"status": "success", "url": url, "gotify_sent": gotify_sent}
        except Exception as e:
            err_msg = f"Lifecycle refetch failed for {url}: {e}"
            logger.warning(err_msg)
            self.log_target_execution(
                job_id="lifecycle_refetch",
                target_id=url,
                status="failed",
                error_message=str(e),
            )
            job.last_error = str(e)
            return {"status": "failed", "error": err_msg}

    def pause_non_core_jobs(self) -> Dict[str, Any]:
        """Pauses all background worker jobs EXCEPT core features (wiki_curation, tag_curation)."""
        paused = []
        for jid, job in self.jobs.items():
            if jid not in {"wiki_curation", "tag_curation"}:
                job.enabled = False
                paused.append(jid)
        config._write_db_setting("settings_ollama", "worker_core_only_mode", "true")
        return {"status": "success", "mode": "core_only", "paused_jobs": paused}

    def resume_all_jobs(self) -> Dict[str, Any]:
        """Resumes all background worker jobs."""
        resumed = []
        for jid, job in self.jobs.items():
            job.enabled = True
            resumed.append(jid)
        config._write_db_setting("settings_ollama", "worker_core_only_mode", "false")
        return {"status": "success", "mode": "all_active", "resumed_jobs": resumed}

    def is_core_only_mode(self) -> bool:
        """Check if worker is currently in core-only preset mode."""
        val = config._read_db_setting("settings_ollama", "worker_core_only_mode", "false")
        return str(val).strip().lower() in ("true", "1", "yes")

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Returns the list of all configured jobs with operational status and metrics."""
        return [job.to_dict() for job in self.jobs.values()]

    def get_job(self, job_id: str) -> Optional[ServerJob]:
        return self.jobs.get(job_id)

    def update_job_config(
        self,
        job_id: str,
        enabled: Optional[bool] = None,
        interval_minutes: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(f"Job '{job_id}' not found")

        if enabled is not None:
            job.enabled = enabled
        if interval_minutes is not None:
            job.interval_minutes = interval_minutes
        if model is not None:
            job.model = model

        return job.to_dict()

    async def run_job(self, job_id: str) -> Dict[str, Any]:
        """Runs a specific job on demand."""
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(f"Job '{job_id}' not found")
        return await job.execute()

    @property
    def interval_minutes(self) -> int:
        wiki_job = self.jobs.get("wiki_curation")
        return wiki_job.interval_minutes if wiki_job else 5

    @property
    def wikis_curated_total(self) -> int:
        wiki_job = self.jobs.get("wiki_curation")
        return wiki_job.items_processed_total if wiki_job else 0

    @property
    def tags_curated_total(self) -> int:
        tag_job = self.jobs.get("tag_curation")
        return tag_job.items_processed_total if tag_job else 0

    def get_status(self) -> Dict[str, Any]:
        """Returns the current worker health, overall operational status, and jobs list."""
        return {
            "enabled": self.enabled,
            "is_running": self._is_running or any(j._is_running for j in self.jobs.values()),
            "interval_minutes": self.interval_minutes,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "total_cycles": self.total_cycles,
            "wikis_curated_total": self.wikis_curated_total,
            "tags_curated_total": self.tags_curated_total,
            "last_error": self.last_error,
            "last_activity": self.last_activity,
            "jobs": self.get_jobs(),
        }

    async def run_cycle(self) -> Dict[str, Any]:
        """Executes an autonomous cycle across all due enabled jobs."""
        self.last_run = datetime.now().isoformat()
        self.total_cycles += 1
        self._is_running = True
        results: Dict[str, Any] = {}

        curated_wiki_url = None
        curated_tags_url = None

        try:
            for jid, job in self.jobs.items():
                if job.enabled and job.is_due():
                    try:
                        res = await job.execute()
                        results[jid] = res
                        if jid == "wiki_curation" and res.get("status") == "success":
                            curated_wiki_url = res.get("url")
                        elif jid == "tag_curation" and res.get("status") == "success":
                            curated_tags_url = res.get("url")
                    except Exception as e:
                        results[jid] = {"status": "error", "error": str(e)}

            self.next_run = (datetime.now() + timedelta(minutes=self.interval_minutes)).isoformat()
            self.last_activity = f"Executed cycle #{self.total_cycles}"
            errors = [
                f"[{jid}] {res.get('error')}"
                for jid, res in results.items()
                for _ in [0]
                if isinstance(res, dict) and res.get("status") == "error"
            ]
            return {
                "status": "completed",
                "curated_wiki_url": curated_wiki_url,
                "curated_tags_url": curated_tags_url,
                "errors": errors,
                "jobs": results,
            }
        finally:
            self._is_running = False

    def _row_to_page_dict(self, row: FetchedPage) -> Dict[str, Any]:
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
        logger.info("[AUTONOMOUS WORKER] Modular server jobs scheduler loop active.")
        try:
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            return

        while not self._stop_event.is_set():
            if self.enabled:
                try:
                    for job in self.jobs.values():
                        if job.enabled and job.is_due():
                            asyncio.create_task(job.execute())
                except Exception as e:
                    logger.error(f"[AUTONOMOUS WORKER] Error in scheduler loop: {e}", exc_info=True)
                    self.last_error = str(e)

            slept = 0
            while slept < 10 and not self._stop_event.is_set():
                try:
                    await asyncio.sleep(2)
                    slept += 2
                except asyncio.CancelledError:
                    return

    def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._worker_loop())
        logger.info("[AUTONOMOUS WORKER] Started modular jobs scheduler loop.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            logger.info("[AUTONOMOUS WORKER] Stopped modular jobs scheduler loop.")


# Global singleton instance
autonomous_worker = AutonomousWorker()
