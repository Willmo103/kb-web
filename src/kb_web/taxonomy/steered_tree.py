"""Steered Taxonomy Tree Schema, Storage, and Governance.

Allows users to define, freeze, and steer a hierarchical taxonomy tree with
per-node gating questions, domain/source blacklists, and lifecycle rules
(auto-freeze vs. auto-refetch).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ..base import config as default_config
from .models import TaxonomyLevel

logger = logging.getLogger("kb_web.taxonomy.steered_tree")

TREE_CONFIG_FILE = Path.home() / ".kb" / "steered_taxonomy_tree.json"
SETTING_EXTERNAL_KEY = "steered_taxonomy_tree_json"


class SteeredTaxonomyNode(BaseModel):
    """Hierarchical node in the steered taxonomy tree."""

    id: str = Field(..., description="Unique node slug, e.g. 'kingdom_software_docs'")
    name: str = Field(..., description="Display title / coordinate token, e.g. 'Software Documentation'")
    level: str = Field(
        default=TaxonomyLevel.KINGDOM.value,
        description="Taxonomic tier level: kingdom | phylum | class | order | family | genus | species",
    )
    description: str = Field(default="", description="Guiding purpose or description for decision models")
    is_frozen: bool = Field(
        default=False,
        description="When true, incoming items MUST route strictly into pre-existing child nodes or leaves; no dynamic branching allowed.",
    )
    gating_questions: List[str] = Field(
        default_factory=list,
        description="Specific qualification questions that content must satisfy to be placed under this node.",
    )
    blacklisted_domains: List[str] = Field(
        default_factory=list,
        description="List of forbidden domain/source patterns (e.g. ['youtube.com', 'reddit.com', 'medium.com']).",
    )
    lifecycle_action: Literal["none", "freeze", "refetch"] = Field(
        default="none",
        description="Action applied to items assigned here: 'none', 'freeze' (sets is_frozen=1), or 'refetch' (scheduled re-fetch).",
    )
    refetch_interval_hours: Optional[int] = Field(
        default=None,
        description="Interval in hours between automated refetches if lifecycle_action is 'refetch'.",
    )
    children: List[SteeredTaxonomyNode] = Field(
        default_factory=list,
        description="Child taxonomy nodes at the subsequent hierarchical tier.",
    )

    def is_domain_blacklisted(self, url_or_domain: str) -> bool:
        """Check if a given URL or hostname is blacklisted on this node."""
        if not url_or_domain or not self.blacklisted_domains:
            return False

        clean_target = url_or_domain.lower().strip()
        if "://" in clean_target:
            try:
                parsed = urlparse(clean_target)
                clean_target = parsed.netloc or clean_target
            except Exception:
                pass

        if clean_target.startswith("www."):
            clean_target = clean_target[4:]

        for pattern in self.blacklisted_domains:
            pat = pattern.lower().strip()
            if pat.startswith("www."):
                pat = pat[4:]
            if not pat:
                continue
            if pat == clean_target or clean_target.endswith("." + pat) or pat in clean_target:
                return True
        return False


def get_default_steered_tree() -> List[SteeredTaxonomyNode]:
    """Generates the baseline default steered taxonomy tree with user-friendly initial topics."""
    return [
        SteeredTaxonomyNode(
            id="kingdom_software_docs",
            name="Software Documentation",
            level="kingdom",
            description="Official technical documentation, API references, library guides, SDK manuals, and developer specifications.",
            is_frozen=True,
            gating_questions=[
                "Does this item provide technical instructions, API documentation, or reference manuals for software or engineering systems?"
            ],
            blacklisted_domains=["tiktok.com", "instagram.com", "pinterest.com"],
            lifecycle_action="none",
            children=[
                SteeredTaxonomyNode(
                    id="phylum_official_docs",
                    name="Official-Documentation",
                    level="phylum",
                    description="Official first-party documentation released by software publishers or project maintainers.",
                    is_frozen=True,
                    gating_questions=["Is this published directly by the official maintainers or canonical project repository?"],
                    lifecycle_action="none",
                    children=[
                        SteeredTaxonomyNode(
                            id="class_python_ecosystem",
                            name="Python-Ecosystem",
                            level="class",
                            description="Official Python language, standard library, and core package documentation.",
                            is_frozen=True,
                            gating_questions=["Does this pertain to Python libraries, tools, or runtimes?"],
                            lifecycle_action="refetch",
                            refetch_interval_hours=168,
                        ),
                        SteeredTaxonomyNode(
                            id="class_supabase",
                            name="Supabase",
                            level="class",
                            description="Official Supabase client, database, auth, and storage documentation.",
                            is_frozen=True,
                            gating_questions=["Does this pertain to Supabase backend architecture, APIs, or tooling?"],
                            lifecycle_action="refetch",
                            refetch_interval_hours=168,
                        ),
                    ],
                ),
                SteeredTaxonomyNode(
                    id="phylum_architecture_specs",
                    name="Architecture-Specs",
                    level="phylum",
                    description="Design proposals, RFCs, and formal architectural specifications.",
                    is_frozen=True,
                    lifecycle_action="freeze",
                ),
            ],
        ),
        SteeredTaxonomyNode(
            id="kingdom_news",
            name="News",
            level="kingdom",
            description="Current affairs, journalistic articles, press releases, breaking stories, and policy updates.",
            is_frozen=False,
            gating_questions=["Is this a time-sensitive journalistic article or current news event?"],
            blacklisted_domains=[],
            lifecycle_action="freeze",
            children=[
                SteeredTaxonomyNode(
                    id="phylum_activism",
                    name="Activism",
                    level="phylum",
                    description="Environmental advocacy, community policy, and civic activism.",
                    is_frozen=True,
                    gating_questions=["Does this cover grassroots activism, community advocacy, or environmental policy?"],
                    children=[
                        SteeredTaxonomyNode(
                            id="class_removal_efforts",
                            name="Removal-Efforts",
                            level="class",
                            description="Dam removal, river restoration, and civic remediation initiatives.",
                            is_frozen=True,
                            lifecycle_action="freeze",
                        )
                    ],
                )
            ],
        ),
        SteeredTaxonomyNode(
            id="kingdom_hobby_leisure",
            name="Hobby/Leisure",
            level="kingdom",
            description="Recreational pursuits, outdoor activities, sports, cooking, crafting, and personal hobbies.",
            is_frozen=True,
            gating_questions=["Is this centered on personal recreation, outdoor activities, or leisurely crafts?"],
            children=[
                SteeredTaxonomyNode(
                    id="phylum_fishing",
                    name="Fishing",
                    level="phylum",
                    description="Angling, fly fishing, tackle craft, and aquatic recreation.",
                    is_frozen=True,
                    gating_questions=["Does this relate to fishing or angling gear/techniques?"],
                    children=[
                        SteeredTaxonomyNode(
                            id="class_ultralight",
                            name="Ultralight",
                            level="class",
                            description="Ultralight tackle, minimalist gear setups, and high-portability setups.",
                            is_frozen=True,
                            gating_questions=["Does this specifically focus on ultralight or minimalist setups?"],
                            lifecycle_action="freeze",
                        )
                    ],
                )
            ],
        ),
        SteeredTaxonomyNode(
            id="kingdom_reference",
            name="Reference",
            level="kingdom",
            description="Encyclopedic knowledge, glossaries, cheat-sheets, taxonomic registries, and static manuals.",
            is_frozen=True,
            lifecycle_action="freeze",
        ),
        SteeredTaxonomyNode(
            id="kingdom_resource",
            name="Resource",
            level="kingdom",
            description="Tools, repositories, curated lists, media assets, datasets, and downloadable utilities.",
            is_frozen=False,
            lifecycle_action="none",
        ),
        SteeredTaxonomyNode(
            id="kingdom_blogpost_article",
            name="Blogpost/Article",
            level="kingdom",
            description="Personal blog essays, tutorials, opinion pieces, commentary, and narrative articles.",
            is_frozen=False,
            lifecycle_action="freeze",
        ),
    ]


class SteeredTaxonomyTreeManager:
    """Manages reading, persisting, searching, and validating the steered taxonomy tree."""

    def __init__(self, config_obj: Any = None) -> None:
        self.config = config_obj or default_config

    def get_tree(self) -> List[SteeredTaxonomyNode]:
        """Load steered taxonomy tree from disk or DB setting; falls back to default seed."""
        # 1. Try disk
        if TREE_CONFIG_FILE.exists():
            try:
                with open(TREE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        return [SteeredTaxonomyNode.model_validate(item) for item in raw]
            except Exception as e:
                logger.warning(f"Failed loading steered taxonomy tree from file {TREE_CONFIG_FILE}: {e}")

        # 2. Try DB setting
        try:
            db_val = self.config._read_db_setting("settings_external", SETTING_EXTERNAL_KEY, None)
            if db_val:
                raw = json.loads(db_val)
                if isinstance(raw, list):
                    return [SteeredTaxonomyNode.model_validate(item) for item in raw]
        except Exception as e:
            logger.warning(f"Failed loading steered taxonomy tree from DB: {e}")

        # 3. Default tree
        default_tree = get_default_steered_tree()
        self.save_tree(default_tree)
        return default_tree

    def save_tree(self, nodes: List[SteeredTaxonomyNode] | List[Dict[str, Any]]) -> List[SteeredTaxonomyNode]:
        """Save steered taxonomy tree to disk and DB setting."""
        validated: List[SteeredTaxonomyNode] = []
        for n in nodes:
            if isinstance(n, SteeredTaxonomyNode):
                validated.append(n)
            elif isinstance(n, dict):
                validated.append(SteeredTaxonomyNode.model_validate(n))

        serialized = [n.model_dump() for n in validated]
        json_str = json.dumps(serialized, indent=2)

        # 1. Write disk
        try:
            TREE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TREE_CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(json_str)
        except Exception as e:
            logger.error(f"Error saving steered taxonomy tree to {TREE_CONFIG_FILE}: {e}")

        # 2. Write DB
        try:
            self.config._write_db_setting("settings_external", SETTING_EXTERNAL_KEY, json_str)
        except Exception as e:
            logger.error(f"Error saving steered taxonomy tree to DB: {e}")

        return validated

    def find_node(
        self,
        node_id_or_name: str,
        nodes: Optional[List[SteeredTaxonomyNode]] = None,
    ) -> Optional[SteeredTaxonomyNode]:
        """Recursively search for a node by id or case-insensitive name."""
        if nodes is None:
            nodes = self.get_tree()

        clean_target = node_id_or_name.strip().lower()
        for node in nodes:
            if node.id.lower() == clean_target or node.name.lower() == clean_target:
                return node
            if node.children:
                found = self.find_node(clean_target, node.children)
                if found:
                    return found
        return None

    def get_valid_children(
        self,
        parent_node: Optional[SteeredTaxonomyNode],
        url_or_domain: str = "",
    ) -> List[SteeredTaxonomyNode]:
        """Return candidate child nodes filtered against domain blacklists."""
        candidates = parent_node.children if parent_node else self.get_tree()
        valid: List[SteeredTaxonomyNode] = []
        for cand in candidates:
            if url_or_domain and cand.is_domain_blacklisted(url_or_domain):
                continue
            valid.append(cand)
        return valid


_global_tree_manager: Optional[SteeredTaxonomyTreeManager] = None


def get_steered_tree_manager() -> SteeredTaxonomyTreeManager:
    """Singleton getter for SteeredTaxonomyTreeManager."""
    global _global_tree_manager
    if _global_tree_manager is None:
        _global_tree_manager = SteeredTaxonomyTreeManager()
    return _global_tree_manager

