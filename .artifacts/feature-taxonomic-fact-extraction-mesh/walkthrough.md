# Walkthrough: 7-Tier Biological Taxonomy, Context Fact Extraction Mesh, & Subconscious Retriever

## 1. Overview & Vision
This implementation on the experimental branch `feature/taxonomic-fact-extraction-mesh` steers `kb-web` from a passive web curation portal into a **subconscious, brain-like memory substrate**:
- **Phase 1: 7-Tier Biological Taxonomy Schema & Engine**: Replaces loose folder categories with Orcastrator's biological taxonomy (`Kingdom -> Phylum -> Class -> Order -> Family -> Genus -> Species`), path serialization, classifier heuristics, and database persistence.
- **Phase 2: Context Mesh Models, ORM Entities, and Fact Extraction Pipeline**: Defines atomic `ContextStatement` structures, database storage with `SafeVector` embedding vectors, score ranking with back-propagation, and a dynamic few-shot feedback extraction pipeline.
- **Phase 3: Hierarchical Bubble-Down Retriever & Prompt Auto-Injector**: Implements `BubbleDownRetriever` with `d1` decision gating and multi-layer vector search (Principles -> Conventions -> Concrete Instances), assembling `<subconscious_context>` blocks with clickable source provenance.
- **Phase 4: Ingestion Pipeline & Background Worker Automation**: Ingests atomic context statements in asynchronous Stage 4b of web imports and registers `fact_extraction` ServerJob in `AutonomousWorker` for continuous background extraction of uncurated pages.

---

## 2. Key Modules & Implementations

### A. Database Schema (`src/kb_web/models_orm.py`)
- `ContextStatementORM` (`__tablename__ = "context_statements"`):
  - Primary key `id` (`stmt_...`).
  - `statement` (Text) and `statement_type` (`intent_mapping`, `negative_invariant`, `affordance`, `habit`, `preference`, `fact`).
  - Full canonical path coordinates: `canonical_path`, `layer_level`, `kingdom`, `phylum`, `class_name`, `order_name`, `family`, `genus`, `species`.
  - Provenance tracking: `source_uri`, `source_title`, `confidence`.
  - Vector column: `statement_vector = Column(SafeVector())` (PostgreSQL `pgvector` with SQLite fallback).
  - Feedback & evaluation ranking: `score_rank` (0.0 to 5.0), `eval_status` (`unreviewed`, `approved`, `flagged`, `rejected`), `eval_feedback`, `eval_count`.
- `TaxonomyEntityORM` (`__tablename__ = "taxonomy_entities"`):
  - Canonical identifier, 7 biological tiers, physical location, attributes JSON, and timestamps.
- Auto-DDL & indexes in `ensure_views_and_indexes()`.

### B. 7-Tier Biological Taxonomy Package (`src/kb_web/taxonomy/`)
- [`src/kb_web/taxonomy/models.py`](file:///c:/src/kb-web/src/kb_web/taxonomy/models.py):
  - `TaxonomyLevel`: Enum covering `KINGDOM`, `PHYLUM`, `CLASS`, `ORDER`, `FAMILY`, `GENUS`, `SPECIES`.
  - Node metadata definitions: `KingdomNodeInfo` through `SpeciesNodeInfo`.
  - `TaxonomyPath`: Pydantic coordinate model with `to_path_string()`, `from_string()` (with generic fallback padding), and `to_frontmatter_dict()`.
  - `TaxonomyEntityRecord`: Detached Pydantic model for database entities.
- [`src/kb_web/taxonomy/engine.py`](file:///c:/src/kb-web/src/kb_web/taxonomy/engine.py):
  - `TaxonomyClassifier`: Heuristic classification for ingested web pages, Git repositories, YouTube videos, and research notes.
  - `TaxonomyEngine`: Persistence in `taxonomy_entities`, coordinate querying (`list_entities`), and YAML frontmatter formatting.

### C. Context Mesh & Fact Extraction Pipeline (`src/kb_web/context_mesh/`)
- [`src/kb_web/context_mesh/models.py`](file:///c:/src/kb-web/src/kb_web/context_mesh/models.py):
  - `StatementType`: Declarative intent taxonomy (`INTENT_MAPPING`, `NEGATIVE_INVARIANT`, `AFFORDANCE`, `HABIT`, `FACT`, `PREFERENCE`).
  - `TaxonomicLayer`: Layer depth (`KINGDOM` through `SPECIES`).
  - `EvalStatus`: Review stages (`UNREVIEWED`, `APPROVED`, `FLAGGED`, `REJECTED`).
  - `ContextStatement`: Atomic model with `to_citation_markdown()`.
- [`src/kb_web/context_mesh/store.py`](file:///c:/src/kb-web/src/kb_web/context_mesh/store.py):
  - `ContextStore`: Multi-engine database store using SQLAlchemy `db_session()`.
  - Evaluation ranking & back-propagation: `update_evaluation()` with score clamp and auto-status promotion.
  - Exemplar fetching: `get_exemplars()` retrieving high-scoring gold standards and low-scoring anti-patterns.
  - Vector similarity search: `search_by_vector()` with composite ranking `0.65 * sim + 0.35 * (score_rank / 5.0)` and rejected pattern suppression.
- [`src/kb_web/context_mesh/pipeline.py`](file:///c:/src/kb-web/src/kb_web/context_mesh/pipeline.py):
  - `FactExtractionPipeline`: Uses Ollama LLM (`config.ollama_model`) and unified embedding model (`get_active_embedding_model()`).
  - Dynamic Prompt: Injects positive exemplars and negative anti-patterns directly into extraction system instructions.
  - Heuristic fallback: Robust local sentence parsing if Ollama is unreachable.
  - DPO dataset exporter: `export_preference_dataset()`.
- [`src/kb_web/context_mesh/retriever.py`](file:///c:/src/kb-web/src/kb_web/context_mesh/retriever.py):
  - `BubbleDownRetriever`: Uses native `d1` decision model (with regex word-boundary fallback) to route query into target Kingdom & Phylum.
  - Layer-by-layer vector search across Top (Kingdom/Phylum), Mid (Order/Family), and Ground (Species) tiers.
  - Generates rich Markdown citation blocks with score badges.
- [`src/kb_web/context_mesh/injector.py`](file:///c:/src/kb-web/src/kb_web/context_mesh/injector.py):
  - `SubconsciousContextInjector`: Wraps context in `<subconscious_context>` tags and injects it directly into agent prompts in the background.

### D. Pipeline & Worker Integration
- [`src/kb_web/pipeline.py`](file:///c:/src/kb-web/src/kb_web/pipeline.py):
  - Added Stage 4b: Context Mesh Atomic Fact Extraction during web page imports.
- [`src/kb_web/worker.py`](file:///c:/src/kb-web/src/kb_web/worker.py):
  - Registered `fact_extraction` ServerJob running every 15 minutes to discover and process unextracted library pages.

---

## 3. Verification & Testing
Added comprehensive unit tests in [`tests/test_taxonomic_fact_extraction.py`](file:///c:/src/kb-web/tests/test_taxonomic_fact_extraction.py):
1. `test_taxonomy_path_serialization_and_parsing`: Validated round-trip parsing, delimiter handling, and generic tier padding.
2. `test_taxonomy_classifier`: Validated automatic coordinate classification for articles, repos, videos, and notes.
3. `test_taxonomy_engine_persistence`: Validated database upserts, queries, and detached record loading.
4. `test_cosine_similarity`: Validated cosine similarity math across orthogonal, parallel, and angled vectors.
5. `test_context_store_crud_and_evaluations`: Validated statement CRUD, markdown citations, evaluation promotions, and composite vector search.
6. `test_fact_extraction_pipeline_dynamic_prompt`: Validated dynamic exemplar injection into system instructions.
7. `test_fact_extraction_pipeline_with_mock_ollama`: Validated extraction, JSON parsing, embedding generation, and database commit.
8. `test_fact_extraction_heuristic_fallback`: Validated offline heuristic fallback.
9. `test_bubble_down_retriever_decision_routing`: Validated `d1` decision routing of Kingdom & Phylum.
10. `test_bubble_down_retriever_heuristic_routing`: Validated whole-word boundary heuristic fallback routing across domains.
11. `test_bubble_down_retriever_hierarchical_traversal`: Validated multi-layer traversal and context block formatting.
12. `test_subconscious_context_injector`: Validated embedding of `<subconscious_context>` into agent prompts.
13. `test_worker_fact_extraction_job`: Validated registration and execution of `fact_extraction` ServerJob.

Results: **13 passed in 10.85s**.

---

## 4. Branch Isolation Status
- **Current Git Branch**: `feature/taxonomic-fact-extraction-mesh`
- **Isolation Constraint**: In accordance with user instruction, this experimental branch has **NOT** been merged into `development` or `production`.
