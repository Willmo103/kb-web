"""Context Mesh Package.

Atomic context statements, declarative intent mappings, negative invariants,
vector persistence, feedback-loop fact extraction pipelines, and personal VK layer.
"""

from .models import (
    StatementType,
    TaxonomicLayer,
    EvalStatus,
    ContextStatement,
    AdmissionDecision,
    AssembledContext,
)
from .store import ContextStore, cosine_similarity
from .pipeline import FactExtractionPipeline
from .retriever import BubbleDownRetriever
from .injector import (
    SubconsciousContextInjector,
    get_subconscious_injector,
    auto_inject_subconscious_context,
)
from .personal_vk import (
    PersonalVKManager,
    get_personal_vk_manager,
    get_default_personal_vk,
)

__all__ = [
    "StatementType",
    "TaxonomicLayer",
    "EvalStatus",
    "ContextStatement",
    "AdmissionDecision",
    "AssembledContext",
    "ContextStore",
    "cosine_similarity",
    "FactExtractionPipeline",
    "BubbleDownRetriever",
    "SubconsciousContextInjector",
    "get_subconscious_injector",
    "auto_inject_subconscious_context",
    "PersonalVKManager",
    "get_personal_vk_manager",
    "get_default_personal_vk",
]
