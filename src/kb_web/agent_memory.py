"""
Agent Memory & Cross-Agent Message Board Engine for kb-web.

Provides persistent shared memory, coordination channels, and decision logs
for all autonomous agents and background workers (Taxonomy State Machine,
Workspace Coding Assistant, RAG Report Agent, and Notes Ingestion Pipeline).
"""

from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from .models_orm import AgentMessage

logger = logging.getLogger(__name__)


def post_agent_memory(
    session: Session,
    agent_name: str,
    channel: str,
    topic: str,
    content: str,
    memory_type: str = "decision",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Posts a new message/memory entry to the centralized agent message board."""
    now_str = datetime.now().isoformat()
    meta_str = json.dumps(metadata or {})

    msg = AgentMessage(
        agent_name=agent_name,
        channel=channel,
        topic=topic,
        content=content,
        memory_type=memory_type,
        metadata_json=meta_str,
        created_at=now_str,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)

    logger.info(f"[{agent_name}] posted to #{channel}/{topic} ({memory_type}): {content[:80]}")

    return {
        "id": msg.id,
        "agent_name": msg.agent_name,
        "channel": msg.channel,
        "topic": msg.topic,
        "content": msg.content,
        "memory_type": msg.memory_type,
        "metadata": metadata or {},
        "created_at": msg.created_at,
    }


def read_agent_memory(
    session: Session,
    channel: Optional[str] = None,
    topic: Optional[str] = None,
    agent_name: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retrieves recent agent memory board entries with optional channel/topic/type filters."""
    query = session.query(AgentMessage).order_by(AgentMessage.id.desc())

    if channel and channel.strip():
        query = query.filter_by(channel=channel.strip())
    if topic and topic.strip():
        query = query.filter_by(topic=topic.strip())
    if agent_name and agent_name.strip():
        query = query.filter_by(agent_name=agent_name.strip())
    if memory_type and memory_type.strip():
        query = query.filter_by(memory_type=memory_type.strip())

    rows = query.limit(limit).all()

    results = []
    for r in rows:
        parsed_meta = {}
        try:
            parsed_meta = json.loads(r.metadata_json or "{}")
        except Exception:
            pass
        results.append({
            "id": r.id,
            "agent_name": r.agent_name,
            "channel": r.channel,
            "topic": r.topic,
            "content": r.content,
            "memory_type": r.memory_type,
            "metadata": parsed_meta,
            "created_at": r.created_at,
        })

    return results


def get_agent_board_summary(session: Session) -> Dict[str, Any]:
    """Computes aggregated channel and agent activity metrics for the board UI."""
    total_messages = session.query(AgentMessage).count()
    recent = read_agent_memory(session, limit=10)

    # Distinct channels and agents
    all_msgs = session.query(AgentMessage).all()
    channels = sorted(list({m.channel for m in all_msgs if m.channel}))
    agents = sorted(list({m.agent_name for m in all_msgs if m.agent_name}))
    types = sorted(list({m.memory_type for m in all_msgs if m.memory_type}))

    return {
        "total_messages": total_messages,
        "channels": channels,
        "agents": agents,
        "memory_types": types,
        "recent_messages": recent,
    }
