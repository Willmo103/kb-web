"""
Router for Topic Wiki Pages (/wiki/{agent_id}/{path}) and Dynamic Agent Pages (/pages/agent/{hash_id}).
Supports themed vs raw rendering modes, interactive forms, and HITL execution approvals.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import markdown

from ..base import (
    COOKIE_NAME,
    _jinja_env,
    config,
    db_session,
    verify_auth,
    verify_session_token,
)
from ..models_orm import (
    AgentPage,
    AgentPythonApproval,
    CustomAgent,
    TopicWikiPage,
    FetchedPage,
    Note,
)
from ..python_kernel import execute_approved_code, reject_code_execution
from ..utils import sanitize_html

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent Pages & Topic Wiki"])


# ==============================================================================
# TOPIC WIKI ROUTES (/wiki/{agent_id}/{path})
# ==============================================================================

@router.get("/wiki/{agent_id}", response_class=HTMLResponse)
@router.get("/wiki/{agent_id}/{path:path}", response_class=HTMLResponse)
def view_topic_wiki_page(agent_id: str, request: Request, path: Optional[str] = None):
    """Renders a curated TopicWikiPage within the agent's living wiki domain layout."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    logical_path = (path or "index").strip("/")
    if not logical_path:
        logical_path = "index"

    with db_session() as session:
        agent = session.query(CustomAgent).filter_by(id=agent_id).first()
        if not agent:
            # Check by name as fallback
            agent = session.query(CustomAgent).filter_by(name=agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Topic Agent '{agent_id}' not found")

        # Fetch targeted topic page
        page = (
            session.query(TopicWikiPage)
            .filter_by(agent_id=agent.id, logical_path=logical_path)
            .first()
        )
        if not page and logical_path == "index":
            # Fallback to first page if index does not exist
            page = (
                session.query(TopicWikiPage)
                .filter_by(agent_id=agent.id)
                .order_by(TopicWikiPage.id.asc())
                .first()
            )

        # Fetch all pages for this agent to build tree navigation sidebar
        all_pages = (
            session.query(TopicWikiPage)
            .filter_by(agent_id=agent.id)
            .order_by(TopicWikiPage.logical_path.asc())
            .all()
        )

        wiki_tree = []
        for p in all_pages:
            wiki_tree.append({
                "id": p.id,
                "path": p.logical_path,
                "title": p.title or p.logical_path,
                "is_current": (page and p.id == page.id),
                "url": f"/wiki/{agent.id}/{p.logical_path}",
            })

        if not page:
            # Placeholder for uninitialized wiki
            rendered_body = f"""<div class="p-8 text-center text-gray-500">
                <span class="text-4xl block mb-2">📚</span>
                <h3 class="text-lg font-bold text-gray-800 dark:text-gray-200">No Wiki Articles Published Yet</h3>
                <p class="text-xs mt-1">Agent <strong>{agent.name}</strong> has not yet compiled articles for path <code>/{logical_path}</code>.</p>
            </div>"""
            title = f"{agent.name} - Topic Wiki"
            references = []
            links = []
        else:
            title = page.title
            try:
                raw_rendered = markdown.markdown(
                    page.body_markdown or "",
                    extensions=["fenced_code", "tables", "nl2br", "toc"],
                )
                rendered_body = sanitize_html(raw_rendered)
            except Exception:
                rendered_body = sanitize_html(page.body_markdown or "")

            try:
                references = json.loads(page.references_json or "[]")
            except Exception:
                references = []
            try:
                links = json.loads(page.links_json or "[]")
            except Exception:
                links = []

        template = _jinja_env.get_template("topic_wiki_page.j2.html")
        html_content = template.render(
            request=request,
            is_admin=is_admin,
            agent=agent,
            page=page,
            page_title=title,
            logical_path=logical_path,
            rendered_body=rendered_body,
            wiki_tree=wiki_tree,
            references=references,
            links=links,
        )
        return HTMLResponse(content=html_content)


# ==============================================================================
# DYNAMIC AGENT CANVAS PAGES (/pages/agent/{hash_id})
# ==============================================================================

@router.get("/pages/agent/{hash_id}", response_class=HTMLResponse)
def view_agent_page(hash_id: str, request: Request):
    """Renders a dynamic AgentPage in either raw HTML mode or themed layout."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        page = session.query(AgentPage).filter_by(hash_id=hash_id).first()
        if not page:
            raise HTTPException(status_code=404, detail="Agent page not found or has expired.")

        # Check raw mode vs themed mode
        if page.render_mode == "raw":
            # Return raw HTML without site chrome or base template
            return HTMLResponse(content=page.body_content or "<!DOCTYPE html><html><body>(empty page)</body></html>")

        # Themed mode: Render with full site layout, form schemas, and hitl approval
        agent = session.query(CustomAgent).filter_by(id=page.agent_id).first()
        agent_name = agent.name if agent else page.agent_id

        try:
            form_schema = json.loads(page.form_schema_json or "{}")
        except Exception:
            form_schema = {}

        try:
            user_response = json.loads(page.user_response_json or "{}")
        except Exception:
            user_response = {}

        try:
            raw_rendered = markdown.markdown(
                page.body_content or "",
                extensions=["fenced_code", "tables", "nl2br"],
            )
            rendered_body = sanitize_html(raw_rendered)
        except Exception:
            rendered_body = sanitize_html(page.body_content or "")

        template = _jinja_env.get_template("agent_page_themed.j2.html")
        html_content = template.render(
            request=request,
            is_admin=is_admin,
            page=page,
            agent_name=agent_name,
            rendered_body=rendered_body,
            form_schema=form_schema,
            user_response=user_response,
        )
        return HTMLResponse(content=html_content)


@router.post("/api/pages/agent/{hash_id}/submit")
async def submit_agent_page_form(hash_id: str, request: Request):
    """Captures interactive form input, approval decisions, or guidance submitted on an AgentPage."""
    content_type = request.headers.get("content-type", "")
    submission_data = {}
    if "application/json" in content_type:
        try:
            submission_data = await request.json()
        except Exception:
            submission_data = {}
    else:
        form = await request.form()
        submission_data = dict(form)

    with db_session() as session:
        page = session.query(AgentPage).filter_by(hash_id=hash_id).first()
        if not page:
            raise HTTPException(status_code=404, detail="Agent page not found")

        try:
            form_schema = json.loads(page.form_schema_json or "{}")
        except Exception:
            form_schema = {}

        now_iso = datetime.now(timezone.utc).isoformat()
        submission_record = {
            "submitted_at": now_iso,
            "data": submission_data,
        }

        # Check if this page is a Human-In-The-Loop (HITL) Python execution approval
        approval_id = form_schema.get("approval_id")
        exec_result = None

        if approval_id:
            decision = submission_data.get("decision", "approve").lower()
            feedback = submission_data.get("feedback", "")

            if decision == "approve":
                approval = session.query(AgentPythonApproval).filter_by(id=approval_id).first()
                if approval:
                    approval.status = "approved"
                    session.commit()
                    exec_result = execute_approved_code(approval_id, session)
            else:
                exec_result = reject_code_execution(approval_id, session, reason=feedback)

            submission_record["execution_result"] = exec_result

        page.user_response_json = json.dumps(submission_record)
        session.commit()

        if "application/json" in content_type:
            return {
                "status": "success",
                "message": "Submission recorded successfully.",
                "execution_result": exec_result,
            }
        else:
            return RedirectResponse(
                url=f"/pages/agent/{hash_id}?msg=Submission+processed+successfully",
                status_code=303,
            )
