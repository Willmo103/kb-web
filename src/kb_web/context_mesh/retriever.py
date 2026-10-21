"""Hierarchical Bubble-Down Retriever.

Classifies top-level Kingdom and Phylum, then queries vector embeddings layer by layer
to assemble rich, intent-grounded context with hard document provenance citations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..base import config as default_config, _get_ollama_client, LoggedOllamaClient
from ..utils import get_active_embedding_model, ensure_model_available
from .models import AssembledContext, ContextStatement, TaxonomicLayer
from .store import ContextStore

logger = logging.getLogger(__name__)


class BubbleDownRetriever:
    """Executes hierarchical retrieval over the context mesh:

    1. Decision router (d1) selects Kingdom & Phylum.
    2. Embedding search queries layer by layer (Kingdom -> Phylum -> Order -> Species).
    3. Assembles multi-tier statements into an intent payload with hard citations.
    """

    def __init__(
        self,
        store: Optional[ContextStore] = None,
        config: Optional[Any] = None,
        client: Optional[LoggedOllamaClient] = None,
        embedding_model: Optional[str] = None,
    ) -> None:
        self.store = store or ContextStore()
        self.config = config or default_config
        self.client = client or _get_ollama_client()
        self.embedding_model = embedding_model or get_active_embedding_model(config=self.config)

    def route_kingdom_and_phylum(self, query: str) -> Tuple[str, str, float]:
        """Evaluate user query against top-level taxonomic coordinates.

        Uses fast decision model (d1) if accessible, with fallback heuristic routing.
        """
        try:
            questions = {
                "kingdom": {
                    "type": "choice",
                    "instructions": "Which domain kingdom best categorizes `query`?",
                    "criteria": {
                        "knowledge": "Articles, documentation, research, wikis, learning notes, reference guides",
                        "software": "Codebases, Git repositories, CLI tools, scripts, Python packages, pull requests",
                        "infrastructure": "Servers, networking, Docker containers, databases, PostgreSQL, Qdrant, system services",
                        "personal": "Home automation, personal devices, daily routine, lighting, smart home",
                        "professional": "Work employment, sprints, job tasks, business meetings",
                    },
                },
                "phylum": {
                    "type": "choice",
                    "instructions": "Which subsystem medium best fits `query`?",
                    "criteria": {
                        "text": "Human-readable articles, documentation, books, written content",
                        "code": "Source code files, scripts, programming logic, pull requests",
                        "media": "Videos, audio streams, YouTube recordings, visual media",
                        "iot": "Smart home devices, sensors, lights, switches",
                        "tooling": "Developer CLI utilities, dev tools, command line tools",
                        "vault": "Markdown notes, journals, obsidian records",
                    },
                },
            }

            resp = self.client.systemone(
                model="d1",
                state={"query": query},
                questions=questions,
            )

            answers = {}
            if isinstance(resp, dict):
                answers = resp.get("answers", {})
            elif hasattr(resp, "answers"):
                answers = resp.answers

            k_data = answers.get("kingdom", {})
            p_data = answers.get("phylum", {})

            k_choice = k_data.get("choice") if isinstance(k_data, dict) else getattr(k_data, "choice", None)
            p_choice = p_data.get("choice") if isinstance(p_data, dict) else getattr(p_data, "choice", None)
            conf = k_data.get("score", 0.9) if isinstance(k_data, dict) else getattr(k_data, "score", 0.9)

            if k_choice and p_choice:
                return str(k_choice), str(p_choice), float(conf or 0.9)
        except Exception as e:
            logger.debug(f"Decision model d1 routing failed, using heuristic: {e}")

        # Robust heuristic fallback router with whole-word matching
        import re
        q_lower = query.lower()

        def has_word(words: List[str]) -> bool:
            return any(re.search(rf"\b{re.escape(w)}\b", q_lower) for w in words)

        if has_word(["video", "youtube", "podcast", "channel", "audio", "movie", "recording"]):
            return "knowledge", "media", 0.90
        if has_word(["git", "repo", "commit", "code", "python", "script", "branch", "cli"]):
            return "software", "code", 0.92
        if has_word(["server", "docker", "postgres", "database", "qdrant", "nginx", "service", "systemd"]):
            return "infrastructure", "tooling", 0.90
        if has_word(["light", "fan", "bedroom", "living", "scene", "home", "sensor"]):
            return "personal", "iot", 0.90
        if has_word(["sprint", "meeting", "work", "job", "ticket", "epicor"]):
            return "professional", "text", 0.85

        return "knowledge", "text", 0.80

    def _embed_query(self, query: str) -> Optional[List[float]]:
        """Generate embedding vector for search query."""
        if not query.strip():
            return None
        emb_model = self.embedding_model or get_active_embedding_model(config=self.config)
        prompt_prefix = "search_query: " if ("gemma" in emb_model.lower() or "nomic" in emb_model.lower()) else ""
        prompt_text = f"{prompt_prefix}{query[:4000]}"
        try:
            ensure_model_available(self.client, emb_model)
            resp = self.client.embeddings(model=emb_model, prompt=prompt_text)
            if isinstance(resp, dict) and "embedding" in resp:
                return resp["embedding"]
            elif hasattr(resp, "embedding"):
                return list(resp.embedding)
        except Exception as e:
            logger.warning(f"BubbleDownRetriever query embedding failed: {e}")
        return None

    def retrieve(self, query: str, top_k_per_layer: int = 3) -> AssembledContext:
        """Execute full hierarchical bubble-down retrieval for the query."""
        kingdom, phylum, router_conf = self.route_kingdom_and_phylum(query)
        query_vec = self._embed_query(query)

        collected_statements: List[ContextStatement] = []
        seen_ids: set[str] = set()

        prefix = f"{kingdom}/{phylum}"

        if query_vec:
            # 1. Top Layer: Kingdom / Phylum Broad Principles
            top_matches = (
                self.store.search_by_vector(
                    query_vector=query_vec,
                    top_k=top_k_per_layer,
                    canonical_prefix=prefix,
                    layer=TaxonomicLayer.KINGDOM,
                )
                + self.store.search_by_vector(
                    query_vector=query_vec,
                    top_k=top_k_per_layer,
                    canonical_prefix=prefix,
                    layer=TaxonomicLayer.PHYLUM,
                )
            )

            for stmt, _ in top_matches:
                if stmt.id not in seen_ids:
                    seen_ids.add(stmt.id)
                    collected_statements.append(stmt)

            # 2. Mid Layer: Order / Family Conventions
            mid_matches = (
                self.store.search_by_vector(
                    query_vector=query_vec,
                    top_k=top_k_per_layer,
                    canonical_prefix=prefix,
                    layer=TaxonomicLayer.ORDER,
                )
                + self.store.search_by_vector(
                    query_vector=query_vec,
                    top_k=top_k_per_layer,
                    canonical_prefix=prefix,
                    layer=TaxonomicLayer.FAMILY,
                )
            )

            for stmt, _ in mid_matches:
                if stmt.id not in seen_ids:
                    seen_ids.add(stmt.id)
                    collected_statements.append(stmt)

            # 3. Ground Layer: Species Concrete Intent & Invariants
            ground_matches = self.store.search_by_vector(
                query_vector=query_vec,
                top_k=top_k_per_layer * 2,
                canonical_prefix=prefix,
                layer=TaxonomicLayer.SPECIES,
            )

            for stmt, _ in ground_matches:
                if stmt.id not in seen_ids:
                    seen_ids.add(stmt.id)
                    collected_statements.append(stmt)

            # If zero matches in prefix, fallback to global similarity search
            if not collected_statements:
                fallback = self.store.search_by_vector(query_vector=query_vec, top_k=5)
                for stmt, _ in fallback:
                    if stmt.id not in seen_ids:
                        seen_ids.add(stmt.id)
                        collected_statements.append(stmt)
        else:
            # If embeddings are unavailable, fallback to prefix/layer query
            prefix_stmts = self.store.list_statements(canonical_prefix=prefix, limit=6)
            for stmt in prefix_stmts:
                if stmt.id not in seen_ids:
                    seen_ids.add(stmt.id)
                    collected_statements.append(stmt)

        # Build formatted context block with citations
        lines = [
            f"### Personal Intent & Operational Context for: '{query}'",
            f"*Classified Domain: `{kingdom}/{phylum}` (confidence: {router_conf:.2f})*",
            "",
        ]

        citations: List[Dict[str, str]] = []
        for stmt in collected_statements:
            lines.append(stmt.to_citation_markdown())
            citations.append({
                "statement_id": stmt.id,
                "type": stmt.statement_type.value,
                "source_title": stmt.source_title,
                "source_uri": stmt.source_uri,
            })

        formatted_block = "\n".join(lines)

        return AssembledContext(
            query=query,
            routed_kingdom=kingdom,
            routed_phylum=phylum,
            router_confidence=router_conf,
            statements=collected_statements,
            formatted_context_block=formatted_block,
            citations=citations,
        )
