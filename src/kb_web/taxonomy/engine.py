"""Taxonomic Classification Engine, Template Renderer, and Abstracted View Layer.

Maps physical assets (web pages, git repos, youtube videos, notes) into 7-tier
taxonomic coordinates (Issue #126) and manages Topic & Sub-Topic governance and
AI assignment (Issue #128).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import or_

from ..base import config as default_config, db_session, _get_ollama_client
from ..models_orm import (
    ContextStatementORM,
    FetchedPage,
    Note,
    TaxonomyEntityORM,
    TaxonomyItem,
    TopicGovernanceORM,
    WorkerJobExecution,
)
from ..utils import ensure_model_available
from .models import TaxonomyEntityRecord, TaxonomyLevel, TaxonomyPath
from .steered_tree import (
    SteeredTaxonomyNode,
    SteeredTaxonomyTreeManager,
    get_steered_tree_manager,
)

logger = logging.getLogger("kb_web.taxonomy.engine")


def slugify(text: str) -> str:
    """Produce a clean lowercase slug with alphanumeric chars and hyphens/underscores."""
    if not text:
        return "unnamed"
    s = re.sub(r"[^\w\s-]", "", text.strip().lower())
    s = re.sub(r"[-\s]+", "_", s)
    return s[:64] or "unnamed"


def clean_tier_token(text: str, default: str = "General") -> str:
    """Sanitize a single taxonomic tier token so '/' never splits a single tier."""
    if not text or not str(text).strip():
        return default
    cleaned = str(text).strip().replace("::", "-").replace("/", "-").replace(">", "-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:64] or default


def split_subtopic_levels(
    sub_topic: Optional[str],
    tags: Optional[List[str]] = None,
    fallback_l1: str = "General",
    fallback_l2: str = "Overview",
) -> Tuple[str, str]:
    """Split a 2-level sub-topic string into (Phylum, Class) coordinates (Issue #126)."""
    if sub_topic and str(sub_topic).strip():
        raw = str(sub_topic).strip().replace(" > ", "/").replace(">", "/").replace("::", "/")
        parts = [p.strip() for p in raw.split("/") if p.strip()]
        if len(parts) >= 2:
            return clean_tier_token(parts[0], fallback_l1), clean_tier_token(parts[1], fallback_l2)
        if len(parts) == 1:
            l1 = clean_tier_token(parts[0], fallback_l1)
            l2 = slugify(tags[0]) if tags and len(tags) > 0 else fallback_l2
            if l2.lower() == l1.lower():
                l2 = slugify(tags[1]) if tags and len(tags) > 1 else fallback_l2
            return l1, clean_tier_token(l2, fallback_l2)

    if tags and len(tags) >= 2:
        return clean_tier_token(tags[0], fallback_l1), clean_tier_token(tags[1], fallback_l2)
    if tags and len(tags) == 1:
        return clean_tier_token(tags[0], fallback_l1), fallback_l2
    return fallback_l1, fallback_l2


def infer_default_topic(
    url: str = "",
    title: str = "",
    tags: Optional[List[str]] = None,
    description: str = "",
    allowed_topics: Optional[List[str]] = None,
    denied_topics: Optional[set[str]] = None,
) -> str:
    """Heuristically infer a top-level general topic (Kingdom) from metadata when AI is not used."""
    denied_lower = {d.lower() for d in (denied_topics or set())}
    allowed = [
        t for t in (allowed_topics or default_config.get_allowed_topics_list())
        if t.lower() not in denied_lower
    ]
    if not allowed:
        allowed = ["Reference", "Resource", "Blogpost/Article", "Software Documentation", "News", "Hobby/Leisure"]

    combined = f"{url} {title} {' '.join(tags or [])} {description[:300]}".lower()

    def _pick(preferred: str) -> str:
        for a in allowed:
            if a.lower() == preferred.lower() or preferred.lower() in a.lower():
                return a
        return allowed[0]

    if any(k in combined for k in ("docs.", "documentation", "api reference", "sdk", "library", "manual", "docstring", "python.org", "supabase")):
        return _pick("Software Documentation")
    if any(k in combined for k in ("news", "breaking", "press release", "announces", "reuters", "associated press", "activism", "removal")):
        return _pick("News")
    if any(k in combined for k in ("fishing", "ultralight", "hobby", "leisure", "gaming", "cooking", "camping", "sport", "outdoors")):
        return _pick("Hobby/Leisure")
    if any(k in combined for k in ("wiki", "reference", "glossary", "specification", "rfc", "standard", "cheatsheet")):
        return _pick("Reference")
    if any(k in combined for k in ("github.com", "repo://", "repository", "dataset", "tool", "resource", "awesome-", "youtube.com", "youtu.be")):
        return _pick("Resource")
    return _pick("Blogpost/Article")


def _unique_article_tiers(url_or_id: str, title: Optional[str], prefix: str = "art") -> Tuple[str, str]:
    """Generate article-unique 6th (Genus) and 7th (Species) tier identifiers (Issue #126)."""
    seed = (url_or_id or title or "entity").strip()
    short_hash = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6]
    base_slug = slugify(title or urlparse(url_or_id).path or prefix)[:32]
    genus = f"{prefix}_{base_slug[:20]}_{short_hash}"
    species = f"{base_slug}_{short_hash}"
    return genus, species


class TaxonomyClassifier:
    """Classifies physical context assets into 7-tier taxonomic coordinates (Issue #126).

    Tiers:
    1. Kingdom: General Topic ('News', 'Software Documentation', 'Blogpost/Article', 'Reference', 'Resource', 'Hobby/Leisure')
    2. Phylum: Sub-Topic Level 1
    3. Class: Sub-Topic Level 2
    4. Order: Content Source / Domain / Publisher
    5. Family: Content Theme / Primary Tag Cluster
    6. Genus: Unique Article Structural Identifier
    7. Species: Unique Article Concrete Identifier
    """

    @staticmethod
    def classify_article(
        url: str,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        description: Optional[str] = None,
        topic: Optional[str] = None,
        sub_topic: Optional[str] = None,
    ) -> TaxonomyPath:
        """Infer 7-tier taxonomic coordinates for an ingested web article."""
        parsed = urlparse(url or "")
        host = (parsed.netloc or "web").replace(".", "_").replace(":", "_").lower()
        if host.startswith("www_"):
            host = host[4:]

        # Lookup stored topic/sub_topic from FetchedPage if not explicitly passed
        resolved_topic = topic
        resolved_sub_topic = sub_topic
        if (not resolved_topic or not resolved_sub_topic) and url:
            try:
                with db_session() as session:
                    fp = session.query(FetchedPage).filter_by(url=url).first()
                    if fp:
                        if not resolved_topic and fp.topic:
                            resolved_topic = fp.topic
                        if not resolved_sub_topic and fp.sub_topic:
                            resolved_sub_topic = fp.sub_topic
            except Exception:
                pass

        if not resolved_topic:
            resolved_topic = infer_default_topic(
                url=url,
                title=title or "",
                tags=tags,
                description=description or "",
            )

        kingdom = clean_tier_token(resolved_topic, "Blogpost-Article")
        phylum, class_ = split_subtopic_levels(
            resolved_sub_topic,
            tags=tags,
            fallback_l1=slugify(tags[0]) if tags else slugify(host),
            fallback_l2=slugify(tags[1]) if (tags and len(tags) > 1) else "article_topic",
        )

        family = slugify(tags[0]) if tags and len(tags) > 0 else "general"
        genus, species = _unique_article_tiers(url, title, prefix="article")

        return TaxonomyPath(
            kingdom=kingdom,
            phylum=phylum,
            class_=class_,
            order=slugify(host),
            family=family,
            genus=genus,
            species=species,
        )

    @staticmethod
    def classify_git_repo(
        repo_name: str,
        remote_url: Optional[str] = None,
        path: Optional[str] = None,
        topic: Optional[str] = None,
        sub_topic: Optional[str] = None,
    ) -> TaxonomyPath:
        """Infer 7-tier taxonomic coordinates for a git repository."""
        clean_name = slugify(repo_name or "repo")
        kingdom = clean_tier_token(topic or "Software Documentation", "Software Documentation")
        phylum, class_ = split_subtopic_levels(
            sub_topic,
            fallback_l1="Source-Repository",
            fallback_l2="rest_api" if "api" in clean_name else "cli_command",
        )
        genus, species = _unique_article_tiers(remote_url or repo_name, repo_name, prefix="repo")
        return TaxonomyPath(
            kingdom=kingdom,
            phylum=phylum,
            class_=class_,
            order=clean_name,
            family="repository",
            genus=genus,
            species=species,
        )

    @staticmethod
    def classify_youtube_video(
        url: str,
        title: Optional[str] = None,
        creator: Optional[str] = None,
        topic: Optional[str] = None,
        sub_topic: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> TaxonomyPath:
        """Infer 7-tier taxonomic coordinates for a YouTube video."""
        creator_slug = slugify(creator or "youtube_creator")
        resolved_topic = topic or infer_default_topic(url=url, title=title or "", tags=tags)
        kingdom = clean_tier_token(resolved_topic, "Resource")
        phylum, class_ = split_subtopic_levels(
            sub_topic,
            tags=tags,
            fallback_l1="Video-Media",
            fallback_l2=creator_slug,
        )
        genus, species = _unique_article_tiers(url, title, prefix="video")
        return TaxonomyPath(
            kingdom=kingdom,
            phylum=phylum,
            class_=class_,
            order=creator_slug,
            family=slugify(tags[0]) if tags else "video_stream",
            genus=genus,
            species=species,
        )

    @staticmethod
    def classify_note(
        title: str,
        tags: Optional[List[str]] = None,
        topic: Optional[str] = None,
        sub_topic: Optional[str] = None,
    ) -> TaxonomyPath:
        """Infer 7-tier taxonomic coordinates for a note or research memo."""
        family = slugify(tags[0]) if tags and len(tags) > 0 else "general"
        kingdom = clean_tier_token(topic or "Reference", "Reference")
        phylum, class_ = split_subtopic_levels(
            sub_topic,
            tags=tags,
            fallback_l1=slugify(tags[0]) if tags else "Knowledge-Notes",
            fallback_l2=slugify(tags[1]) if (tags and len(tags) > 1) else "daily_notes",
        )
        genus, species = _unique_article_tiers(f"note://{title}", title, prefix="note")
        return TaxonomyPath(
            kingdom=kingdom,
            phylum=phylum,
            class_=class_,
            order="kb_web",
            family=family,
            genus=genus,
            species=species,
        )


# ---------------------------------------------------------------------------
# Issue #128: Topic & Sub-Topic Governance, AI Assignment, Approval & Denial
# ---------------------------------------------------------------------------


def ensure_default_topics_seeded(config_obj: Any = None) -> List[str]:
    """Seed default allowed top-level topics into TopicGovernanceORM if not present."""
    cfg = config_obj or default_config
    allowed_list = cfg.get_allowed_topics_list()
    now_iso = datetime.now(timezone.utc).isoformat()

    with db_session() as session:
        existing_rows = session.query(TopicGovernanceORM).all()
        existing_by_lower = {r.name.lower(): r for r in existing_rows}

        for topic_name in allowed_list:
            clean_name = topic_name.strip()
            if not clean_name:
                continue
            if clean_name.lower() not in existing_by_lower:
                rec = TopicGovernanceORM(
                    name=clean_name,
                    level="topic",
                    parent_topic=None,
                    status="allowed",
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                session.add(rec)
                existing_by_lower[clean_name.lower()] = rec
        session.commit()

        final_allowed = [
            r.name
            for r in session.query(TopicGovernanceORM)
            .filter_by(level="topic", status="allowed")
            .order_by(TopicGovernanceORM.id.asc())
            .all()
        ]
        return final_allowed or allowed_list


def get_topic_governance_summary(config_obj: Any = None) -> Dict[str, Any]:
    """Return all governed topics & sub-topics, their approval status, and article counts."""
    allowed_topics = ensure_default_topics_seeded(config_obj)

    with db_session() as session:
        gov_rows = (
            session.query(TopicGovernanceORM)
            .order_by(TopicGovernanceORM.level.asc(), TopicGovernanceORM.name.asc())
            .all()
        )
        pages = session.query(
            FetchedPage.url,
            FetchedPage.title,
            FetchedPage.topic,
            FetchedPage.sub_topic,
            FetchedPage.topic_status,
        ).all()

        topic_counts: Dict[str, int] = {}
        subtopic_counts: Dict[str, int] = {}
        unassigned_count = 0
        pending_count = 0
        approved_count = 0
        unassigned_items: List[Dict[str, str]] = []
        pending_items: List[Dict[str, str]] = []

        for url, title, top, sub, status in pages:
            st = (status or "unassigned").lower()
            if not top or st == "unassigned":
                unassigned_count += 1
                if len(unassigned_items) < 50:
                    unassigned_items.append({"url": url, "title": title or url})
            elif st == "pending":
                pending_count += 1
                if len(pending_items) < 50:
                    pending_items.append({
                        "url": url,
                        "title": title or url,
                        "topic": top or "",
                        "sub_topic": sub or "",
                    })
            elif st == "approved":
                approved_count += 1

            if top:
                topic_counts[top] = topic_counts.get(top, 0) + 1
            if sub:
                subtopic_counts[sub] = subtopic_counts.get(sub, 0) + 1

        topics_list: List[Dict[str, Any]] = []
        denied_topics: List[str] = []
        for r in gov_rows:
            if r.status == "denied":
                denied_topics.append(r.name)
            cnt = topic_counts.get(r.name, 0) if r.level == "topic" else subtopic_counts.get(r.name, 0)
            topics_list.append({
                "id": r.id,
                "name": r.name,
                "level": r.level,
                "parent_topic": r.parent_topic,
                "status": r.status,
                "article_count": cnt,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            })

        return {
            "status": "success",
            "allowed_topics": allowed_topics,
            "denied_topics": denied_topics,
            "topics": topics_list,
            "unassigned_count": unassigned_count,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "unassigned_items": unassigned_items,
            "pending_items": pending_items,
        }


def _prompt_choice_selection(
    level: str,
    parent_name: Optional[str],
    candidates: List[SteeredTaxonomyNode],
    url: str,
    title: Optional[str],
    content: Optional[str],
    tags: Optional[List[str]],
    client: Any,
    model_name: str,
) -> SteeredTaxonomyNode:
    if len(candidates) == 1:
        return candidates[0]

    candidate_map = {c.id: c for c in candidates}
    candidate_lines = []
    for c in candidates:
        gating_clause = f" [Gating Criteria: {'; '.join(c.gating_questions)}]" if c.gating_questions else ""
        desc_clause = f" - {c.description}" if c.description else ""
        candidate_lines.append(f"- Candidate ID: '{c.id}' | Display Name: '{c.name}'{desc_clause}{gating_clause}")

    parent_clause = f" under '{parent_name}'" if parent_name else ""
    sys_prompt = (
        f"You are a Hierarchical Taxonomic Decision Model selecting the best {level.upper()} coordinate{parent_clause}.\n"
        "Strictly evaluate candidate descriptions and enforce all Gating Criteria.\n"
        "ALLOWED CANDIDATES:\n" + "\n".join(candidate_lines) + "\n\n"
        "Rules:\n"
        "1. Select EXACTLY ONE 'selected_id' from the candidate IDs provided.\n"
        "2. Do NOT invent new categories outside the candidate choices.\n"
        "3. If an item fails a candidate's gating criteria, it must not be chosen.\n"
        "4. Respond with valid JSON only: {\"selected_id\": \"<id>\", \"rationale\": \"...\"}"
    )
    user_prompt = (
        f"URL: {url}\n"
        f"Title: {title or url}\n"
        f"Tags: {', '.join(tags or [])}\n"
        f"Content Snippet:\n{(content or '')[:1500]}\n\n"
        "Return JSON with selected_id:"
    )
    try:
        if client:
            ensure_model_available(client, model_name)
            resp = client.chat(
                model=model_name,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": 0.0},
            )
            msg_content = ""
            if isinstance(resp, dict):
                msg_content = resp.get("message", {}).get("content", "")
            elif hasattr(resp, "message") and hasattr(resp.message, "content"):
                msg_content = resp.message.content

            if msg_content:
                cleaned = msg_content.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.splitlines()
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    cleaned = "\n".join(lines).strip()
                parsed = json.loads(cleaned)
                selected_id = str(parsed.get("selected_id", "")).strip()
                if selected_id in candidate_map:
                    return candidate_map[selected_id]
                for cid, cnode in candidate_map.items():
                    if cnode.name.lower() == selected_id.lower():
                        return cnode
    except Exception as e:
        logger.debug(f"Choice selection model invocation failed, using heuristic: {e}")

    # Heuristic fallback among valid candidates:
    combined = f"{url} {title or ''} {' '.join(tags or [])} {(content or '')[:800]}".lower()
    for c in candidates:
        if c.name.lower() in combined or any(q.lower() in combined for q in c.gating_questions):
            return c
    return candidates[0]


def classify_steered_hierarchical(
    url: str,
    title: Optional[str] = None,
    md_content: Optional[str] = None,
    tags: Optional[List[str]] = None,
    config_obj: Any = None,
    client: Any = None,
    enforce_frozen: bool = True,
) -> Dict[str, Any]:
    """Classifies an item strictly layer-by-layer through the user-steered taxonomy tree.

    1. Checks candidate choices at each level (Kingdom -> Phylum -> Class).
    2. Excludes nodes where URL matches blacklisted domains.
    3. Prompts decision model with choice set and gating questions.
    4. Enforces frozen tree boundaries (no dynamic arbitrary categories under frozen nodes).
    5. Applies node lifecycle actions ('freeze' -> is_frozen=1, 'refetch' -> marks periodic interval).
    6. Persists taxonomy entity, updates page topic/sub_topic, and coordinates context statements.
    """
    cfg = config_obj or default_config
    ollama_client = client or _get_ollama_client()
    tree_mgr = get_steered_tree_manager()

    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=url).first()
        if page:
            if not title:
                title = page.title or url
            if not md_content:
                md_content = page.description or page.md_content or ""
            if tags is None and page.tags:
                try:
                    parsed_t = json.loads(page.tags)
                    if isinstance(parsed_t, list):
                        tags = parsed_t
                except Exception:
                    tags = [t.strip() for t in str(page.tags).split(",") if t.strip()]

    tags = tags or []
    model_name = getattr(cfg, "ollama_model", "gemma4:latest")
    parsed_url = urlparse(url or "")
    domain = parsed_url.netloc or ""

    # Layer 1: Kingdom candidates
    kingdom_candidates = tree_mgr.get_valid_children(None, url_or_domain=domain)
    if not kingdom_candidates:
        with db_session() as session:
            fp = session.query(FetchedPage).filter_by(url=url).first()
            if fp:
                fp.topic_status = f"blacklisted_domain: {domain}"
            session.commit()
        return {
            "status": "blacklisted",
            "url": url,
            "reason": f"Domain {domain} is blacklisted across root taxonomy nodes",
            "topic": None,
            "sub_topic": None,
            "topic_status": f"blacklisted_domain: {domain}",
        }

    selected_kingdom = _prompt_choice_selection(
        level="kingdom",
        parent_name=None,
        candidates=kingdom_candidates,
        url=url,
        title=title,
        content=md_content,
        tags=tags,
        client=ollama_client,
        model_name=model_name,
    )
    assigned_topic = selected_kingdom.name

    # Layer 2: Phylum candidates
    phylum_candidates = tree_mgr.get_valid_children(selected_kingdom, url_or_domain=domain)
    selected_phylum: Optional[SteeredTaxonomyNode] = None
    if phylum_candidates:
        selected_phylum = _prompt_choice_selection(
            level="phylum",
            parent_name=selected_kingdom.name,
            candidates=phylum_candidates,
            url=url,
            title=title,
            content=md_content,
            tags=tags,
            client=ollama_client,
            model_name=model_name,
        )
        assigned_phylum = selected_phylum.name
    else:
        if selected_kingdom.is_frozen and enforce_frozen:
            assigned_phylum = "General"
        else:
            l1, _ = split_subtopic_levels(None, tags=tags, fallback_l1=slugify(tags[0]) if tags else "General")
            assigned_phylum = l1

    # Layer 3: Class candidates
    class_candidates = (
        tree_mgr.get_valid_children(selected_phylum, url_or_domain=domain)
        if selected_phylum
        else []
    )
    selected_class: Optional[SteeredTaxonomyNode] = None
    if class_candidates:
        selected_class = _prompt_choice_selection(
            level="class",
            parent_name=selected_phylum.name if selected_phylum else assigned_phylum,
            candidates=class_candidates,
            url=url,
            title=title,
            content=md_content,
            tags=tags,
            client=ollama_client,
            model_name=model_name,
        )
        assigned_class = selected_class.name
    else:
        if (selected_phylum and selected_phylum.is_frozen) or (selected_kingdom.is_frozen and enforce_frozen):
            assigned_class = "Overview"
        else:
            _, l2 = split_subtopic_levels(
                None,
                tags=tags,
                fallback_l2=slugify(tags[1]) if (tags and len(tags) > 1) else clean_tier_token(domain.split(".")[0] if domain else "Overview", "Overview"),
            )
            assigned_class = l2

    assigned_sub_topic = f"{assigned_phylum}/{assigned_class}"

    # Determine Lifecycle Action:
    # Priority: leaf class -> phylum -> kingdom
    effective_lifecycle = "none"
    refetch_hours = None
    for node in [selected_class, selected_phylum, selected_kingdom]:
        if node and node.lifecycle_action != "none":
            effective_lifecycle = node.lifecycle_action
            refetch_hours = node.refetch_interval_hours
            break

    now_iso = datetime.now(timezone.utc).isoformat()
    topic_status = "approved"

    with db_session() as session:
        top_row = (
            session.query(TopicGovernanceORM)
            .filter(TopicGovernanceORM.name.ilike(assigned_topic))
            .first()
        )
        if not top_row:
            top_row = TopicGovernanceORM(
                name=assigned_topic,
                level="topic",
                parent_topic=None,
                status="allowed",
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(top_row)

        sub_row = (
            session.query(TopicGovernanceORM)
            .filter(TopicGovernanceORM.name.ilike(assigned_sub_topic))
            .first()
        )
        if not sub_row:
            sub_row = TopicGovernanceORM(
                name=assigned_sub_topic,
                level="sub_topic",
                parent_topic=assigned_topic,
                status="allowed",
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(sub_row)

        fp = session.query(FetchedPage).filter_by(url=url).first()
        if fp:
            fp.topic = assigned_topic
            fp.sub_topic = assigned_sub_topic
            fp.topic_status = topic_status
            if effective_lifecycle == "freeze":
                fp.is_frozen = 1
            elif effective_lifecycle == "refetch":
                fp.is_frozen = 0

        session.commit()

    if "youtube.com" in url or "youtu.be" in url:
        tax_path = TaxonomyClassifier.classify_youtube_video(
            url=url,
            title=title,
            topic=assigned_topic,
            sub_topic=assigned_sub_topic,
            tags=tags,
        )
    else:
        tax_path = TaxonomyClassifier.classify_article(
            url=url,
            title=title,
            tags=tags,
            description=md_content,
            topic=assigned_topic,
            sub_topic=assigned_sub_topic,
        )

    entity_attributes = {
        "title": title or url,
        "tags": tags,
        "topic": assigned_topic,
        "sub_topic": assigned_sub_topic,
        "topic_status": topic_status,
        "source_type": "video" if ("youtube.com" in url or "youtu.be" in url) else "article",
        "lifecycle_action": effective_lifecycle,
        "refetch_interval_hours": refetch_hours,
        "steered_nodes": {
            "kingdom": selected_kingdom.id,
            "phylum": selected_phylum.id if selected_phylum else None,
            "class": selected_class.id if selected_class else None,
        },
    }

    TaxonomyEngine().register_entity(
        taxonomy=tax_path,
        physical_location=url,
        attributes=entity_attributes,
    )

    try:
        from ..context_mesh.store import ContextStore
        ContextStore().update_statements_taxonomy_for_source(url, tax_path.to_path_string("/"))
    except Exception:
        pass

    return {
        "status": "success",
        "url": url,
        "topic": assigned_topic,
        "sub_topic": assigned_sub_topic,
        "topic_status": topic_status,
        "taxonomy_path": tax_path.to_path_string("/"),
        "lifecycle_action": effective_lifecycle,
        "refetch_interval_hours": refetch_hours,
    }


def nuke_all_taxonomy(confirm: bool = False) -> Dict[str, Any]:
    """Completely resets and wipes all taxonomy entries across all items."""
    if not confirm:
        return {
            "status": "error",
            "message": "Nuke confirmation parameter 'confirm=True' is required to wipe all taxonomy data.",
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    with db_session() as session:
        deleted_entities = session.query(TaxonomyEntityORM).delete(synchronize_session=False)
        deleted_items = session.query(TaxonomyItem).delete(synchronize_session=False)
        reset_pages = session.query(FetchedPage).update(
            {
                FetchedPage.topic: None,
                FetchedPage.sub_topic: None,
                FetchedPage.topic_status: "unassigned",
            },
            synchronize_session=False,
        )
        reset_statements = session.query(ContextStatementORM).update(
            {
                ContextStatementORM.canonical_path: "unassigned",
                ContextStatementORM.kingdom: None,
                ContextStatementORM.phylum: None,
                ContextStatementORM.class_name: None,
                ContextStatementORM.order_name: None,
                ContextStatementORM.family: None,
                ContextStatementORM.genus: None,
                ContextStatementORM.species: None,
            },
            synchronize_session=False,
        )
        session.commit()

    logger.info(
        f"Taxonomy nuked: {deleted_entities} entities deleted, {deleted_items} items deleted, "
        f"{reset_pages} pages reset, {reset_statements} statements reset."
    )
    return {
        "status": "success",
        "action": "taxonomy_nuked",
        "deleted_entities_count": deleted_entities,
        "deleted_items_count": deleted_items,
        "reset_pages_count": reset_pages,
        "reset_statements_count": reset_statements,
        "timestamp": now_iso,
    }


def assign_topic_and_subtopic(
    url: str,
    title: Optional[str] = None,
    md_content: Optional[str] = None,
    tags: Optional[List[str]] = None,
    config_obj: Any = None,
    client: Any = None,
    use_steered_hierarchy: bool = True,
) -> Dict[str, Any]:
    """Pipeline & Worker step:
    1. By default, executes steered layer-by-layer hierarchical decision classification.
    2. Enforces user tree governance, per-node gating questions, domain blacklists, and lifecycle rules.
    3. Falls back gracefully to heuristic/legacy path if needed.
    """
    if use_steered_hierarchy:
        try:
            return classify_steered_hierarchical(
                url=url,
                title=title,
                md_content=md_content,
                tags=tags,
                config_obj=config_obj,
                client=client,
            )
        except Exception as e:
            logger.warning(f"Steered hierarchical classification encountered error, falling back: {e}")
    cfg = config_obj or default_config
    ollama_client = client or _get_ollama_client()
    allowed_topics = ensure_default_topics_seeded(cfg)

    with db_session() as session:
        gov_rows = session.query(TopicGovernanceORM).all()
        denied_set = {r.name.strip().lower() for r in gov_rows if r.status == "denied"}
        allowed_map = {
            r.name.strip().lower(): r.name.strip()
            for r in gov_rows
            if r.level == "topic" and r.status == "allowed"
        }
        for at in allowed_topics:
            if at.strip().lower() not in denied_set:
                allowed_map[at.strip().lower()] = at.strip()

        page = session.query(FetchedPage).filter_by(url=url).first()
        if page:
            if not title:
                title = page.title or url
            if not md_content:
                md_content = page.description or page.md_content or ""
            if tags is None and page.tags:
                try:
                    parsed_t = json.loads(page.tags)
                    if isinstance(parsed_t, list):
                        tags = parsed_t
                except Exception:
                    tags = [t.strip() for t in str(page.tags).split(",") if t.strip()]

    tags = tags or []
    allowed_display = ", ".join(allowed_map.values())
    denied_display = ", ".join(sorted(denied_set)) if denied_set else "None"

    assigned_topic = ""
    assigned_sub_topic = ""

    # Step 1 & 3: Prompt LLM for Topic and 2-level Sub-Topic
    system_prompt = (
        "You are a Taxonomic Classification Agent. "
        "Assign a Top-Level General Topic (Kingdom) and a 2-Level Sub-Topic (Phylum/Class) to the provided item.\n"
        f"ALLOWED TOP-LEVEL TOPICS: [{allowed_display}]\n"
        f"DENIED / FORBIDDEN TOPICS & SUB-TOPICS (NEVER USE THESE): [{denied_display}]\n"
        "Rules:\n"
        "1. 'topic' should be selected from ALLOWED TOP-LEVEL TOPICS whenever applicable.\n"
        "2. 'sub_topic' MUST be a 2-level hierarchy separated by a slash '/', e.g. 'Fishing/Ultralight', 'Activism/Removal-Efforts', 'Official-Documentation/Supabase'.\n"
        "3. Never output any topic or sub-topic listed in DENIED / FORBIDDEN.\n"
        "4. Output valid JSON only: {\"topic\": \"...\", \"sub_topic\": \"Category/Subcategory\"}"
    )
    user_prompt = (
        f"URL: {url}\n"
        f"Title: {title or url}\n"
        f"Tags: {', '.join(tags)}\n"
        f"Content Snippet:\n{(md_content or '')[:2000]}\n\n"
        "Return JSON with 'topic' and 'sub_topic':"
    )

    model_name = getattr(cfg, "ollama_model", "gemma4:latest")
    try:
        ensure_model_available(ollama_client, model_name)
        resp = ollama_client.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.1},
        )
        msg_content = ""
        if isinstance(resp, dict):
            msg_content = resp.get("message", {}).get("content", "")
        elif hasattr(resp, "message") and hasattr(resp.message, "content"):
            msg_content = resp.message.content

        if msg_content:
            cleaned = msg_content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                assigned_topic = str(parsed.get("topic", "")).strip()
                assigned_sub_topic = str(parsed.get("sub_topic", "")).strip()
    except Exception:
        pass

    # Step 2: Validate against allowed_topics and denied_set (Fallback if offline or denied)
    if not assigned_topic or assigned_topic.lower() in denied_set:
        assigned_topic = infer_default_topic(
            url=url,
            title=title or "",
            tags=tags,
            description=md_content or "",
            allowed_topics=list(allowed_map.values()),
            denied_topics=denied_set,
        )

    # Normalize to canonical allowed topic casing if matched
    if assigned_topic.lower() in allowed_map:
        assigned_topic = allowed_map[assigned_topic.lower()]

    # Validate 2-level sub_topic
    l1, l2 = split_subtopic_levels(
        assigned_sub_topic,
        tags=tags,
        fallback_l1=clean_tier_token(tags[0], "General") if tags else "General",
        fallback_l2=clean_tier_token(tags[1], "Overview") if (tags and len(tags) > 1) else clean_tier_token(urlparse(url).netloc.split(".")[0] if urlparse(url).netloc else "Overview", "Overview"),
    )
    candidate_sub = f"{l1}/{l2}"
    if (
        candidate_sub.lower() in denied_set
        or l1.lower() in denied_set
        or l2.lower() in denied_set
    ):
        alt_l1 = "General" if l1.lower() in denied_set else l1
        alt_l2 = slugify(title or "item")[:24]
        if alt_l2.lower() in denied_set:
            alt_l2 = "Overview"
        candidate_sub = f"{alt_l1}/{alt_l2}"
    assigned_sub_topic = candidate_sub

    now_iso = datetime.now(timezone.utc).isoformat()
    topic_status = "approved"

    with db_session() as session:
        # Check/register Topic in TopicGovernanceORM
        top_row = (
            session.query(TopicGovernanceORM)
            .filter(TopicGovernanceORM.name.ilike(assigned_topic))
            .first()
        )
        if not top_row:
            is_in_allowed = assigned_topic.lower() in allowed_map
            top_row = TopicGovernanceORM(
                name=assigned_topic,
                level="topic",
                parent_topic=None,
                status="allowed" if is_in_allowed else "pending",
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(top_row)
            if not is_in_allowed:
                topic_status = "pending"
        elif top_row.status == "pending":
            topic_status = "pending"

        # Check/register Sub-Topic in TopicGovernanceORM
        sub_row = (
            session.query(TopicGovernanceORM)
            .filter(TopicGovernanceORM.name.ilike(assigned_sub_topic))
            .first()
        )
        if not sub_row:
            sub_row = TopicGovernanceORM(
                name=assigned_sub_topic,
                level="sub_topic",
                parent_topic=assigned_topic,
                status="allowed",
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(sub_row)
        elif sub_row.status == "pending":
            topic_status = "pending"

        # Update FetchedPage
        fp = session.query(FetchedPage).filter_by(url=url).first()
        if fp:
            fp.topic = assigned_topic
            fp.sub_topic = assigned_sub_topic
            fp.topic_status = topic_status

        session.commit()

    # Update 7-tier TaxonomyEntityORM and ContextStatements for this URL
    if "youtube.com" in url or "youtu.be" in url:
        tax_path = TaxonomyClassifier.classify_youtube_video(
            url=url,
            title=title,
            topic=assigned_topic,
            sub_topic=assigned_sub_topic,
            tags=tags,
        )
    else:
        tax_path = TaxonomyClassifier.classify_article(
            url=url,
            title=title,
            tags=tags,
            description=md_content,
            topic=assigned_topic,
            sub_topic=assigned_sub_topic,
        )

    TaxonomyEngine().register_entity(
        taxonomy=tax_path,
        physical_location=url,
        attributes={
            "title": title or url,
            "tags": tags,
            "topic": assigned_topic,
            "sub_topic": assigned_sub_topic,
            "topic_status": topic_status,
            "source_type": "video" if ("youtube.com" in url or "youtu.be" in url) else "article",
        },
    )

    try:
        from ..context_mesh.store import ContextStore
        ContextStore().update_statements_taxonomy_for_source(url, tax_path.to_path_string("/"))
    except Exception:
        pass

    return {
        "status": "success",
        "url": url,
        "topic": assigned_topic,
        "sub_topic": assigned_sub_topic,
        "topic_status": topic_status,
        "taxonomy_path": tax_path.to_path_string("/"),
    }


def approve_topic_or_subtopic(
    name: str,
    level: str = "topic",
    parent_topic: Optional[str] = None,
    config_obj: Any = None,
) -> Dict[str, Any]:
    """Approve a topic or sub-topic and mark matching articles/videos as approved."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Topic or sub-topic name is required.")

    cfg = config_obj or default_config
    now_iso = datetime.now(timezone.utc).isoformat()
    updated_articles = 0

    with db_session() as session:
        row = (
            session.query(TopicGovernanceORM)
            .filter(TopicGovernanceORM.name.ilike(clean_name))
            .first()
        )
        if row:
            row.status = "allowed"
            if parent_topic:
                row.parent_topic = parent_topic
            row.updated_at = now_iso
            clean_name = row.name
            level = row.level or level
        else:
            row = TopicGovernanceORM(
                name=clean_name,
                level=level,
                parent_topic=parent_topic,
                status="allowed",
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(row)

        if level == "topic":
            pages = session.query(FetchedPage).filter(FetchedPage.topic.ilike(clean_name)).all()
        else:
            pages = session.query(FetchedPage).filter(FetchedPage.sub_topic.ilike(clean_name)).all()

        for p in pages:
            p.topic_status = "approved"
            updated_articles += 1

        session.commit()

    if level == "topic":
        current = cfg.get_allowed_topics_list()
        if not any(t.lower() == clean_name.lower() for t in current):
            current.append(clean_name)
            cfg.allowed_topics = ", ".join(current)

    return {
        "status": "success",
        "name": clean_name,
        "level": level,
        "governance_status": "allowed",
        "updated_articles": updated_articles,
    }


def deny_topic_or_subtopic(
    name: str,
    level: Optional[str] = None,
    config_obj: Any = None,
) -> Dict[str, Any]:
    """Deny/delete a topic or sub-topic (Issue #128):
    1. Records it as 'denied' in TopicGovernanceORM so AI does not re-propose it.
    2. Clears topic/sub_topic on all affected articles & videos and sets topic_status='unassigned'.
    3. Clears WorkerJobExecution & in-memory worker targets for 'topic_assignment' so affected items
       are immediately re-added to the queue for reassignment.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Topic or sub-topic name is required.")

    cfg = config_obj or default_config
    now_iso = datetime.now(timezone.utc).isoformat()
    requeued_urls: List[str] = []

    with db_session() as session:
        row = (
            session.query(TopicGovernanceORM)
            .filter(TopicGovernanceORM.name.ilike(clean_name))
            .first()
        )
        resolved_level = level or (row.level if row else ("sub_topic" if "/" in clean_name else "topic"))
        if row:
            row.status = "denied"
            row.updated_at = now_iso
        else:
            row = TopicGovernanceORM(
                name=clean_name,
                level=resolved_level,
                parent_topic=None,
                status="denied",
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(row)

        # Find all articles & videos assigned to this topic or sub-topic
        affected_pages = (
            session.query(FetchedPage)
            .filter(
                or_(
                    FetchedPage.topic.ilike(clean_name),
                    FetchedPage.sub_topic.ilike(clean_name),
                    FetchedPage.sub_topic.ilike(f"{clean_name}/%"),
                    FetchedPage.sub_topic.ilike(f"%/{clean_name}"),
                )
            )
            .all()
        )

        for p in affected_pages:
            requeued_urls.append(p.url)
            p.topic = None
            p.sub_topic = None
            p.topic_status = "unassigned"

        if requeued_urls:
            session.query(WorkerJobExecution).filter(
                WorkerJobExecution.job_id == "topic_assignment",
                WorkerJobExecution.target_id.in_(requeued_urls),
            ).delete(synchronize_session=False)

        session.commit()

    # Remove from allowed_topics config if it was a top-level topic
    current_allowed = cfg.get_allowed_topics_list()
    filtered_allowed = [t for t in current_allowed if t.lower() != clean_name.lower()]
    if len(filtered_allowed) != len(current_allowed) and filtered_allowed:
        cfg.allowed_topics = ", ".join(filtered_allowed)

    # Clear from autonomous_worker in-memory recent_targets so worker picks them up immediately
    try:
        from ..worker import autonomous_worker
        recent_set = autonomous_worker._recent_targets.get("topic_assignment")
        if recent_set:
            for u in requeued_urls:
                recent_set.discard(u)
    except Exception:
        pass

    return {
        "status": "success",
        "name": clean_name,
        "level": resolved_level,
        "governance_status": "denied",
        "requeued_count": len(requeued_urls),
        "requeued_urls": requeued_urls,
    }


class TaxonomyEngine:
    """Persistence, template generation, and abstract view querying."""

    @staticmethod
    def _orm_to_record(orm: TaxonomyEntityORM) -> TaxonomyEntityRecord:
        attr = {}
        if orm.attributes_json:
            try:
                parsed = json.loads(orm.attributes_json)
                if isinstance(parsed, dict):
                    attr = parsed
            except Exception:
                pass
        return TaxonomyEntityRecord(
            canonical_id=orm.canonical_id,
            taxonomy_path=orm.taxonomy_path,
            kingdom=orm.kingdom,
            phylum=orm.phylum,
            class_name=orm.class_name,
            order_name=orm.order_name,
            family=orm.family,
            genus=orm.genus,
            species=orm.species,
            physical_location=orm.physical_location,
            attributes=attr,
            updated_at=orm.updated_at,
        )

    def register_entity(
        self,
        taxonomy: TaxonomyPath,
        physical_location: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> TaxonomyEntityRecord:
        """Upsert an entity and its taxonomic coordinates into the database."""
        canonical_id = taxonomy.to_path_string("/")
        now_iso = datetime.now(timezone.utc).isoformat()
        attr_json = json.dumps(attributes or {})

        with db_session() as session:
            # Also check if an entity already exists for this physical_location so we update it cleanly
            entity = (
                session.query(TaxonomyEntityORM).filter_by(canonical_id=canonical_id).first()
                or session.query(TaxonomyEntityORM).filter_by(physical_location=physical_location).first()
            )
            if entity:
                entity.canonical_id = canonical_id
                entity.taxonomy_path = canonical_id
                entity.kingdom = taxonomy.kingdom
                entity.phylum = taxonomy.phylum
                entity.class_name = taxonomy.class_
                entity.order_name = taxonomy.order
                entity.family = taxonomy.family
                entity.genus = taxonomy.genus
                entity.species = taxonomy.species
                entity.physical_location = physical_location
                entity.attributes_json = attr_json
                entity.updated_at = now_iso
            else:
                entity = TaxonomyEntityORM(
                    canonical_id=canonical_id,
                    taxonomy_path=canonical_id,
                    kingdom=taxonomy.kingdom,
                    phylum=taxonomy.phylum,
                    class_name=taxonomy.class_,
                    order_name=taxonomy.order,
                    family=taxonomy.family,
                    genus=taxonomy.genus,
                    species=taxonomy.species,
                    physical_location=physical_location,
                    attributes_json=attr_json,
                    updated_at=now_iso,
                )
                session.add(entity)
            session.commit()
            return self._orm_to_record(entity)

    def get_entity(self, canonical_id: str) -> Optional[TaxonomyEntityRecord]:
        """Fetch an entity by canonical taxonomy path ID."""
        with db_session() as session:
            orm = session.query(TaxonomyEntityORM).filter_by(canonical_id=canonical_id).first()
            if not orm:
                return None
            return self._orm_to_record(orm)

    def list_entities(
        self,
        kingdom: Optional[str] = None,
        phylum: Optional[str] = None,
        order: Optional[str] = None,
        family: Optional[str] = None,
        limit: int = 100,
    ) -> List[TaxonomyEntityRecord]:
        """Query taxonomy entities filtered by biological coordinates."""
        with db_session() as session:
            q = session.query(TaxonomyEntityORM)
            if kingdom:
                q = q.filter(TaxonomyEntityORM.kingdom == kingdom)
            if phylum:
                q = q.filter(TaxonomyEntityORM.phylum == phylum)
            if order:
                q = q.filter(TaxonomyEntityORM.order_name == order)
            if family:
                q = q.filter(TaxonomyEntityORM.family == family)
            q = q.order_by(TaxonomyEntityORM.updated_at.desc()).limit(limit)
            return [self._orm_to_record(r) for r in q.all()]

    def sync_entities_from_library(self, limit: int = 1000) -> Dict[str, Any]:
        """Backfill and register 7-tier taxonomy coordinates for all library items and notes."""
        synced_pages = 0
        synced_notes = 0

        with db_session() as session:
            pages = session.query(FetchedPage).limit(limit).all()
            for page in pages:
                url = page.url or ""
                title = page.title or url
                tags = []
                if page.tags:
                    try:
                        parsed = json.loads(page.tags)
                        if isinstance(parsed, list):
                            tags = parsed
                    except Exception:
                        tags = [t.strip() for t in str(page.tags).split(",") if t.strip()]

                if "youtube.com" in url or "youtu.be" in url:
                    tax = TaxonomyClassifier.classify_youtube_video(
                        url=url,
                        title=title,
                        topic=page.topic,
                        sub_topic=page.sub_topic,
                        tags=tags,
                    )
                elif url.startswith("repo://") or "git" in tags or "repo" in tags:
                    tax = TaxonomyClassifier.classify_git_repo(
                        repo_name=title,
                        remote_url=url,
                        topic=page.topic,
                        sub_topic=page.sub_topic,
                    )
                elif url.startswith("note://"):
                    tax = TaxonomyClassifier.classify_note(
                        title=title,
                        tags=tags,
                        topic=page.topic,
                        sub_topic=page.sub_topic,
                    )
                else:
                    tax = TaxonomyClassifier.classify_article(
                        url=url,
                        title=title,
                        tags=tags,
                        description=page.description,
                        topic=page.topic,
                        sub_topic=page.sub_topic,
                    )

                self.register_entity(
                    taxonomy=tax,
                    physical_location=url,
                    attributes={
                        "title": title,
                        "tags": tags,
                        "topic": page.topic or tax.kingdom,
                        "sub_topic": page.sub_topic or f"{tax.phylum}/{tax.class_}",
                        "source_type": "page",
                    },
                )
                synced_pages += 1

            notes = session.query(Note).limit(limit).all()
            for note in notes:
                note_title = note.title or f"note_{note.id}"
                note_url = note.url or f"note://{note.vault_name or 'PersonalVault'}/{note_title}"
                note_tags = []
                if note.tags:
                    try:
                        parsed = json.loads(note.tags)
                        if isinstance(parsed, list):
                            note_tags = parsed
                    except Exception:
                        note_tags = [t.strip() for t in str(note.tags).split(",") if t.strip()]

                tax = TaxonomyClassifier.classify_note(title=note_title, tags=note_tags)
                self.register_entity(
                    taxonomy=tax,
                    physical_location=note_url,
                    attributes={"title": note_title, "tags": note_tags, "source_type": "note"},
                )
                synced_notes += 1

        return {
            "status": "success",
            "synced_pages": synced_pages,
            "synced_notes": synced_notes,
            "total_synced": synced_pages + synced_notes,
        }

    def get_7tier_tree(self) -> Dict[str, Any]:
        """Builds hierarchical 7-tier taxonomy tree populated from taxonomy_entities and context_statements."""
        tree: Dict[str, Any] = {}
        total_entities = 0
        total_statements = 0

        with db_session() as session:
            entities = session.query(TaxonomyEntityORM).all()
            total_entities = len(entities)

            stmt_rows = session.query(
                ContextStatementORM.canonical_path,
                ContextStatementORM.kingdom,
                ContextStatementORM.phylum,
                ContextStatementORM.order_name,
                ContextStatementORM.family,
            ).all()
            total_statements = len(stmt_rows)

            stmt_counts: Dict[str, int] = {}
            for r in stmt_rows:
                k = r[1] or "General"
                p = r[2] or "General"
                o = r[3] or "general"
                stmt_counts[f"{k}"] = stmt_counts.get(f"{k}", 0) + 1
                stmt_counts[f"{k}/{p}"] = stmt_counts.get(f"{k}/{p}", 0) + 1
                stmt_counts[f"{k}/{p}/{o}"] = stmt_counts.get(f"{k}/{p}/{o}", 0) + 1

            for e in entities:
                k = e.kingdom or "General"
                p = e.phylum or "General"
                o = e.order_name or "general"
                f = e.family or "general"

                if k not in tree:
                    tree[k] = {
                        "name": k,
                        "level": "kingdom",
                        "path": k,
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(k, 0),
                        "phyla": {},
                    }
                tree[k]["entity_count"] += 1

                phyla = tree[k]["phyla"]
                if p not in phyla:
                    phyla[p] = {
                        "name": p,
                        "level": "phylum",
                        "path": f"{k}/{p}",
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(f"{k}/{p}", 0),
                        "orders": {},
                    }
                phyla[p]["entity_count"] += 1

                orders = phyla[p]["orders"]
                if o not in orders:
                    orders[o] = {
                        "name": o,
                        "level": "order",
                        "path": f"{k}/{p}/{o}",
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(f"{k}/{p}/{o}", 0),
                        "families": {},
                    }
                orders[o]["entity_count"] += 1

                families = orders[o]["families"]
                if f not in families:
                    families[f] = {
                        "name": f,
                        "level": "family",
                        "path": f"{k}/{p}/{o}/{f}",
                        "entity_count": 0,
                        "statement_count": 0,
                        "entities": [],
                    }
                families[f]["entity_count"] += 1
                if len(families[f]["entities"]) < 50:
                    families[f]["entities"].append(self._orm_to_record(e).model_dump())

            # Ensure statements whose kingdom/phylum/order don't have a TaxonomyEntityORM yet are still represented
            for r in stmt_rows:
                k = r[1] or "General"
                p = r[2] or "General"
                o = r[3] or "general"
                f = r[4] or "general"
                if k not in tree:
                    tree[k] = {
                        "name": k,
                        "level": "kingdom",
                        "path": k,
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(k, 0),
                        "phyla": {},
                    }
                phyla = tree[k]["phyla"]
                if p not in phyla:
                    phyla[p] = {
                        "name": p,
                        "level": "phylum",
                        "path": f"{k}/{p}",
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(f"{k}/{p}", 0),
                        "orders": {},
                    }
                orders = phyla[p]["orders"]
                if o not in orders:
                    orders[o] = {
                        "name": o,
                        "level": "order",
                        "path": f"{k}/{p}/{o}",
                        "entity_count": 0,
                        "statement_count": stmt_counts.get(f"{k}/{p}/{o}", 0),
                        "families": {},
                    }
                families = orders[o]["families"]
                if f not in families:
                    families[f] = {
                        "name": f,
                        "level": "family",
                        "path": f"{k}/{p}/{o}/{f}",
                        "entity_count": 0,
                        "statement_count": 0,
                        "entities": [],
                    }

        return {
            "total_entities": total_entities,
            "total_statements": total_statements,
            "tree": tree,
        }

    def to_yaml_frontmatter(self, taxonomy: TaxonomyPath) -> str:
        """Render markdown YAML frontmatter string."""
        return (
            "---\n"
            "taxonomy:\n"
            f"  path: \"{taxonomy.to_path_string('/')}\"\n"
            f"  kingdom: \"{taxonomy.kingdom}\"\n"
            f"  phylum: \"{taxonomy.phylum}\"\n"
            f"  class: \"{taxonomy.class_}\"\n"
            f"  order: \"{taxonomy.order}\"\n"
            f"  family: \"{taxonomy.family}\"\n"
            f"  genus: \"{taxonomy.genus}\"\n"
            f"  species: \"{taxonomy.species}\"\n"
            "---\n"
        )
