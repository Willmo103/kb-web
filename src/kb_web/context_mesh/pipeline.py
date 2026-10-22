"""Fact Extraction & Intent Derivation Pipeline.

Parses raw ingested web sources, repos, and notes into atomic context statements
using dynamic system instructions, live positive/negative exemplars, Ollama models,
and unified vector embeddings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..base import config as default_config, _get_ollama_client, LoggedOllamaClient
from ..taxonomy.engine import TaxonomyClassifier, TaxonomyEngine
from ..utils import get_active_embedding_model, ensure_model_available
from .models import ContextStatement, EvalStatus, StatementType, TaxonomicLayer
from .store import ContextStore


class FactExtractionPipeline:
    """Orchestrates atomic fact and intent extraction from ingested sources with a dynamic feedback loop.

    Uses positive exemplars and negative anti-patterns to adapt prompt instructions without retraining.
    """

    def __init__(
        self,
        store: Optional[ContextStore] = None,
        config: Optional[Any] = None,
        client: Optional[LoggedOllamaClient] = None,
        model_name: Optional[str] = None,
        embedding_model: Optional[str] = None,
        temperature: float = 0.1,
    ) -> None:
        self.store = store or ContextStore()
        self.config = config or default_config
        self.client = client or _get_ollama_client()
        self.model_name = model_name or getattr(self.config, "ollama_model", "ornith-1.5:9b")
        self.embedding_model = embedding_model or get_active_embedding_model(config=self.config)
        self.temperature = temperature

    def build_system_prompt(self) -> str:
        """Dynamically build extraction system instructions with live positive & negative exemplars.

        Closes the reinforcement loop without model retraining.
        """
        positives, negatives = self.store.get_exemplars(positive_limit=4, negative_limit=3)

        prompt_parts = [
            "You are the Personal Context & Intent Extraction Engine for knowledge curation.",
            "Your objective is to extract atomic, declarative context sentences capturing true intent, operational rules, core architectural constraints, habits, and domain facts.",
            "",
            "CRITICAL PRINCIPLES:",
            "1. Declarative & Atomic: Extract discrete, self-contained sentences rather than vague generalities.",
            "2. Ground Truth & Provenance: Extract facts directly supported by the provided source; do not hallucinate.",
            "3. Statement Types: Classify each into: 'intent_mapping', 'negative_invariant', 'affordance', 'habit', 'preference', or 'fact'.",
            "4. Taxonomic Layer: Classify each statement's depth level into: 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', or 'species'.",
            "5. Output Format: Output valid JSON only, conforming to a list of objects with keys: 'statement', 'statement_type', 'layer_level'.",
        ]

        if positives:
            prompt_parts.append("\n## GOLD-STANDARD EXEMPLARS (Adopt This Style):")
            for p in positives:
                prompt_parts.append(f"- [{p.statement_type.value.upper()}] \"{p.statement}\" (Score: {p.score_rank:.1f})")

        if negatives:
            prompt_parts.append("\n## OFF-BASE ANTI-PATTERNS (Avoid These Patterns):")
            for n in negatives:
                feedback = f" [Feedback: {n.eval_feedback}]" if n.eval_feedback else ""
                prompt_parts.append(f"- [{n.statement_type.value.upper()}] \"{n.statement}\"{feedback}")

        return "\n".join(prompt_parts)

    def _embed_text(self, text: str) -> Optional[List[float]]:
        """Generate embedding vector for a single statement using active embedding model."""
        if not text.strip():
            return None
        emb_model = self.embedding_model or get_active_embedding_model(config=self.config)
        prompt_prefix = "search_document: " if ("gemma" in emb_model.lower() or "nomic" in emb_model.lower()) else ""
        prompt_text = f"{prompt_prefix}{text[:4000]}"
        try:
            ensure_model_available(self.client, emb_model)
            resp = self.client.embeddings(model=emb_model, prompt=prompt_text)
            if isinstance(resp, dict) and "embedding" in resp:
                return resp["embedding"]
            elif hasattr(resp, "embedding"):
                return list(resp.embedding)
        except Exception as e:
            print(f"Fact extraction embedding failed with model '{emb_model}': {e}")
        return None

    def _heuristic_fallback_extraction(self, text: str, title: str) -> List[Dict[str, Any]]:
        """Fallback rule-based sentence chunking when Ollama is offline or fails."""
        lines = [line.strip().lstrip("-*#0123456789. ") for line in text.split("\n") if len(line.strip()) > 20]
        results = []
        for line in lines[:4]:
            results.append({
                "statement": line,
                "statement_type": "fact",
                "layer_level": "species",
            })
        return results

    def extract_from_text(
        self,
        source_text: str,
        source_uri: str,
        source_title: str,
        canonical_path: str,
    ) -> List[ContextStatement]:
        """Extract atomic context statements from source text using dynamic prompt & Ollama."""
        system_prompt = self.build_system_prompt()
        user_prompt = (
            f"Source Title: {source_title}\n"
            f"Canonical Path: {canonical_path}\n"
            f"Content:\n{source_text[:3500]}\n\n"
            "Extract 2 to 6 atomic context statements as a JSON list:\n"
            '[{"statement": "...", "statement_type": "...", "layer_level": "..."}]'
        )

        extracted_raw: List[Dict[str, Any]] = []
        try:
            ensure_model_available(self.client, self.model_name)
            resp = self.client.chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": self.temperature},
            )
            msg_content = ""
            if isinstance(resp, dict):
                msg_content = resp.get("message", {}).get("content", "")
            elif hasattr(resp, "message") and hasattr(resp.message, "content"):
                msg_content = resp.message.content

            if msg_content:
                # Strip markdown code blocks if wrapped in ```json ... ```
                cleaned_content = msg_content.strip()
                if cleaned_content.startswith("```"):
                    lines = cleaned_content.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    cleaned_content = "\n".join(lines).strip()

                parsed = json.loads(cleaned_content)
                if isinstance(parsed, list):
                    extracted_raw = parsed
                elif isinstance(parsed, dict) and "statements" in parsed:
                    extracted_raw = parsed["statements"]
        except Exception as e:
            print(f"Ollama chat extraction failed, using heuristic fallback: {e}")
            extracted_raw = self._heuristic_fallback_extraction(source_text, source_title)

        if not extracted_raw:
            extracted_raw = self._heuristic_fallback_extraction(source_text, source_title)

        statements: List[ContextStatement] = []
        for item in extracted_raw:
            stmt_text = str(item.get("statement", "")).strip()
            if not stmt_text or len(stmt_text) < 5:
                continue

            raw_type = str(item.get("statement_type", "fact")).lower().strip()
            try:
                st_type = StatementType(raw_type)
            except ValueError:
                st_type = StatementType.FACT

            raw_layer = str(item.get("layer_level", "species")).lower().strip()
            try:
                tx_layer = TaxonomicLayer(raw_layer)
            except ValueError:
                tx_layer = TaxonomicLayer.SPECIES

            embedding = self._embed_text(stmt_text)

            stmt = ContextStatement(
                statement=stmt_text,
                statement_type=st_type,
                canonical_path=canonical_path,
                layer_level=tx_layer,
                source_uri=source_uri,
                source_title=source_title,
                confidence=0.9,
                embedding=embedding,
                score_rank=3.0,
                eval_status=EvalStatus.UNREVIEWED,
            )
            self.store.upsert(stmt)
            statements.append(stmt)

        return statements

    def extract_from_page(
        self,
        url: str,
        title: Optional[str] = None,
        md_content: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[ContextStatement]:
        """Convenience method to classify taxonomy and extract atomic statements for a page."""
        tax_path = TaxonomyClassifier.classify_article(
            url=url,
            title=title,
            tags=tags,
        )
        try:
            TaxonomyEngine().register_entity(
                taxonomy=tax_path,
                physical_location=url,
                attributes={"title": title or url, "tags": tags or [], "source_type": "article"},
            )
        except Exception as e:
            print(f"Taxonomy entity registration warning for {url}: {e}")

        canonical_path = tax_path.to_path_string("/")
        content_text = md_content or title or url
        return self.extract_from_text(
            source_text=content_text,
            source_uri=url,
            source_title=title or url,
            canonical_path=canonical_path,
        )

    def export_preference_dataset(self, output_path: Path | str) -> int:
        """Export a pairwise ranking dataset from user-evaluated statements.

        Pairs high-rated statements (chosen) with low-rated/rejected statements (rejected).
        """
        positives, negatives = self.store.get_exemplars(positive_limit=50, negative_limit=50)
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with p.open("w", encoding="utf-8") as f:
            for pos in positives:
                for neg in negatives:
                    pos_order = pos.canonical_path.split("/")[3] if len(pos.canonical_path.split("/")) > 3 else ""
                    neg_order = neg.canonical_path.split("/")[3] if len(neg.canonical_path.split("/")) > 3 else ""
                    if pos_order and neg_order and pos_order == neg_order:
                        record = {
                            "prompt": f"Extract true personal context for: {pos.source_title}",
                            "chosen": f"[{pos.statement_type.value.upper()}] {pos.statement}",
                            "rejected": f"[{neg.statement_type.value.upper()}] {neg.statement}",
                            "chosen_score": pos.score_rank,
                            "rejected_score": neg.score_rank,
                        }
                        f.write(json.dumps(record) + "\n")
                        count += 1
        return count
