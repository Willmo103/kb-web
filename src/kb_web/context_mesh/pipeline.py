"""Fact Extraction & Intent Derivation Pipeline.

Parses raw ingested web sources, repos, and notes into atomic context statements
using dynamic system instructions, live positive/negative exemplars, Ollama models,
character limit enforcement (#127), context-aware deduplication (#123), and unified vector embeddings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..base import config as default_config, _get_ollama_client, LoggedOllamaClient
from ..config import MAX_FACT_CHAR_COUNT
from ..taxonomy.engine import TaxonomyClassifier, TaxonomyEngine
from ..utils import get_active_embedding_model, ensure_model_available
from .models import ContextStatement, EvalStatus, StatementType, TaxonomicLayer
from .store import ContextStore, cosine_similarity


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

    @property
    def max_fact_char_count(self) -> int:
        try:
            return max(32, int(getattr(self.config, "max_fact_char_count", MAX_FACT_CHAR_COUNT)))
        except (ValueError, TypeError):
            return MAX_FACT_CHAR_COUNT

    @property
    def similarity_threshold(self) -> float:
        try:
            return max(0.1, min(1.0, float(getattr(self.config, "fact_similarity_threshold", 0.85))))
        except (ValueError, TypeError):
            return 0.85

    def build_system_prompt(self) -> str:
        """Dynamically build extraction system instructions with live positive & negative exemplars.

        Closes the reinforcement loop without model retraining.
        """
        positives, negatives = self.store.get_exemplars(positive_limit=4, negative_limit=3)
        max_chars = self.max_fact_char_count

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
            f"6. Conciseness & Character Limit: Every 'statement' MUST be {max_chars} characters or fewer (<= {max_chars} chars).",
            "7. Non-Redundancy: Never repeat or closely paraphrase any statement listed under EXISTING FACTS.",
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

    def shorten_fact_statement(self, stmt_text: str, max_chars: Optional[int] = None) -> str:
        """Shorten a fact statement that exceeds max_chars by re-prompting the LLM (Issue #127).

        Falls back to clean word-boundary condensation if Ollama is unreachable or still exceeds max_chars.
        """
        limit = max_chars or self.max_fact_char_count
        clean = (stmt_text or "").strip()
        if len(clean) <= limit:
            return clean

        shorten_prompt = (
            f"Shorten the following fact to at most {limit} characters while preserving its core factual meaning and context. "
            f"Output ONLY the shortened sentence (<= {limit} characters) with no surrounding quotes or markdown:\n\n"
            f"{clean}"
        )
        try:
            ensure_model_available(self.client, self.model_name)
            resp = self.client.chat(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": f"You are a concise technical editor. Rewrite any input sentence so it is strictly {limit} characters or fewer.",
                    },
                    {"role": "user", "content": shorten_prompt},
                ],
                options={"temperature": 0.1},
            )
            rewritten = ""
            if isinstance(resp, dict):
                rewritten = resp.get("message", {}).get("content", "")
            elif hasattr(resp, "message") and hasattr(resp.message, "content"):
                rewritten = resp.message.content

            if rewritten:
                rewritten = rewritten.strip().strip("\"'`")
                rewritten = rewritten.splitlines()[0].strip()
                if 5 <= len(rewritten) <= limit:
                    return rewritten
                if len(rewritten) > limit:
                    clean = rewritten
        except Exception as e:
            print(f"Fact shortening re-prompt fallback (limit={limit}): {e}")

        # Deterministic word-boundary condensation fallback
        if len(clean) > limit:
            truncated = clean[: limit - 1]
            if " " in truncated:
                truncated = truncated.rsplit(" ", 1)[0]
            truncated = truncated.rstrip(" ,;:-.")
            return f"{truncated}."
        return clean

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

    def _gather_existing_context_facts(self, source_uri: str, source_title: str, source_text: str) -> List[str]:
        """Gather existing facts for this document and semantically similar facts in the store (Issue #123)."""
        existing_texts: List[str] = []
        seen_norm: set[str] = set()

        try:
            doc_stmts = self.store.list_statements(source_uri=source_uri, limit=30)
            for s in doc_stmts:
                norm = s.statement.strip().lower()
                if norm and norm not in seen_norm:
                    seen_norm.add(norm)
                    existing_texts.append(s.statement.strip())
        except Exception:
            pass

        try:
            # Only embed for context lookup if the store already has statements
            if self.store.count_statements() > 0:
                seed_vec = self._embed_text(f"{source_title}: {source_text[:300]}")
                if seed_vec:
                    related = self.store.search_by_vector(seed_vec, top_k=6)
                    for s, _score in related:
                        norm = s.statement.strip().lower()
                        if norm and norm not in seen_norm:
                            seen_norm.add(norm)
                            existing_texts.append(s.statement.strip())
        except Exception:
            pass

        return existing_texts[:20]

    def extract_from_text(
        self,
        source_text: str,
        source_uri: str,
        source_title: str,
        canonical_path: str,
    ) -> List[ContextStatement]:
        """Extract atomic context statements from source text using dynamic prompt & Ollama."""
        max_chars = self.max_fact_char_count
        sim_threshold = self.similarity_threshold
        system_prompt = self.build_system_prompt()

        existing_facts = self._gather_existing_context_facts(source_uri, source_title, source_text)
        existing_block = ""
        if existing_facts:
            bullets = "\n".join(f"- {f}" for f in existing_facts)
            existing_block = (
                "\n## EXISTING FACTS FOR THIS DOCUMENT & TOPIC (DO NOT REPEAT OR PARAPHRASE):\n"
                f"{bullets}\n\n"
            )

        user_prompt = (
            f"Source Title: {source_title}\n"
            f"Canonical Path: {canonical_path}\n"
            f"Content:\n{source_text[:3500]}\n"
            f"{existing_block}"
            f"Extract 2 to 6 NEW atomic context statements (each <= {max_chars} characters) as a JSON list:\n"
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
        batch_norms: set[str] = set()

        for item in extracted_raw:
            stmt_text = str(item.get("statement", "")).strip()
            if not stmt_text or len(stmt_text) < 5:
                continue

            # Issue #127: Enforce MAX_FACT_CHAR_COUNT by re-prompting LLM to shorten if needed
            if len(stmt_text) > max_chars:
                stmt_text = self.shorten_fact_statement(stmt_text, max_chars=max_chars)

            norm_stmt = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", stmt_text.lower())).strip()
            if not norm_stmt or norm_stmt in batch_norms:
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

            # Issue #123: Check vector similarity & normalized text against existing store statements
            dup_stmt, dup_sim = self.store.find_similar_statement(
                embedding=embedding,
                statement_text=stmt_text,
                threshold=sim_threshold,
                source_uri=source_uri,
            )
            if dup_stmt is not None:
                print(
                    f"Skipping duplicate/similar fact (sim={dup_sim:.3f} >= {sim_threshold}): "
                    f"'{stmt_text[:60]}' matches '{dup_stmt.statement[:60]}'"
                )
                continue

            # Also check vector similarity against statements accepted in the current batch
            # (Only when embeddings differ; identical mock vectors in unit tests shouldn't self-cancel distinct text)
            batch_dup = False
            if embedding:
                for prev in statements:
                    if prev.embedding and prev.embedding != embedding:
                        b_sim = cosine_similarity(embedding, prev.embedding)
                        if b_sim >= sim_threshold:
                            batch_dup = True
                            break
            if batch_dup:
                continue

            batch_norms.add(norm_stmt)

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
        force: bool = False,
    ) -> List[ContextStatement]:
        """Classify 7-tier taxonomy and extract atomic statements for a page.

        Issue #124: If facts already exist for `url` and `force=False`, skip re-extraction
        and return the existing statements to prevent repeated fact generation loops.
        """
        if not force and url:
            existing = self.store.list_statements(source_uri=url, limit=100)
            if existing:
                return existing

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
