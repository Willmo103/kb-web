"""
FastAPI Router for Autonomous Category Taxonomy, 7-Tier Ontology Browser,
Topic/Sub-Topic Governance (#128), and Taxonomical Fact Management CRUDS (#122, #125).

Provides:
- GET /taxonomy: Interactive taxonomy tree, 7-tier ontology, and Topic Governance UI
- GET /facts: Dedicated Taxonomical Fact Management CRUDS & Search portal (#122)
- GET /api/taxonomy/tree: Hierarchical JSON category tree data
- GET /api/taxonomy/categories/{id}: Detail of specific category, items, and living wiki doc
- POST /api/taxonomy/crawl: Triggers background classification of unclassified items
- POST /api/taxonomy/classify-item: Classifies a single item on-demand
- GET /api/taxonomy/status: Operational status of the taxonomy state machine
- GET /api/taxonomy/topics: Lists governed topics & sub-topics with counts (#128)
- POST /api/taxonomy/topics/approve: Approves a topic or sub-topic (#128)
- POST /api/taxonomy/topics/deny: Denies/blocklists a topic or sub-topic and re-queues items (#128)
- POST /api/taxonomy/topics/assign-now: Runs AI topic & sub-topic assignment on-demand (#128)
- CRUDS & Search API under /api/context-mesh/statements & /api/context-mesh/search (#122, #125)
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from sqlalchemy import or_

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token
from ..models_orm import TaxonomyCategory, TaxonomyItem, Note, FetchedPage
from ..taxonomy_state_machine import (
    get_category_tree_data,
    classify_single_item,
    crawl_and_classify_all,
    is_partitioning_paused,
)
from ..taxonomy.engine import (
    TaxonomyEngine,
    get_topic_governance_summary,
    assign_topic_and_subtopic,
    approve_topic_or_subtopic,
    deny_topic_or_subtopic,
)
from ..context_mesh.models import ContextStatement, EvalStatus, StatementType, TaxonomicLayer
from ..context_mesh.store import ContextStore
from ..context_mesh.pipeline import FactExtractionPipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Taxonomy"])


class ClassifyItemRequest(BaseModel):
    item_type: str = Field(..., description="Item type: 'article', 'note', 'video', or 'workspace'")
    item_id: str = Field(..., description="ID or URL of the target item")


class ClassifyNotesRequest(BaseModel):
    vault: Optional[str] = Field(None, description="Optional vault name filter")
    force_reclassify: bool = Field(False, description="Whether to re-classify already classified notes")
    limit: Optional[int] = Field(None, ge=1, le=50000, description="Max notes to classify in this batch (defaults to config.taxonomy_batch_limit)")


class EvaluateStatementRequest(BaseModel):
    eval_status: Optional[str] = Field(None, description="Review status: 'approved', 'flagged', 'rejected', or 'unreviewed'")
    score_rank: Optional[float] = Field(None, ge=0.0, le=5.0, description="Evaluation score from 0.0 to 5.0")
    eval_feedback: Optional[str] = Field(None, description="Optional reviewer feedback notes")


class ExtractNowRequest(BaseModel):
    url: str = Field(..., description="Target page URL to extract facts and context statements from")
    force: bool = Field(True, description="Whether to force extraction even if statements already exist for this URL")


class CreateStatementRequest(BaseModel):
    statement: str = Field(..., min_length=3, description="Atomic declarative fact statement")
    statement_type: str = Field("fact", description="Statement type: fact, intent_mapping, negative_invariant, affordance, habit, preference")
    layer_level: str = Field("species", description="Taxonomic layer: kingdom, phylum, class, order, family, genus, species")
    canonical_path: str = Field("Reference/General/Overview/kb_web/general/manual_fact/entry", description="7-tier canonical path")
    source_uri: str = Field("manual://facts", description="Source URI or URL")
    source_title: str = Field("Manual Fact Entry", description="Source document title")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    score_rank: float = Field(4.0, ge=0.0, le=5.0)
    eval_status: str = Field("approved", description="Initial review status")
    tags: List[str] = Field(default_factory=list)


class UpdateStatementRequest(BaseModel):
    statement: Optional[str] = Field(None, description="Updated statement text")
    statement_type: Optional[str] = Field(None, description="Updated statement type")
    layer_level: Optional[str] = Field(None, description="Updated taxonomic layer")
    canonical_path: Optional[str] = Field(None, description="Updated 7-tier canonical path")
    source_uri: Optional[str] = Field(None, description="Updated source URI")
    source_title: Optional[str] = Field(None, description="Updated source title")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Updated extraction confidence")
    score_rank: Optional[float] = Field(None, ge=0.0, le=5.0)
    eval_status: Optional[str] = Field(None)
    eval_feedback: Optional[str] = Field(None)
    tags: Optional[List[str]] = Field(None)


class BulkDeleteStatementsRequest(BaseModel):
    statement_ids: List[str] = Field(..., description="List of statement IDs to permanently delete")


class TopicGovernanceActionRequest(BaseModel):
    name: str = Field(..., description="Topic or sub-topic name (e.g. 'News' or 'Fishing/Ultralight')")
    level: str = Field("topic", description="'topic' or 'sub_topic'")
    parent_topic: Optional[str] = Field(None, description="Parent top-level topic when level='sub_topic'")


class TopicAssignNowRequest(BaseModel):
    url: Optional[str] = Field(None, description="Specific URL to assign topic & sub-topic for; if omitted, processes a batch of unassigned items")
    limit: int = Field(10, ge=1, le=200, description="Max unassigned items to process when url is omitted")


# --- UI Pages ---

@router.get("/taxonomy", response_class=HTMLResponse)
def view_taxonomy_browser(request: Request):
    """Renders the interactive Autonomous Category Taxonomy tree, 7-tier ontology, Topic Governance, and living facts viewer."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        tree = get_category_tree_data(session)
        total_cats = session.query(TaxonomyCategory).count()
        total_items = session.query(TaxonomyItem).count()
        is_paused = is_partitioning_paused()

    engine = TaxonomyEngine()
    tree_7tier_data = engine.get_7tier_tree()
    topic_gov = get_topic_governance_summary(config)

    template = _jinja_env.get_template("taxonomy.j2.html")
    content = template.render(
        request=request,
        is_admin=is_admin,
        categories_tree=tree,
        total_categories=total_cats,
        total_items=total_items,
        is_partitioning_paused=is_paused,
        tree_7tier=tree_7tier_data["tree"],
        total_7tier_entities=tree_7tier_data["total_entities"],
        total_statements=tree_7tier_data["total_statements"],
        topic_governance=topic_gov,
        max_fact_char_count=config.max_fact_char_count,
    )
    return HTMLResponse(content=content)


@router.get("/facts", response_class=HTMLResponse)
def view_facts_management(request: Request):
    """Renders the dedicated Taxonomical Fact Management CRUDS & Search page (Issue #122)."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    store = ContextStore()
    initial_statements = [s.model_dump() for s in store.list_statements(limit=100)]
    total_statements = store.count_statements()
    topic_gov = get_topic_governance_summary(config)

    template = _jinja_env.get_template("facts_management.j2.html")
    content = template.render(
        request=request,
        is_admin=is_admin,
        statements=initial_statements,
        total_statements=total_statements,
        topic_governance=topic_gov,
        allowed_topics=config.get_allowed_topics_list(),
        max_fact_char_count=config.max_fact_char_count,
        fact_similarity_threshold=config.fact_similarity_threshold,
        statement_types=[t.value for t in StatementType],
        taxonomic_layers=[l.value for l in TaxonomicLayer],
    )
    return HTMLResponse(content=content)


# --- REST API Endpoints ---

@router.get("/api/taxonomy/tree")
def get_taxonomy_tree() -> Dict[str, Any]:
    """Returns the full hierarchical category tree with item counts, depths, and container states."""
    with db_session() as session:
        tree = get_category_tree_data(session)
        return {
            "status": "success",
            "total_categories": session.query(TaxonomyCategory).count(),
            "total_items": session.query(TaxonomyItem).count(),
            "is_partitioning_paused": is_partitioning_paused(),
            "tree": tree,
        }


@router.get("/api/taxonomy/categories/{cat_id}")
def get_category_detail(cat_id: int) -> Dict[str, Any]:
    """Retrieves full details of a specific category including its living wiki doc and assigned items."""
    with db_session() as session:
        cat = session.query(TaxonomyCategory).filter_by(id=cat_id).first()
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")

        items = session.query(TaxonomyItem).filter_by(category_id=cat.id).order_by(TaxonomyItem.assigned_at.desc()).all()
        children = session.query(TaxonomyCategory).filter_by(parent_id=cat.id).all()

        return {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "parent_id": cat.parent_id,
            "doc": cat.doc or "",
            "item_count": cat.item_count,
            "depth": cat.depth,
            "is_container": bool(cat.is_container),
            "created_at": cat.created_at,
            "updated_at": cat.updated_at,
            "children": [{"id": c.id, "name": c.name, "item_count": c.item_count, "is_container": bool(c.is_container)} for c in children],
            "items": [
                {
                    "id": it.id,
                    "item_type": it.item_type,
                    "item_id": it.item_id,
                    "item_title": it.item_title,
                    "fit_score": it.fit_score,
                    "assigned_at": it.assigned_at,
                }
                for it in items
            ],
        }


@router.post("/api/taxonomy/crawl")
def trigger_taxonomy_crawler(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=200, description="Max unclassified items to process in this crawl batch"),
) -> Dict[str, Any]:
    """Triggers background crawling and classification of unclassified articles, notes, videos, and workspaces."""
    if is_partitioning_paused():
        return {
            "status": "paused",
            "message": "Taxonomy state machine is currently executing an inner partitioning loop. Please wait.",
        }

    def _run_crawler():
        with db_session() as session:
            crawl_and_classify_all(session=session, limit=limit)

    background_tasks.add_task(_run_crawler)

    return {
        "status": "initiated",
        "message": f"Autonomous taxonomy crawler scheduled for up to {limit} items in background.",
    }


@router.post("/api/taxonomy/classify-item")
def classify_item_endpoint(payload: ClassifyItemRequest) -> Dict[str, Any]:
    """Runs a single item through the decision state machine on-demand."""
    res = classify_single_item(item_type=payload.item_type, item_id=payload.item_id)
    return res


@router.post("/api/taxonomy/classify-notes")
def trigger_classify_notes(
    payload: ClassifyNotesRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Triggers background taxonomy classification specifically for notes (unclassified or force re-classified)."""
    if is_partitioning_paused():
        return {
            "status": "paused",
            "message": "Taxonomy state machine is currently partitioning. Please wait.",
        }

    with db_session() as session:
        query = session.query(Note)
        if payload.vault:
            query = query.filter(Note.vault_name == payload.vault)

        effective_limit = payload.limit or getattr(config, "taxonomy_batch_limit", 500)
        if not payload.force_reclassify:
            classified_item_ids = {r[0] for r in session.query(TaxonomyItem.item_id).filter_by(item_type="note").all()}
            all_matching = query.with_entities(Note.id, Note.url).all()
            target_ids = [
                nid for (nid, nurl) in all_matching
                if f"note_{nid}" not in classified_item_ids and str(nid) not in classified_item_ids and (nurl or "") not in classified_item_ids
            ][:effective_limit]
        else:
            target_ids = [r[0] for r in query.with_entities(Note.id).limit(effective_limit).all()]

    if not target_ids:
        return {
            "status": "up_to_date",
            "message": "No unclassified notes found matching criteria.",
            "count": 0,
        }

    def _run_notes_classification():
        with db_session() as s:
            for note_id in target_ids:
                if payload.force_reclassify:
                    existing = s.query(TaxonomyItem).filter(
                        TaxonomyItem.item_type == "note",
                        or_(
                            TaxonomyItem.item_id == str(note_id),
                            TaxonomyItem.item_id == f"note_{note_id}",
                        )
                    ).all()
                    for ti in existing:
                        if ti.category_id:
                            c = s.query(TaxonomyCategory).filter_by(id=ti.category_id).first()
                            if c and c.item_count and c.item_count > 0:
                                c.item_count -= 1
                        s.delete(ti)
                    s.commit()
                classify_single_item("note", note_id)

    background_tasks.add_task(_run_notes_classification)

    return {
        "status": "scheduled",
        "message": f"Scheduled classification for {len(target_ids)} note(s) in background.",
        "target_count": len(target_ids),
        "target_ids": target_ids,
    }


@router.get("/api/taxonomy/status")
def get_taxonomy_status() -> Dict[str, Any]:
    """Returns the operational status of the taxonomy state machine."""
    with db_session() as session:
        return {
            "is_partitioning_paused": is_partitioning_paused(),
            "total_categories": session.query(TaxonomyCategory).count(),
            "total_items": session.query(TaxonomyItem).count(),
        }


# --- Issue #128: Topic & Sub-Topic Governance & Assignment Endpoints ---

@router.get("/api/taxonomy/topics")
def list_governed_topics_endpoint() -> Dict[str, Any]:
    """Lists allowed, pending, and denied topics and sub-topics with item counts."""
    return get_topic_governance_summary(config)


@router.post("/api/taxonomy/topics/approve")
def approve_topic_endpoint(payload: TopicGovernanceActionRequest) -> Dict[str, Any]:
    """Approves a topic or sub-topic and updates matching articles/videos to 'approved'."""
    try:
        return approve_topic_or_subtopic(
            name=payload.name,
            level=payload.level,
            parent_topic=payload.parent_topic,
            config_obj=config,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/taxonomy/topics/deny")
def deny_topic_endpoint(payload: TopicGovernanceActionRequest) -> Dict[str, Any]:
    """Denies/deletes a topic or sub-topic, blocklists it, clears affected items, and re-queues them for reassignment."""
    try:
        return deny_topic_or_subtopic(
            name=payload.name,
            level=payload.level,
            config_obj=config,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/taxonomy/topics/assign-now")
def assign_topics_now_endpoint(payload: TopicAssignNowRequest) -> Dict[str, Any]:
    """Triggers immediate AI topic & sub-topic assignment for a specific URL or batch of unassigned items."""
    if payload.url:
        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=payload.url).first()
            if not page:
                raise HTTPException(status_code=404, detail=f"Page not found for URL: {payload.url}")
        res = assign_topic_and_subtopic(url=payload.url, config_obj=config)
        return res

    # Batch assign unassigned items
    target_urls: List[str] = []
    with db_session() as session:
        rows = (
            session.query(FetchedPage.url)
            .filter(
                or_(
                    FetchedPage.topic.is_(None),
                    FetchedPage.topic == "",
                    FetchedPage.topic_status == "unassigned",
                )
            )
            .limit(payload.limit)
            .all()
        )
        target_urls = [r[0] for r in rows if r[0]]

    results = []
    for u in target_urls:
        try:
            r = assign_topic_and_subtopic(url=u, config_obj=config)
            results.append(r)
        except Exception as e:
            logger.warning(f"Batch topic assignment failed for {u}: {e}")

    return {
        "status": "success",
        "assigned_count": len(results),
        "results": results,
    }


# --- 7-Tier Biological Taxonomy & Context Mesh API Endpoints ---

@router.post("/api/taxonomy/sync-entities")
def sync_taxonomy_entities(
    limit: int = Query(1000, ge=1, le=50000, description="Max library items to sync"),
) -> Dict[str, Any]:
    """Scans library articles and notes, infers 7-tier taxonomy coordinates, and registers entities."""
    engine = TaxonomyEngine()
    result = engine.sync_entities_from_library(limit=limit)
    return result


@router.get("/api/taxonomy/7tier/tree")
def get_7tier_tree_endpoint() -> Dict[str, Any]:
    """Returns the hierarchical 7-tier biological taxonomy tree with entity and statement counts."""
    engine = TaxonomyEngine()
    return engine.get_7tier_tree()


# --- Issue #122 & #125: Context Mesh Statements CRUDS & Search ---

@router.get("/api/context-mesh/statements")
def list_context_statements_endpoint(
    url: Optional[str] = Query(None, description="Filter by source URL"),
    statement_type: Optional[str] = Query(None, description="Filter by statement type"),
    layer_level: Optional[str] = Query(None, description="Filter by taxonomic layer"),
    eval_status: Optional[str] = Query(None, description="Filter by evaluation status"),
    prefix: Optional[str] = Query(None, description="Filter by canonical path prefix"),
    kingdom: Optional[str] = Query(None, description="Filter by Topic / Kingdom"),
    phylum: Optional[str] = Query(None, description="Filter by Sub-Topic Level 1 / Phylum"),
    class_name: Optional[str] = Query(None, description="Filter by Sub-Topic Level 2 / Class"),
    query: Optional[str] = Query(None, description="Search keyword in statement, title, or path"),
    min_score: Optional[float] = Query(None, ge=0.0, le=5.0, description="Minimum score rank cutoff"),
    limit: int = Query(50, ge=1, le=500, description="Max statements to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> Dict[str, Any]:
    """Queries atomic context statements / facts with multi-criteria filtering."""
    store = ContextStore()

    layer_enum = None
    if layer_level:
        try:
            layer_enum = TaxonomicLayer(layer_level.lower())
        except Exception:
            pass

    type_enum = None
    if statement_type:
        try:
            type_enum = StatementType(statement_type.lower())
        except Exception:
            pass

    status_enum = None
    if eval_status:
        try:
            status_enum = EvalStatus(eval_status.lower())
        except Exception:
            pass

    stmts = store.list_statements(
        layer=layer_enum,
        statement_type=type_enum,
        canonical_prefix=prefix,
        eval_status=status_enum,
        min_score=min_score,
        source_uri=url,
        query=query,
        kingdom=kingdom,
        phylum=phylum,
        class_name=class_name,
        limit=limit,
        offset=offset,
    )
    total_count = store.count_statements(
        layer=layer_enum,
        statement_type=type_enum,
        canonical_prefix=prefix,
        eval_status=status_enum,
        source_uri=url,
        query=query,
        kingdom=kingdom,
        phylum=phylum,
        class_name=class_name,
    )

    return {
        "status": "success",
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "statements": [s.model_dump() for s in stmts],
    }


@router.get("/api/context-mesh/search")
def search_context_statements_endpoint(
    query: Optional[str] = Query(None, description="Search query string"),
    q: Optional[str] = Query(None, description="Search query string alias"),
    mode: str = Query("hybrid", description="Search mode: 'semantic', 'lexical', or 'hybrid'"),
    top_k: int = Query(25, ge=1, le=200, description="Max results to return"),
    statement_type: Optional[str] = Query(None, description="Optional statement type filter"),
    layer_level: Optional[str] = Query(None, description="Optional taxonomic layer filter"),
    prefix: Optional[str] = Query(None, description="Optional canonical path prefix filter"),
) -> Dict[str, Any]:
    """Performs semantic vector similarity search and/or lexical search across documental facts (Issue #122)."""
    search_query = (query or q or "").strip()
    if not search_query:
        raise HTTPException(status_code=400, detail="Query parameter 'query' or 'q' is required.")

    store = ContextStore()
    pipeline = FactExtractionPipeline(store=store, config=config)

    layer_enum = None
    if layer_level:
        try:
            layer_enum = TaxonomicLayer(layer_level.lower())
        except Exception:
            pass

    type_enum = None
    if statement_type:
        try:
            type_enum = StatementType(statement_type.lower())
        except Exception:
            pass

    results_map: Dict[str, Dict[str, Any]] = {}

    # 1. Semantic vector search
    if mode in ("semantic", "hybrid"):
        q_vec = pipeline._embed_text(search_query)
        if q_vec:
            vec_hits = store.search_by_vector(
                query_vector=q_vec,
                top_k=top_k,
                canonical_prefix=prefix,
                layer=layer_enum,
                statement_type=type_enum,
                include_rejected=False,
            )
            for stmt, sim_score in vec_hits:
                d = stmt.model_dump()
                d["search_score"] = round(float(sim_score), 4)
                d["match_type"] = "semantic"
                results_map[stmt.id] = d

    # 2. Lexical search (or fallback if embedding model is offline)
    if mode in ("lexical", "hybrid") or not results_map:
        lex_hits = store.list_statements(
            layer=layer_enum,
            statement_type=type_enum,
            canonical_prefix=prefix,
            query=search_query,
            limit=top_k,
        )
        for stmt in lex_hits:
            if stmt.id in results_map:
                results_map[stmt.id]["match_type"] = "hybrid"
                results_map[stmt.id]["search_score"] = round(
                    min(1.0, results_map[stmt.id]["search_score"] + 0.15), 4
                )
            else:
                d = stmt.model_dump()
                d["search_score"] = round(stmt.score_rank / 5.0, 4)
                d["match_type"] = "lexical"
                results_map[stmt.id] = d

    sorted_results = sorted(
        results_map.values(),
        key=lambda x: (x.get("search_score", 0.0), x.get("score_rank", 0.0)),
        reverse=True,
    )[:top_k]

    return {
        "status": "success",
        "query": query,
        "mode": mode,
        "total": len(sorted_results),
        "statements": sorted_results,
    }


@router.post("/api/context-mesh/statements")
def create_context_statement_endpoint(
    payload: CreateStatementRequest,
) -> Dict[str, Any]:
    """Creates a new atomic fact / context statement (Issue #122 & #127)."""
    store = ContextStore()
    pipeline = FactExtractionPipeline(store=store, config=config)

    # Enforce MAX_FACT_CHAR_COUNT (#127)
    clean_text = pipeline.shorten_fact_statement(payload.statement.strip(), max_chars=config.max_fact_char_count)

    try:
        st_type = StatementType(payload.statement_type.lower().strip())
    except ValueError:
        st_type = StatementType.FACT

    try:
        tx_layer = TaxonomicLayer(payload.layer_level.lower().strip())
    except ValueError:
        tx_layer = TaxonomicLayer.SPECIES

    try:
        ev_status = EvalStatus(payload.eval_status.lower().strip())
    except ValueError:
        ev_status = EvalStatus.APPROVED

    embedding = pipeline._embed_text(clean_text)

    stmt = ContextStatement(
        statement=clean_text,
        statement_type=st_type,
        canonical_path=payload.canonical_path.strip() or "Reference/General/Overview/kb_web/general/manual_fact/entry",
        layer_level=tx_layer,
        source_uri=payload.source_uri.strip() or "manual://facts",
        source_title=payload.source_title.strip() or "Manual Fact Entry",
        confidence=payload.confidence,
        embedding=embedding,
        tags=payload.tags or [],
        score_rank=payload.score_rank,
        eval_status=ev_status,
    )
    store.upsert(stmt)
    return {
        "status": "success",
        "id": stmt.id,
        "statement": stmt.model_dump(),
    }


@router.put("/api/context-mesh/statements/{statement_id}")
def update_context_statement_endpoint(
    statement_id: str,
    payload: UpdateStatementRequest,
) -> Dict[str, Any]:
    """Updates an existing fact / context statement (Issue #122, #125, #127)."""
    store = ContextStore()
    existing = store.get_by_id(statement_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Context statement '{statement_id}' not found.")

    pipeline = FactExtractionPipeline(store=store, config=config)

    if payload.eval_status and payload.eval_status.lower().strip() == EvalStatus.REJECTED.value:
        store.delete_statement(statement_id)
        existing.eval_status = EvalStatus.REJECTED
        return {
            "status": "success",
            "deleted": True,
            "statement": existing.model_dump(),
        }

    if payload.statement is not None and payload.statement.strip():
        new_text = pipeline.shorten_fact_statement(
            payload.statement.strip(),
            max_chars=config.max_fact_char_count,
        )
        if new_text != existing.statement:
            existing.statement = new_text
            new_emb = pipeline._embed_text(new_text)
            if new_emb:
                existing.embedding = new_emb

    if payload.statement_type is not None:
        try:
            existing.statement_type = StatementType(payload.statement_type.lower().strip())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid statement_type: {payload.statement_type}")

    if payload.layer_level is not None:
        try:
            existing.layer_level = TaxonomicLayer(payload.layer_level.lower().strip())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid layer_level: {payload.layer_level}")

    if payload.canonical_path is not None and payload.canonical_path.strip():
        existing.canonical_path = payload.canonical_path.strip()

    if payload.source_uri is not None and payload.source_uri.strip():
        existing.source_uri = payload.source_uri.strip()

    if payload.source_title is not None and payload.source_title.strip():
        existing.source_title = payload.source_title.strip()

    if payload.confidence is not None:
        existing.confidence = max(0.0, min(1.0, float(payload.confidence)))

    if payload.score_rank is not None:
        existing.score_rank = max(0.0, min(5.0, float(payload.score_rank)))

    if payload.eval_status is not None:
        try:
            existing.eval_status = EvalStatus(payload.eval_status.lower().strip())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid eval_status: {payload.eval_status}")

    if payload.eval_feedback is not None:
        existing.eval_feedback = payload.eval_feedback

    if payload.tags is not None:
        existing.tags = payload.tags

    existing.updated_at = datetime.now(timezone.utc).isoformat()
    store.upsert(existing)

    return {
        "status": "success",
        "deleted": False,
        "statement": existing.model_dump(),
    }


@router.delete("/api/context-mesh/statements/{statement_id}")
def delete_context_statement_endpoint(statement_id: str) -> Dict[str, Any]:
    """Permanently deletes a single context statement by ID (Issue #122)."""
    store = ContextStore()
    deleted = store.delete_statement(statement_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Context statement '{statement_id}' not found.")
    return {
        "status": "success",
        "deleted": True,
        "id": statement_id,
    }


@router.post("/api/context-mesh/statements/bulk-delete")
def bulk_delete_context_statements_endpoint(
    payload: BulkDeleteStatementsRequest,
) -> Dict[str, Any]:
    """Permanently deletes multiple context statements by ID (Issue #122)."""
    store = ContextStore()
    deleted_count = store.bulk_delete_statements(payload.statement_ids)
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "statement_ids": payload.statement_ids,
    }


@router.post("/api/context-mesh/statements/{statement_id}/evaluate")
def evaluate_statement_endpoint(
    statement_id: str,
    payload: EvaluateStatementRequest,
) -> Dict[str, Any]:
    """Updates evaluation status, score rank, and reviewer feedback for a context statement.

    Issue #125: Rejected facts are automatically deleted from the database.
    """
    store = ContextStore()
    status_enum = None
    if payload.eval_status:
        try:
            status_enum = EvalStatus(payload.eval_status.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid eval_status: {payload.eval_status}")

    score = payload.score_rank if payload.score_rank is not None else (
        5.0 if status_enum == EvalStatus.APPROVED else (
            1.0 if status_enum == EvalStatus.REJECTED else 2.5
        )
    )

    try:
        updated = store.update_evaluation(
            statement_id=statement_id,
            score=score,
            status=status_enum,
            feedback=payload.eval_feedback,
        )
        is_deleted = updated.eval_status == EvalStatus.REJECTED
        return {
            "status": "success",
            "deleted": is_deleted,
            "statement": updated.model_dump(),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/context-mesh/extract-now")
def extract_facts_now_endpoint(
    payload: ExtractNowRequest,
) -> Dict[str, Any]:
    """Triggers on-demand atomic fact & context statement extraction for a specific page."""
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=payload.url).first()
        if not page:
            raise HTTPException(status_code=404, detail=f"Page not found for URL: {payload.url}")

        tags = []
        if page.tags:
            try:
                parsed = json.loads(page.tags)
                if isinstance(parsed, list):
                    tags = parsed
            except Exception:
                tags = [t.strip() for t in str(page.tags).split(",") if t.strip()]

        pipeline = FactExtractionPipeline(config=config)
        md_text = page.description or page.md_content or ""
        stmts = pipeline.extract_from_page(
            url=page.url,
            title=page.title or page.url,
            md_content=md_text,
            tags=tags,
            force=payload.force,
        )

        return {
            "status": "success",
            "url": page.url,
            "extracted_count": len(stmts),
            "statements": [s.model_dump() for s in stmts],
        }
