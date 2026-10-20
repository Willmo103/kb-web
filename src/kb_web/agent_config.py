"""
Central Agent Configuration Registry for kb-web.

Exposes every single aspect of every Ollama model call:
- model, call_type (llm, decision, embedding, coding)
- system_prompt, user_prompt_template (with Jinja {{ data.<key> }} support)
- thinking toggle, temperature, num_predict, num_ctx, top_p, top_k
- tools (allowed tool primitives)
- enabled/disabled state
- full control over maintenance_agent (log error agent), curation, crawler, and rag agents.
"""

from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Dict, List, Optional

import jinja2
from sqlalchemy.orm import Session

from .base import db_session, config, _get_ollama_client
from .models_orm import AgentConfiguration
from .config import (
    DEFAULT_WIKI_PROMPT,
    DEFAULT_TAGS_PROMPT,
    DEFAULT_YOUTUBE_WIKI_PROMPT,
    DEFAULT_RAG_SYSTEM_PROMPT,
    DEFAULT_TAXONOMY_SYSTEM_PROMPT,
    DEFAULT_RAG_REPORT_PROMPT,
    DEFAULT_MAINTENANCE_AGENT_PROMPT,
    DEFAULT_WORKSPACE_AGENT_PROMPT,
    DEFAULT_ARTICLE_CHAT_PROMPT,
    DEFAULT_ONTOLOGY_SYNTHESIS_PROMPT,
)

logger = logging.getLogger(__name__)

DEFAULT_AGENT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "maintenance_agent",
        "name": "Error Diagnostics & Maintenance Agent",
        "category": "diagnostics",
        "call_type": "llm",
        "model": "gemma4:e4b",
        "system_prompt": DEFAULT_MAINTENANCE_AGENT_PROMPT,
        "user_prompt_template": "Diagnose and propose remediation for server error:\nMessage: {{ data.error_message }}\nStack Trace:\n{{ data.stack_trace }}\nRequest URL: {{ data.request_url }}",
        "thinking": 0,
        "temperature": 0.2,
        "num_predict": 2048,
        "num_ctx": 4096,
        "top_p": 0.9,
        "top_k": 40,
        "tools": json.dumps(["search_logs", "read_file", "inspect_route", "check_systemctl"]),
        "enabled": 1,
        "extra_options": json.dumps({"auto_diagnose": True, "alert_on_fix": True}),
    },
    {
        "id": "wiki_curation",
        "name": "Wiki Extraction & Synthesis Agent",
        "category": "curation",
        "call_type": "llm",
        "model": "gemma4:e4b",
        "system_prompt": DEFAULT_WIKI_PROMPT,
        "user_prompt_template": "---\nurl: {{ data.url }}\ntitle: {{ data.title }}\n---\n\n{{ data.md_content or data.html_content }}",
        "thinking": 0,
        "temperature": 0.2,
        "num_predict": 4096,
        "num_ctx": 8192,
        "top_p": 0.9,
        "top_k": 40,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
    {
        "id": "tag_curation",
        "name": "Topic Taxonomy & Tag Curation Agent",
        "category": "curation",
        "call_type": "llm",
        "model": "gemma4:e4b",
        "system_prompt": DEFAULT_TAGS_PROMPT,
        "user_prompt_template": "Title: {{ data.title }}\nURL: {{ data.url }}\nContent excerpt:\n{{ data.md_content or data.description }}",
        "thinking": 0,
        "temperature": 0.1,
        "num_predict": 512,
        "num_ctx": 4096,
        "top_p": 0.9,
        "top_k": 40,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
    {
        "id": "link_crawler",
        "name": "Link Discovery Gating Agent (d1)",
        "category": "crawler",
        "call_type": "decision",
        "model": "d1",
        "system_prompt": "Evaluate candidate URLs extracted from web articles for high-value technical ingestion.",
        "user_prompt_template": json.dumps({
            "source_page": "{{ data.title }}",
            "source_url": "{{ data.url }}",
            "candidate_url": "{{ data.candidate_url }}",
            "candidate_anchor": "{{ data.candidate_anchor_text }}"
        }, indent=2),
        "thinking": 0,
        "temperature": None,
        "num_predict": None,
        "num_ctx": 16384,
        "top_p": None,
        "top_k": None,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({
            "questions": {
                "relevance_gate": {
                    "type": "noul",
                    "instructions": "Is this candidate link highly relevant to the technical knowledge base?",
                    "criteria": {
                        "true": "Technical tutorial, specification, architecture doc, or engineering blog post.",
                        "false": "Off-topic marketing, social share link, legal disclosure, or generic navigation."
                    }
                },
                "priority_tier": {
                    "type": "choice",
                    "instructions": "Which priority tier should be assigned for immediate crawling?",
                    "criteria": {
                        "high": "Core architecture specification directly extending document subject.",
                        "medium": "Related documentation or supplemental reference.",
                        "low": "Loosely related or tertiary mention."
                    }
                }
            }
        }),
    },
    {
        "id": "rag_eval",
        "name": "RAG Decision Benchmark Agent (d1)",
        "category": "evaluation",
        "call_type": "decision",
        "model": "d1",
        "system_prompt": "Decision gating evaluating retrieval precision and factual alignment between query and evidence.",
        "user_prompt_template": json.dumps({
            "query": "{{ data.query }}",
            "candidate_title": "{{ data.title }}",
            "candidate_content": "{{ data.content }}"
        }, indent=2),
        "thinking": 0,
        "temperature": None,
        "num_predict": None,
        "num_ctx": 16384,
        "top_p": None,
        "top_k": None,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({
            "questions": {
                "evidence_alignment": {
                    "type": "noul",
                    "instructions": "Does the candidate excerpt directly answer or substantiate the research query?",
                    "criteria": {
                        "true": "Contains concrete technical evidence directly relevant to query.",
                        "false": "Fails to substantiate or lacks relevant technical context."
                    }
                },
                "depth_score": {
                    "type": "score",
                    "instructions": "How thorough is the technical depth provided?",
                    "criteria": ["Superficial mention", "Conceptual summary", "Detailed explanation", "Exhaustive with code/architecture"]
                }
            }
        }),
    },
    {
        "id": "synthetic_qa",
        "name": "Synthetic QA Benchmark Agent",
        "category": "evaluation",
        "call_type": "llm",
        "model": "gemma4:e4b",
        "system_prompt": "You are an expert QA evaluation engineer. Generate 3 to 5 realistic user questions and ground-truth answers based solely on the provided document.",
        "user_prompt_template": "Title: {{ data.title }}\nContent:\n{{ data.md_content }}",
        "thinking": 0,
        "temperature": 0.3,
        "num_predict": 1024,
        "num_ctx": 4096,
        "top_p": 0.9,
        "top_k": 40,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
    {
        "id": "article_chat",
        "name": "Article Document Reading Assistant",
        "category": "chat",
        "call_type": "llm",
        "model": "gemma4:e4b",
        "system_prompt": DEFAULT_ARTICLE_CHAT_PROMPT,
        "user_prompt_template": "Document Content:\n{{ data.md_content or data.content }}\n\nUser Question:\n{{ data.question }}",
        "thinking": 0,
        "temperature": 0.3,
        "num_predict": 2048,
        "num_ctx": 8192,
        "top_p": 0.9,
        "top_k": 40,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
    {
        "id": "workspace_agent",
        "name": "In-Browser IDE Coding Agent",
        "category": "coding",
        "call_type": "coding",
        "model": "gemma4:e4b",
        "system_prompt": DEFAULT_WORKSPACE_AGENT_PROMPT,
        "user_prompt_template": "Project Files:\n{{ data.files_summary }}\n\nRequest:\n{{ data.user_prompt }}",
        "thinking": 0,
        "temperature": 0.2,
        "num_predict": 4096,
        "num_ctx": 8192,
        "top_p": 0.95,
        "top_k": 50,
        "tools": json.dumps(["create_file", "read_file", "edit_file", "delete_file", "list_files", "run_terminal"]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
    {
        "id": "taxonomy_agent",
        "name": "Domain Taxonomy & Ontology Architect",
        "category": "taxonomy",
        "call_type": "llm",
        "model": "gemma4:e4b",
        "system_prompt": DEFAULT_TAXONOMY_SYSTEM_PROMPT,
        "user_prompt_template": "Document Details:\nURL: {{ data.url }}\nTitle: {{ data.title }}\nDescription: {{ data.description }}\nTags: {{ data.tags }}\n\nCurrent Taxonomy Tree:\n{{ data.taxonomy_tree_str }}",
        "thinking": 0,
        "temperature": 0.1,
        "num_predict": 512,
        "num_ctx": 4096,
        "top_p": 0.9,
        "top_k": 40,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
    {
        "id": "rag_synthesis",
        "name": "Senior Research Report Synthesis Agent",
        "category": "rag",
        "call_type": "llm",
        "model": "gemma4:e4b",
        "system_prompt": DEFAULT_RAG_REPORT_PROMPT,
        "user_prompt_template": "Research Query: {{ data.query }}\nPurpose: {{ data.purpose }}\n\nVetted Evidence Table:\n{{ data.evidence_table }}\n\nDetailed Evidence Excerpts:\n{{ data.evidence_chunks }}",
        "thinking": 0,
        "temperature": 0.2,
        "num_predict": 8192,
        "num_ctx": 16384,
        "top_p": 0.9,
        "top_k": 40,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
    {
        "id": "embedding_default",
        "name": "Vector Embedding Indexer",
        "category": "embedding",
        "call_type": "embedding",
        "model": "nomic-embed-text",
        "system_prompt": "Vector Embedding Model for Qdrant and Semantic Search",
        "user_prompt_template": "{{ data.text_to_embed }}",
        "thinking": 0,
        "temperature": None,
        "num_predict": None,
        "num_ctx": 8192,
        "top_p": None,
        "top_k": None,
        "tools": json.dumps([]),
        "enabled": 1,
        "extra_options": json.dumps({}),
    },
]


DATABASE_FIELDS: List[str] = [
    "title",
    "url",
    "description",
    "md_content",
    "content",
    "tags",
    "reading_time_minutes",
    "fetched_at",
]

AGENT_RUNTIME_FIELDS: Dict[str, List[str]] = {
    "maintenance_agent": ["error_message", "stack_trace", "request_url"],
    "link_crawler": ["candidate_url", "candidate_anchor_text"],
    "rag_eval": ["query"],
    "article_chat": ["question"],
    "workspace_agent": ["files_summary", "user_prompt"],
    "taxonomy_agent": ["taxonomy_tree_str"],
    "rag_synthesis": ["query", "purpose", "evidence_table", "evidence_chunks"],
    "embedding_default": ["text_to_embed"],
}


def get_available_fields_for_agent(agent_id: str, template: Optional[str] = None) -> List[str]:
    """Returns valid Jinja parameter keys for an agent, combining standard database fields with agent runtime parameters."""
    fields = list(DATABASE_FIELDS)
    for rf in AGENT_RUNTIME_FIELDS.get(agent_id, []):
        if rf not in fields:
            fields.append(rf)
    if template:
        import re
        tokens = re.findall(r"\{\{\s*data\.([a-zA-Z0-9_]+)\s*\}\}", template)
        for token in tokens:
            if token not in fields:
                fields.append(token)
    return fields


def ensure_default_agent_configs(session: Optional[Session] = None) -> None:
    """Seeds the agent_configurations table with default entries if not already present."""
    owns_session = session is None
    if owns_session:
        session_ctx = db_session()
        session = session_ctx.__enter__()
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        existing_ids = {row[0] for row in session.query(AgentConfiguration.id).all()}

        for d in DEFAULT_AGENT_DEFINITIONS:
            if d["id"] not in existing_ids:
                row = AgentConfiguration(
                    id=d["id"],
                    name=d["name"],
                    category=d.get("category", "curation"),
                    call_type=d.get("call_type", "llm"),
                    model=d.get("model", "gemma4:e4b"),
                    system_prompt=d.get("system_prompt", ""),
                    user_prompt_template=d.get("user_prompt_template", ""),
                    thinking=d.get("thinking", 0),
                    temperature=d.get("temperature"),
                    num_predict=d.get("num_predict"),
                    num_ctx=d.get("num_ctx"),
                    top_p=d.get("top_p"),
                    top_k=d.get("top_k"),
                    tools=d.get("tools", "[]"),
                    enabled=d.get("enabled", 1),
                    extra_options=d.get("extra_options", "{}"),
                    updated_at=now_iso,
                )
                session.add(row)
            else:
                # Migrate any legacy alias variables in existing default agent templates to standard database fields
                existing_row = session.query(AgentConfiguration).filter_by(id=d["id"]).first()
                if existing_row and existing_row.user_prompt_template:
                    tpl = existing_row.user_prompt_template
                    updated_tpl = (
                        tpl.replace("{{ data.page_title }}", "{{ data.title }}")
                           .replace("{{ data.base_url }}", "{{ data.url }}")
                           .replace("{{ data.article_content }}", "{{ data.md_content or data.content }}")
                    )
                    if updated_tpl != tpl:
                        existing_row.user_prompt_template = updated_tpl
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning(f"Failed to seed agent_configurations: {e}")
    finally:
        if owns_session:
            session_ctx.__exit__(None, None, None)


def get_agent_config(agent_id: str, session: Optional[Session] = None) -> Optional[Dict[str, Any]]:
    """Retrieves an agent configuration by ID."""
    owns_session = session is None
    if owns_session:
        session_ctx = db_session()
        session = session_ctx.__enter__()
    try:
        row = session.query(AgentConfiguration).filter_by(id=agent_id).first()
        if not row:
            # Check default definitions fallback
            for d in DEFAULT_AGENT_DEFINITIONS:
                if d["id"] == agent_id:
                    return dict(d)
            return None
        return {
            "id": row.id,
            "name": row.name,
            "category": row.category,
            "call_type": row.call_type,
            "model": row.model,
            "system_prompt": row.system_prompt,
            "user_prompt_template": row.user_prompt_template,
            "thinking": bool(row.thinking),
            "temperature": row.temperature,
            "num_predict": row.num_predict,
            "num_ctx": row.num_ctx,
            "top_p": row.top_p,
            "top_k": row.top_k,
            "tools": json.loads(row.tools or "[]"),
            "enabled": bool(row.enabled),
            "extra_options": json.loads(row.extra_options or "{}"),
            "version": getattr(row, "version", 1) or 1,
            "is_published": bool(getattr(row, "is_published", 0)),
            "published_at": getattr(row, "published_at", None),
            "frozen_snapshot_json": getattr(row, "frozen_snapshot_json", None),
            "available_fields": get_available_fields_for_agent(row.id, row.user_prompt_template),
            "updated_at": row.updated_at,
        }
    finally:
        if owns_session:
            session_ctx.__exit__(None, None, None)


def list_agent_configs(session: Optional[Session] = None) -> List[Dict[str, Any]]:
    """Returns all registered agent configurations."""
    ensure_default_agent_configs(session)
    owns_session = session is None
    if owns_session:
        session_ctx = db_session()
        session = session_ctx.__enter__()
    try:
        rows = session.query(AgentConfiguration).order_by(AgentConfiguration.category, AgentConfiguration.name).all()
        result = []
        for r in rows:
            tools_list = []
            extra_dict = {}
            try:
                tools_list = json.loads(r.tools or "[]")
            except Exception:
                pass
            try:
                extra_dict = json.loads(r.extra_options or "{}")
            except Exception:
                pass
            result.append({
                "id": r.id,
                "name": r.name,
                "category": r.category,
                "call_type": r.call_type,
                "model": r.model,
                "system_prompt": r.system_prompt,
                "user_prompt_template": r.user_prompt_template,
                "thinking": bool(r.thinking),
                "temperature": r.temperature,
                "num_predict": r.num_predict,
                "num_ctx": r.num_ctx,
                "top_p": r.top_p,
                "top_k": r.top_k,
                "tools": tools_list,
                "enabled": bool(r.enabled),
                "extra_options": extra_dict,
                "version": getattr(r, "version", 1) or 1,
                "is_published": bool(getattr(r, "is_published", 0)),
                "published_at": getattr(r, "published_at", None),
                "frozen_snapshot_json": getattr(r, "frozen_snapshot_json", None),
                "available_fields": get_available_fields_for_agent(r.id, r.user_prompt_template),
                "updated_at": r.updated_at,
            })
        return result
    finally:
        if owns_session:
            session_ctx.__exit__(None, None, None)


def save_agent_config(agent_id: str, data: Dict[str, Any], session: Optional[Session] = None) -> Dict[str, Any]:
    """Updates or creates an agent configuration."""
    owns_session = session is None
    if owns_session:
        session_ctx = db_session()
        session = session_ctx.__enter__()
    try:
        row = session.query(AgentConfiguration).filter_by(id=agent_id).first()
        now_iso = datetime.now(timezone.utc).isoformat()
        if not row:
            row = AgentConfiguration(id=agent_id, version=1, is_published=0)
            session.add(row)
        else:
            # If changing configuration on an already published agent, revert is_published to 0 (draft)
            if getattr(row, "is_published", 0) and not data.get("is_published"):
                row.is_published = 0

        if "name" in data:
            row.name = data["name"]
        if "category" in data:
            row.category = data["category"]
        if "call_type" in data:
            row.call_type = data["call_type"]
        if "model" in data:
            row.model = data["model"]
        if "system_prompt" in data:
            row.system_prompt = data["system_prompt"]
        if "user_prompt_template" in data:
            row.user_prompt_template = data["user_prompt_template"]
        if "thinking" in data:
            row.thinking = 1 if data["thinking"] else 0
        if "temperature" in data:
            row.temperature = float(data["temperature"]) if data["temperature"] is not None else None
        if "num_predict" in data:
            row.num_predict = int(data["num_predict"]) if data["num_predict"] is not None else None
        if "num_ctx" in data:
            row.num_ctx = int(data["num_ctx"]) if data["num_ctx"] is not None else None
        if "top_p" in data:
            row.top_p = float(data["top_p"]) if data["top_p"] is not None else None
        if "top_k" in data:
            row.top_k = int(data["top_k"]) if data["top_k"] is not None else None
        if "tools" in data:
            row.tools = json.dumps(data["tools"]) if isinstance(data["tools"], list) else str(data["tools"])
        if "enabled" in data:
            row.enabled = 1 if data["enabled"] else 0
        if "extra_options" in data:
            row.extra_options = json.dumps(data["extra_options"]) if isinstance(data["extra_options"], dict) else str(data["extra_options"])
        if "is_published" in data:
            row.is_published = 1 if data["is_published"] else 0
        if "version" in data and data["version"] is not None:
            row.version = int(data["version"])
        row.updated_at = now_iso

        session.commit()
        return get_agent_config(agent_id, session=session)
    except Exception as e:
        session.rollback()
        raise e
    finally:
        if owns_session:
            session_ctx.__exit__(None, None, None)


def publish_agent_config(agent_id: str, session: Optional[Session] = None) -> Dict[str, Any]:
    """Publishes the current agent configuration as a frozen snapshot commit, incrementing its version."""
    owns_session = session is None
    if owns_session:
        session_ctx = db_session()
        session = session_ctx.__enter__()
    try:
        row = session.query(AgentConfiguration).filter_by(id=agent_id).first()
        if not row:
            raise ValueError(f"Agent '{agent_id}' not found")
        now_iso = datetime.now(timezone.utc).isoformat()
        current_version = getattr(row, "version", 1) or 1
        new_version = current_version + 1
        snapshot = {
            "id": row.id,
            "name": row.name,
            "category": row.category,
            "call_type": row.call_type,
            "model": row.model,
            "system_prompt": row.system_prompt,
            "user_prompt_template": row.user_prompt_template,
            "thinking": bool(row.thinking),
            "temperature": row.temperature,
            "num_predict": row.num_predict,
            "num_ctx": row.num_ctx,
            "top_p": row.top_p,
            "top_k": row.top_k,
            "tools": json.loads(row.tools or "[]"),
            "enabled": bool(row.enabled),
            "extra_options": json.loads(row.extra_options or "{}"),
            "version": new_version,
            "published_at": now_iso,
        }
        row.version = new_version
        row.is_published = 1
        row.published_at = now_iso
        row.frozen_snapshot_json = json.dumps(snapshot)
        row.updated_at = now_iso
        session.commit()
        return get_agent_config(agent_id, session=session)
    except Exception as e:
        session.rollback()
        raise e
    finally:
        if owns_session:
            session_ctx.__exit__(None, None, None)


def delete_agent_config(agent_id: str, session: Optional[Session] = None) -> bool:
    """Deletes an agent configuration from the registry."""
    owns_session = session is None
    if owns_session:
        session_ctx = db_session()
        session = session_ctx.__enter__()
    try:
        row = session.query(AgentConfiguration).filter_by(id=agent_id).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        raise e
    finally:
        if owns_session:
            session_ctx.__exit__(None, None, None)


def test_run_agent_config(agent_id: str, sample_data: Dict[str, Any], session: Optional[Session] = None) -> Dict[str, Any]:
    """Runs a draft or published agent on sample input data to vet outputs before publishing."""
    cfg = get_agent_config(agent_id, session=session)
    if not cfg:
        raise ValueError(f"Agent '{agent_id}' not found")

    call_type = cfg.get("call_type", "llm")
    model_name = cfg.get("model") or "gemma4:e4b"
    user_template = cfg.get("user_prompt_template") or ""
    client = _get_ollama_client(timeout=60.0)

    # Render Jinja template with sample_data
    rendered_input = user_template
    if user_template:
        try:
            t = jinja2.Template(user_template)
            rendered_input = t.render(data=sample_data)
        except Exception as e:
            logger.warning(f"Failed to render user_prompt_template: {e}")

    start_time = time.time()

    if call_type == "decision":
        # SystemOne decision execution
        state = sample_data
        if rendered_input and rendered_input.strip().startswith("{") and rendered_input.strip().endswith("}"):
            try:
                state = json.loads(rendered_input)
            except Exception:
                state = {"rendered_context": rendered_input, **sample_data}
        else:
            state = {"rendered_context": rendered_input, **sample_data}

        extra_opts = cfg.get("extra_options") or {}
        raw_questions = extra_opts.get("questions") or {
            "relevance": {
                "type": "score",
                "instructions": "Rate relevance and suitability for this agent's task domain from 0 to 1.",
            }
        }
        num_ctx = cfg.get("num_ctx") or 16384
        try:
            resp = client.systemone(
                model=model_name,
                state=state,
                questions=raw_questions,
                context_window=num_ctx,
            )
            duration_ms = round((time.time() - start_time) * 1000, 1)
            raw_answers = getattr(resp, "answers", None) or (resp.get("answers") if isinstance(resp, dict) else resp)
            return {
                "status": "success",
                "agent_id": agent_id,
                "call_type": "decision",
                "model": model_name,
                "latency_ms": duration_ms,
                "output": raw_answers,
                "rendered_prompt": str(state),
            }
        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 1)
            return {
                "status": "error",
                "agent_id": agent_id,
                "call_type": "decision",
                "model": model_name,
                "latency_ms": duration_ms,
                "error": str(e),
                "rendered_prompt": str(state),
            }
    else:
        # LLM completion
        system_prompt = cfg.get("system_prompt") or ""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": rendered_input})

        options = {
            "temperature": float(cfg.get("temperature", 0.2) or 0.2),
            "num_predict": int(cfg.get("num_predict", 2048) or 2048),
            "num_ctx": max(2048, int(cfg.get("num_ctx", 8192) or 8192)),
        }
        if cfg.get("top_p") is not None:
            options["top_p"] = float(cfg["top_p"])
        if cfg.get("top_k") is not None:
            options["top_k"] = int(cfg["top_k"])

        try:
            resp = client.chat(
                model=model_name,
                messages=messages,
                options=options,
            )
            duration_ms = round((time.time() - start_time) * 1000, 1)
            msg = getattr(resp, "message", None) if not isinstance(resp, dict) else resp.get("message")
            if isinstance(msg, dict):
                content = msg.get("content", "")
                thinking = msg.get("thinking", "")
            elif msg:
                content = getattr(msg, "content", "")
                thinking = getattr(msg, "thinking", "")
            else:
                content = ""
                thinking = ""
            return {
                "status": "success",
                "agent_id": agent_id,
                "call_type": "llm",
                "model": model_name,
                "latency_ms": duration_ms,
                "output": content,
                "thinking": thinking,
                "rendered_prompt": rendered_input,
            }
        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 1)
            return {
                "status": "error",
                "agent_id": agent_id,
                "call_type": "llm",
                "model": model_name,
                "latency_ms": duration_ms,
                "error": str(e),
                "rendered_prompt": rendered_input,
            }

