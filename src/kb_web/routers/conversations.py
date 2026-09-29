"""
FastAPI Router for article-level and global Ollama chat conversations in kb-web.

Supports persistent chat threads per article, context injection (wiki + chunks),
history retrieval, message dispatching, and dedicated /conversations dashboard.
"""

from datetime import datetime
import json
from typing import Optional, Dict, Any, List
from urllib.parse import unquote_plus, quote_plus

from fastapi import APIRouter, Query, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import desc

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token
from ..models_orm import (
    ChatConversation,
    ChatMessage,
    FetchedPage,
    YouTubeVideo,
    ChunkEmbedding,
    Note,
)
from ..utils import _get_ollama_client, ensure_model_available

router = APIRouter(tags=["Conversations"])


# --- API Endpoints ---

@router.get("/api/conversations")
def list_conversations_api(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
) -> Dict[str, Any]:
    """Returns paginated list of all active conversations with message counts and previews."""
    with db_session() as session:
        query = session.query(ChatConversation).order_by(ChatConversation.updated_at.desc())
        total = query.count()
        offset = (page - 1) * limit
        rows = query.offset(offset).limit(limit).all()

        conversations = []
        for conv in rows:
            msg_count = session.query(ChatMessage).filter_by(conversation_id=conv.id).count()
            last_msg = (
                session.query(ChatMessage)
                .filter_by(conversation_id=conv.id)
                .order_by(ChatMessage.id.desc())
                .first()
            )
            conversations.append(
                {
                    "id": conv.id,
                    "title": conv.title or "Untitled Conversation",
                    "source_type": conv.source_type,
                    "source_id": conv.source_id,
                    "safe_source_url": quote_plus(conv.source_id) if conv.source_id else "",
                    "created_at": conv.created_at,
                    "updated_at": conv.updated_at,
                    "message_count": msg_count,
                    "last_message": last_msg.content[:160] if last_msg else None,
                    "last_role": last_msg.role if last_msg else None,
                }
            )

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "conversations": conversations,
        }


@router.get("/api/conversations/by-source")
def get_conversation_by_source(
    url: str = Query(..., description="Target article or video URL"),
) -> Dict[str, Any]:
    """Retrieves or creates active conversation for a given article URL along with its messages."""
    decoded_url = unquote_plus(url)
    with db_session() as session:
        conv = (
            session.query(ChatConversation)
            .filter_by(source_id=decoded_url)
            .order_by(ChatConversation.id.desc())
            .first()
        )
        if not conv:
            # Determine title from page or video
            page = session.query(FetchedPage).filter_by(url=decoded_url).first()
            title = page.title if page and page.title else decoded_url
            conv = ChatConversation(
                title=f"Chat: {title[:80]}",
                source_type="article",
                source_id=decoded_url,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)

        messages = (
            session.query(ChatMessage)
            .filter_by(conversation_id=conv.id)
            .order_by(ChatMessage.id.asc())
            .all()
        )

        return {
            "conversation_id": conv.id,
            "conversation": {
                "id": conv.id,
                "title": conv.title,
                "source_id": conv.source_id,
                "source_type": conv.source_type,
            },
            "title": conv.title,
            "source_id": conv.source_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "model": m.model,
                }
                for m in messages
            ],
        }


@router.get("/api/conversations/{conversation_id}")
def get_conversation_detail(conversation_id: int) -> Dict[str, Any]:
    """Retrieves messages and metadata for a specific conversation ID."""
    with db_session() as session:
        conv = session.query(ChatConversation).filter_by(id=conversation_id).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = (
            session.query(ChatMessage)
            .filter_by(conversation_id=conv.id)
            .order_by(ChatMessage.id.asc())
            .all()
        )

        return {
            "conversation_id": conv.id,
            "title": conv.title,
            "source_type": conv.source_type,
            "source_id": conv.source_id,
            "safe_source_url": quote_plus(conv.source_id) if conv.source_id else "",
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "model": m.model,
                }
                for m in messages
            ],
        }


@router.post("/api/conversations/chat")
def post_chat_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Sends a user message, injects article context, queries Ollama, and persists responses."""
    user_prompt = payload.get("message", "").strip()
    if not user_prompt:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    source_id = payload.get("source_id")
    conv_id = payload.get("conversation_id")
    target_model = payload.get("model") or getattr(config, "ollama_model", "gemma4:latest")

    with db_session() as session:
        conv = None
        if conv_id:
            conv = session.query(ChatConversation).filter_by(id=conv_id).first()
        elif source_id:
            conv = (
                session.query(ChatConversation)
                .filter_by(source_id=source_id)
                .order_by(ChatConversation.id.desc())
                .first()
            )

        if not conv:
            title = "Article Chat"
            if source_id:
                page = session.query(FetchedPage).filter_by(url=source_id).first()
                if page and page.title:
                    title = f"Chat: {page.title[:80]}"
            conv = ChatConversation(
                title=title,
                source_type="article",
                source_id=source_id or "",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)

        # 1. Save user message
        user_msg = ChatMessage(
            conversation_id=conv.id,
            role="user",
            content=user_prompt,
            timestamp=datetime.now().isoformat(),
            model=target_model,
        )
        session.add(user_msg)
        session.commit()

        # 2. Gather context if source_id is set
        doc_context = ""
        if conv.source_id:
            page = session.query(FetchedPage).filter_by(url=conv.source_id).first()
            if page:
                wiki_summary = page.description or ""
                doc_context += f"Document Title: {page.title or page.url}\n\nDocument Summary:\n{wiki_summary[:2000]}\n"

            # Retrieve top chunks for context
            chunks = (
                session.query(ChunkEmbedding)
                .filter_by(source_id=conv.source_id)
                .order_by(ChunkEmbedding.chunk_number.asc())
                .limit(5)
                .all()
            )
            if chunks:
                doc_context += "\nRelevant Document Excerpts:\n"
                for c in chunks:
                    doc_context += f"--- Chunk {c.chunk_number + 1} ---\n{c.chunk_content[:600]}\n"

        # 3. Build messages list for Ollama
        past_msgs = (
            session.query(ChatMessage)
            .filter_by(conversation_id=conv.id)
            .order_by(ChatMessage.id.asc())
            .limit(12)
            .all()
        )

        system_instruction = (
            "You are an expert AI knowledge-base assistant. Answer the user's questions accurately, "
            "helpfully, and concisely based on the document context provided below.\n\n"
            f"{doc_context}"
        )

        ollama_messages = [{"role": "system", "content": system_instruction}]
        for m in past_msgs:
            ollama_messages.append({"role": m.role, "content": m.content})

        # 4. Invoke Ollama Client
        client = _get_ollama_client()
        try:
            ensure_model_available(client, target_model)
            response = client.chat(model=target_model, messages=ollama_messages)
            if isinstance(response, dict):
                assistant_text = str(response.get("message", {}).get("content", ""))
            elif hasattr(response, "message") and hasattr(response.message, "content"):
                assistant_text = str(response.message.content)
            else:
                assistant_text = str(response)
        except Exception as e:
            assistant_text = f"I'm sorry, I encountered an error communicating with the Ollama model ({target_model}): {str(e)}"

        # 5. Save assistant message
        asst_msg = ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=assistant_text,
            timestamp=datetime.now().isoformat(),
            model=target_model,
        )
        session.add(asst_msg)
        conv.updated_at = datetime.now().isoformat()
        session.commit()

        return {
            "conversation_id": conv.id,
            "role": "assistant",
            "content": assistant_text,
            "reply": assistant_text,
            "timestamp": asst_msg.timestamp,
            "model": target_model,
        }


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int) -> Dict[str, Any]:
    """Permanently deletes a conversation thread and its messages."""
    with db_session() as session:
        conv = session.query(ChatConversation).filter_by(id=conversation_id).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        session.query(ChatMessage).filter_by(conversation_id=conv.id).delete()
        session.delete(conv)
        session.commit()
        return {"status": "deleted", "id": conversation_id}


# --- UI Route: /conversations ---

@router.get("/conversations", response_class=HTMLResponse)
def view_conversations_dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """HTML Dashboard listing all conversation threads with linked articles."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        query = session.query(ChatConversation).order_by(ChatConversation.updated_at.desc())
        total = query.count()
        offset = (page - 1) * limit
        rows = query.offset(offset).limit(limit).all()

        conversations = []
        for conv in rows:
            msg_count = session.query(ChatMessage).filter_by(conversation_id=conv.id).count()
            last_msg = (
                session.query(ChatMessage)
                .filter_by(conversation_id=conv.id)
                .order_by(ChatMessage.id.desc())
                .first()
            )
            conversations.append(
                {
                    "id": conv.id,
                    "title": conv.title or "Untitled Thread",
                    "source_type": conv.source_type,
                    "source_id": conv.source_id,
                    "safe_source_url": quote_plus(conv.source_id) if conv.source_id else "",
                    "created_at": conv.created_at,
                    "updated_at": conv.updated_at,
                    "message_count": msg_count,
                    "last_message": last_msg.content[:180] if last_msg else "No messages yet.",
                    "last_role": last_msg.role if last_msg else None,
                }
            )

    template = _jinja_env.get_template("conversations_list.j2.html")
    return HTMLResponse(
        content=template.render(
            conversations=conversations,
            total=total,
            page=page,
            limit=limit,
            is_admin=is_admin,
            total_pages=(total + limit - 1) // limit if limit > 0 else 1,
        )
    )
