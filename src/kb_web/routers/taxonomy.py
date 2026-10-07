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

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from sqlalchemy import or_

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token
from ..models_orm import TaxonomyCategory, TaxonomyItem, Note
from ..taxonomy_state_machine import (
    get_category_tree_data,
    classify_single_item,
    crawl_and_classify_all,
    is_partitioning_paused,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Taxonomy"])


class ClassifyItemRequest(BaseModel):
    item_type: str = Field(..., description="Item type: 'article', 'note', 'video', or 'workspace'")
    item_id: str = Field(..., description="ID or URL of the target item")


class ClassifyNotesRequest(BaseModel):
    vault: Optional[str] = Field(None, description="Optional vault name filter")
    force_reclassify: bool = Field(False, description="Whether to re-classify already classified notes")
    limit: int = Field(100, ge=1, le=500, description="Max notes to classify in this batch")


# --- UI Pages ---

@router.get("/taxonomy", response_class=HTMLResponse)
def view_taxonomy_browser(request: Request):
    """Renders the interactive Autonomous Category Taxonomy tree and living wiki viewer."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        tree = get_category_tree_data(session)
        total_cats = session.query(TaxonomyCategory).count()
        total_items = session.query(TaxonomyItem).count()
        is_paused = is_partitioning_paused()

        template = _jinja_env.get_template("taxonomy.j2.html")
        content = template.render(
            request=request,
            is_admin=is_admin,
            categories_tree=tree,
            total_categories=total_cats,
            total_items=total_items,
            is_partitioning_paused=is_paused,
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

        if not payload.force_reclassify:
            classified_item_ids = {r[0] for r in session.query(TaxonomyItem.item_id).filter_by(item_type="note").all()}
            all_matching = query.all()
            target_notes = [
                n for n in all_matching
                if f"note_{n.id}" not in classified_item_ids and str(n.id) not in classified_item_ids and (n.url or "") not in classified_item_ids
            ]
        else:
            target_notes = query.limit(payload.limit).all()

        target_ids = [n.id for n in target_notes[:payload.limit]]

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
