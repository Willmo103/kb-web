"""7-Tier Biological Taxonomy Classification & Management Package.

Implements the biological taxonomy hierarchy (Kingdom -> Phylum -> Class -> Order -> Family -> Genus -> Species)
for organizing knowledge, physical assets, notes, and code repositories.
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
from .engine import TaxonomyEngine, TaxonomyClassifier

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
]
