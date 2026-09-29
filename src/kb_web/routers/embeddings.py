"""
FastAPI Router for multi-model embedding management, reindexing, model comparison,
and vector source toggling in kb-web.
"""

from datetime import datetime
import json
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, HTTPException, Request, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token, verify_auth
from ..models_orm import (
    ChunkEmbedding,
    ArticleEmbedding,
    VideoEmbedding,
    FetchedPage,
    SettingOllama,
    SettingExternal,
)
from ..utils import _get_ollama_client, ensure_model_available, chunk_text_with_overlap, cosine_similarity

router = APIRouter(tags=["Embeddings"])


def _reindex_worker(model_name: str):
    """Background task to generate chunk embeddings for all fetched pages with target model."""
    client = _get_ollama_client()
    try:
        ensure_model_available(client, model_name)
    except Exception as e:
        print(f"Failed to ensure model {model_name}: {e}")
        return

    with db_session() as session:
        pages = session.query(FetchedPage).all()
        for page in pages:
            md_content = page.md_content or page.description or ""
            if not md_content.strip():
                continue

            chunks = chunk_text_with_overlap(md_content, 1500, 150)
            chunk_vectors = []
            for idx, chunk in enumerate(chunks):
                prompt = f"search_document: {chunk}" if ("gemma" in model_name or "nomic" in model_name) else chunk
                try:
                    resp = client.embeddings(model=model_name, prompt=prompt)
                    vec = resp.get("embedding")
                    if vec:
                        chunk_vectors.append((idx, chunk, vec))
                except Exception as err:
                    print(f"Error embedding chunk {idx} for {page.url} with {model_name}: {err}")

            # Upsert chunks for this page and model
            session.query(ChunkEmbedding).filter_by(source_id=page.url, model_name=model_name).delete()
            for idx, chunk, vec in chunk_vectors:
                session.add(
                    ChunkEmbedding(
                        source_type="articles",
                        source_id=page.url,
                        source_title=page.title or page.url,
                        chunk_number=idx,
                        chunk_content=chunk,
                        chunk_vector=vec,
                        model_name=model_name,
                        created_at=datetime.now().isoformat(),
                    )
                )
            session.commit()


@router.get("/api/embeddings/models")
def list_embedding_models() -> Dict[str, Any]:
    """Returns available embedding models, active model, and chunk counts per model."""
    client = _get_ollama_client()
    available_models = ["embeddinggemma", "nomic-embed-text", "bge-m3", "all-minilm"]
    try:
        models_resp = client.list()
        installed = [m.get("name") or m.get("model") for m in models_resp.get("models", [])]
        for m in installed:
            if m and m not in available_models:
                available_models.append(m)
    except Exception:
        pass

    with db_session() as session:
        active_setting = session.query(SettingExternal).filter_by(key="active_embedding_model").first()
        active_model = active_setting.value if active_setting else getattr(config, "ollama_embedding_model", "embeddinggemma")

        counts = (
            session.query(ChunkEmbedding.model_name, func.count(ChunkEmbedding.id))
            .group_by(ChunkEmbedding.model_name)
            .all()
        )
        counts_dict = {m or "embeddinggemma": cnt for m, cnt in counts}

    return {
        "active_model": active_model,
        "available_models": available_models,
        "indexed_chunks_by_model": counts_dict,
    }


@router.get("/api/embeddings/active-model")
def get_active_embedding_model() -> Dict[str, Any]:
    """Returns the currently active embedding model."""
    with db_session() as session:
        active_setting = session.query(SettingExternal).filter_by(key="active_embedding_model").first()
        active_model = active_setting.value if active_setting else getattr(config, "ollama_embedding_model", "embeddinggemma")
        return {"active_model": active_model}


@router.post("/api/embeddings/active-model")
def set_active_embedding_model(payload: Dict[str, Any], token: Optional[str] = Depends(verify_auth)) -> Dict[str, Any]:
    """Updates the active embedding model used across the entire application."""
    model_name = payload.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name is required")

    with db_session() as session:
        setting = session.query(SettingExternal).filter_by(key="active_embedding_model").first()
        if not setting:
            setting = SettingExternal(key="active_embedding_model", value=model_name)
            session.add(setting)
        else:
            setting.value = model_name

        # Also update SettingOllama for backward compatibility
        ollama_setting = session.query(SettingOllama).filter_by(key="ollama_embedding_model").first()
        if ollama_setting:
            ollama_setting.value = model_name
        else:
            session.add(SettingOllama(key="ollama_embedding_model", value=model_name))

        session.commit()

    return {"status": "success", "active_model": model_name}


@router.post("/api/embeddings/reindex")
def trigger_reindex(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    token: Optional[str] = Depends(verify_auth),
) -> Dict[str, Any]:
    """Schedules background reindexing of all items with a target embedding model."""
    model_name = payload.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name is required")

    background_tasks.add_task(_reindex_worker, model_name)
    return {
        "status": "started",
        "message": f"Reindexing all documents with embedding model '{model_name}' initiated in background.",
        "model": model_name,
    }


@router.post("/api/embeddings/compare")
def compare_embedding_models(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Executes a search query against two embedding models and returns side-by-side results."""
    query = payload.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query is required")

    models = payload.get("models", ["embeddinggemma", "nomic-embed-text"])
    top_k = int(payload.get("top_k", 5))

    client = _get_ollama_client()
    comparisons = {}

    for model in models:
        prompt = f"search_query: {query}" if ("gemma" in model or "nomic" in model) else query
        query_vector = None
        try:
            resp = client.embeddings(model=model, prompt=prompt)
            query_vector = resp.get("embedding")
        except Exception as e:
            comparisons[model] = {"error": f"Model failed: {str(e)}", "results": []}
            continue

        if not query_vector:
            comparisons[model] = {"error": "Empty vector returned", "results": []}
            continue

        with db_session() as session:
            dialect = session.bind.dialect.name
            query_obj = session.query(ChunkEmbedding).filter_by(model_name=model)
            if dialect == "postgresql":
                dist_col = ChunkEmbedding.chunk_vector.cosine_distance(query_vector)
                rows = (
                    query_obj.add_columns(dist_col)
                    .filter(ChunkEmbedding.chunk_vector.isnot(None))
                    .order_by(dist_col.asc())
                    .limit(top_k)
                    .all()
                )
                items = []
                for chunk, dist in rows:
                    if dist is None:
                        continue
                    sim = max(0.0, 1.0 - float(dist))
                    items.append({
                        "source_title": chunk.source_title,
                        "source_id": chunk.source_id,
                        "chunk_number": chunk.chunk_number,
                        "chunk_content": chunk.chunk_content[:240],
                        "similarity": round(sim * 100, 1),
                    })
                comparisons[model] = {"results": items}
            else:
                chunks = query_obj.filter(ChunkEmbedding.chunk_vector.isnot(None)).all()
                scored = []
                for c in chunks:
                    vec = c.chunk_vector
                    if isinstance(vec, str):
                        try:
                            vec = json.loads(vec)
                        except Exception:
                            continue
                    if not vec:
                        continue
                    sim = cosine_similarity(query_vector, vec)
                    scored.append((sim, c))
                scored.sort(key=lambda x: x[0], reverse=True)
                items = [
                    {
                        "source_title": c.source_title,
                        "source_id": c.source_id,
                        "chunk_number": c.chunk_number,
                        "chunk_content": c.chunk_content[:240],
                        "similarity": round(max(0.0, sim) * 100, 1),
                    }
                    for sim, c in scored[:top_k]
                ]
                comparisons[model] = {"results": items}

    return {"query": query, "models": models, "comparisons": comparisons}


# --- UI Page: /similarity/compare ---

@router.get("/similarity/compare", response_class=HTMLResponse)
def view_model_comparison(request: Request):
    """Side-by-side visual explorer for comparing embedding models."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    template = _jinja_env.get_template("embedding_comparison.j2.html")
    return HTMLResponse(content=template.render(is_admin=is_admin))
