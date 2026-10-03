"""
Agentic RAG Report Generator Engine for kb-web.

Orchestrates multi-sub-agent retrieval (Tag-searching, Vector query-RAG, Pure text)
paired with tev1 decision gating (via native ollama.systemone with up to 64 questions
per turn) and synthesis report compilation.
"""

from datetime import datetime
import json
import logging
import re
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from .models_orm import FetchedPage, Note, ChunkEmbedding, SettingExternal
from .utils import _get_ollama_client, chunk_text_with_overlap, cosine_similarity

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it",
    "its", "itself", "just", "me", "more", "most", "my", "myself", "no", "nor", "not",
    "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "with", "would", "you", "your", "yours", "yourself", "yourselves"
}


def _extract_query_keywords(query: str) -> List[str]:
    """Tokenizes query into clean alphanumeric keywords excluding common stopwords."""
    words = re.findall(r"[a-zA-Z0-9_\-\.]{2,}", query.lower())
    return [w for w in words if w not in STOPWORDS]


# ==============================================================================
# PIPELINE CONFIGURATION & DEFAULTS
# ==============================================================================

DEFAULT_RAG_CONFIG: Dict[str, Any] = {
    "searches": {
        "use_tag_search": True,
        "use_vector_search": True,
        "use_text_search": True,
    },
    "limits": {
        "tag_limit": 12,
        "vector_limit": 15,
        "text_limit": 15,
        "max_candidates": 24,
        "max_sources": 6,
    },
    "thresholds": {
        "min_similarity": 0.35,
        "min_decision_score": 50.0,
    },
    "models": {
        "synthesis_model": "",
        "decision_model": "tev1",
    },
    "gating_questions": [
        {
            "id": "relevance",
            "enabled": True,
            "type": "noul",
            "name": "Relevance Check",
            "instructions": "Does candidate contain relevant information directly addressing the user's research query?",
            "criteria_true": "Content directly addresses or provides relevant facts for the query.",
            "criteria_false": "Content is off-topic, unrelated, or lacks relevant facts.",
        },
        {
            "id": "code_quality",
            "enabled": True,
            "type": "noul",
            "name": "Code & Commands",
            "instructions": "Does candidate contain actionable code snippets, commands, or concrete implementation details?",
            "criteria_true": "Contains working code, terminal commands, or API schemas.",
            "criteria_false": "No code or commands found.",
        },
        {
            "id": "depth",
            "enabled": True,
            "type": "choice",
            "name": "Technical Depth",
            "instructions": "Rate the technical depth of the candidate.",
            "criteria": {
                "deep": "In-depth architecture, code implementation, or database schema.",
                "overview": "High-level summary, concepts, or introduction.",
                "shallow": "Superficial or tangential mention.",
            },
        },
        {
            "id": "factual",
            "enabled": True,
            "type": "noul",
            "name": "Information Density",
            "instructions": "Does candidate have high factual information density?",
            "criteria_true": "High signal-to-noise ratio with concrete facts and data.",
            "criteria_false": "Low density, boilerplate, or promotional content.",
        },
        {
            "id": "include",
            "enabled": True,
            "type": "noul",
            "name": "Synthesis Recommendation",
            "instructions": "Should candidate be included as primary evidence in the research report?",
            "criteria_true": "Recommended for citation and synthesis in the report.",
            "criteria_false": "Exclude from final report synthesis.",
        },
    ],
}


def get_rag_pipeline_config(session: Session) -> Dict[str, Any]:
    """Retrieves saved RAG pipeline configuration from database, merged with defaults."""
    setting = session.query(SettingExternal).filter_by(key="rag_pipeline_config").first()
    if setting and setting.value:
        try:
            stored = json.loads(setting.value)
            merged = json.loads(json.dumps(DEFAULT_RAG_CONFIG))
            for k, v in stored.items():
                if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
                    merged[k].update(v)
                else:
                    merged[k] = v
            return merged
        except Exception as e:
            logger.warning(f"Failed to parse stored rag_pipeline_config: {e}")
    return json.loads(json.dumps(DEFAULT_RAG_CONFIG))


def save_rag_pipeline_config(session: Session, config_data: Dict[str, Any]) -> Dict[str, Any]:
    """Persists RAG pipeline configuration into database SettingExternal."""
    setting = session.query(SettingExternal).filter_by(key="rag_pipeline_config").first()
    if not setting:
        setting = SettingExternal(key="rag_pipeline_config", value=json.dumps(config_data))
        session.add(setting)
    else:
        setting.value = json.dumps(config_data)
    session.commit()
    return config_data


# ==============================================================================
# 1. RETRIEVAL SUB-AGENTS
# ==============================================================================

def tag_search_subagent(
    session: Session,
    query: str,
    limit: int = 12,
    enabled: bool = True,
) -> List[Dict[str, Any]]:
    """Sub-agent that searches taxonomy and user tags matching or related to query terms."""
    if not enabled:
        return []
    keywords = _extract_query_keywords(query)
    if not keywords:
        return []

    candidates: Dict[str, Dict[str, Any]] = {}

    # 1. Search FetchedPages by tags
    pages = session.query(FetchedPage).filter(
        FetchedPage.tags.isnot(None),
        FetchedPage.tags != "",
        FetchedPage.tags != "[]",
    ).all()

    for p in pages:
        tags_raw = p.tags or ""
        tags_list: List[str] = []
        try:
            parsed = json.loads(tags_raw)
            if isinstance(parsed, list):
                tags_list = [str(t).lower() for t in parsed]
            else:
                tags_list = [str(tags_raw).lower()]
        except Exception:
            tags_list = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]

        matched_tags = []
        for kw in keywords:
            for t in tags_list:
                if kw in t or t in kw:
                    matched_tags.append(t)

        if matched_tags:
            snippet = (p.description or p.md_content or "")[:600]
            candidates[p.url] = {
                "url": p.url,
                "title": p.title or p.url,
                "source_type": "article",
                "matched_tags": list(set(matched_tags)),
                "snippet": snippet,
                "match_type": "tag",
                "score": len(matched_tags) * 0.25,
            }

    # 2. Search Notes by tags
    notes = session.query(Note).filter(
        Note.tags.isnot(None),
        Note.tags != "",
        Note.tags != "[]",
    ).all()

    for n in notes:
        tags_raw = n.tags or ""
        tags_list: List[str] = []
        try:
            parsed = json.loads(tags_raw)
            if isinstance(parsed, list):
                tags_list = [str(t).lower() for t in parsed]
            else:
                tags_list = [str(tags_raw).lower()]
        except Exception:
            tags_list = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]

        matched_tags = []
        for kw in keywords:
            for t in tags_list:
                if kw in t or t in kw:
                    matched_tags.append(t)

        if matched_tags:
            snippet = (n.content or n.wiki_summary or "")[:600]
            candidates[n.url] = {
                "url": n.url,
                "title": n.title or n.url,
                "source_type": "note",
                "matched_tags": list(set(matched_tags)),
                "snippet": snippet,
                "match_type": "tag",
                "score": len(matched_tags) * 0.25,
            }

    results = list(candidates.values())
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def vector_rag_subagent(
    session: Session,
    client: Any,
    query: str,
    active_model: str = "embeddinggemma",
    limit: int = 15,
    enabled: bool = True,
    min_similarity: float = 0.0,
) -> List[Dict[str, Any]]:
    """Sub-agent that embeds search query and performs cosine vector similarity search."""
    if not enabled:
        return []
    prompt = f"search_query: {query}" if ("gemma" in active_model or "nomic" in active_model) else query
    query_vector = None
    try:
        resp = client.embeddings(model=active_model, prompt=prompt)
        query_vector = resp.get("embedding")
    except Exception as e:
        logger.warning(f"Vector RAG embedding generation failed with {active_model}: {e}")
        return []

    if not query_vector:
        return []

    dialect = session.bind.dialect.name
    query_obj = session.query(ChunkEmbedding).filter_by(model_name=active_model)
    results: List[Dict[str, Any]] = []

    if dialect == "postgresql":
        try:
            dist_col = ChunkEmbedding.chunk_vector.cosine_distance(query_vector)
            rows = (
                query_obj.add_columns(dist_col)
                .filter(ChunkEmbedding.chunk_vector.isnot(None))
                .order_by(dist_col.asc())
                .limit(limit)
                .all()
            )
            for chunk, dist in rows:
                if dist is None:
                    continue
                sim = max(0.0, 1.0 - float(dist))
                if sim < min_similarity:
                    continue
                results.append({
                    "url": chunk.source_id,
                    "title": chunk.source_title or chunk.source_id,
                    "source_type": chunk.source_type or "article",
                    "chunk_number": chunk.chunk_number,
                    "snippet": chunk.chunk_content or "",
                    "match_type": "vector",
                    "similarity": round(sim * 100, 1),
                    "score": sim,
                })
        except Exception as err:
            logger.warning(f"pgvector query failed: {err}")
    else:
        # SQLite fallback with cosine similarity
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
            if sim < min_similarity:
                continue
            scored.append((sim, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        for sim, c in scored[:limit]:
            results.append({
                "url": c.source_id,
                "title": c.source_title or c.source_id,
                "source_type": c.source_type or "article",
                "chunk_number": c.chunk_number,
                "snippet": c.chunk_content or "",
                "match_type": "vector",
                "similarity": round(max(0.0, sim) * 100, 1),
                "score": max(0.0, sim),
            })

    return results


def text_search_subagent(
    session: Session,
    query: str,
    limit: int = 15,
    enabled: bool = True,
) -> List[Dict[str, Any]]:
    """Sub-agent that executes pure lexical and full-text keyword matching."""
    if not enabled:
        return []
    keywords = _extract_query_keywords(query)
    if not keywords:
        return []

    candidates: Dict[str, Dict[str, Any]] = {}

    # Query articles
    page_filters = []
    for kw in keywords[:5]:
        pat = f"%{kw}%"
        page_filters.append(FetchedPage.title.ilike(pat))
        page_filters.append(FetchedPage.description.ilike(pat))
        page_filters.append(FetchedPage.md_content.ilike(pat))

    pages = session.query(FetchedPage).filter(or_(*page_filters)).limit(50).all()
    for p in pages:
        content = (p.md_content or p.description or "")
        title_lower = (p.title or "").lower()
        content_lower = content.lower()

        score = 0.0
        for kw in keywords:
            if kw in title_lower:
                score += 2.0
            if kw in content_lower:
                score += 1.0

        candidates[p.url] = {
            "url": p.url,
            "title": p.title or p.url,
            "source_type": "article",
            "snippet": content[:700],
            "match_type": "text",
            "score": score,
        }

    # Query notes
    note_filters = []
    for kw in keywords[:5]:
        pat = f"%{kw}%"
        note_filters.append(Note.title.ilike(pat))
        note_filters.append(Note.content.ilike(pat))
        note_filters.append(Note.wiki_summary.ilike(pat))

    notes = session.query(Note).filter(or_(*note_filters)).limit(50).all()
    for n in notes:
        content = (n.content or n.wiki_summary or "")
        title_lower = (n.title or "").lower()
        content_lower = content.lower()

        score = 0.0
        for kw in keywords:
            if kw in title_lower:
                score += 2.0
            if kw in content_lower:
                score += 1.0

        candidates[n.url] = {
            "url": n.url,
            "title": n.title or n.url,
            "source_type": "note",
            "snippet": content[:700],
            "match_type": "text",
            "score": score,
        }

    results = list(candidates.values())
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def aggregate_candidates(
    tag_results: List[Dict[str, Any]],
    vector_results: List[Dict[str, Any]],
    text_results: List[Dict[str, Any]],
    max_candidates: int = 24,
) -> List[Dict[str, Any]]:
    """Deduplicates candidates across sub-agents and computes multi-source provenance."""
    merged: Dict[str, Dict[str, Any]] = {}

    for item in tag_results:
        u = item["url"]
        merged[u] = {
            "url": u,
            "title": item["title"],
            "source_type": item.get("source_type", "article"),
            "snippet": item.get("snippet", ""),
            "match_types": ["tag"],
            "matched_tags": item.get("matched_tags", []),
            "provenance_count": 1,
            "base_score": item.get("score", 0.5),
        }

    for item in vector_results:
        u = item["url"]
        if u not in merged:
            merged[u] = {
                "url": u,
                "title": item["title"],
                "source_type": item.get("source_type", "article"),
                "snippet": item.get("snippet", ""),
                "match_types": ["vector"],
                "matched_tags": [],
                "provenance_count": 1,
                "base_score": item.get("score", 0.7),
            }
        else:
            if "vector" not in merged[u]["match_types"]:
                merged[u]["match_types"].append("vector")
                merged[u]["provenance_count"] += 1
            if len(item.get("snippet", "")) > len(merged[u]["snippet"]):
                merged[u]["snippet"] = item["snippet"]
            merged[u]["base_score"] += item.get("score", 0.5)

    for item in text_results:
        u = item["url"]
        if u not in merged:
            merged[u] = {
                "url": u,
                "title": item["title"],
                "source_type": item.get("source_type", "article"),
                "snippet": item.get("snippet", ""),
                "match_types": ["text"],
                "matched_tags": [],
                "provenance_count": 1,
                "base_score": item.get("score", 0.5),
            }
        else:
            if "text" not in merged[u]["match_types"]:
                merged[u]["match_types"].append("text")
                merged[u]["provenance_count"] += 1
            merged[u]["base_score"] += 0.5

    candidates = list(merged.values())
    # Sort by provenance count first, then base score
    candidates.sort(key=lambda x: (x["provenance_count"], x["base_score"]), reverse=True)
    return candidates[:max_candidates]


# ==============================================================================
# 2. DECISION SCORING SUB-AGENT (UP TO 64 QUESTIONS PER TURN)
# ==============================================================================

def tev1_scoring_subagent(
    client: Any,
    query: str,
    candidates: List[Dict[str, Any]],
    tev1_model: str = "tev1",
    purpose: str = "",
    gating_questions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Evaluates candidates using decision model via native ollama.systemone with up to 64 questions per turn."""
    if not candidates:
        return []

    # Resolve active gating questions
    if gating_questions is None:
        gating_questions = DEFAULT_RAG_CONFIG.get("gating_questions", [])

    active_questions = [q for q in gating_questions if q.get("enabled", True)]
    if not active_questions:
        # Fallback if all gating questions are disabled
        active_questions = DEFAULT_RAG_CONFIG.get("gating_questions", [])[:3]

    q_count = max(1, len(active_questions))
    # Ollama systemone allows up to 64 questions per turn. Batch accordingly:
    batch_size = max(1, min(len(candidates), 64 // q_count))
    eval_candidates = candidates[:batch_size]

    state: Dict[str, Any] = {
        "user_query": query,
        "research_purpose": purpose or "Synthesizing a factual, high-depth technical research report.",
        "candidate_count": len(eval_candidates),
        "candidates": [
            {
                "index": idx,
                "title": c["title"],
                "url": c["url"],
                "match_types": c.get("match_types", []),
                "excerpt": c["snippet"][:400],
            }
            for idx, c in enumerate(eval_candidates)
        ],
    }

    questions: Dict[str, Dict[str, Any]] = {}
    for idx, c in enumerate(eval_candidates):
        prefix = f"c{idx}"
        for q_def in active_questions:
            qid = q_def.get("id", "q")
            q_key = f"{prefix}_{qid}"
            q_type = q_def.get("type", "noul")
            q_instr = q_def.get("instructions", "")

            if q_type == "choice":
                questions[q_key] = {
                    "type": "choice",
                    "instructions": f"Candidate {idx} ('{c['title'][:40]}'): {q_instr}",
                    "criteria": q_def.get("criteria", {
                        "deep": "Comprehensive, technical, or concrete implementation details.",
                        "overview": "High-level summary or conceptual overview.",
                        "shallow": "Superficial or tangential mention.",
                    }),
                }
            else:
                questions[q_key] = {
                    "type": "noul",
                    "instructions": f"Candidate {idx} ('{c['title'][:40]}'): {q_instr} (Query: '{query[:60]}')",
                    "criteria": {
                        "true": q_def.get("criteria_true", "Satisfies criteria directly."),
                        "false": q_def.get("criteria_false", "Does not satisfy criteria."),
                    },
                }

    scored_candidates: List[Dict[str, Any]] = []
    try:
        resp = client.systemone(
            model=tev1_model,
            state=state,
            questions=questions,
        )
        answers = getattr(resp, "answers", {})

        for idx, c in enumerate(eval_candidates):
            prefix = f"c{idx}"
            scores_dict: Dict[str, Any] = {}
            score_acc = 0.0

            for q_def in active_questions:
                qid = q_def.get("id", "q")
                q_key = f"{prefix}_{qid}"
                ans = answers.get(q_key)

                if q_def.get("type") == "choice":
                    choice_val = getattr(ans, "choice", "overview")
                    scores_dict[qid] = choice_val
                    if choice_val == "deep":
                        score_acc += 1.0
                    elif choice_val == "overview":
                        score_acc += 0.6
                    else:
                        score_acc += 0.2
                else:
                    noul_val = float(getattr(ans, "noul", 0.5))
                    scores_dict[qid] = round(noul_val * 100, 1)
                    score_acc += noul_val

            avg_score = score_acc / q_count
            provenance_boost = min(0.25, c.get("provenance_count", 1) * 0.08)
            composite = min(1.0, (avg_score * 0.8) + provenance_boost)

            eval_summary = {
                "scores": scores_dict,
                "relevance": scores_dict.get("relevance", round(composite * 100, 1)),
                "depth": scores_dict.get("depth", "overview"),
                "has_code": scores_dict.get("code_quality", 0) > 50 if isinstance(scores_dict.get("code_quality"), (int, float)) else ("```" in c.get("snippet", "")),
                "factual": scores_dict.get("factual", 75.0),
                "include": scores_dict.get("include", 100) > 40 if isinstance(scores_dict.get("include"), (int, float)) else True,
                "composite_score": round(composite * 100, 1),
            }

            c["decision_eval"] = eval_summary
            c["tev1_eval"] = eval_summary
            c["final_score"] = composite
            scored_candidates.append(c)

    except Exception as e:
        logger.warning(f"Decision systemone evaluation failed: {e}. Applying fallback ranking.")
        for idx, c in enumerate(eval_candidates):
            prov = c.get("provenance_count", 1)
            comp_score = round(min(100.0, c.get("base_score", 0.5) * 50 + prov * 25), 1)
            eval_summary = {
                "scores": {"fallback": True},
                "relevance": round(min(100.0, c.get("base_score", 0.5) * 60 + prov * 20), 1),
                "depth": "deep" if len(c.get("snippet", "")) > 300 else "overview",
                "has_code": "```" in c.get("snippet", "") or "def " in c.get("snippet", ""),
                "factual": 75.0,
                "include": True,
                "composite_score": comp_score,
            }
            c["decision_eval"] = eval_summary
            c["tev1_eval"] = eval_summary
            c["final_score"] = comp_score / 100.0
            scored_candidates.append(c)

    # Append remaining un-evaluated candidates with default fallback
    for c in candidates[batch_size:]:
        prov = c.get("provenance_count", 1)
        comp_score = round(prov * 20.0, 1)
        eval_summary = {
            "scores": {"fallback": True},
            "relevance": 50.0,
            "depth": "overview",
            "has_code": "```" in c.get("snippet", ""),
            "factual": 50.0,
            "include": False,
            "composite_score": comp_score,
        }
        c["decision_eval"] = eval_summary
        c["tev1_eval"] = eval_summary
        c["final_score"] = prov * 0.2
        scored_candidates.append(c)

    scored_candidates.sort(key=lambda x: x["final_score"], reverse=True)
    return scored_candidates


# ==============================================================================
# 3. REPORT COMPILER & SYNTHESIS SUB-AGENT
# ==============================================================================

def compile_rag_report(
    client: Any,
    query: str,
    vetted_candidates: List[Dict[str, Any]],
    synthesis_model: str = "gemma4:latest",
    purpose: str = "",
    max_sources: int = 6,
    min_decision_score: float = 50.0,
) -> Dict[str, Any]:
    """Compiles vetted multi-agent evidence into a structured Markdown research report."""
    qualified = [
        c for c in vetted_candidates
        if c.get("decision_eval", {}).get("composite_score", 0) >= min_decision_score
    ]
    if not qualified:
        qualified = vetted_candidates

    top_evidence = qualified[:max_sources]

    evidence_text = ""
    for idx, c in enumerate(top_evidence, 1):
        dec = c.get("decision_eval", c.get("tev1_eval", {}))
        evidence_text += f"\n### Source [{idx}]: {c['title']}\n"
        evidence_text += f"- **URL**: {c['url']}\n"
        evidence_text += f"- **Discovery Channels**: {', '.join(c.get('match_types', []))}\n"
        evidence_text += f"- **Relevance Score**: {dec.get('relevance', 'N/A')}%\n"
        evidence_text += f"- **Technical Depth**: {dec.get('depth', 'N/A')}\n"
        evidence_text += f"- **Excerpt**:\n{c.get('snippet', '')[:800]}\n"

    system_prompt = (
        "You are the expert Senior Research & Synthesis Agent for kb-web.\n"
        "Your task is to analyze the user's research query and synthesize the provided vetted evidence "
        "into a comprehensive, publication-grade Markdown research report.\n\n"
        "Structure your output strictly using the following Markdown sections:\n"
        "# [Concise, Descriptive Report Title]\n\n"
        "## Executive Summary\n"
        "[A clear, synthesized overview directly answering the query]\n\n"
        "## Key Findings & Core Insights\n"
        "[Detailed, bulleted breakdown of actionable facts and architectural insights]\n\n"
        "## Technical Architecture & Code Examples\n"
        "[Concrete code snippets, configuration rules, SQL queries, or commands extracted from evidence]\n\n"
        "## Evidence & Citations Table\n"
        "| # | Source Title | Channel | Decision Score | URL |\n"
        "|---|---|---|---|---|\n"
        "[Fill table rows based on sources provided]\n\n"
        "Do not invent false details. If certain specifics are not covered in the evidence, state so clearly."
    )

    user_prompt = (
        f"Research Query: {query}\n"
        f"Research Purpose: {purpose or 'Comprehensive factual report'}\n\n"
        f"Vetted Evidence ({len(top_evidence)} sources):\n"
        f"{evidence_text}\n\n"
        "Please generate the complete Markdown research report now."
    )

    try:
        resp = client.chat(
            model=synthesis_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.2},
        )
        report_md = ""
        if hasattr(resp, "message") and hasattr(resp.message, "content"):
            report_md = resp.message.content
        elif isinstance(resp, dict) and "message" in resp:
            report_md = resp["message"].get("content", "")
        else:
            report_md = str(resp)

        # Extract title
        title_match = re.search(r"^#\s+(.+)$", report_md, re.MULTILINE)
        report_title = title_match.group(1).strip() if title_match else f"Research Report: {query[:60]}"

    except Exception as e:
        logger.warning(f"Report synthesis LLM failed ({synthesis_model}): {e}. Building structured fallback report.")
        report_title = f"Research Report: {query[:60]}"
        rows = []
        for idx, c in enumerate(top_evidence, 1):
            t = c.get("decision_eval", c.get("tev1_eval", {}))
            score_val = t.get("composite_score", t.get("relevance", "N/A"))
            rows.append(
                f"| {idx} | {c['title'][:40]} | {', '.join(c.get('match_types', []))} | {score_val}% | [{c['url'][:30]}]({c['url']}) |"
            )
        table_str = "\n".join(rows)

        report_md = f"""# {report_title}

## Executive Summary
This report was generated using multi-sub-agent retrieval (tag, vector, and lexical search) paired with structured decision scoring across the Knowledge Base.

**Query Objective**: {query}

## Key Findings & Core Insights
- Evaluated **{len(vetted_candidates)}** candidates across taxonomy tags, vector chunk embeddings, and lexical search.
- **{len(top_evidence)}** primary evidence sources were selected through decision scoring.

## Evidence & Citations Table
| # | Source Title | Channel | Decision Score | URL |
|---|---|---|---|---|
{table_str}

*Note: Deep synthesis LLM call encountered a timeout or model error ({e}); source evidence and decision matrix preserved above.*
"""

    return {
        "title": report_title,
        "report_markdown": report_md,
        "sources": [
            {
                "title": c["title"],
                "url": c["url"],
                "source_type": c.get("source_type", "article"),
                "match_types": c.get("match_types", []),
                "decision_score": c.get("decision_eval", {}).get("composite_score", 0),
                "tev1_score": c.get("decision_eval", {}).get("composite_score", 0),
                "relevance": c.get("decision_eval", {}).get("relevance", 0),
                "depth": c.get("decision_eval", {}).get("depth", "overview"),
                "has_code": c.get("decision_eval", {}).get("has_code", False),
            }
            for c in top_evidence
        ],
        "all_candidates_count": len(vetted_candidates),
        "vetted_count": len(top_evidence),
    }


# ==============================================================================
# 4. MASTER WORKFLOW COORDINATOR
# ==============================================================================

def run_agentic_rag_pipeline(
    session: Session,
    query: str,
    purpose: str = "",
    client: Optional[Any] = None,
    synthesis_model: Optional[str] = None,
    active_embedding_model: Optional[str] = None,
    decision_model: Optional[str] = None,
    tev1_model: Optional[str] = None,
    pipeline_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Coordinates full end-to-end multi-agent RAG report generation with configurable pipeline."""
    if client is None:
        client = _get_ollama_client()

    # Load stored or default configuration
    if pipeline_config is None:
        pipeline_config = get_rag_pipeline_config(session)

    searches = pipeline_config.get("searches", {})
    limits = pipeline_config.get("limits", {})
    thresholds = pipeline_config.get("thresholds", {})
    models = pipeline_config.get("models", {})
    gating_questions = pipeline_config.get("gating_questions", [])

    use_tags = searches.get("use_tag_search", True)
    use_vector = searches.get("use_vector_search", True)
    use_text = searches.get("use_text_search", True)

    tag_limit = int(limits.get("tag_limit", 12))
    vector_limit = int(limits.get("vector_limit", 15))
    text_limit = int(limits.get("text_limit", 15))
    max_candidates = int(limits.get("max_candidates", 24))
    max_sources = int(limits.get("max_sources", 6))

    min_similarity = float(thresholds.get("min_similarity", 0.35))
    min_decision_score = float(thresholds.get("min_decision_score", 50.0))

    chosen_decision_model = (
        decision_model
        or tev1_model
        or models.get("decision_model")
        or "tev1"
    )

    if not active_embedding_model:
        setting = session.query(SettingExternal).filter_by(key="active_embedding_model").first()
        active_embedding_model = setting.value if setting else "embeddinggemma"

    chosen_synthesis_model = (
        synthesis_model
        or models.get("synthesis_model")
        or getattr(client, "model", "gemma4:latest")
    )

    logger.info(f"Initiating Configured RAG Pipeline for query: '{query}'")

    # Step 1: Parallel retrieval sub-agents
    tag_hits = tag_search_subagent(session, query, limit=tag_limit, enabled=use_tags)
    vector_hits = vector_rag_subagent(
        session,
        client,
        query,
        active_model=active_embedding_model,
        limit=vector_limit,
        enabled=use_vector,
        min_similarity=min_similarity,
    )
    text_hits = text_search_subagent(session, query, limit=text_limit, enabled=use_text)

    # Step 2: Deduplication and provenance aggregation
    candidates = aggregate_candidates(tag_hits, vector_hits, text_hits, max_candidates=max_candidates)

    # Step 3: Decision scoring & gating (up to 64 questions per turn)
    vetted_candidates = tev1_scoring_subagent(
        client=client,
        query=query,
        candidates=candidates,
        tev1_model=chosen_decision_model,
        purpose=purpose,
        gating_questions=gating_questions,
    )

    # Step 4: Report synthesis
    report_data = compile_rag_report(
        client=client,
        query=query,
        vetted_candidates=vetted_candidates,
        synthesis_model=chosen_synthesis_model,
        purpose=purpose,
        max_sources=max_sources,
        min_decision_score=min_decision_score,
    )

    eval_results = [
        {
            "url": c["url"],
            "title": c["title"],
            "match_types": c.get("match_types", []),
            "eval": c.get("decision_eval", c.get("tev1_eval", {})),
        }
        for c in vetted_candidates[:12]
    ]

    # Post generation event to cross-agent memory board
    try:
        from .agent_memory import post_agent_memory
        post_agent_memory(
            session=session,
            agent_name="RAGAgent",
            channel="rag",
            topic="report_generated",
            content=(
                f"Generated research report '{report_data['title']}' for query '{query[:60]}'. "
                f"Retrieved {len(candidates)} candidates, vetted {len(report_data['sources'])} sources."
            ),
            memory_type="artifact",
            metadata={
                "query": query,
                "title": report_data["title"],
                "sources_count": len(report_data["sources"]),
                "subagent_metrics": {
                    "tag_hits": len(tag_hits),
                    "vector_hits": len(vector_hits),
                    "text_hits": len(text_hits),
                    "total_candidates": len(candidates),
                },
            },
        )
    except Exception as e:
        logger.warning(f"Failed to post RAG agent memory: {e}")

    return {
        "query": query,
        "purpose": purpose,
        "title": report_data["title"],
        "report_markdown": report_data["report_markdown"],
        "subagent_metrics": {
            "tag_hits": len(tag_hits),
            "vector_hits": len(vector_hits),
            "text_hits": len(text_hits),
            "total_candidates": len(candidates),
            "vetted_sources": len(report_data["sources"]),
        },
        "sources": report_data["sources"],
        "decision_evaluations": eval_results,
        "tev1_evaluations": eval_results,
        "pipeline_config": pipeline_config,
    }
