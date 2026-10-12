"""
Server Error Logs and Maintenance Agent REST Router.
Provides inspection endpoints for viewing, searching, and diagnosing server errors.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, desc

from ..base import db_session
from ..models_orm import ServerErrorLog
from ..maintenance_agent import analyze_error_with_agent

router = APIRouter(prefix="/api/errors", tags=["Server Errors"])


@router.get("", response_model=Dict[str, Any])
def list_server_errors(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by status ('open', 'analyzed', etc.)"),
):
    """Lists server error incidents with pagination and status filtering."""
    with db_session() as session:
        query = session.query(ServerErrorLog)
        if status:
            query = query.filter(ServerErrorLog.status == status)

        total = query.count()
        logs = query.order_by(desc(ServerErrorLog.id)).offset(offset).limit(limit).all()

        items = [
            {
                "id": l.id,
                "timestamp": l.timestamp,
                "error_type": l.error_type,
                "error_message": l.error_message,
                "request_method": l.request_method,
                "request_url": l.request_url,
                "client_ip": l.client_ip,
                "status": l.status,
                "has_feedback": bool(l.agent_feedback),
            }
            for l in logs
        ]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }


@router.get("/search", response_model=Dict[str, Any])
def search_server_errors(
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(25, ge=1, le=100),
):
    """Searches error logs by keywords in error type, message, stack trace, or request URL."""
    pattern = f"%{q}%"
    with db_session() as session:
        logs = (
            session.query(ServerErrorLog)
            .filter(
                or_(
                    ServerErrorLog.error_type.ilike(pattern),
                    ServerErrorLog.error_message.ilike(pattern),
                    ServerErrorLog.stack_trace.ilike(pattern),
                    ServerErrorLog.request_url.ilike(pattern),
                )
            )
            .order_by(desc(ServerErrorLog.id))
            .limit(limit)
            .all()
        )

        items = [
            {
                "id": l.id,
                "timestamp": l.timestamp,
                "error_type": l.error_type,
                "error_message": l.error_message,
                "request_method": l.request_method,
                "request_url": l.request_url,
                "client_ip": l.client_ip,
                "status": l.status,
                "has_feedback": bool(l.agent_feedback),
            }
            for l in logs
        ]

        return {"query": q, "count": len(items), "items": items}


@router.get("/{error_id}", response_model=Dict[str, Any])
def get_server_error_detail(error_id: int):
    """Retrieves full details of a specific server error, including traceback and agent diagnosis."""
    with db_session() as session:
        err = session.query(ServerErrorLog).filter_by(id=error_id).first()
        if not err:
            raise HTTPException(status_code=404, detail=f"Server error #{error_id} not found.")

        return {
            "id": err.id,
            "timestamp": err.timestamp,
            "error_type": err.error_type,
            "error_message": err.error_message,
            "stack_trace": err.stack_trace,
            "request_method": err.request_method,
            "request_url": err.request_url,
            "query_params": err.query_params,
            "client_ip": err.client_ip,
            "agent_feedback": err.agent_feedback,
            "status": err.status,
        }


@router.post("/{error_id}/analyze", response_model=Dict[str, Any])
def trigger_agent_analysis(error_id: int):
    """Triggers the Maintenance Agent to analyze the specified server error."""
    with db_session() as session:
        err = session.query(ServerErrorLog).filter_by(id=error_id).first()
        if not err:
            raise HTTPException(status_code=404, detail=f"Server error #{error_id} not found.")

    diagnosis = analyze_error_with_agent(error_id, send_gotify=True)
    return {
        "id": error_id,
        "status": "analyzed",
        "agent_feedback": diagnosis,
    }
