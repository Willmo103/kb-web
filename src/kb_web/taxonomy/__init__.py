"""7-Tier Biological Taxonomy Classification & Management Package.

Implements the biological taxonomy hierarchy (Kingdom -> Phylum -> Class -> Order -> Family -> Genus -> Species)
for organizing knowledge, physical assets, notes, and code repositories, coupled with
steered tree governance, gating questions, domain blacklists, and lifecycle controls.
"""

from .models import (
    TaxonomyLevel,
    TaxonomyPath,
    KingdomNodeInfo,
    PhylumNodeInfo,
    ClassNodeInfo,
    OrderNodeInfo,
    FamilyNodeInfo,
    GenusNodeInfo,
    SpeciesNodeInfo,
    TaxonomyEntityRecord,
)
from .engine import (
    TaxonomyEngine,
    TaxonomyClassifier,
    assign_topic_and_subtopic,
    classify_steered_hierarchical,
    nuke_all_taxonomy,
    delete_topic_or_subtopic,
    bulk_move_items,
    bulk_move_facts,
)
from .steered_tree import (
    SteeredTaxonomyNode,
    SteeredTaxonomyTreeManager,
    get_steered_tree_manager,
    get_default_steered_tree,
)

__all__ = [
    "TaxonomyLevel",
    "TaxonomyPath",
    "KingdomNodeInfo",
    "PhylumNodeInfo",
    "ClassNodeInfo",
    "OrderNodeInfo",
    "FamilyNodeInfo",
    "GenusNodeInfo",
    "SpeciesNodeInfo",
    "TaxonomyEntityRecord",
    "TaxonomyEngine",
    "TaxonomyClassifier",
    "assign_topic_and_subtopic",
    "classify_steered_hierarchical",
    "nuke_all_taxonomy",
    "delete_topic_or_subtopic",
    "bulk_move_items",
    "bulk_move_facts",
    "SteeredTaxonomyNode",
    "SteeredTaxonomyTreeManager",
    "get_steered_tree_manager",
    "get_default_steered_tree",
]
