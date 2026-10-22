"""Context Mesh Package.

Atomic context statements, declarative intent mappings, negative invariants,
vector persistence, and feedback-loop fact extraction pipelines.
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
]

