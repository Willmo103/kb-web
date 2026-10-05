"""
FastAPI Router for Agentic RAG Reports in kb-web.

Provides:
- GET /reports/rag: Modern interactive research studio web UI
- POST /api/reports/rag/generate: Runs multi-sub-agent retrieval + tev1 decision scoring + synthesis
- GET /api/reports/rag: Lists saved reports
- GET /api/reports/rag/{id}: Retrieves specific report details
- POST /api/reports/rag/{id}/save-to-notes: Converts report to Monaco KB Note
- DELETE /api/reports/rag/{id}: Deletes report
"""

from datetime import datetime
import json
import logging
import re
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..base import db_session, config, _jinja_env, verify_auth, COOKIE_NAME, verify_session_token
from ..models_orm import RagReport, Note, SettingExternal, SettingOllama
from ..rag_agent import (
    run_agentic_rag_pipeline,
    get_rag_pipeline_config,
    save_rag_pipeline_config,
    DEFAULT_RAG_CONFIG,
)
from ..utils import _get_ollama_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["RAG Reports"])


class RagGenerateRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Research query or task")
    purpose: Optional[str] = Field("", description="Optional research goal or focus")
    synthesis_model: Optional[str] = Field(None, description="LLM synthesis model override")
    decision_model: Optional[str] = Field(None, description="Decision model override")
    tev1_model: Optional[str] = Field(None, description="Legacy alias for decision model")
    pipeline_config: Optional[Dict[str, Any]] = Field(None, description="Per-run pipeline configuration override")


# ==============================================================================
# UI ROUTE
# ==============================================================================

@router.get("/reports/rag", response_class=HTMLResponse)
def view_rag_report_generator(
    request: Request,
    q: Optional[str] = Query(None, description="Pre-filled search query"),
    report_id: Optional[int] = Query(None, description="Load existing report ID"),
):
    """Renders the interactive Agentic RAG Report Generator workspace."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        rag_config = get_rag_pipeline_config(session)
        # Load recent reports for sidebar
        recent_reports = (
            session.query(RagReport)
            .order_by(RagReport.id.desc())
            .limit(15)
            .all()
        )
        reports_list = [
            {
                "id": r.id,
                "title": r.title,
                "query": r.query,
                "created_at": r.created_at,
            }
            for r in recent_reports
        ]

        active_report = None
        if report_id:
            active_obj = session.query(RagReport).filter_by(id=report_id).first()
            if active_obj:
                sources = []
                evals = []
                try:
                    sources = json.loads(active_obj.sources_json or "[]")
                except Exception:
                    pass
                try:
                    evals = json.loads(active_obj.tev1_evaluations_json or "[]")
                except Exception:
                    pass

                active_report = {
                    "id": active_obj.id,
                    "title": active_obj.title,
                    "query": active_obj.query,
                    "report_markdown": active_obj.report_markdown,
                    "sources": sources,
                    "decision_evaluations": evals,
                    "tev1_evaluations": evals,
                    "created_at": active_obj.created_at,
                }

        # Available Ollama models
        client = _get_ollama_client()
        available_models = ["gemma4:latest", "llama3.2:latest", "qwen2.5-coder:latest"]
        try:
            m_resp = client.list()
            installed = [m.get("name") or m.get("model") for m in m_resp.get("models", [])]
            for im in installed:
                if im and im not in available_models and not im.startswith("embedding"):
                    available_models.append(im)
        except Exception:
            pass

        setting = session.query(SettingOllama).filter_by(key="ollama_model").first()
        default_model = setting.value if setting else getattr(config, "ollama_model", "gemma4:latest")

    template = _jinja_env.get_template("rag_report.j2.html")
    return HTMLResponse(
        content=template.render(
            initial_query=q or "",
            active_report=active_report,
            recent_reports=reports_list,
            available_models=available_models,
            default_model=default_model,
            rag_config=rag_config,
            is_admin=is_admin,
        )
    )


# ==============================================================================
# REST API ENDPOINTS
# ==============================================================================

@router.get("/api/reports/rag/config")
def get_rag_config_api(
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Retrieves saved RAG pipeline configuration."""
    with db_session() as session:
        return get_rag_pipeline_config(session)


@router.post("/api/reports/rag/config")
def save_rag_config_api(
    payload: Dict[str, Any],
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Persists customized RAG pipeline configuration."""
    with db_session() as session:
        saved = save_rag_pipeline_config(session, payload)
        return {"status": "saved", "config": saved}


@router.post("/api/reports/rag/config/reset")
def reset_rag_config_api(
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Resets RAG pipeline configuration to defaults."""
    with db_session() as session:
        saved = save_rag_pipeline_config(session, DEFAULT_RAG_CONFIG)
        return {"status": "reset", "config": saved}


@router.post("/api/reports/rag/generate")
def generate_rag_report_api(
    payload: RagGenerateRequest,
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Executes the full agentic multi-sub-agent RAG workflow with decision gating."""
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    client = _get_ollama_client()

    with db_session() as session:
        # Determine synthesis model
        synthesis_model = payload.synthesis_model
        if not synthesis_model:
            setting = session.query(SettingOllama).filter_by(key="ollama_model").first()
            synthesis_model = setting.value if setting else getattr(config, "ollama_model", "gemma4:latest")

        # Determine active embedding model
        emb_setting = session.query(SettingExternal).filter_by(key="active_embedding_model").first()
        active_embedding_model = emb_setting.value if emb_setting else "embeddinggemma"

        # Execute multi-agent RAG pipeline
        result = run_agentic_rag_pipeline(
            session=session,
            query=query,
            purpose=payload.purpose or "",
            client=client,
            synthesis_model=synthesis_model,
            active_embedding_model=active_embedding_model,
            decision_model=payload.decision_model or payload.tev1_model,
            pipeline_config=payload.pipeline_config,
        )

        # Persist report in database
        now_str = datetime.now().isoformat()
        db_report = RagReport(
            query=query,
            title=result["title"],
            report_markdown=result["report_markdown"],
            sources_json=json.dumps(result["sources"]),
            tev1_evaluations_json=json.dumps(result.get("decision_evaluations", result.get("tev1_evaluations", []))),
            model_synthesis=synthesis_model,
            created_at=now_str,
        )
        session.add(db_report)
        session.commit()
        session.refresh(db_report)

        result["id"] = db_report.id
        result["created_at"] = db_report.created_at

    return result


@router.get("/api/reports/rag")
def list_rag_reports_api(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Returns paginated list of generated RAG reports."""
    with db_session() as session:
        query_obj = session.query(RagReport).order_by(RagReport.id.desc())
        total = query_obj.count()
        offset = (page - 1) * limit
        rows = query_obj.offset(offset).limit(limit).all()

        reports = []
        for r in rows:
            source_count = 0
            try:
                source_count = len(json.loads(r.sources_json or "[]"))
            except Exception:
                pass
            reports.append({
                "id": r.id,
                "title": r.title,
                "query": r.query,
                "source_count": source_count,
                "model_synthesis": r.model_synthesis,
                "created_at": r.created_at,
            })

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "reports": reports,
        }


@router.get("/api/reports/rag/{report_id}")
def get_rag_report_api(
    report_id: int,
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Retrieves full details, evidence citations, and tev1 decision data for a report."""
    with db_session() as session:
        report = session.query(RagReport).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="RAG Report not found")

        sources = []
        evals = []
        try:
            sources = json.loads(report.sources_json or "[]")
        except Exception:
            pass
        try:
            evals = json.loads(report.tev1_evaluations_json or "[]")
        except Exception:
            pass

        return {
            "id": report.id,
            "title": report.title,
            "query": report.query,
            "report_markdown": report.report_markdown,
            "sources": sources,
            "decision_evaluations": evals,
            "tev1_evaluations": evals,
            "model_synthesis": report.model_synthesis,
            "created_at": report.created_at,
        }


@router.post("/api/reports/rag/{report_id}/save-to-notes")
def save_rag_report_to_notes_api(
    report_id: int,
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Exports a generated RAG report directly into a Knowledge Base note (Note)."""
    with db_session() as session:
        report = session.query(RagReport).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="RAG Report not found")

        clean_slug = re.sub(r"[^a-zA-Z0-9_\-]+", "-", report.title.lower()).strip("-")
        note_url = f"note://rag-reports/{clean_slug}-{report.id}"

        existing = session.query(Note).filter_by(url=note_url).first()
        now_str = datetime.now().isoformat()

        if existing:
            existing.title = report.title
            existing.content = report.report_markdown
            existing.updated_at = now_str
            note_obj = existing
        else:
            note_obj = Note(
                url=note_url,
                title=report.title,
                content=report.report_markdown,
                syntax="markdown",
                folder_path="RAG Reports",
                vault_name="Personal",
                tags=json.dumps(["rag-report", "ai-synthesis"]),
                wiki_summary=f"Synthesized RAG report for: {report.query[:100]}",
                created_at=now_str,
                updated_at=now_str,
            )
            session.add(note_obj)

        session.commit()
        session.refresh(note_obj)

        return {
            "status": "success",
            "message": "Report successfully saved to Knowledge Base Notes",
            "note_url": note_obj.url,
            "note_id": note_obj.id,
            "edit_url": f"/notes/edit?url={quote_plus(note_obj.url)}",
        }


@router.delete("/api/reports/rag/{report_id}")
def delete_rag_report_api(
    report_id: int,
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Deletes a saved RAG report."""
    with db_session() as session:
        report = session.query(RagReport).filter_by(id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="RAG Report not found")
        session.delete(report)
        session.commit()
        return {"status": "deleted", "report_id": report_id}
