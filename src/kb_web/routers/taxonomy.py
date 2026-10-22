"""
FastAPI Router for Autonomous Category Taxonomy & Ontology Browser.

Provides:
- GET /taxonomy: Modern interactive taxonomy tree & category wiki browser
- GET /api/taxonomy/tree: Hierarchical JSON category tree data
- GET /api/taxonomy/categories/{id}: Detail of specific category, items, and living wiki doc
- POST /api/taxonomy/crawl: Triggers background classification of unclassified items
- POST /api/taxonomy/classify-item: Classifies a single item on-demand
- GET /api/taxonomy/status: Operational status of the taxonomy state machine
"""

import json
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
from ..taxonomy.engine import TaxonomyEngine
from ..context_mesh.models import EvalStatus, StatementType, TaxonomicLayer
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


# --- UI Pages ---

@router.get("/taxonomy", response_class=HTMLResponse)
def view_taxonomy_browser(request: Request):
    """Renders the interactive Autonomous Category Taxonomy tree, 7-tier biological ontology, and living facts viewer."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        tree = get_category_tree_data(session)
        total_cats = session.query(TaxonomyCategory).count()
        total_items = session.query(TaxonomyItem).count()
        is_paused = is_partitioning_paused()

    engine = TaxonomyEngine()
    tree_7tier_data = engine.get_7tier_tree()

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
                    # Clean existing taxonomy item for this note if re-classifying
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


@router.get("/api/context-mesh/statements")
def list_context_statements_endpoint(
    url: Optional[str] = Query(None, description="Filter by source URL"),
    statement_type: Optional[str] = Query(None, description="Filter by statement type"),
    layer_level: Optional[str] = Query(None, description="Filter by taxonomic layer"),
    eval_status: Optional[str] = Query(None, description="Filter by evaluation status"),
    prefix: Optional[str] = Query(None, description="Filter by canonical path prefix"),
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
    )

    return {
        "status": "success",
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "statements": [s.model_dump() for s in stmts],
    }


@router.post("/api/context-mesh/statements/{statement_id}/evaluate")
def evaluate_statement_endpoint(
    statement_id: str,
    payload: EvaluateStatementRequest,
) -> Dict[str, Any]:
    """Updates evaluation status, score rank, and reviewer feedback for a context statement."""
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
        return {
            "status": "success",
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
        md_text = page.md_content or page.description or ""
        stmts = pipeline.extract_from_page(
            url=page.url,
            title=page.title or page.url,
            md_content=md_text,
            tags=tags,
        )

        return {
            "status": "success",
            "url": page.url,
            "extracted_count": len(stmts),
            "statements": [s.model_dump() for s in stmts],
        }
