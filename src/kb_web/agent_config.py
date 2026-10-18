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
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .base import db_session, config
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
            "source_page": "{{ data.page_title }}",
            "source_url": "{{ data.base_url }}",
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
        "user_prompt_template": "Document Content:\n{{ data.article_content }}\n\nUser Question:\n{{ data.question }}",
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
            row = AgentConfiguration(id=agent_id)
            session.add(row)

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
        row.updated_at = now_iso

        session.commit()
        return get_agent_config(agent_id, session=session)
    except Exception as e:
        session.rollback()
        raise e
    finally:
        if owns_session:
            session_ctx.__exit__(None, None, None)
