"""
Autonomous Category Taxonomy State Machine for kb-web.

Orchestrates an agentic, self-organizing category taxonomy using the tev1
decision gate (ollama.systemone) and LLM-driven ontology synthesis.

Key Behaviors:
1. Cold Start: 0 initial categories; inaugural item prompts LLM to generate Category #1.
2. Tev1 Top-Down Decision Gate: Evaluates candidate category tree or creates new categories.
3. Live Category Wiki Docs: Category `doc` attribute is updated upon every item addition.
4. 10-Item Threshold & Partitioning Loop: When any category reaches 10 items, global additions
   pause while the 10 items are partitioned into >=2 child sub-categories, turning the parent
   into a group container.
5. Persistent Agent Memory: Updates posted to #taxonomy on the Agent Message Board.
"""

from datetime import datetime
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .base import config as default_config, db_session, _get_ollama_client
from .models_orm import (
    TaxonomyCategory,
    TaxonomyItem,
    FetchedPage,
    Note,
    PageCardView,
    Workspace,
    WorkspaceFile,
    PageVersion,
    Collection,
    CollectionItem,
)
from .agent_memory import post_agent_memory

logger = logging.getLogger(__name__)

# Global thread lock and pause flag for category partitioning
_taxonomy_lock = threading.Lock()
_partitioning_paused: bool = False


def is_partitioning_paused() -> bool:
    """Returns True if the global taxonomy state machine is currently locked during an inner partitioning loop."""
    return _partitioning_paused


def set_partitioning_paused(paused: bool) -> None:
    """Sets the global partitioning pause flag."""
    global _partitioning_paused
    _partitioning_paused = paused


def format_category_tree_for_prompt(categories: List[TaxonomyCategory]) -> str:
    """Renders the existing taxonomy category hierarchy into an indented tree string for LLMs and tev1."""
    if not categories:
        return "(No categories currently exist - system is in cold start state)"

    # Build parent -> children map
    by_id = {c.id: c for c in categories}
    children_map: Dict[Optional[int], List[TaxonomyCategory]] = {}
    for c in categories:
        pid = c.parent_id
        if pid not in children_map:
            children_map[pid] = []
        children_map[pid].append(c)

    lines: List[str] = []

    def _render_branch(pid: Optional[int], indent_level: int):
        kids = children_map.get(pid, [])
        for k in kids:
            indent = "  " * indent_level
            container_tag = " [Container Branch]" if k.is_container else f" ({k.item_count} items)"
            doc_snippet = (k.doc or "").replace("\n", " ").strip()[:100]
            lines.append(f"{indent}- [cat_{k.id}] {k.name}{container_tag}: {doc_snippet}")
            _render_branch(k.id, indent_level + 1)

    _render_branch(None, 0)
    return "\n".join(lines)


def get_category_tree_data(session: Session) -> List[Dict[str, Any]]:
    """Builds a nested dictionary representation of the category hierarchy for API/UI visualization."""
    categories = session.query(TaxonomyCategory).order_by(TaxonomyCategory.depth.asc(), TaxonomyCategory.name.asc()).all()
    if not categories:
        return []

    cats_dict = {
        c.id: {
            "id": c.id,
            "name": c.name,
            "slug": c.slug,
            "parent_id": c.parent_id,
            "doc": c.doc,
            "item_count": c.item_count,
            "depth": c.depth,
            "is_container": bool(c.is_container),
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "children": [],
        }
        for c in categories
    }

    roots: List[Dict[str, Any]] = []
    for c in categories:
        node = cats_dict[c.id]
        if c.parent_id and c.parent_id in cats_dict:
            cats_dict[c.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots


def _generate_category_slug(name: str) -> str:
    """Generates a clean URL-safe slug from a category title."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-") or f"category-{int(time.time())}"


def _ensure_unique_slug(session: Session, slug: str) -> str:
    """Ensures a category slug is strictly unique within the database by appending numeric suffixes if needed."""
    candidate = slug
    counter = 2
    while session.query(TaxonomyCategory).filter_by(slug=candidate).first():
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


def _format_metadata_summary(meta: Optional[Dict[str, Any]]) -> str:
    """Formats provenance metadata into readable markdown bullet points for taxonomy agents."""
    if not meta:
        return ""
    lines = []
    vault = meta.get("vault_name") or meta.get("vault")
    if vault:
        lines.append(f"- Vault: {vault}")
    folder = meta.get("folder_path") or meta.get("folder")
    if folder and folder not in ["root", ""]:
        lines.append(f"- Folder: {folder}")
    if "syntax" in meta and meta["syntax"]:
        lines.append(f"- Syntax: {meta['syntax']}")
    if "collections" in meta and meta["collections"]:
        lines.append(f"- Belongs to Collections: {', '.join(meta['collections'])}")
    if "source_url" in meta:
        lines.append(f"- Source URL: {meta['source_url']}")
    if "note_url" in meta:
        lines.append(f"- Note URI: {meta['note_url']}")
    if "version_count" in meta and meta["version_count"] > 1:
        lines.append(f"- Version History: {meta['version_count']} revisions recorded")
    if "fetched_at" in meta:
        lines.append(f"- Ingested At: {meta['fetched_at']}")
    if "created_at" in meta:
        lines.append(f"- Created At: {meta['created_at']}")
    if "template" in meta:
        lines.append(f"- Project Type: {meta['template']}")
    if "file_count" in meta:
        lines.append(f"- File Count: {meta['file_count']}")
    return "\n".join(lines)


def _is_generic_domain_name(name: str) -> bool:
    """Checks whether a category name is an uninformative, generic, or numbered placeholder."""
    if not name or len(name.strip()) < 3:
        return True
    norm = name.strip().lower()
    # Check for patterns like "Domain 1", "Domain 10", "Category 2", "Topic 4"
    if re.match(r"^(domain|category|topic|sub-category|section)\s*\d*$", norm):
        return True
    return False


def _derive_meaningful_domain_name(
    item_title: str,
    item_tags: Optional[List[str]] = None,
    item_class: Optional[str] = None,
) -> str:
    """Intelligently synthesizes an authoritative 2-4 word knowledge domain title from item attributes.
    Strictly forbids generic numbered placeholders like 'Domain X' or 'Category Y'.
    """
    tags = item_tags or []
    cleaned_title = re.sub(r"^[📝📂⚡•#\s\-*]+", "", item_title).strip()
    lower_title = cleaned_title.lower()
    lower_tags = [t.lower() for t in tags]
    combined_text = f"{lower_title} {' '.join(lower_tags)}"

    # Topic-specific domain mapping
    if any(k in combined_text for k in ["date", "dating", "relationship", "romance", "dinner"]):
        return "Personal Lifestyle & Dating"
    if any(k in combined_text for k in ["docker", "container", "k8s", "kubernetes", "podman", "cloudflared"]):
        return "DevOps & Cloud Infrastructure"
    if any(k in combined_text for k in ["song", "guitar", "tab", "chords", "music", "audio"]):
        return "Music & Performing Arts"
    if any(k in combined_text for k in ["sqlite", "postgres", "sql", "database", "docling", "qdrant"]):
        return "Databases & Data Engineering"
    if any(k in combined_text for k in ["python", "powershell", "script", "bash", "cli", "terminal"]):
        return "Developer Tooling & Scripting"
    if any(k in combined_text for k in ["ai", "llm", "gemma", "ollama", "agent", "transformer"]):
        return "Artificial Intelligence & Agents"
    if any(k in combined_text for k in ["cooking", "recipe", "culinary", "baking", "food"]):
        return "Culinary Arts & Gastronomy"

    # Fallback to item_class + title keywords
    words = [w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", cleaned_title) if len(w) > 2]
    if words:
        short_title = " ".join(words[:2])
        cls_prefix = item_class or "General"
        return f"{cls_prefix} - {short_title}"

    return "General Knowledge & Research"


def _create_cold_start_category(
    session: Session,
    item_title: str,
    item_excerpt: str,
    item_tags: List[str],
    client: Any,
    config: Any,
    item_class: Optional[str] = None,
    item_metadata: Optional[Dict[str, Any]] = None,
) -> TaxonomyCategory:
    """Cold Start: Prompts the LLM to invent the inaugural top-level category when 0 categories exist."""
    meta_summary = _format_metadata_summary(item_metadata)
    meta_block = f"\nItem Provenance & Context:\n{meta_summary}\n" if meta_summary else ""

    prompt = (
        "You are an expert ontology and taxonomy architect. The knowledge base is currently empty with 0 categories.\n"
        "Analyze the following incoming item and create the inaugural top-level knowledge domain for it.\n\n"
        f"Item Class: {item_class or 'Notes'}\n"
        f"Item Title: {item_title}\n"
        f"Item Tags: {', '.join(item_tags) if item_tags else 'None'}\n"
        f"{meta_block}"
        f"Item Excerpt: {item_excerpt[:1000]}\n\n"
        "DOMAIN NAMING MANDATE:\n"
        "You MUST assign a descriptive, authoritative, 2-4 word knowledge domain title (e.g. 'Personal Lifestyle & Dating', 'DevOps & Cloud Infrastructure', 'Python & System Utilities').\n"
        "You are STRICTLY FORBIDDEN from generating generic names, numeric suffixes, or placeholder labels like 'Domain X', 'Category Y', 'Topic Z', or numbered sequences.\n\n"
        "Respond with a strict JSON object:\n"
        "{\n"
        '  "category_name": "Authoritative Domain Title (2-4 words)",\n'
        '  "category_doc": "Comprehensive initial markdown wiki doc (2-3 paragraphs) outlining the scope, topics, and criteria for this domain."\n'
        "}\n"
        "Do NOT include any filler before or after the JSON."
    )

    model = getattr(config, "ollama_model", "gemma2")
    cat_name = _derive_meaningful_domain_name(item_title, item_tags, item_class)
    cat_doc = f"# {cat_name}\n\nInitial repository topic covering {item_title}."

    try:
        resp = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_predict": 400},
        )
        content = resp["message"]["content"].strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            candidate_name = data.get("category_name", "").strip()
            if candidate_name and not _is_generic_domain_name(candidate_name):
                cat_name = candidate_name
            cat_doc = data.get("category_doc", cat_doc).strip()
    except Exception as e:
        logger.warning(f"Cold-start category generation LLM fallback: {e}")

    now_str = datetime.now().isoformat()
    slug = _generate_category_slug(cat_name)

    cat = TaxonomyCategory(
        name=cat_name,
        slug=slug,
        parent_id=None,
        doc=cat_doc,
        item_count=0,
        depth=0,
        is_container=0,
        created_at=now_str,
        updated_at=now_str,
    )
    session.add(cat)
    session.commit()
    session.refresh(cat)

    post_agent_memory(
        session=session,
        agent_name="TaxonomyAgent",
        channel="taxonomy",
        topic="cold_start",
        content=f"Initialized cold-start inaugural category '{cat.name}' (ID: {cat.id}) with wiki doc.",
        memory_type="lifecycle",
        metadata={"category_id": cat.id, "name": cat.name, "slug": cat.slug},
    )

    return cat


def _synthesize_new_category(
    session: Session,
    item_title: str,
    item_excerpt: str,
    item_tags: List[str],
    existing_categories: List[TaxonomyCategory],
    client: Any,
    config: Any,
    item_class: Optional[str] = None,
    item_metadata: Optional[Dict[str, Any]] = None,
) -> TaxonomyCategory:
    """Prompts LLM to create a new category that fits the incoming item without duplicating existing ones."""
    tree_text = format_category_tree_for_prompt(existing_categories)
    meta_summary = _format_metadata_summary(item_metadata)
    meta_block = f"\nItem Provenance & Context:\n{meta_summary}\n" if meta_summary else ""

    prompt = (
        "You are an expert ontology architect. An incoming item does not fit into any of our existing categories.\n"
        "Review the existing category tree and create a NEW, distinct knowledge domain for this item.\n\n"
        f"Existing Category Tree:\n{tree_text}\n\n"
        f"Item Class: {item_class or 'Notes'}\n"
        f"Incoming Item Title: {item_title}\n"
        f"Item Tags: {', '.join(item_tags) if item_tags else 'None'}\n"
        f"{meta_block}"
        f"Item Excerpt: {item_excerpt[:1000]}\n\n"
        "DOMAIN NAMING MANDATE:\n"
        "You MUST assign a descriptive, authoritative, 2-4 word knowledge domain title (e.g. 'Personal Lifestyle & Dating', 'DevOps & Cloud Infrastructure', 'Developer Tooling & Scripting').\n"
        "You are STRICTLY FORBIDDEN from generating generic names, numeric suffixes, or placeholder labels like 'Domain X', 'Category Y', 'Topic Z', or numbered sequences.\n\n"
        "Respond with a strict JSON object:\n"
        "{\n"
        '  "category_name": "Authoritative Domain Title (2-4 words)",\n'
        '  "category_doc": "Comprehensive initial markdown wiki doc explaining the domain, scope, and related topics."\n'
        "}\n"
        "Do NOT include any filler before or after the JSON."
    )

    model = getattr(config, "ollama_model", "gemma2")
    cat_name = _derive_meaningful_domain_name(item_title, item_tags, item_class)
    cat_doc = f"# {cat_name}\n\nDedicated knowledge category covering {item_title}."

    try:
        resp = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_predict": 400},
        )
        content = resp["message"]["content"].strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            candidate_name = data.get("category_name", "").strip()
            if candidate_name and not _is_generic_domain_name(candidate_name):
                cat_name = candidate_name
            cat_doc = data.get("category_doc", cat_doc).strip()
    except Exception as e:
        logger.warning(f"New category generation LLM fallback: {e}")

    # Check for slug collision against existing categories
    existing_slug_map = {c.slug: c for c in existing_categories}
    slug = _generate_category_slug(cat_name)

    # Retry loop with feedback to LLM agent if slug already exists
    attempts = 0
    while slug in existing_slug_map and attempts < 3:
        attempts += 1
        collided_cat = existing_slug_map[slug]
        logger.info(f"Taxonomy slug collision for '{slug}' (attempt {attempts}). Re-prompting agent harness...")
        collision_prompt = (
            f"ERROR: A category with slug '{slug}' ('{collided_cat.name}') ALREADY exists in the ontology.\n"
            f"Incoming item: '{item_title}'\n"
            "Action required: Either select a MORE SPECIFIC, DISTINCT category title (2-4 words) that avoids this collision, "
            "or if this item actually belongs to the existing category, respond with that exact existing category name.\n"
            "Respond with strict JSON: {\"category_name\": \"...\", \"category_doc\": \"...\"}"
        )
        try:
            retry_resp = client.chat(
                model=model,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": json.dumps({"category_name": cat_name, "category_doc": cat_doc})},
                    {"role": "user", "content": collision_prompt},
                ],
                options={"temperature": 0.4, "num_predict": 400},
            )
            retry_content = retry_resp["message"]["content"].strip()
            retry_match = re.search(r"\{.*\}", retry_content, re.DOTALL)
            if retry_match:
                retry_data = json.loads(retry_match.group(0))
                candidate_name = retry_data.get("category_name", "").strip()
                if candidate_name and not _is_generic_domain_name(candidate_name):
                    cat_name = candidate_name
                    cat_doc = retry_data.get("category_doc", cat_doc).strip()
                    slug = _generate_category_slug(cat_name)
                    if slug == collided_cat.slug:
                        # Agent chose to merge with existing category!
                        logger.info(f"Agent chose to merge into existing category '{collided_cat.name}'.")
                        return collided_cat
        except Exception as retry_err:
            logger.warning(f"Agent collision retry error: {retry_err}")
            break

    # If it still collides with an existing category after retries, check if we should merge
    if slug in existing_slug_map and cat_name.lower().strip() == existing_slug_map[slug].name.lower().strip():
        return existing_slug_map[slug]

    # Always ensure slug uniqueness in database table
    slug = _ensure_unique_slug(session, slug)

    now_str = datetime.now().isoformat()
    cat = TaxonomyCategory(
        name=cat_name,
        slug=slug,
        parent_id=None,
        doc=cat_doc,
        item_count=0,
        depth=0,
        is_container=0,
        created_at=now_str,
        updated_at=now_str,
    )
    session.add(cat)
    session.commit()
    session.refresh(cat)

    post_agent_memory(
        session=session,
        agent_name="TaxonomyAgent",
        channel="taxonomy",
        topic="new_category",
        content=f"Created new distinct category '{cat.name}' (ID: {cat.id}, Slug: {cat.slug}) to house '{item_title}'.",
        memory_type="decision",
        metadata={"category_id": cat.id, "name": cat.name, "slug": cat.slug, "item_title": item_title},
    )

    return cat



def _update_category_wiki_doc(
    session: Session,
    category: TaxonomyCategory,
    new_item_title: str,
    new_item_excerpt: str,
    client: Any,
    config: Any,
) -> None:
    """Updates the category's living wiki `doc` attribute upon the addition of a new item."""
    current_doc = category.doc or f"# {category.name}\n\nCategory documentation."
    prompt = (
        f"You are maintaining the authoritative wiki documentation for knowledge category '{category.name}'.\n"
        "A new item has just been classified into this category. Update and enrich the category wiki documentation "
        "to incorporate this new item's knowledge and synthesis.\n\n"
        f"Current Wiki Doc:\n{current_doc[:1500]}\n\n"
        f"Newly Added Item:\nTitle: {new_item_title}\nExcerpt: {new_item_excerpt[:800]}\n\n"
        "Provide ONLY the updated markdown wiki documentation. Do not wrap in quotes or add conversational chatter."
    )

    model = getattr(config, "ollama_model", "gemma2")
    try:
        resp = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_predict": 500},
        )
        updated_text = resp["message"]["content"].strip()
        if updated_text and len(updated_text) > 30:
            category.doc = updated_text
            category.updated_at = datetime.now().isoformat()
            session.commit()
    except Exception as e:
        logger.warning(f"Category wiki update failed for '{category.name}': {e}")


def partition_category(
    session: Session,
    category_id: int,
    client: Any,
    config: Any,
) -> None:
    """Executes the inner partitioning loop when a category hits 10 items.

    Pauses global additions, splits all 10 items into >=2 child sub-categories,
    marks the parent category as a pure group container, and updates wiki docs.
    """
    category = session.query(TaxonomyCategory).filter_by(id=category_id).first()
    if not category:
        return

    # 1. Acquire global pause lock
    set_partitioning_paused(True)
    post_agent_memory(
        session=session,
        agent_name="TaxonomyAgent",
        channel="taxonomy",
        topic="partition_start",
        content=(
            f"Category '{category.name}' reached 10 items. "
            "PAUSING global item classification to execute inner partitioning loop."
        ),
        memory_type="state_machine",
        metadata={"category_id": category.id, "name": category.name, "item_count": category.item_count},
    )

    try:
        # 2. Fetch all items currently assigned to this category
        items = session.query(TaxonomyItem).filter_by(category_id=category.id).all()
        if len(items) < 10:
            logger.info(f"Category {category.id} has {len(items)} items (<10); skipping partition.")
            return

        items_summary = "\n".join([
            f"[{idx}] (ID: {item.item_id}, Type: {item.item_type}) Title: {item.item_title}"
            for idx, item in enumerate(items)
        ])

        # 3. Prompt LLM to partition into 2 or more sub-categories
        prompt = (
            f"Category '{category.name}' has reached capacity with {len(items)} items.\n"
            "You MUST partition all 10 items into 2 or more distinct, cohesive child sub-categories.\n"
            f"CONTAINMENT DIRECTIVE: All created sub-categories MUST be specialized child sub-domains strictly within the parent domain boundary of '{category.name}'. Never cross domain boundaries.\n"
            f"DOMAIN NAMING DIRECTIVE: Assign clear, authoritative titles without generic numbering (e.g. '{category.name} - Core Foundations', '{category.name} - Applied Topics'). Generic labels like 'Sub-Category 1' or 'Domain X' are strictly forbidden.\n"
            f"Parent Category Wiki Doc:\n{(category.doc or '')[:800]}\n\n"
            f"Items to Partition:\n{items_summary}\n\n"
            "Requirements:\n"
            "1. Output a JSON object with a 'sub_categories' array containing at least 2 sub-categories.\n"
            "2. Each sub-category must have 'name', 'doc' (initial markdown wiki summary), and 'item_indices' (list of integers from 0 to 9).\n"
            "3. Every index from 0 to 9 MUST be assigned to exactly one sub-category.\n\n"
            "Format:\n"
            "{\n"
            '  "sub_categories": [\n'
            f'    {{"name": "{category.name} - Core Concepts", "doc": "#{category.name} - Core Concepts\\nOverview...", "item_indices": [0, 2, 4, 6, 8]}},\n'
            f'    {{"name": "{category.name} - Applied Topics", "doc": "#{category.name} - Applied Topics\\nOverview...", "item_indices": [1, 3, 5, 7, 9]}}\n'
            "  ]\n"
            "}\n"
            "Respond ONLY with the JSON."
        )

        model = getattr(config, "ollama_model", "gemma2")
        sub_categories_spec: List[Dict[str, Any]] = []

        try:
            resp = client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1, "num_predict": 600},
            )
            raw = resp["message"]["content"].strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                sub_categories_spec = parsed.get("sub_categories", [])
        except Exception as e:
            logger.warning(f"LLM partitioning error: {e}. Executing balanced fallback partition.")

        # Fallback if LLM output invalid or <2 sub-categories
        if len(sub_categories_spec) < 2:
            mid = len(items) // 2
            sub_categories_spec = [
                {
                    "name": f"{category.name} - Core Focus",
                    "doc": f"# {category.name} - Core Focus\n\nPrimary foundational resources for {category.name}.",
                    "item_indices": list(range(0, mid)),
                },
                {
                    "name": f"{category.name} - Applied Topics",
                    "doc": f"# {category.name} - Applied Topics\n\nSpecialized applications and domain tools for {category.name}.",
                    "item_indices": list(range(mid, len(items))),
                },
            ]

        # 4. Create child sub-categories and reassign items
        now_str = datetime.now().isoformat()
        assigned_indices = set()
        created_sub_cats = []

        for sub_spec in sub_categories_spec:
            sub_name = sub_spec.get("name", "Specialized Sub-Category").strip()
            if _is_generic_domain_name(sub_name) or sub_name.lower().startswith("sub-category"):
                sub_name = f"{category.name} - Specialized Focus {len(created_sub_cats) + 1}"
            sub_doc = sub_spec.get("doc", f"# {sub_name}\n\nSub-category wiki doc.").strip()
            indices = sub_spec.get("item_indices", [])


            valid_indices = [idx for idx in indices if 0 <= idx < len(items) and idx not in assigned_indices]
            if not valid_indices:
                continue

            sub_slug = _ensure_unique_slug(session, _generate_category_slug(sub_name))
            sub_cat = TaxonomyCategory(
                name=sub_name,
                slug=sub_slug,
                parent_id=category.id,
                doc=sub_doc,
                item_count=len(valid_indices),
                depth=category.depth + 1,
                is_container=0,
                created_at=now_str,
                updated_at=now_str,
            )
            session.add(sub_cat)
            session.commit()
            session.refresh(sub_cat)

            for idx in valid_indices:
                assigned_indices.add(idx)
                items[idx].category_id = sub_cat.id

            created_sub_cats.append(sub_cat)

        # Catch any leftover unassigned items and assign to the first sub-category
        leftovers = [idx for idx in range(len(items)) if idx not in assigned_indices]
        if leftovers and created_sub_cats:
            first_sub = created_sub_cats[0]
            for idx in leftovers:
                items[idx].category_id = first_sub.id
                first_sub.item_count += 1
            session.commit()

        # 5. Transform parent category into pure group container
        category.is_container = 1
        category.item_count = 0  # direct items = 0; items now live in sub-categories
        category.updated_at = now_str
        sub_list_str = "\n".join([f"- **{sc.name}** ({sc.item_count} items)" for sc in created_sub_cats])
        category.doc = (
            f"# {category.name} (Container)\n\n"
            f"This branch houses {len(created_sub_cats)} specialized sub-categories:\n\n"
            f"{sub_list_str}\n\n"
            f"### Overview\n{(category.doc or '')}"
        )
        session.commit()

        post_agent_memory(
            session=session,
            agent_name="TaxonomyAgent",
            channel="taxonomy",
            topic="partition_complete",
            content=(
                f"Successfully partitioned category '{category.name}' into {len(created_sub_cats)} sub-categories: "
                f"{', '.join([c.name for c in created_sub_cats])}. Parent transformed to group container. UNPAUSING additions."
            ),
            memory_type="state_machine",
            metadata={
                "parent_id": category.id,
                "parent_name": category.name,
                "sub_categories": [{"id": sc.id, "name": sc.name, "count": sc.item_count} for sc in created_sub_cats],
            },
        )

    finally:
        # 6. Release global pause lock
        set_partitioning_paused(False)


def classify_item_class(
    item_title: str,
    item_content: str,
    item_tags: Optional[List[str]] = None,
    client: Any = None,
    config: Any = None,
    item_metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Classifies an incoming item into one of 6 distinct classes using tev1 decision gating.

    Classes:
    - Personal: Personal notes, personal information, journal thoughts, date ideas.
    - Documentation: Code resources, reference documents, technical manuals.
    - Notes: Markdown notes that are not personal and not documentation or code.
    - Articles: Web articles, news essays, YouTube video transcripts.
    - Source Code: Flattened code, workspace snapshots, scripts.
    - Unclassifiable: Catchall for corrupted, unreadable, or meaningless items.
    """
    cfg = config or default_config
    cli = client or _get_ollama_client()
    tags = item_tags or []
    tev1_model = getattr(cfg, "tev1_model", "tev1")
    meta_summary = _format_metadata_summary(item_metadata)

    state: Dict[str, Any] = {
        "item_title": item_title,
        "item_tags": tags,
        "item_excerpt": item_content[:800],
        "provenance_metadata": meta_summary,
        "policies": [
            "Policy 1 (Personal): Private thoughts, personal journal entries, relationship/dating ideas, lifestyle planning, and personal tasks must be classified as 'Personal'. Items from personal vaults or journal folders default to 'Personal'.",
            "Policy 2 (Documentation): Reference materials, technical documentation, API guides, architecture manuals, and cheat sheets must be classified as 'Documentation'.",
            "Policy 3 (Notes): Non-personal, non-code informational scratchpad notes, meeting summaries, or project scratchpads must be classified as 'Notes'.",
            "Policy 4 (Articles): Published web articles, blog posts, news essays, and video transcripts must be classified as 'Articles'.",
            "Policy 5 (Source Code): Code files, scripts, functions, algorithm implementations, and workspace project snapshots must be classified as 'Source Code'.",
            "Policy 6 (Unclassifiable): Unreadable, corrupted, purely empty, or non-substantive text must be classified as 'Unclassifiable'.",
        ],
    }

    questions: Dict[str, Dict[str, Any]] = {
        "item_class": {
            "type": "choice",
            "instructions": (
                f"Classify the incoming item '{item_title[:50]}' into exactly one of the 6 canonical classes. "
                "Adhere strictly to the policy directives in the state object."
            ),
            "criteria": {
                "Personal": "Private notes, dating/relationship ideas, personal journal reflections, personal plans.",
                "Documentation": "Technical references, API manuals, architecture specs, cheat sheets.",
                "Notes": "General markdown informational notes (not personal, not code, not external articles).",
                "Articles": "External web articles, blog posts, news essays, YouTube video transcripts.",
                "Source Code": "Scripts, code snippets, syntax implementations, workspace snapshots.",
                "Unclassifiable": "Unreadable, corrupted, or non-substantive text.",
            },
        }
    }

    try:
        resp = cli.systemone(
            model=tev1_model,
            state=state,
            questions=questions,
        )
        answers = getattr(resp, "answers", {})
        ans = answers.get("item_class")
        choice = getattr(ans, "choice", None)
        if choice in ["Personal", "Documentation", "Notes", "Articles", "Source Code", "Unclassifiable"]:
            return choice
    except Exception as e:
        logger.warning(f"tev1 systemone item_class evaluation failed: {e}. Running heuristics.")

    # Rule-based fallback
    lower_title = item_title.lower()
    lower_content = item_content[:500].lower()
    meta_str = (meta_summary or "").lower()
    combined = f"{lower_title} {lower_content} {meta_str} {' '.join(tags).lower()}"

    if not item_content.strip() or len(item_content.strip()) < 5:
        return "Unclassifiable"
    if any(k in combined for k in ["date ideas", "dating", "personal", "journal", "diary"]):
        return "Personal"
    if any(k in combined for k in ["api reference", "documentation", "spec", "manual", "guide", "cheatsheet"]):
        return "Documentation"
    if any(k in combined for k in ["def ", "class ", "import ", "function ", "select ", "curl "]) and ("```" in item_content or len(item_content.splitlines()) >= 2):
        return "Source Code"

    if any(k in combined for k in ["http://", "https://", "youtube.com", "article", "author:"]):
        return "Articles"
    return "Notes"


def evaluate_category_fit_tev1(
    item_title: str,
    item_excerpt: str,
    item_tags: List[str],
    candidate_categories: List[TaxonomyCategory],
    client: Any,
    config: Any,
    item_class: str = "Notes",
    item_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[int], bool]:
    """Uses the tev1 decision model (via client.systemone) to evaluate candidate categories.

    Returns:
        (chosen_category_id, is_confident):
        If decision model picks 'new_category' or confidence is False, category_id will be None.
    """
    if not candidate_categories:
        return None, False

    tev1_model = getattr(config, "tev1_model", "tev1")
    meta_summary = _format_metadata_summary(item_metadata)

    # Format choices for tev1 choice question
    choices_criteria: Dict[str, str] = {}
    for cat in candidate_categories:
        doc_snippet = (cat.doc or "").replace("\n", " ").strip()[:140]
        choices_criteria[f"cat_{cat.id}"] = f"Directly aligns with '{cat.name}': {doc_snippet}"
    choices_criteria["new_category"] = "Item represents a distinct subject domain not covered by existing categories."

    tree_representation = format_category_tree_for_prompt(candidate_categories)

    state: Dict[str, Any] = {
        "item_title": item_title,
        "item_class": item_class,
        "item_tags": item_tags,
        "item_excerpt": item_excerpt[:600],
        "item_provenance": meta_summary,
        "category_tree": tree_representation,
        "policies": [
            "Policy 1 (Thematic Purity): An item must only be assigned to a category if its core topic directly aligns with that category's scope. Never force-fit an item into an unrelated category.",
            "Policy 2 (Domain Meaning): Categories represent distinct, cohesive knowledge domains. If none of the existing categories match the item's topic, you must declare that it does not fit.",
            "Policy 3 (Domain Containment): Sub-categories must strictly represent thematic specializations within the parent domain boundary.",
            "Policy 4 (Exclusion of Numbered Labels): Generic placeholders or numbered titles (e.g. 'Domain 1', 'Category 2') are strictly forbidden.",
        ],
    }

    questions: Dict[str, Dict[str, Any]] = {
        "fits_any_category": {
            "type": "noul",
            "instructions": f"Does the incoming {item_class} item '{item_title[:50]}' clearly belong to ANY of the active categories listed in the ontology tree?",
            "criteria": {
                "true": "The item's core subject directly fits into at least one of the active categories in the tree.",
                "false": "The item's subject does not fit any existing category at all and requires synthesizing a new domain.",
            },
        },
        "category_choice": {
            "type": "choice",
            "instructions": (
                f"Evaluate the incoming {item_class} item '{item_title[:50]}' against the knowledge ontology. "
                "Select the single best fitting category key, or choose 'new_category' if it belongs elsewhere."
            ),
            "criteria": choices_criteria,
        },
        "fit_confidence": {
            "type": "noul",
            "instructions": f"Is '{item_title[:50]}' an unambiguous, strong conceptual fit for the chosen category?",
            "criteria": {
                "true": "High confidence fit: item clearly belongs in the selected category.",
                "false": "Low confidence or ambiguous fit: a distinct new category should be created instead.",
            },
        },
    }

    try:
        resp = client.systemone(
            model=tev1_model,
            state=state,
            questions=questions,
        )
        answers = getattr(resp, "answers", {})

        fits_any_ans = answers.get("fits_any_category")
        fits_any_val = getattr(fits_any_ans, "noul", True) if fits_any_ans else True
        if not fits_any_val:
            return None, False

        cat_ans = answers.get("category_choice")
        choice_val = getattr(cat_ans, "choice", "new_category") if cat_ans else "new_category"

        conf_ans = answers.get("fit_confidence")
        conf_val = getattr(conf_ans, "noul", True) if conf_ans else True

        if choice_val and choice_val.startswith("cat_") and conf_val:
            try:
                cat_id = int(choice_val.replace("cat_", ""))
                return cat_id, True
            except ValueError:
                return None, False

        return None, False

    except Exception as e:
        logger.warning(f"tev1 systemone evaluation failed: {e}. Running LLM classification fallback.")


    # Fallback to standard Ollama LLM prompt
    try:
        model = getattr(config, "ollama_model", "gemma2")
        prompt = (
            f"Incoming item: '{item_title}'\nExcerpt: {item_excerpt[:500]}\nTags: {', '.join(item_tags)}\n\n"
            f"Available Categories:\n{tree_representation}\n\n"
            "Which category does this item best fit? If it fits an existing category, respond with its ID (e.g. 'cat_1'). "
            "If it does not fit any existing category with high confidence, respond with 'new_category'.\n"
            "Format: ONLY the token (e.g. 'cat_2' or 'new_category')."
        )
        resp = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0, "num_predict": 15},
        )
        ans = resp["message"]["content"].strip().lower()
        match = re.search(r"cat_(\d+)", ans)
        if match:
            return int(match.group(1)), True
    except Exception as ex:
        logger.warning(f"LLM fallback classification failed: {ex}")

    return None, False


def classify_item(
    session: Session,
    item_type: str,
    item_id: str,
    item_title: str,
    item_content: str,
    item_tags: Optional[List[str]] = None,
    client: Any = None,
    config: Any = None,
    item_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Classifies an individual item into the autonomous taxonomy state machine.

    Steps:
    1. Check global pause; if paused, wait for inner partitioning loop to finish.
    2. Check if already classified in TaxonomyItem.
    3. Check category count:
       - 0 categories -> Cold Start: synthesize inaugural Category #1.
       - >0 categories -> Fetch candidate assignable categories (leaf categories where is_container=0).
    4. Run tev1 decision gate (choice + confidence noul).
    5. If fit confirmed:
       - Assign item to category.
       - Increment category.item_count.
       - Update category wiki doc with LLM synthesis.
       - If item_count reaches 10 -> trigger partition_category inner loop!
    6. If new_category:
       - Synthesize new Category with LLM.
       - Assign item, item_count=1.
    7. Post Agent Memory update to #taxonomy.
    """
    cfg = config or default_config
    cli = client or _get_ollama_client()
    tags = item_tags or []

    # 1. Wait if global pause is active
    wait_cycles = 0
    while is_partitioning_paused() and wait_cycles < 30:
        time.sleep(0.5)
        wait_cycles += 1

    with _taxonomy_lock:
        # 2. Check existing
        existing_tax_item = session.query(TaxonomyItem).filter_by(item_type=item_type, item_id=item_id).first()
        if existing_tax_item:
            cat = session.query(TaxonomyCategory).filter_by(id=existing_tax_item.category_id).first()
            return {
                "status": "already_classified",
                "category_id": existing_tax_item.category_id,
                "category_name": cat.name if cat else "Unknown",
                "item_id": item_id,
            }

        now_str = datetime.now().isoformat()

        # 3. Prior 6-Class Item Classification Gate
        item_class = classify_item_class(
            item_title=item_title,
            item_content=item_content,
            item_tags=tags,
            client=cli,
            config=cfg,
            item_metadata=item_metadata,
        )

        # Handle Unclassifiable items (skip domain assignment, record on message board)
        if item_class == "Unclassifiable":
            tax_item = TaxonomyItem(
                category_id=None,
                item_type=item_type,
                item_id=item_id,
                item_title=item_title[:255],
                fit_score=0.0,
                assigned_at=now_str,
                item_class="Unclassifiable",
            )
            session.add(tax_item)
            session.commit()

            post_agent_memory(
                session=session,
                agent_name="TaxonomyAgent",
                channel="taxonomy",
                topic="unclassifiable",
                content=(
                    f"Item '{item_title}' (Type: {item_type}, ID: {item_id}) classified as "
                    "Unclassifiable. Skipping domain ontology placement."
                ),
                memory_type="observation",
                metadata={"item_type": item_type, "item_id": item_id, "item_title": item_title, "item_class": "Unclassifiable"},
            )

            return {
                "status": "unclassifiable_skipped",
                "item_class": "Unclassifiable",
                "item_id": item_id,
                "item_title": item_title,
            }

        all_categories = session.query(TaxonomyCategory).all()

        # 4. Cold Start Check (0 initial categories)
        if not all_categories:
            cat = _create_cold_start_category(
                session=session,
                item_title=item_title,
                item_excerpt=item_content,
                item_tags=tags,
                client=cli,
                config=cfg,
                item_class=item_class,
                item_metadata=item_metadata,
            )
            tax_item = TaxonomyItem(
                category_id=cat.id,
                item_type=item_type,
                item_id=item_id,
                item_title=item_title[:255],
                fit_score=1.0,
                assigned_at=now_str,
                item_class=item_class,
            )
            session.add(tax_item)
            cat.item_count = 1
            session.commit()

            return {
                "status": "cold_start_created",
                "category_id": cat.id,
                "category_name": cat.name,
                "item_class": item_class,
                "action": "created_first_category",
            }

        # 5. Filter for assignable candidate categories (leaf categories, not containers)
        assignable = [c for c in all_categories if not c.is_container]
        if not assignable:
            # All categories are containers; evaluate against all
            assignable = all_categories

        chosen_cat_id, is_confident = evaluate_category_fit_tev1(
            item_title=item_title,
            item_excerpt=item_content,
            item_tags=tags,
            candidate_categories=assignable,
            client=cli,
            config=cfg,
            item_class=item_class,
            item_metadata=item_metadata,
        )

        # 6. Fit confirmed
        if chosen_cat_id is not None and is_confident:
            cat = session.query(TaxonomyCategory).filter_by(id=chosen_cat_id).first()
            if cat:
                tax_item = TaxonomyItem(
                    category_id=cat.id,
                    item_type=item_type,
                    item_id=item_id,
                    item_title=item_title[:255],
                    fit_score=0.95,
                    assigned_at=now_str,
                    item_class=item_class,
                )
                session.add(tax_item)
                cat.item_count += 1
                session.commit()

                # Update category wiki doc
                _update_category_wiki_doc(
                    session=session,
                    category=cat,
                    new_item_title=item_title,
                    new_item_excerpt=item_content,
                    client=cli,
                    config=cfg,
                )

                post_agent_memory(
                    session=session,
                    agent_name="TaxonomyAgent",
                    channel="taxonomy",
                    topic="fit_assigned",
                    content=(
                        f"Assigned {item_class} item '{item_title}' to category '{cat.name}' (ID: {cat.id}) "
                        f"[Item Count: {cat.item_count}]. Updated category wiki doc."
                    ),
                    memory_type="decision",
                    metadata={
                        "category_id": cat.id,
                        "category_name": cat.name,
                        "item_type": item_type,
                        "item_id": item_id,
                        "item_class": item_class,
                        "count": cat.item_count,
                    },
                )

                # Check 10-Item threshold!
                if cat.item_count >= 10:
                    partition_category(
                        session=session,
                        category_id=cat.id,
                        client=cli,
                        config=cfg,
                    )

                return {
                    "status": "assigned",
                    "category_id": cat.id,
                    "category_name": cat.name,
                    "item_class": item_class,
                    "item_count": cat.item_count,
                }

        # 7. New Category synthesis
        new_cat = _synthesize_new_category(
            session=session,
            item_title=item_title,
            item_excerpt=item_content,
            item_tags=tags,
            existing_categories=all_categories,
            client=cli,
            config=cfg,
            item_class=item_class,
            item_metadata=item_metadata,
        )

        tax_item = TaxonomyItem(
            category_id=new_cat.id,
            item_type=item_type,
            item_id=item_id,
            item_title=item_title[:255],
            fit_score=1.0,
            assigned_at=now_str,
            item_class=item_class,
        )
        session.add(tax_item)
        new_cat.item_count = 1
        session.commit()

        return {
            "status": "new_category_created",
            "category_id": new_cat.id,
            "category_name": new_cat.name,
            "item_class": item_class,
            "item_count": 1,
        }



def classify_single_item(item_type: str, item_id: Any) -> Dict[str, Any]:
    """Helper entry point to classify an item by type and ID from background ingestion tasks."""
    with db_session() as session:
        title = "Untitled Item"
        content = ""
        tags: List[str] = []
        metadata: Dict[str, Any] = {}

        if item_type == "note":
            note = session.query(Note).filter_by(id=int(item_id)).first()
            if not note:
                return {"error": "Note not found"}
            title = note.title or "Untitled Note"
            content = note.content or ""
            try:
                tags = json.loads(note.tags or "[]")
            except Exception:
                pass
            item_id_str = f"note_{note.id}"
            metadata = {
                "vault": getattr(note, "vault_name", "Personal") or "Personal",
                "vault_name": getattr(note, "vault_name", "Personal") or "Personal",
                "folder": getattr(note, "folder_path", "") or "",
                "folder_path": getattr(note, "folder_path", "") or "",
                "url": note.url,
                "note_url": note.url,
                "created_at": str(note.created_at) if note.created_at else None,
                "updated_at": str(note.updated_at) if note.updated_at else None,
                "syntax": getattr(note, "syntax", "markdown"),
            }

        elif item_type == "article":
            page = session.query(FetchedPage).filter_by(url=str(item_id)).first()
            if not page:
                return {"error": "Article not found"}
            title = page.title or page.url
            content = page.description or page.md_content or ""
            try:
                tags = json.loads(page.tags or "[]")
            except Exception:
                pass
            item_id_str = page.url
            ver_count = session.query(PageVersion).filter_by(page_url=page.url).count()
            metadata = {
                "url": page.url,
                "domain": page.domain,
                "fetched_at": str(page.fetched_at) if hasattr(page, "fetched_at") else None,
                "version_count": ver_count,
            }

        elif item_type == "video":
            page = session.query(FetchedPage).filter_by(url=str(item_id)).first()
            if not page:
                return {"error": "Video not found"}
            title = page.title or "YouTube Video"
            content = page.description or ""
            item_id_str = page.url
            metadata = {
                "url": page.url,
                "domain": page.domain,
                "video_title": page.title,
            }

        elif item_type == "workspace":
            ws = session.query(Workspace).filter_by(id=int(item_id)).first()
            if not ws:
                return {"error": "Workspace not found"}
            title = ws.name or "Studio Workspace"
            content = ws.description or ""
            item_id_str = f"workspace_{ws.id}"
            file_count = session.query(WorkspaceFile).filter_by(workspace_id=ws.id).count()
            metadata = {
                "workspace_id": ws.id,
                "template": ws.template,
                "file_count": file_count,
            }

        else:
            return {"error": f"Unsupported item_type: {item_type}"}

        return classify_item(
            session=session,
            item_type=item_type,
            item_id=item_id_str,
            item_title=title,
            item_content=content,
            item_tags=tags,
            item_metadata=metadata,
        )


def crawl_and_classify_all(session: Session, limit: int = 50) -> Dict[str, Any]:
    """Autonomous background crawler that inspects unclassified articles, notes, videos,

    and workspaces, running them sequentially through the decision state machine.
    """
    classified_ids = {r[0] for r in session.query(TaxonomyItem.item_id).all()}

    # 1. Collect unclassified notes
    notes = session.query(Note).all()
    unclassified_notes = [n for n in notes if f"note_{n.id}" not in classified_ids]

    # 2. Collect unclassified articles and videos
    pages = session.query(FetchedPage).filter(~FetchedPage.url.like("note://%")).all()
    unclassified_pages = [p for p in pages if p.url not in classified_ids]

    # 3. Collect unclassified workspaces
    workspaces = session.query(Workspace).all()
    unclassified_workspaces = [w for w in workspaces if f"workspace_{w.id}" not in classified_ids]

    total_unclassified = len(unclassified_notes) + len(unclassified_pages) + len(unclassified_workspaces)
    processed_count = 0
    results: List[Dict[str, Any]] = []

    # Process batch up to limit
    for note in unclassified_notes:
        if processed_count >= limit:
            break
        res = classify_single_item("note", note.id)
        results.append(res)
        processed_count += 1

    for page in unclassified_pages:
        if processed_count >= limit:
            break
        item_t = "video" if "youtube.com" in page.url or "youtu.be" in page.url else "article"
        res = classify_single_item(item_t, page.url)
        results.append(res)
        processed_count += 1

    for ws in unclassified_workspaces:
        if processed_count >= limit:
            break
        res = classify_single_item("workspace", ws.id)
        results.append(res)
        processed_count += 1

    post_agent_memory(
        session=session,
        agent_name="TaxonomyCrawler",
        channel="taxonomy",
        topic="crawl_summary",
        content=f"Completed crawling run: processed {processed_count} unclassified items into taxonomy.",
        memory_type="observation",
        metadata={"processed": processed_count, "remaining": max(0, total_unclassified - processed_count)},
    )

    return {
        "total_unclassified_found": total_unclassified,
        "processed": processed_count,
        "remaining": max(0, total_unclassified - processed_count),
        "results": results,
    }
