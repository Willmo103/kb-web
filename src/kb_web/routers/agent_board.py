"""
FastAPI Router for Centralized Agent Memory & Cross-Agent Message Board.

Provides:
- GET /agents/board: Interactive Agent Message Board HTML UI
- GET /api/agent-memory: Lists structured memories/messages with channel & agent filters
- POST /api/agent-memory: Posts new memory entry
- GET /api/agent-memory/summary: High-level metrics of agent activity and channel distribution
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token
from ..agent_memory import post_agent_memory, read_agent_memory, get_agent_board_summary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent Board"])


class PostMemoryRequest(BaseModel):
    agent_name: str = Field(..., description="Name of the reporting agent")
    channel: str = Field(..., description="Message board channel (e.g. taxonomy, rag, workspaces, ingestion)")
    topic: str = Field(..., description="Topic or event label")
    content: str = Field(..., description="Content, observation, or decision rationale")
    memory_type: str = Field("decision", description="Memory type: 'decision', 'observation', 'state_machine', 'lifecycle', 'artifact'")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Structured contextual metadata")


# --- UI Route ---

@router.get("/agents/board", response_class=HTMLResponse)
def view_agent_message_board(
    request: Request,
    channel: Optional[str] = Query(None, description="Filter by channel"),
    agent: Optional[str] = Query(None, description="Filter by agent"),
):
    """Renders the interactive Agent Message Board interface."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        summary = get_agent_board_summary(session)
        messages = read_agent_memory(
            session=session,
            channel=channel,
            agent_name=agent,
            limit=100,
        )

        template = _jinja_env.get_template("agent_board.j2.html")
        content = template.render(
            request=request,
            is_admin=is_admin,
            summary=summary,
            messages=messages,
            selected_channel=channel or "",
            selected_agent=agent or "",
        )
        return HTMLResponse(content=content)


# --- REST API Endpoints ---

@router.get("/api/agent-memory")
def list_agent_memories(
    channel: Optional[str] = Query(None, description="Filter by channel"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    agent_name: Optional[str] = Query(None, description="Filter by agent name"),
    memory_type: Optional[str] = Query(None, description="Filter by memory type"),
    limit: int = Query(50, ge=1, le=500, description="Max messages to return"),
) -> Dict[str, Any]:
    """Retrieves chronological agent memory logs matching optional filters."""
    with db_session() as session:
        items = read_agent_memory(
            session=session,
            channel=channel,
            topic=topic,
            agent_name=agent_name,
            memory_type=memory_type,
            limit=limit,
        )
        return {
            "status": "success",
            "count": len(items),
            "messages": items,
        }


@router.post("/api/agent-memory")
def create_agent_memory(payload: PostMemoryRequest) -> Dict[str, Any]:
    """Posts a new message to the centralized agent memory board."""
    with db_session() as session:
        msg = post_agent_memory(
            session=session,
            agent_name=payload.agent_name,
            channel=payload.channel,
            topic=payload.topic,
            content=payload.content,
            memory_type=payload.memory_type,
            metadata=payload.metadata,
        )
        return {
            "status": "created",
            "message": msg,
        }


@router.get("/api/agent-memory/summary")
def get_agent_board_summary_endpoint() -> Dict[str, Any]:
    """Returns aggregated channel and agent metrics for board dashboards."""
    with db_session() as session:
        return get_agent_board_summary(session)
