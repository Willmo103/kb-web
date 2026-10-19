"""
FastAPI Router for the Model Evaluation Studio (/evals) in kb-web.

Provides:
- GET /evals: Dedicated evaluation studio UI for side-by-side comparative testing
- POST /api/evals/content: Loads article or note content into the studio
- GET /api/evals/datasets: Lists saved evaluation datasets
- POST /api/evals/datasets/preview: Previews query results and validates minimum 20 rows
- POST /api/evals/datasets: Saves a new evaluation dataset (strictly enforced >= 20 rows)
- DELETE /api/evals/datasets/{id}: Deletes an evaluation dataset
- GET /api/evals/datasets/{id}/rows: Fetches full uncompressed rows for dataset iteration
- POST /api/evals/matrix/run: Runs matrix comparison of models × prompts (single input or multi-row dataset)
- POST /api/evals/decision/run: Evaluates decision gating models (d1, tev1) via native systemone
- POST /api/evals/embedding/run: Benchmarks embedding models and cosine retrieval accuracy
"""

from datetime import datetime, timezone
import json
import logging
import math
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
import jinja2
from pydantic import BaseModel, Field
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from ..base import (
    COOKIE_NAME,
    _jinja_env,
    config,
    db_session,
    verify_auth,
    verify_session_token,
    _get_ollama_client,
)
from ..models_orm import EvalDataset, FetchedPage, Note
from .reports import (
    TABLE_METADATA,
    FilterCondition,
    ReportQueryRequest,
    _build_sql_query,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Evaluation Studio"])


# ==============================================================================
# PYDANTIC SCHEMAS
# ==============================================================================

class ContentFetchRequest(BaseModel):
    source_type: str = Field(..., description="'article' or 'note'")
    identifier: str = Field(..., description="URL or Note ID")


class DatasetFilter(BaseModel):
    column: str
    operator: str = "eq"
    value: Any = None


class PreviewDatasetRequest(BaseModel):
    base_table: str = "fetched_pages"
    selected_columns: List[str] = Field(default_factory=list)
    filters: List[DatasetFilter] = Field(default_factory=list)
    joins: List[str] = Field(default_factory=list)


class CreateDatasetRequest(BaseModel):
    name: str = Field(..., min_length=2)
    description: Optional[str] = ""
    base_table: str = "fetched_pages"
    selected_columns: List[str] = Field(default_factory=list)
    filters: List[DatasetFilter] = Field(default_factory=list)
    joins: List[str] = Field(default_factory=list)


class MatrixRunRequest(BaseModel):
    models: List[str] = Field(..., min_length=1, description="List of model names to test")
    prompts: List[Dict[str, str]] = Field(
        ..., min_length=1, description="List of prompt definitions [{'id': str, 'name': str, 'text': str}]"
    )
    dataset_id: Optional[int] = Field(None, description="Optional EvalDataset ID for multi-row execution")
    template: Optional[str] = Field(None, description="Jinja2 template using {{ data.<field> }}")
    input_text: Optional[str] = Field(None, description="Input text or article markdown for single run")
    sample_limit: Optional[int] = Field(5, ge=1, le=50, description="Max rows to process when using dataset")
    temperature: Optional[float] = Field(0.2, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(2048, ge=16, le=262144, description="Max predict tokens / context window limit")


class DecisionRunRequest(BaseModel):
    model: str = Field("d1", description="Decision model name (e.g. d1, tev1)")
    dataset_id: Optional[int] = Field(None, description="Optional EvalDataset ID for multi-row execution")
    state_template: Optional[str] = Field(None, description="Jinja2 template for state context using {{ data.<field> }}")
    state: Optional[Dict[str, Any]] = Field(default_factory=dict, description="State dictionary context for single run")
    questions: Dict[str, Any] = Field(..., description="Questions dictionary definition")
    sample_limit: Optional[int] = Field(5, ge=1, le=50, description="Max rows to process when using dataset")
    context_window: Optional[int] = Field(16384, ge=512, le=262144, description="Decision context window size in tokens")


class EmbeddingRunRequest(BaseModel):
    models: List[str] = Field(..., min_length=1, description="Embedding models to compare")
    query: str = Field(..., min_length=1, description="Search query or test string")
    dataset_id: Optional[int] = Field(None, description="Optional EvalDataset ID to draw candidate rows from")
    candidate_template: Optional[str] = Field(None, description="Jinja2 template for candidate texts using {{ data.<field> }}")
    candidates: Optional[List[str]] = Field(default_factory=list, description="Candidate texts to score")
    sample_limit: Optional[int] = Field(10, ge=1, le=50)
    top_k: Optional[int] = Field(5, ge=1, le=50)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Computes cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def _format_row_context(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Flattens and aliases table-prefixed dictionary keys for intuitive Jinja templating.
    E.g. {'fetched_pages.url': '...'} is accessible as data.url, data.title, data.wiki.
    """
    ctx: Dict[str, Any] = dict(row_dict)
    for k, v in list(row_dict.items()):
        if "." in k:
            short_key = k.split(".", 1)[1]
            if short_key not in ctx:
                ctx[short_key] = v
            if short_key == "md_content":
                if "wiki" not in ctx:
                    ctx["wiki"] = v
                if "content" not in ctx:
                    ctx["content"] = v
    return ctx


def _render_jinja_safely(template_str: Optional[str], data: Dict[str, Any], fallback: str = "") -> str:
    """Safely renders a Jinja2 template with row data context, falling back gracefully on syntax error."""
    if not template_str:
        return fallback
    try:
        t = jinja2.Template(template_str)
        return t.render(data=data)
    except Exception as e:
        logger.warning(f"Jinja template render error: {e}")
        return template_str


def get_model_context_info(model_name: str, client: Any = None) -> Dict[str, Any]:
    """Retrieves runtime context window limits and loaded status for an Ollama model.
    Checks client.ps() first for active loaded models, then falls back to client.show() modelinfo.
    """
    if client is None:
        client = _get_ollama_client(timeout=5.0)

    result = {
        "model": model_name,
        "context_length": 16384,
        "loaded": False,
        "size_vram": 0,
        "source": "default",
    }

    # 1. Try client.ps() for loaded models
    try:
        ps_resp = client.ps()
        models_list = getattr(ps_resp, "models", None)
        if models_list is None and isinstance(ps_resp, dict):
            models_list = ps_resp.get("models", [])

        for m in (models_list or []):
            m_name = getattr(m, "name", None) or getattr(m, "model", None) or (m.get("name") if isinstance(m, dict) else "")
            if m_name == model_name or (m_name and m_name.split(":")[0] == model_name.split(":")[0]):
                ctx = getattr(m, "context_length", None) or getattr(m, "num_ctx", None)
                if ctx is None and isinstance(m, dict):
                    ctx = m.get("context_length") or m.get("num_ctx")
                if ctx and int(ctx) > 0:
                    result["context_length"] = int(ctx)
                    result["loaded"] = True
                    result["size_vram"] = getattr(m, "size_vram", 0) or (m.get("size_vram", 0) if isinstance(m, dict) else 0)
                    result["source"] = "runtime_ps"
                    return result
    except Exception as e:
        logger.debug(f"ps() check failed for {model_name}: {e}")

    # 2. Try client.show() for modelinfo / architecture context
    try:
        show_resp = client.show(model_name)
        info = getattr(show_resp, "modelinfo", None) or getattr(show_resp, "model_info", None)
        if info is None and isinstance(show_resp, dict):
            info = show_resp.get("modelinfo") or show_resp.get("model_info", {})

        if isinstance(info, dict):
            for k, v in info.items():
                if "context_length" in k and isinstance(v, (int, float)) and v > 0:
                    result["context_length"] = int(v)
                    result["source"] = "modelinfo"
                    return result

        params = getattr(show_resp, "parameters", "") or (show_resp.get("parameters", "") if isinstance(show_resp, dict) else "")
        if isinstance(params, str):
            for line in params.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == "num_ctx" and parts[1].isdigit():
                    result["context_length"] = int(parts[1])
                    result["source"] = "parameters"
                    return result
    except Exception as e:
        logger.debug(f"show() check failed for {model_name}: {e}")

    return result


def _fetch_dataset_rows(session: Any, dataset: EvalDataset, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches full uncompressed database rows matching an EvalDataset definition."""
    config_data = dataset.query_config or {}
    if isinstance(config_data, str):
        try:
            config_data = json.loads(config_data)
        except Exception:
            config_data = {}

    raw_filters = config_data.get("filters", [])
    filters = [
        FilterCondition(column=f.get("column", ""), operator=f.get("operator", "eq"), value=f.get("value"))
        for f in raw_filters
        if f.get("column")
    ]
    joins = config_data.get("joins", [])
    
    # Ensure heavy content columns are included for rich Jinja templating if base table is fetched_pages or notes
    raw_cols = dataset.selected_columns or []
    if isinstance(raw_cols, str):
        try:
            raw_cols = json.loads(raw_cols)
        except Exception:
            raw_cols = []
    cols = list(raw_cols)
    if dataset.base_table == "fetched_pages":
        if "fetched_pages.md_content" not in cols:
            cols.append("fetched_pages.md_content")
        if "fetched_pages.title" not in cols:
            cols.append("fetched_pages.title")
        if "fetched_pages.url" not in cols:
            cols.append("fetched_pages.url")
        if "fetched_pages.tags" not in cols:
            cols.append("fetched_pages.tags")
    elif dataset.base_table == "notes":
        if "notes.content" not in cols:
            cols.append("notes.content")
        if "notes.title" not in cols:
            cols.append("notes.title")

    req = ReportQueryRequest(
        base_table=dataset.base_table,
        columns=cols,
        joins=joins,
        filters=filters,
        limit=min(limit, 100),
        offset=0,
        fetch_heavy=True,
    )
    query_sql, query_params = _build_sql_query(req, fetch_heavy=True, is_count=False)
    result = session.execute(text(query_sql), query_params)
    rows = [dict(r._mapping) for r in result.fetchall()]
    return [_format_row_context(r) for r in rows]


def _serialize_systemone_answers(raw_answers: Any) -> Dict[str, Any]:
    """Normalizes structured systemone answers (noul, choice, score) into clean JSON."""
    serialized: Dict[str, Any] = {}
    if not isinstance(raw_answers, dict):
        return {"raw": str(raw_answers)}

    for q_key, ans_obj in raw_answers.items():
        if hasattr(ans_obj, "__dict__"):
            q_dict: Dict[str, Any] = {}
            for attr in ("type", "choice", "noul", "score", "confidence", "probabilities", "legend", "reasoning"):
                val = getattr(ans_obj, attr, None)
                if val is not None:
                    q_dict[attr] = val
            serialized[q_key] = q_dict
        elif isinstance(ans_obj, dict):
            serialized[q_key] = ans_obj
        else:
            serialized[q_key] = str(ans_obj)
    return serialized


# ==============================================================================
# UI ROUTE
# ==============================================================================

@router.get("/evals", response_class=HTMLResponse)
def view_evals_studio(request: Request):
    """Renders the Model Evaluation Studio."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))
    if not is_admin:
        return RedirectResponse(url="/login?next=/evals", status_code=303)

    # 1. Discover available Ollama models
    models: List[str] = []
    try:
        cli = _get_ollama_client(timeout=5.0)
        resp = cli.list()
        raw_list = getattr(resp, "models", None)
        if raw_list is None and isinstance(resp, dict):
            raw_list = resp.get("models", [])
        for m in (raw_list or []):
            name = getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else None) or str(m)
            if name and name not in models:
                models.append(name)
    except Exception as e:
        logger.warning(f"Could not fetch Ollama models list: {e}")

    # Ensure baseline models are present
    baseline_models = [
        config.ollama_model,
        getattr(config, "decision_model", "d1"),
        "d1",
        "tev1",
        config.ollama_embedding_model,
    ]
    for b in baseline_models:
        if b and b not in models:
            models.append(b)

    # 2. Get registered system prompts
    prompts = config.get_all_prompts()

    # 3. Retrieve sample articles, notes, and saved eval datasets
    sample_articles = []
    sample_notes = []
    saved_datasets = []

    with db_session() as session:
        try:
            articles = (
                session.query(FetchedPage)
                .order_by(FetchedPage.fetched_at.desc())
                .limit(20)
                .all()
            )
            for a in articles:
                sample_articles.append({
                    "url": a.url,
                    "title": a.title or a.url,
                    "snippet": (a.md_content or "")[:250],
                    "tags": a.tags or "",
                })
        except Exception as e:
            logger.warning(f"Error loading sample articles: {e}")

        try:
            notes = (
                session.query(Note)
                .order_by(Note.id.desc())
                .limit(10)
                .all()
            )
            for n in notes:
                sample_notes.append({
                    "id": n.id,
                    "title": n.title or f"Note #{n.id}",
                    "snippet": (n.content or "")[:250],
                })
        except Exception as e:
            logger.warning(f"Error loading sample notes: {e}")

        try:
            dsets = (
                session.query(EvalDataset)
                .order_by(EvalDataset.created_at.desc())
                .all()
            )
            for d in dsets:
                cols = d.selected_columns or []
                if isinstance(cols, str):
                    try:
                        cols = json.loads(cols)
                    except Exception:
                        cols = []
                created_str = str(d.created_at or "")[:16]
                saved_datasets.append({
                    "id": d.id,
                    "name": d.name,
                    "description": d.description or "",
                    "base_table": d.base_table,
                    "selected_columns": cols,
                    "row_count": d.row_count,
                    "created_at": created_str,
                })
        except Exception as e:
            logger.warning(f"Error loading eval datasets: {e}")

    models_info = {}
    try:
        cli = _get_ollama_client(timeout=3.0)
        for m in models:
            models_info[m] = get_model_context_info(m, cli)
    except Exception as e:
        logger.debug(f"Failed to prefetch models_info for evals page: {e}")

    template = _jinja_env.get_template("evals.j2.html")
    html_content = template.render(
        is_admin=True,
        models=models,
        models_info=models_info,
        prompts=prompts,
        sample_articles=sample_articles,
        sample_notes=sample_notes,
        saved_datasets=saved_datasets,
        tables_metadata=TABLE_METADATA,
        default_model=config.ollama_model,
        default_decision_model=getattr(config, "decision_model", "d1"),
        default_embedding_model=config.ollama_embedding_model,
        current_user="Admin",
    )
    return HTMLResponse(content=html_content)


# ==============================================================================
# CONTENT & DATASET API ENDPOINTS
# ==============================================================================

@router.post("/api/evals/content")
def fetch_evaluation_content(payload: ContentFetchRequest, request: Request):
    """Fetches full markdown or text content for a given article URL or Note ID."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    with db_session() as session:
        if payload.source_type == "article":
            article = session.query(FetchedPage).filter_by(url=payload.identifier).first()
            if not article:
                raise HTTPException(status_code=404, detail="Article not found")
            return {
                "title": article.title or article.url,
                "url": article.url,
                "content": article.md_content or "",
                "tags": article.tags or "",
            }
        elif payload.source_type == "note":
            try:
                note_id = int(payload.identifier)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid note ID")
            note = session.query(Note).filter_by(id=note_id).first()
            if not note:
                raise HTTPException(status_code=404, detail="Note not found")
            return {
                "title": note.title or f"Note #{note.id}",
                "content": note.content or "",
            }
        else:
            raise HTTPException(status_code=400, detail="Unknown source_type")


@router.get("/api/evals/datasets")
def list_eval_datasets(request: Request):
    """Returns all saved evaluation datasets."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    with db_session() as session:
        datasets = session.query(EvalDataset).order_by(EvalDataset.created_at.desc()).all()
        datasets_out = []
        for d in datasets:
            cols = d.selected_columns or []
            if isinstance(cols, str):
                try:
                    cols = json.loads(cols)
                except Exception:
                    cols = []
            q_cfg = d.query_config or {}
            if isinstance(q_cfg, str):
                try:
                    q_cfg = json.loads(q_cfg)
                except Exception:
                    q_cfg = {}
            datasets_out.append({
                "id": d.id,
                "name": d.name,
                "description": d.description or "",
                "base_table": d.base_table,
                "selected_columns": cols,
                "query_config": q_cfg,
                "row_count": d.row_count,
                "created_at": str(d.created_at) if d.created_at else None,
            })
        return {"datasets": datasets_out}


@router.post("/api/evals/datasets/preview")
def preview_eval_dataset(payload: PreviewDatasetRequest, request: Request):
    """Executes dataset query and returns sample rows + row count, verifying minimum 20 rows."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    filters = [
        FilterCondition(column=f.column, operator=f.operator, value=f.value)
        for f in payload.filters
        if f.column
    ]
    req = ReportQueryRequest(
        base_table=payload.base_table,
        columns=payload.selected_columns or [f"{payload.base_table}.*"],
        joins=payload.joins,
        filters=filters,
        limit=10,
        offset=0,
        fetch_heavy=True,
    )

    with db_session() as session:
        # 1. Total row count check
        count_sql, count_params = _build_sql_query(req, is_count=True)
        try:
            total_count = session.execute(text(count_sql), count_params).scalar() or 0
        except Exception as e:
            logger.error(f"Dataset preview count failed: {e}")
            total_count = 0

        # 2. Fetch sample rows
        sample_rows = []
        try:
            query_sql, query_params = _build_sql_query(req, fetch_heavy=True, is_count=False)
            result = session.execute(text(query_sql), query_params)
            rows = [dict(r._mapping) for r in result.fetchall()]
            sample_rows = [_format_row_context(r) for r in rows]
        except Exception as e:
            logger.error(f"Dataset preview rows failed: {e}")

        return {
            "total_count": total_count,
            "min_required": 20,
            "can_save": total_count >= 20,
            "sample_rows": sample_rows,
            "columns": payload.selected_columns,
        }


@router.post("/api/evals/datasets")
def create_eval_dataset(payload: CreateDatasetRequest, request: Request):
    """Creates a saved evaluation dataset. Strictly enforces minimum 20 matching rows."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    filters = [
        FilterCondition(column=f.column, operator=f.operator, value=f.value)
        for f in payload.filters
        if f.column
    ]
    req = ReportQueryRequest(
        base_table=payload.base_table,
        columns=payload.selected_columns or [f"{payload.base_table}.*"],
        joins=payload.joins,
        filters=filters,
        limit=1,
        offset=0,
    )

    with db_session() as session:
        count_sql, count_params = _build_sql_query(req, is_count=True)
        try:
            total_count = session.execute(text(count_sql), count_params).scalar() or 0
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid dataset query: {e}")

        if total_count < 20:
            raise HTTPException(
                status_code=400,
                detail=f"Evaluation dataset must contain at least 20 rows to be saved. Query returned {total_count} row(s).",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        dataset = EvalDataset(
            name=payload.name.strip(),
            description=payload.description.strip() if payload.description else "",
            base_table=payload.base_table,
            selected_columns=json.dumps(payload.selected_columns),
            query_config=json.dumps({
                "filters": [f.model_dump() for f in payload.filters],
                "joins": payload.joins,
            }),
            row_count=total_count,
            created_at=now_iso,
            updated_at=now_iso,
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)

        return {
            "status": "success",
            "message": f"Saved evaluation dataset '{dataset.name}' with {total_count} rows.",
            "dataset": {
                "id": dataset.id,
                "name": dataset.name,
                "base_table": dataset.base_table,
                "row_count": dataset.row_count,
            },
        }


@router.delete("/api/evals/datasets/{dataset_id}")
def delete_eval_dataset(dataset_id: int, request: Request):
    """Deletes an evaluation dataset."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    with db_session() as session:
        ds = session.query(EvalDataset).filter_by(id=dataset_id).first()
        if not ds:
            raise HTTPException(status_code=404, detail="Dataset not found")
        session.delete(ds)
        session.commit()
        return {"status": "success", "message": f"Deleted dataset {dataset_id}"}


@router.get("/api/evals/datasets/{dataset_id}/rows")
def get_dataset_sample_rows(dataset_id: int, request: Request, limit: int = 10):
    """Returns uncompressed sample rows for a dataset with flattened aliases for Jinja preview."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    with db_session() as session:
        ds = session.query(EvalDataset).filter_by(id=dataset_id).first()
        if not ds:
            raise HTTPException(status_code=404, detail="Dataset not found")
        rows = _fetch_dataset_rows(session, ds, limit=limit)
        return {"dataset_id": ds.id, "name": ds.name, "rows": rows}


@router.get("/api/evals/models/info")
def get_evals_models_info(request: Request) -> Dict[str, Any]:
    """Returns runtime context limits and loaded status for all available models."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    cli = _get_ollama_client(timeout=10.0)
    models_data = {}
    try:
        list_resp = cli.list()
        raw_list = getattr(list_resp, "models", None) or (list_resp.get("models", []) if isinstance(list_resp, dict) else [])
        for m in (raw_list or []):
            name = getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else None) or str(m)
            if name:
                models_data[name] = get_model_context_info(name, cli)
    except Exception as e:
        logger.warning(f"Failed to query models info: {e}")

    return {"status": "success", "models": models_data}


@router.post("/api/evals/matrix/stream")
async def run_matrix_eval_stream(payload: MatrixRunRequest, request: Request):
    """Executes evaluation matrix with live Server-Sent Events (SSE) streaming,
    buffering thinking and response tokens and emitting real-time token/card updates
    to completely prevent Cloudflare 524 timeouts.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    if not payload.models:
        raise HTTPException(status_code=400, detail="At least one model must be specified")
    if not payload.prompts:
        raise HTTPException(status_code=400, detail="At least one prompt must be specified")

    # Fetch rows if dataset mode
    rows_to_process = []
    is_dataset = False
    if payload.dataset_id is not None:
        is_dataset = True
        with db_session() as session:
            dataset = session.query(EvalDataset).filter_by(id=payload.dataset_id).first()
            if not dataset:
                raise HTTPException(status_code=404, detail="Specified dataset not found")
            limit = payload.sample_limit or 5
            raw_rows = _fetch_dataset_rows(session, dataset, limit=limit)

        if not raw_rows:
            raise HTTPException(status_code=400, detail="Dataset returned zero rows")

        for idx, row_data in enumerate(raw_rows):
            rendered_input = _render_jinja_safely(payload.template or payload.input_text, row_data, fallback="")
            if not rendered_input.strip():
                continue
            summary = row_data.get("title") or row_data.get("url") or f"Row #{idx + 1}"
            rows_to_process.append({"row_idx": idx + 1, "input": rendered_input, "summary": summary})
    else:
        input_text = (payload.input_text or "").strip()
        if not input_text:
            raise HTTPException(status_code=400, detail="Input text or dataset_id must be provided")
        rows_to_process.append({"row_idx": None, "input": input_text, "summary": None})

    total_runs = len(rows_to_process) * len(payload.models) * len(payload.prompts)

    async def event_generator():
        client = _get_ollama_client(timeout=1200.0)
        # 1. Immediately emit handshake so Cloudflare sees HTTP 200 and initial bytes < 100ms
        yield f"event: start\ndata: {json.dumps({'total_runs': total_runs, 'is_dataset': is_dataset})}\n\n"

        completed_count = 0
        run_counter = 0

        for row_info in rows_to_process:
            row_idx = row_info["row_idx"]
            rendered_input = row_info["input"]
            row_summary = row_info["summary"]

            for model_name in payload.models:
                model_ctx = get_model_context_info(model_name, client).get("context_length", 16384)
                eff_num_ctx = min(payload.max_tokens, model_ctx) if payload.max_tokens else model_ctx

                for prompt_def in payload.prompts:
                    run_counter += 1
                    run_id = f"run_{run_counter}"
                    prompt_id = prompt_def.get("id", "prompt")
                    prompt_name = prompt_def.get("name", prompt_id)
                    prompt_text = prompt_def.get("text", "")

                    yield f"event: run_start\ndata: {json.dumps({'run_id': run_id, 'run_idx': run_counter, 'total_runs': total_runs, 'model': model_name, 'prompt_id': prompt_id, 'prompt_name': prompt_name, 'row_idx': row_idx, 'row_summary': row_summary})}\n\n"

                    messages = [
                        {"role": "system", "content": prompt_text},
                        {"role": "user", "content": rendered_input},
                    ]
                    options = {
                        "temperature": payload.temperature,
                        "num_predict": payload.max_tokens,
                        "num_ctx": max(4096, eff_num_ctx),
                    }

                    start_t = time.time()
                    accumulated_content = []
                    accumulated_thinking = []
                    eval_count = None
                    eval_duration = None

                    try:
                        def _get_stream():
                            return client.chat(model=model_name, messages=messages, options=options, stream=True)

                        stream = await run_in_threadpool(_get_stream)

                        for chunk in stream:
                            msg = getattr(chunk, "message", None) or (chunk.get("message") if isinstance(chunk, dict) else None)
                            delta_content = ""
                            delta_thinking = ""
                            if msg:
                                delta_content = getattr(msg, "content", "") or (msg.get("content", "") if isinstance(msg, dict) else "")
                                delta_thinking = getattr(msg, "thinking", "") or (msg.get("thinking", "") if isinstance(msg, dict) else "")

                            if delta_content:
                                accumulated_content.append(delta_content)
                            if delta_thinking:
                                accumulated_thinking.append(delta_thinking)

                            if delta_content or delta_thinking:
                                yield f"event: token\ndata: {json.dumps({'run_id': run_id, 'delta': delta_content, 'thinking': delta_thinking})}\n\n"

                            if getattr(chunk, "done", False) or (isinstance(chunk, dict) and chunk.get("done")):
                                eval_count = getattr(chunk, "eval_count", None) or (chunk.get("eval_count") if isinstance(chunk, dict) else None)
                                eval_duration = getattr(chunk, "eval_duration", None) or (chunk.get("eval_duration") if isinstance(chunk, dict) else None)

                        duration = time.time() - start_t
                        tokens_per_sec = None
                        if eval_count and eval_duration and eval_duration > 0:
                            tokens_per_sec = round(eval_count / (eval_duration / 1e9), 1)

                        completed_count += 1
                        result_item = {
                            "run_id": run_id,
                            "run_idx": run_counter,
                            "row_idx": row_idx,
                            "row_summary": row_summary,
                            "model": model_name,
                            "prompt_id": prompt_id,
                            "prompt_name": prompt_name,
                            "latency_ms": round(duration * 1000, 1),
                            "response": "".join(accumulated_content),
                            "thinking": "".join(accumulated_thinking),
                            "eval_count": eval_count,
                            "tokens_per_sec": tokens_per_sec,
                            "status": "success",
                        }
                        yield f"event: item\ndata: {json.dumps(result_item)}\n\n"

                    except Exception as e:
                        duration = time.time() - start_t
                        logger.error(f"Matrix stream error for {model_name}: {e}")
                        completed_count += 1
                        result_item = {
                            "run_id": run_id,
                            "run_idx": run_counter,
                            "row_idx": row_idx,
                            "row_summary": row_summary,
                            "model": model_name,
                            "prompt_id": prompt_id,
                            "prompt_name": prompt_name,
                            "latency_ms": round(duration * 1000, 1),
                            "response": f"ERROR: {str(e)}",
                            "thinking": "".join(accumulated_thinking),
                            "eval_count": None,
                            "tokens_per_sec": None,
                            "status": "error",
                        }
                        yield f"event: item\ndata: {json.dumps(result_item)}\n\n"

        yield f"event: done\ndata: {json.dumps({'total_runs': total_runs, 'completed': completed_count, 'status': 'completed'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==============================================================================
# MATRIX EVALUATION ENDPOINT
# ==============================================================================

@router.post("/api/evals/matrix/run")
def run_matrix_eval(payload: MatrixRunRequest, request: Request):
    """Runs a side-by-side evaluation matrix across selected models and prompts.
    Supports either single manual input or multi-row dataset iteration using Jinja2 templates.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    if not payload.models:
        raise HTTPException(status_code=400, detail="At least one model must be specified")
    if not payload.prompts:
        raise HTTPException(status_code=400, detail="At least one prompt must be specified")

    client = _get_ollama_client(timeout=180.0)
    results = []

    # Case A: Dataset iteration mode
    if payload.dataset_id:
        with db_session() as session:
            dataset = session.query(EvalDataset).filter_by(id=payload.dataset_id).first()
            if not dataset:
                raise HTTPException(status_code=404, detail="Specified dataset not found")
            limit = payload.sample_limit or 5
            rows = _fetch_dataset_rows(session, dataset, limit=limit)

        if not rows:
            raise HTTPException(status_code=400, detail="Dataset returned zero rows")

        for row_idx, row_data in enumerate(rows):
            rendered_input = _render_jinja_safely(payload.template or payload.input_text, row_data, fallback="")
            if not rendered_input.strip():
                continue

            row_summary = row_data.get("title") or row_data.get("url") or f"Row #{row_idx + 1}"

            for model_name in payload.models:
                for prompt_def in payload.prompts:
                    prompt_id = prompt_def.get("id", "prompt")
                    prompt_name = prompt_def.get("name", prompt_id)
                    prompt_text = prompt_def.get("text", "")

                    start_t = time.time()
                    try:
                        messages = [
                            {"role": "system", "content": prompt_text},
                            {"role": "user", "content": rendered_input},
                        ]
                        model_ctx = get_model_context_info(model_name, client).get("context_length", 16384)
                        eff_num_ctx = min(payload.max_tokens, model_ctx) if payload.max_tokens else model_ctx
                        options = {
                            "temperature": payload.temperature,
                            "num_predict": payload.max_tokens,
                            "num_ctx": max(4096, eff_num_ctx),
                        }
                        resp = client.chat(model=model_name, messages=messages, options=options)
                        duration = time.time() - start_t

                        response_content = ""
                        if hasattr(resp, "message") and hasattr(resp.message, "content"):
                            response_content = resp.message.content
                        elif isinstance(resp, dict):
                            msg = resp.get("message", {})
                            response_content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                        else:
                            response_content = str(resp)

                        eval_count = getattr(resp, "eval_count", None) or (
                            resp.get("eval_count") if isinstance(resp, dict) else None
                        )
                        eval_duration = getattr(resp, "eval_duration", None) or (
                            resp.get("eval_duration") if isinstance(resp, dict) else None
                        )
                        tokens_per_sec = None
                        if eval_count and eval_duration and eval_duration > 0:
                            tokens_per_sec = round(eval_count / (eval_duration / 1e9), 1)

                        results.append({
                            "row_idx": row_idx + 1,
                            "row_summary": row_summary,
                            "model": model_name,
                            "prompt_id": prompt_id,
                            "prompt_name": prompt_name,
                            "latency_ms": round(duration * 1000, 1),
                            "response": response_content,
                            "eval_count": eval_count,
                            "tokens_per_sec": tokens_per_sec,
                            "status": "success",
                        })
                    except Exception as e:
                        duration = time.time() - start_t
                        logger.error(f"Matrix eval failed for row {row_idx + 1}, model={model_name}: {e}")
                        results.append({
                            "row_idx": row_idx + 1,
                            "row_summary": row_summary,
                            "model": model_name,
                            "prompt_id": prompt_id,
                            "prompt_name": prompt_name,
                            "latency_ms": round(duration * 1000, 1),
                            "response": f"ERROR: {str(e)}",
                            "eval_count": None,
                            "tokens_per_sec": None,
                            "status": "error",
                        })

        return {"results": results, "is_dataset": True, "total_runs": len(results)}

    # Case B: Single manual input mode
    input_text = (payload.input_text or "").strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="Input text or dataset_id must be provided")

    for model_name in payload.models:
        for prompt_def in payload.prompts:
            prompt_id = prompt_def.get("id", "prompt")
            prompt_name = prompt_def.get("name", prompt_id)
            prompt_text = prompt_def.get("text", "")

            start_t = time.time()
            try:
                messages = [
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": input_text},
                ]
                model_ctx = get_model_context_info(model_name, client).get("context_length", 16384)
                eff_num_ctx = min(payload.max_tokens, model_ctx) if payload.max_tokens else model_ctx
                options = {
                    "temperature": payload.temperature,
                    "num_predict": payload.max_tokens,
                    "num_ctx": max(4096, eff_num_ctx),
                }
                resp = client.chat(model=model_name, messages=messages, options=options)
                duration = time.time() - start_t

                response_content = ""
                if hasattr(resp, "message") and hasattr(resp.message, "content"):
                    response_content = resp.message.content
                elif isinstance(resp, dict):
                    msg = resp.get("message", {})
                    response_content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                else:
                    response_content = str(resp)

                eval_count = getattr(resp, "eval_count", None) or (
                    resp.get("eval_count") if isinstance(resp, dict) else None
                )
                eval_duration = getattr(resp, "eval_duration", None) or (
                    resp.get("eval_duration") if isinstance(resp, dict) else None
                )
                tokens_per_sec = None
                if eval_count and eval_duration and eval_duration > 0:
                    tokens_per_sec = round(eval_count / (eval_duration / 1e9), 1)

                results.append({
                    "model": model_name,
                    "prompt_id": prompt_id,
                    "prompt_name": prompt_name,
                    "latency_ms": round(duration * 1000, 1),
                    "response": response_content,
                    "eval_count": eval_count,
                    "tokens_per_sec": tokens_per_sec,
                    "status": "success",
                })
            except Exception as e:
                duration = time.time() - start_t
                logger.error(f"Matrix eval failed for model={model_name}, prompt={prompt_id}: {e}")
                results.append({
                    "model": model_name,
                    "prompt_id": prompt_id,
                    "prompt_name": prompt_name,
                    "latency_ms": round(duration * 1000, 1),
                    "response": f"ERROR: {str(e)}",
                    "eval_count": None,
                    "tokens_per_sec": None,
                    "status": "error",
                })

    return {"results": results, "is_dataset": False, "total_runs": len(results)}


# ==============================================================================
# DECISION GATING ENDPOINT (D1 / TEV1 via SYSTEMONE)
# ==============================================================================

@router.post("/api/evals/decision/run")
def run_decision_eval(payload: DecisionRunRequest, request: Request):
    """Evaluates decision gating models (d1, tev1) via native client.systemone.
    DOES NOT pass chat options or temperature to systemone. Supports single state or dataset iteration.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    client = _get_ollama_client(timeout=90.0)

    # Case A: Dataset iteration mode
    if payload.dataset_id:
        with db_session() as session:
            dataset = session.query(EvalDataset).filter_by(id=payload.dataset_id).first()
            if not dataset:
                raise HTTPException(status_code=404, detail="Specified dataset not found")
            limit = payload.sample_limit or 5
            rows = _fetch_dataset_rows(session, dataset, limit=limit)

        if not rows:
            raise HTTPException(status_code=400, detail="Dataset returned zero rows")

        batch_results = []
        for row_idx, row_data in enumerate(rows):
            rendered_state_str = _render_jinja_safely(payload.state_template, row_data, fallback="")
            state_obj: Any = rendered_state_str
            try:
                state_obj = json.loads(rendered_state_str)
            except Exception:
                state_obj = rendered_state_str

            row_summary = row_data.get("title") or row_data.get("url") or f"Row #{row_idx + 1}"
            start_t = time.time()
            try:
                resp = client.systemone(
                    model=payload.model,
                    state=state_obj,
                    questions=payload.questions,
                )
                duration_ms = round((time.time() - start_t) * 1000, 1)
                raw_answers = getattr(resp, "answers", None)
                if raw_answers is None and isinstance(resp, dict):
                    raw_answers = resp.get("answers", {})

                serialized_answers = _serialize_systemone_answers(raw_answers)
                batch_results.append({
                    "row_idx": row_idx + 1,
                    "row_summary": row_summary,
                    "latency_ms": duration_ms,
                    "answers": serialized_answers,
                    "status": "success",
                })
            except Exception as e:
                duration_ms = round((time.time() - start_t) * 1000, 1)
                logger.warning(f"Decision eval failed for row {row_idx + 1}: {e}")
                batch_results.append({
                    "row_idx": row_idx + 1,
                    "row_summary": row_summary,
                    "latency_ms": duration_ms,
                    "error": str(e),
                    "answers": {},
                    "status": "error",
                })

        return {
            "success": True,
            "is_dataset": True,
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "model": payload.model,
            "results": batch_results,
            "total_runs": len(batch_results),
        }

    # Case B: Single state context mode
    start_t = time.time()
    try:
        resp = client.systemone(
            model=payload.model,
            state=payload.state or {},
            questions=payload.questions,
        )
        duration_ms = round((time.time() - start_t) * 1000, 1)

        raw_answers = getattr(resp, "answers", None)
        if raw_answers is None and isinstance(resp, dict):
            raw_answers = resp.get("answers", {})

        serialized_answers = _serialize_systemone_answers(raw_answers)
        return {
            "success": True,
            "is_dataset": False,
            "model": payload.model,
            "latency_ms": duration_ms,
            "answers": serialized_answers,
            "raw": str(getattr(resp, "answers", resp)),
        }
    except Exception as e:
        duration_ms = round((time.time() - start_t) * 1000, 1)
        logger.warning(f"Decision systemone evaluation failed: {e}")
        return {
            "success": False,
            "is_dataset": False,
            "model": payload.model,
            "latency_ms": duration_ms,
            "error": str(e),
            "answers": {},
            "raw": None,
        }


# ==============================================================================
# EMBEDDING BENCHMARK ENDPOINT
# ==============================================================================

@router.post("/api/evals/embedding/run")
def run_embedding_eval(payload: EmbeddingRunRequest, request: Request):
    """Runs embedding similarity benchmarks across specified models.
    Supports either manual candidate texts or rendering candidates from dataset rows.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    client = _get_ollama_client(timeout=60.0)
    candidates = list(payload.candidates or [])

    # If dataset_id is supplied, render candidates from dataset rows
    if payload.dataset_id:
        with db_session() as session:
            dataset = session.query(EvalDataset).filter_by(id=payload.dataset_id).first()
            if dataset:
                limit = payload.sample_limit or 10
                rows = _fetch_dataset_rows(session, dataset, limit=limit)
                for r in rows:
                    cand_text = _render_jinja_safely(payload.candidate_template, r, fallback="")
                    if not cand_text.strip():
                        # Default formatting if no template provided
                        title = r.get("title", "")
                        url = r.get("url", "")
                        wiki = r.get("wiki") or r.get("md_content") or ""
                        cand_text = f"{title} | {url}\n{wiki[:300]}"
                    if cand_text.strip() and cand_text not in candidates:
                        candidates.append(cand_text.strip())

    results = []

    for model_name in payload.models:
        start_t = time.time()
        try:
            # 1. Embed query
            query_resp = client.embeddings(model=model_name, prompt=payload.query)
            query_vec = getattr(query_resp, "embedding", None) or (
                query_resp.get("embedding") if isinstance(query_resp, dict) else None
            )

            if not query_vec:
                raise ValueError(f"No embedding vector returned for model {model_name}")

            # 2. Score candidate texts
            scored_candidates = []
            for text in candidates:
                if not text.strip():
                    continue
                cand_resp = client.embeddings(model=model_name, prompt=text)
                cand_vec = getattr(cand_resp, "embedding", None) or (
                    cand_resp.get("embedding") if isinstance(cand_resp, dict) else None
                )
                sim = _cosine_similarity(query_vec, cand_vec) if cand_vec else 0.0
                scored_candidates.append({
                    "text": text[:300],
                    "similarity": round(sim, 4),
                    "percentage": round(sim * 100, 2),
                })

            scored_candidates.sort(key=lambda x: x["similarity"], reverse=True)
            duration_ms = round((time.time() - start_t) * 1000, 1)

            results.append({
                "model": model_name,
                "dimension": len(query_vec),
                "latency_ms": duration_ms,
                "candidates": scored_candidates[: payload.top_k or 5],
                "status": "success",
            })
        except Exception as e:
            duration_ms = round((time.time() - start_t) * 1000, 1)
            logger.error(f"Embedding eval failed for {model_name}: {e}")
            results.append({
                "model": model_name,
                "dimension": 0,
                "latency_ms": duration_ms,
                "candidates": [],
                "error": str(e),
                "status": "error",
            })

    return {"results": results}
