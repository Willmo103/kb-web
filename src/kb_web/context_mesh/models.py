"""Models for Context Statements, Intent Mappings, and Dynamic Context Mesh."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StatementType(str, enum.Enum):
    INTENT_MAPPING = "intent_mapping"
    NEGATIVE_INVARIANT = "negative_invariant"
    AFFORDANCE = "affordance"
    HABIT = "habit"
    FACT = "fact"
    PREFERENCE = "preference"


class TaxonomicLayer(str, enum.Enum):
    KINGDOM = "kingdom"
    PHYLUM = "phylum"
    CLASS = "class"
    ORDER = "order"
    FAMILY = "family"
    GENUS = "genus"
    SPECIES = "species"


class EvalStatus(str, enum.Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REJECTED = "rejected"


class ContextStatement(BaseModel):
    """An atomic declarative context sentence grounded in personal intent,

    annotated with taxonomic coordinates, layer depth, and hard provenance.
    """

    id: str = Field(default_factory=lambda: f"stmt_{uuid.uuid4().hex[:10]}")
    statement: str
    statement_type: StatementType = StatementType.FACT
    canonical_path: str  # e.g., 'knowledge/text/human_read/kb_web/architecture/ArticleWiki/embedding_unification'
    layer_level: TaxonomicLayer = TaxonomicLayer.SPECIES
    source_uri: str  # Hard clickable reference URL or markdown URI
    source_title: str
    confidence: float = 1.0
    embedding: Optional[List[float]] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Score ranking & evaluation feedback for back-propagation
    score_rank: float = 3.0  # Default 3.0 on 0.0 - 5.0 scale
    eval_status: EvalStatus = EvalStatus.UNREVIEWED
    eval_feedback: Optional[str] = None
    eval_count: int = 0
    last_evaluated_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_citation_markdown(self) -> str:
        """Render a formatted markdown statement with hard document citation and score badge."""
        rank_badge = f" [⭐{self.score_rank:.1f}]" if self.eval_status != EvalStatus.UNREVIEWED else ""
        return f"- **[{self.statement_type.value.upper()}]** {self.statement} *([Source: {self.source_title}]({self.source_uri})){rank_badge}*"


class AdmissionDecision(BaseModel):
    """Outcome of evaluating an asset against top-level user admission rules."""

    admitted: bool
    target_kingdom: Optional[str] = None
    target_phylum: Optional[str] = None
    rationale: str = ""
    extracted_metadata: Dict[str, Any] = Field(default_factory=dict)


class AssembledContext(BaseModel):
    """Aggregated result of a hierarchical context retrieval pass."""

    query: str
    routed_kingdom: str
    routed_phylum: str
    router_confidence: float
    statements: List[ContextStatement]
    formatted_context_block: str
    citations: List[Dict[str, str]]
