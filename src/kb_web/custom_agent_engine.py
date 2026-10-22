"""
Autonomous deliberation engine for topic-expert custom agents ("Mini OpenClaw").
Coordinates working memory observations, self-directed task queues, steered grounding,
and living TopicWikiPage compilation.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import or_

from .base import db_session, config, _get_ollama_client
from .models_orm import (
    CustomAgent,
    TopicWikiPage,
    AgentObservation,
    AgentSelfTask,
    FetchedPage,
    Note,
)
from .python_kernel import propose_python_execution

logger = logging.getLogger(__name__)


def find_relevant_library_items(topic_domain: str, session, limit: int = 10) -> List[Dict[str, Any]]:
    """Discovers already-imported knowledge items strictly matching the agent's topic domain."""
    keywords = [w.strip() for w in topic_domain.replace(",", " ").split() if len(w.strip()) > 3]
    if not keywords:
        keywords = [topic_domain]

    filters = []
    for kw in keywords[:3]:
        term = f"%{kw}%"
        filters.append(FetchedPage.title.ilike(term))
        filters.append(FetchedPage.tags.ilike(term))
        filters.append(FetchedPage.md_content.ilike(term))

    pages = (
        session.query(FetchedPage)
        .filter(or_(*filters))
        .order_by(FetchedPage.fetched_at.desc())
        .limit(limit)
        .all()
    )

    items = []
    for p in pages:
        items.append({
            "type": "article",
            "url": p.url,
            "title": p.title or p.url,
            "snippet": (p.md_content or "")[:350],
            "tags": p.tags or "",
        })
    return items


def steer_topic_grounding(agent_id: str, session) -> Dict[str, Any]:
    """Steers grounding by discovering relevant imported library items and recording observations."""
    agent = session.query(CustomAgent).filter_by(id=agent_id).first()
    if not agent:
        return {"status": "error", "message": f"Agent '{agent_id}' not found"}

    now_iso = datetime.now(timezone.utc).isoformat()
    relevant_items = find_relevant_library_items(agent.topic_domain, session, limit=5)

    recorded_count = 0
    for item in relevant_items:
        # Check if already observed
        existing = session.query(AgentObservation).filter_by(
            agent_id=agent.id, source_url=item["url"]
        ).first()
        if not existing:
            obs = AgentObservation(
                agent_id=agent.id,
                observation_type="source_grounding",
                content=f"Discovered imported source '{item['title']}' with tags [{item['tags']}]. Excerpt: {item['snippet']}",
                source_url=item["url"],
                created_at=now_iso,
            )
            session.add(obs)
            recorded_count += 1

    session.commit()
    return {"status": "success", "agent_id": agent.id, "new_observations": recorded_count}


def deliberate_agent(agent_id: str, session, auto_generate: bool = True) -> Dict[str, Any]:
    """Autonomous deliberation turn for an agent: reviews tasks, gathers context, and updates wiki pages."""
    agent = session.query(CustomAgent).filter_by(id=agent_id).first()
    if not agent:
        return {"status": "error", "message": f"Agent '{agent_id}' not found"}

    now_iso = datetime.now(timezone.utc).isoformat()
    agent.status = "deliberating"
    session.commit()

    try:
        # 1. Steer grounding from library sources
        steer_topic_grounding(agent.id, session)

        # 2. Check pending self-tasks
        pending_task = (
            session.query(AgentSelfTask)
            .filter_by(agent_id=agent.id, status="pending")
            .order_by(AgentSelfTask.id.asc())
            .first()
        )

        if not pending_task:
            # Agent sets a task for itself based on its domain
            task_desc = f"Synthesize and refine core architectural overview for {agent.topic_domain}"
            pending_task = AgentSelfTask(
                agent_id=agent.id,
                task_description=task_desc,
                status="in_progress",
                result="",
                created_at=now_iso,
            )
            session.add(pending_task)
            session.commit()
            session.refresh(pending_task)
        else:
            pending_task.status = "in_progress"
            session.commit()

        # 3. Retrieve grounding observations & existing wiki pages
        observations = (
            session.query(AgentObservation)
            .filter_by(agent_id=agent.id)
            .order_by(AgentObservation.id.desc())
            .limit(10)
            .all()
        )
        sources_context = "\n".join([f"- [{o.source_url}]: {o.content[:200]}" for o in observations if o.content])

        existing_wiki_page = (
            session.query(TopicWikiPage)
            .filter_by(agent_id=agent.id, logical_path="index")
            .first()
        )

        # 4. Synthesize or update living TopicWikiPage
        if auto_generate:
            prompt_instruction = agent.system_prompt or (
                f"You are {agent.name}, an expert research and curation agent specialized in {agent.topic_domain}. "
                "Synthesize a thorough, highly technical markdown living wiki page summarizing the core principles, "
                "data structures, and architectural trade-offs."
            )

            client = _get_ollama_client(timeout=120.0)
            model_to_use = agent.model or config.ollama_model

            user_msg = f"""Topic Domain: {agent.topic_domain}
Active Task: {pending_task.task_description}

Grounding Observations:
{sources_context}

Please generate an updated Living Wiki Article in clean Markdown with:
1. Executive Summary & Principles
2. Architecture & Internals
3. Practical Best Practices & Gotchas
"""
            try:
                chat_resp = client.chat(
                    model=model_to_use,
                    messages=[
                        {"role": "system", "content": prompt_instruction},
                        {"role": "user", "content": user_msg},
                    ],
                    options={"temperature": 0.2, "num_predict": 2048},
                )
                wiki_markdown = ""
                if hasattr(chat_resp, "message") and hasattr(chat_resp.message, "content"):
                    wiki_markdown = chat_resp.message.content
                elif isinstance(chat_resp, dict):
                    wiki_markdown = chat_resp.get("message", {}).get("content", "")
            except Exception as e:
                logger.warning(f"Ollama chat failed for agent {agent.id}: {e}")
                wiki_markdown = f"# {agent.name}: {agent.topic_domain}\n\n*Living wiki initialized.* Observations gathered:\n\n{sources_context}"

            # References cited
            refs = [{"url": o.source_url, "title": o.source_url} for o in observations if o.source_url]

            if existing_wiki_page:
                existing_wiki_page.body_markdown = wiki_markdown
                existing_wiki_page.references_json = json.dumps(refs)
                existing_wiki_page.updated_at = now_iso
            else:
                existing_wiki_page = TopicWikiPage(
                    agent_id=agent.id,
                    logical_path="index",
                    title=f"{agent.name} - {agent.topic_domain} Overview",
                    body_markdown=wiki_markdown,
                    links_json=json.dumps(["architecture", "faq", "guides"]),
                    references_json=json.dumps(refs),
                    metadata_json=json.dumps({"domain": agent.topic_domain, "curated_by": agent.id}),
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                session.add(existing_wiki_page)

            pending_task.status = "completed"
            pending_task.result = f"Compiled living wiki at /wiki/{agent.id}/index"
            pending_task.completed_at = now_iso

        agent.status = "idle"
        agent.last_run_at = now_iso
        session.commit()

        return {
            "status": "success",
            "agent_id": agent.id,
            "task_completed": pending_task.task_description,
            "wiki_path": f"/wiki/{agent.id}/index",
        }
    except Exception as e:
        logger.error(f"Deliberation error for agent {agent.id}: {e}")
        agent.status = "error"
        session.commit()
        return {"status": "error", "message": str(e)}
