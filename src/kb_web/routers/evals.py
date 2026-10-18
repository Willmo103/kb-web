"""
FastAPI Router for the Model Evaluation Studio (/evals) in kb-web.

Provides:
- GET /evals: Dedicated evaluation studio UI for side-by-side comparative testing
- POST /api/evals/content: Loads article or note content into the studio
- POST /api/evals/matrix/run: Runs matrix comparison of models × prompt formats on sample text
- POST /api/evals/decision/run: Evaluates decision gating models (d1, tev1) via native systemone
- POST /api/evals/embedding/run: Benchmarks embedding models and cosine retrieval accuracy
"""

from datetime import datetime
import json
import logging
import math
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..base import (
    COOKIE_NAME,
    _jinja_env,
    config,
    db_session,
    verify_auth,
    verify_session_token,
    _get_ollama_client,
)
from ..models_orm import FetchedPage, Note

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Evaluation Studio"])


class ContentFetchRequest(BaseModel):
    source_type: str = Field(..., description="'article' or 'note'")
    identifier: str = Field(..., description="URL or Note ID")


class MatrixRunRequest(BaseModel):
    models: List[str] = Field(..., min_length=1, description="List of model names to test")
    prompts: List[Dict[str, str]] = Field(
        ..., min_length=1, description="List of prompt definitions [{'id': str, 'name': str, 'text': str}]"
    )
    input_text: str = Field(..., min_length=1, description="Input text or article markdown to process")
    temperature: Optional[float] = Field(0.2, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(2048, ge=64, le=16384)


class DecisionRunRequest(BaseModel):
    model: str = Field("d1", description="Decision model name (e.g. d1, tev1)")
    state: Dict[str, Any] = Field(default_factory=dict, description="State dictionary context")
    questions: Dict[str, Any] = Field(..., description="Questions dictionary definition")
    context_window: Optional[int] = Field(16384, ge=1024, le=65536)


class EmbeddingRunRequest(BaseModel):
    models: List[str] = Field(..., min_length=1, description="Embedding models to compare")
    query: str = Field(..., min_length=1, description="Search query or test string")
    candidates: Optional[List[str]] = Field(default_factory=list, description="Candidate texts to score")
    top_k: Optional[int] = Field(5, ge=1, le=50)


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

    # 3. Retrieve sample articles and notes for quick testing
    sample_articles = []
    sample_notes = []
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

    template = _jinja_env.get_template("evals.j2.html")
    html_content = template.render(
        is_admin=True,
        models=models,
        prompts=prompts,
        sample_articles=sample_articles,
        sample_notes=sample_notes,
        default_model=config.ollama_model,
        default_decision_model=getattr(config, "decision_model", "d1"),
        default_embedding_model=config.ollama_embedding_model,
        current_user="Admin",
    )
    return HTMLResponse(content=html_content)


# ==============================================================================
# API ENDPOINTS
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


@router.post("/api/evals/matrix/run")
def run_matrix_eval(payload: MatrixRunRequest, request: Request):
    """Runs a side-by-side evaluation matrix across selected models and prompts."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    if not payload.models:
        raise HTTPException(status_code=400, detail="At least one model must be specified")
    if not payload.prompts:
        raise HTTPException(status_code=400, detail="At least one prompt must be specified")
    if not payload.input_text.strip():
        raise HTTPException(status_code=400, detail="Input text cannot be empty")

    client = _get_ollama_client(timeout=180.0)
    results = []

    for model_name in payload.models:
        for prompt_def in payload.prompts:
            prompt_id = prompt_def.get("id", "prompt")
            prompt_name = prompt_def.get("name", prompt_id)
            prompt_text = prompt_def.get("text", "")

            start_t = time.time()
            try:
                messages = [
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": payload.input_text},
                ]
                options = {
                    "temperature": payload.temperature,
                    "num_predict": payload.max_tokens,
                }
                resp = client.chat(
                    model=model_name,
                    messages=messages,
                    options=options,
                )
                duration = time.time() - start_t
                response_content = ""
                if hasattr(resp, "message") and hasattr(resp.message, "content"):
                    response_content = resp.message.content
                elif isinstance(resp, dict):
                    msg = resp.get("message", {})
                    response_content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                else:
                    response_content = str(resp)

                # Extract token metrics if provided by Ollama
                eval_count = getattr(resp, "eval_count", None) or (resp.get("eval_count") if isinstance(resp, dict) else None)
                eval_duration = getattr(resp, "eval_duration", None) or (resp.get("eval_duration") if isinstance(resp, dict) else None)
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

    return {"results": results, "total_runs": len(results)}


@router.post("/api/evals/decision/run")
def run_decision_eval(payload: DecisionRunRequest, request: Request):
    """Evaluates decision gating models (d1, tev1) via native client.systemone."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    client = _get_ollama_client(timeout=60.0)
    start_t = time.time()
    try:
        resp = client.systemone(
            model=payload.model,
            state=payload.state,
            questions=payload.questions,
            options={"num_ctx": payload.context_window or 16384},
        )
        duration_ms = round((time.time() - start_t) * 1000, 1)

        # Parse structured answers
        raw_answers = getattr(resp, "answers", None)
        if raw_answers is None and isinstance(resp, dict):
            raw_answers = resp.get("answers", {})

        serialized_answers: Dict[str, Any] = {}
        if isinstance(raw_answers, dict):
            for q_key, ans_obj in raw_answers.items():
                if hasattr(ans_obj, "__dict__"):
                    serialized_answers[q_key] = {
                        "choice": getattr(ans_obj, "choice", None),
                        "noul": getattr(ans_obj, "noul", None),
                        "reasoning": getattr(ans_obj, "reasoning", None),
                    }
                elif isinstance(ans_obj, dict):
                    serialized_answers[q_key] = ans_obj
                else:
                    serialized_answers[q_key] = str(ans_obj)
        else:
            serialized_answers = {"raw": str(raw_answers)}

        return {
            "success": True,
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
            "model": payload.model,
            "latency_ms": duration_ms,
            "error": str(e),
            "answers": {},
            "raw": None,
        }


@router.post("/api/evals/embedding/run")
def run_embedding_eval(payload: EmbeddingRunRequest, request: Request):
    """Runs embedding similarity benchmarks across specified models."""
    token = request.cookies.get(COOKIE_NAME)
    if not (token and verify_session_token(token)):
        raise HTTPException(status_code=401, detail="Authentication required")

    client = _get_ollama_client(timeout=60.0)
    candidates = payload.candidates or []
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

            # Sort descending by similarity
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
