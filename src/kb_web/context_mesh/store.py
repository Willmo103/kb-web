"""Persistence store for context statements.

Supports metadata filtering, layer queries, vector similarity search,
and feedback score ranking with back-propagation using SQLAlchemy.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..base import db_session
from ..models_orm import ContextStatementORM
from .models import ContextStatement, EvalStatus, StatementType, TaxonomicLayer


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


class ContextStore:
    """Manages context_statements persistence, similarity querying, and evaluation ranking."""

    @staticmethod
    def _orm_to_model(orm: ContextStatementORM) -> ContextStatement:
        """Convert ContextStatementORM to Pydantic ContextStatement."""
        embedding_val: Optional[List[float]] = None
        if orm.statement_vector:
            if isinstance(orm.statement_vector, list):
                embedding_val = [float(x) for x in orm.statement_vector]
            elif isinstance(orm.statement_vector, str):
                try:
                    parsed = json.loads(orm.statement_vector)
                    if isinstance(parsed, list):
                        embedding_val = [float(x) for x in parsed]
                except Exception:
                    pass

        tags_val: List[str] = []
        if orm.tags_json:
            try:
                parsed_tags = json.loads(orm.tags_json)
                if isinstance(parsed_tags, list):
                    tags_val = parsed_tags
            except Exception:
                pass

        meta_val: Dict[str, Any] = {}
        if orm.metadata_json:
            try:
                parsed_meta = json.loads(orm.metadata_json)
                if isinstance(parsed_meta, dict):
                    meta_val = parsed_meta
            except Exception:
                pass

        return ContextStatement(
            id=orm.id,
            statement=orm.statement,
            statement_type=StatementType(orm.statement_type),
            canonical_path=orm.canonical_path,
            layer_level=TaxonomicLayer(orm.layer_level),
            source_uri=orm.source_uri,
            source_title=orm.source_title,
            confidence=orm.confidence or 1.0,
            embedding=embedding_val,
            tags=tags_val,
            metadata=meta_val,
            score_rank=orm.score_rank if orm.score_rank is not None else 3.0,
            eval_status=EvalStatus(orm.eval_status or "unreviewed"),
            eval_feedback=orm.eval_feedback,
            eval_count=orm.eval_count or 0,
            last_evaluated_at=orm.last_evaluated_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def upsert(self, stmt: ContextStatement) -> ContextStatement:
        """Insert or update a single context statement."""
        parts = [p.strip() for p in stmt.canonical_path.replace("::", "/").split("/") if p.strip()]
        kingdom = parts[0] if len(parts) > 0 else None
        phylum = parts[1] if len(parts) > 1 else None
        class_name = parts[2] if len(parts) > 2 else None
        order_name = parts[3] if len(parts) > 3 else None
        family = parts[4] if len(parts) > 4 else None
        genus = parts[5] if len(parts) > 5 else None
        species = parts[6] if len(parts) > 6 else None

        tags_json = json.dumps(stmt.tags)
        meta_json = json.dumps(stmt.metadata)

        with db_session() as session:
            existing = session.query(ContextStatementORM).filter_by(id=stmt.id).first()
            if existing:
                existing.statement = stmt.statement
                existing.statement_type = stmt.statement_type.value
                existing.canonical_path = stmt.canonical_path
                existing.layer_level = stmt.layer_level.value
                existing.kingdom = kingdom
                existing.phylum = phylum
                existing.class_name = class_name
                existing.order_name = order_name
                existing.family = family
                existing.genus = genus
                existing.species = species
                existing.source_uri = stmt.source_uri
                existing.source_title = stmt.source_title
                existing.confidence = stmt.confidence
                if stmt.embedding:
                    existing.statement_vector = stmt.embedding
                existing.tags_json = tags_json
                existing.metadata_json = meta_json
                existing.score_rank = stmt.score_rank
                existing.eval_status = stmt.eval_status.value
                existing.eval_feedback = stmt.eval_feedback
                existing.eval_count = stmt.eval_count
                existing.last_evaluated_at = stmt.last_evaluated_at
                existing.updated_at = datetime.now(timezone.utc).isoformat()
            else:
                new_orm = ContextStatementORM(
                    id=stmt.id,
                    statement=stmt.statement,
                    statement_type=stmt.statement_type.value,
                    canonical_path=stmt.canonical_path,
                    layer_level=stmt.layer_level.value,
                    kingdom=kingdom,
                    phylum=phylum,
                    class_name=class_name,
                    order_name=order_name,
                    family=family,
                    genus=genus,
                    species=species,
                    source_uri=stmt.source_uri,
                    source_title=stmt.source_title,
                    confidence=stmt.confidence,
                    statement_vector=stmt.embedding,
                    tags_json=tags_json,
                    metadata_json=meta_json,
                    score_rank=stmt.score_rank,
                    eval_status=stmt.eval_status.value,
                    eval_feedback=stmt.eval_feedback,
                    eval_count=stmt.eval_count,
                    last_evaluated_at=stmt.last_evaluated_at,
                    created_at=stmt.created_at,
                    updated_at=stmt.updated_at,
                )
                session.add(new_orm)
            session.commit()
            return stmt

    def upsert_batch(self, statements: List[ContextStatement]) -> int:
        """Batch upsert multiple context statements."""
        for stmt in statements:
            self.upsert(stmt)
        return len(statements)

    def get_by_id(self, statement_id: str) -> Optional[ContextStatement]:
        """Fetch a statement by primary key."""
        with db_session() as session:
            orm = session.query(ContextStatementORM).filter_by(id=statement_id).first()
            if not orm:
                return None
            return self._orm_to_model(orm)

    def update_evaluation(
        self,
        statement_id: str,
        score: float,
        status: Optional[EvalStatus] = None,
        feedback: Optional[str] = None,
    ) -> ContextStatement:
        """Assign score rank, update review status, and record evaluation feedback."""
        stmt = self.get_by_id(statement_id)
        if not stmt:
            raise KeyError(f"Context statement '{statement_id}' not found.")

        if status is None:
            if score >= 3.5:
                derived_status = EvalStatus.APPROVED
            elif score >= 2.0:
                derived_status = EvalStatus.FLAGGED
            else:
                derived_status = EvalStatus.REJECTED
        else:
            derived_status = status

        stmt.score_rank = max(0.0, min(5.0, score))
        stmt.eval_status = derived_status
        if feedback is not None:
            stmt.eval_feedback = feedback
        stmt.eval_count += 1
        stmt.last_evaluated_at = datetime.now(timezone.utc).isoformat()
        stmt.updated_at = datetime.now(timezone.utc).isoformat()

        self.upsert(stmt)
        return stmt

    def list_statements(
        self,
        layer: Optional[TaxonomicLayer] = None,
        statement_type: Optional[StatementType] = None,
        canonical_prefix: Optional[str] = None,
        eval_status: Optional[EvalStatus] = None,
        min_score: Optional[float] = None,
        source_uri: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ContextStatement]:
        """Query statements filtered by layer, type, status, source URI, or path prefix."""
        with db_session() as session:
            q = session.query(ContextStatementORM)
            if layer:
                q = q.filter(ContextStatementORM.layer_level == layer.value)
            if statement_type:
                q = q.filter(ContextStatementORM.statement_type == statement_type.value)
            if canonical_prefix:
                q = q.filter(ContextStatementORM.canonical_path.like(f"{canonical_prefix}%"))
            if eval_status:
                q = q.filter(ContextStatementORM.eval_status == eval_status.value)
            if min_score is not None:
                q = q.filter(ContextStatementORM.score_rank >= min_score)
            if source_uri:
                q = q.filter(ContextStatementORM.source_uri == source_uri)
            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    (ContextStatementORM.statement.ilike(pattern))
                    | (ContextStatementORM.source_title.ilike(pattern))
                    | (ContextStatementORM.canonical_path.ilike(pattern))
                )

            q = q.order_by(ContextStatementORM.score_rank.desc(), ContextStatementORM.created_at.desc())
            if offset > 0:
                q = q.offset(offset)
            results = q.limit(limit).all()
            return [self._orm_to_model(r) for r in results]

    def count_statements(
        self,
        layer: Optional[TaxonomicLayer] = None,
        statement_type: Optional[StatementType] = None,
        canonical_prefix: Optional[str] = None,
        eval_status: Optional[EvalStatus] = None,
        source_uri: Optional[str] = None,
        query: Optional[str] = None,
    ) -> int:
        """Count statements matching the given criteria."""
        with db_session() as session:
            q = session.query(ContextStatementORM)
            if layer:
                q = q.filter(ContextStatementORM.layer_level == layer.value)
            if statement_type:
                q = q.filter(ContextStatementORM.statement_type == statement_type.value)
            if canonical_prefix:
                q = q.filter(ContextStatementORM.canonical_path.like(f"{canonical_prefix}%"))
            if eval_status:
                q = q.filter(ContextStatementORM.eval_status == eval_status.value)
            if source_uri:
                q = q.filter(ContextStatementORM.source_uri == source_uri)
            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    (ContextStatementORM.statement.ilike(pattern))
                    | (ContextStatementORM.source_title.ilike(pattern))
                    | (ContextStatementORM.canonical_path.ilike(pattern))
                )
            return q.count()

    def get_exemplars(
        self,
        positive_limit: int = 5,
        negative_limit: int = 3,
    ) -> Tuple[List[ContextStatement], List[ContextStatement]]:
        """Fetch approved gold-standard exemplars and rejected anti-patterns."""
        with db_session() as session:
            pos_orms = (
                session.query(ContextStatementORM)
                .filter(
                    (ContextStatementORM.eval_status == EvalStatus.APPROVED.value)
                    | (ContextStatementORM.score_rank >= 4.0)
                )
                .order_by(ContextStatementORM.score_rank.desc())
                .limit(positive_limit)
                .all()
            )

            neg_orms = (
                session.query(ContextStatementORM)
                .filter(
                    (ContextStatementORM.eval_status == EvalStatus.REJECTED.value)
                    | (ContextStatementORM.score_rank < 2.0)
                )
                .order_by(ContextStatementORM.score_rank.asc())
                .limit(negative_limit)
                .all()
            )

            positives = [self._orm_to_model(r) for r in pos_orms]
            negatives = [self._orm_to_model(r) for r in neg_orms]
            return positives, negatives

    def search_by_vector(
        self,
        query_vector: List[float],
        top_k: int = 5,
        canonical_prefix: Optional[str] = None,
        layer: Optional[TaxonomicLayer] = None,
        statement_type: Optional[StatementType] = None,
        include_rejected: bool = False,
    ) -> List[Tuple[ContextStatement, float]]:
        """Vector similarity search with score-rank composite weighting.

        Composite ranking metric:
          final_score = 0.65 * cosine_sim + 0.35 * (score_rank / 5.0)
        Suppresses rejected/flagged statements (< 2.0 score) unless include_rejected is True.
        """
        candidates = self.list_statements(
            layer=layer,
            statement_type=statement_type,
            canonical_prefix=canonical_prefix,
            limit=500,
        )

        scored: List[Tuple[ContextStatement, float]] = []
        for stmt in candidates:
            if not stmt.embedding:
                continue

            if not include_rejected and (stmt.eval_status == EvalStatus.REJECTED or stmt.score_rank < 2.0):
                continue

            sim = cosine_similarity(query_vector, stmt.embedding)
            norm_rank = stmt.score_rank / 5.0
            composite_score = round(0.65 * sim + 0.35 * norm_rank, 4)

            scored.append((stmt, composite_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
