# Implementation Plan — Taxonomic Facts CRUDS, Vector Deduplication, 7-Tier Topic Hierarchy, Character Limits & Pipeline Topic Assignment (Issues #122 – #128)

## Overview
This sprint resolves GitHub Issues **#122, #123, #124, #125, #126, #127, and #128** across the context mesh, 7-tier taxonomy engine, ingestion pipeline, autonomous worker, and UI templates.

---

## Detailed Design by Issue

### 1. Issue #122: Taxonomical Fact Management Page (`/facts` + CRUDS & Search API)
- **Backend REST API (`src/kb_web/routers/taxonomy.py`, `src/kb_web/context_mesh/store.py`)**:
  - `GET /facts`: Dedicated Fact Management UI page (`templates/facts_management.j2.html`) linked in the main navigation bar (`base.j2.html`) and `/taxonomy` header.
  - **Create**: `POST /api/context-mesh/statements` — creates a new `ContextStatement`, automatically enforces `MAX_FACT_CHAR_COUNT`, embeds the statement vector, and persists it via `ContextStore.upsert()`.
  - **Read / Search (Lexical + Semantic Vector Search)**:
    - `GET /api/context-mesh/statements` — supports filtering by `url`, `statement_type`, `layer_level`, `eval_status`, `prefix`, `kingdom` (Topic), `phylum`/`class_name` (Sub-Topic), keyword `query`, and pagination (`limit`, `offset`).
    - `GET /api/context-mesh/search` — semantic vector similarity search (`search_by_vector`) + hybrid lexical search across all documental facts.
  - **Update**: `PUT /api/context-mesh/statements/{statement_id}` — edits statement text, `statement_type`, `layer_level`, `canonical_path`, `source_uri`, `source_title`, `score_rank`, `eval_status`, and re-computes the vector embedding when statement text changes.
  - **Delete**: `DELETE /api/context-mesh/statements/{statement_id}` and bulk `POST /api/context-mesh/statements/bulk-delete` — permanently removes one or more facts from `context_statements`.
- **Frontend UI (`src/kb_web/templates/facts_management.j2.html`)**:
  - Search bar with mode toggle (**Keyword Search** vs **Semantic Vector Search**), filters for Topic (`Kingdom`), Statement Type, Layer Level, and Review Status.
  - Create Fact modal & inline Edit Fact modal (modifying text with live character counter `<= MAX_FACT_CHAR_COUNT`, statement type, layer, and 7-tier canonical path).
  - Bulk selection checkboxes with Bulk Delete and one-click Approve / Flag / Reject (Delete) buttons.

---

### 2. Issue #123: Fact Extraction Context Awareness & Vector Similarity Deduplication
- **Prompt Context Awareness (`src/kb_web/context_mesh/pipeline.py`)**:
  - Before calling the LLM in `extract_from_text()`, query `self.store.list_statements(source_uri=source_uri)` to gather all existing facts for the target document.
  - Also embed the document title/summary snippet and run `self.store.search_by_vector(..., top_k=8)` across all documents to surface semantically related facts already in the knowledge base.
  - Inject an explicit `## EXISTING FACTS FOR THIS DOCUMENT & TOPIC (DO NOT REPEAT OR PARAPHRASE)` section into the extraction prompt.
- **Pre-Save Vector Similarity & Normalized Text Gate (`src/kb_web/context_mesh/pipeline.py`, `src/kb_web/context_mesh/store.py`)**:
  - Add `fact_similarity_threshold` (default `0.85`, configurable in `/admin` under Rule 7) to `config.py`.
  - For each candidate fact generated:
    1. Check normalized case-insensitive text against existing statements for the document and batch.
    2. Compute the candidate's embedding vector via `_embed_text()`.
    3. Compare cosine similarity against both existing statements in `ContextStore` (`find_similar_statement(embedding, statement_text, threshold)`) and statements already accepted in the current extraction batch.
    4. If cosine similarity `>= config.fact_similarity_threshold` (or normalized text matches), skip saving the duplicate/near-duplicate fact.

---

### 3. Issue #124: Decouple Pipeline Stages & Prevent Fact Generation Loops on Failed Wikis
- **Root Cause & Fix (`src/kb_web/pipeline.py`, `src/kb_web/worker.py`, `src/kb_web/context_mesh/pipeline.py`)**:
  - In `FactExtractionPipeline.extract_from_page()`, check if facts already exist for `url` (`store.count_statements(source_uri=url) > 0`). If facts already exist and `force=False`, skip re-extraction and return the existing statements.
  - In `pipeline.py`, decouple Stage 2 (Wiki Synthesis), Stage 3 (Tag Extraction), Stage 3b (Topic & Sub-Topic Assignment), Stage 4 (Vector Indexing), and Stage 4b (Fact Extraction) so each stage checks its own completion state independently:
    - Stage 4b only runs if the article does not already have extracted facts in `context_statements` (and logs execution to `WorkerJobExecution` for `fact_extraction` immediately so the background worker never re-runs it).
    - If Wiki Synthesis (Stage 2) fails, `wiki_curation` in the worker only retries wiki generation (`extract_wiki_content` + `update_article_embedding`) and never triggers `fact_extraction`.
    - In `worker.py` (`_run_fact_extraction`), require that candidate pages either have a valid non-failed wiki (`FetchedPage.description.isnot(None)` and `FetchedPage.description != ""`) OR have been explicitly queued, and strictly exclude any `url` already present in `ContextStatementORM.source_uri` or `WorkerJobExecution(job_id="fact_extraction")`.

---

### 4. Issue #125: Automatically Delete Rejected Facts from the Database
- **Store & Endpoint Behavior (`src/kb_web/context_mesh/store.py`, `src/kb_web/routers/taxonomy.py`)**:
  - Add `ContextStore.delete_statement(statement_id: str) -> bool`.
  - Update `ContextStore.update_evaluation()`: when `derived_status == EvalStatus.REJECTED` (or `status == EvalStatus.REJECTED`), immediately delete the row from `context_statements` (`session.delete(orm)`) instead of keeping it attached with `eval_status="rejected"`.
  - Return `"deleted": True` in the API response (`POST /api/context-mesh/statements/{statement_id}/evaluate`) when `eval_status == "rejected"`.
  - Update the UI (`view_page.j2.html`, `taxonomy.j2.html`, and `facts_management.j2.html`) so clicking `👎 Reject` removes the fact card from the DOM and decrements the counter badge.

---

### 5. Issue #126: New 7-Tier Taxonomical Pattern for Facts & Entities
- **Revised 7-Tier Assignment Pattern (`src/kb_web/taxonomy/engine.py`, `src/kb_web/taxonomy/models.py`, `src/kb_web/context_mesh/pipeline.py`)**:
  - **Tier 1 (`Kingdom`) — General Topic**: Represents the high-level general topic of the information: e.g., `News`, `Software Documentation`, `Blogpost/Article`, `Reference`, `Resource`, `Hobby/Leisure`, `Video/Media`, `Research` (governed by Allowed Topics from #128, never hardcoded to `"knowledge"`).
  - **Tier 2 (`Phylum`) & Tier 3 (`Class`) — Sub-Topic Hierarchy (2 Levels)**: Relate to the 2-level sub-topic breakdown (e.g., `Activism > Removal-Efforts`, `Fishing > Ultralight`, `Official-Documentation > Supabase`).
  - **Tier 4 (`Order`) & Tier 5 (`Family`) — Content / Source Specifics**: Fill in information specific to the article's source/publisher/domain (`Order`, e.g., `github_com`, `supabase_com`, creator channel) and content theme/tag cluster (`Family`, e.g., `authentication`, `postgres_migrations`).
  - **Tier 6 (`Genus`) & Tier 7 (`Species`) — Unique to the Article**:
    - `Genus`: Unique article-level structural identifier / short hash-qualified slug (e.g., `supabase_v1_1_1_guide_a1b2`).
    - `Species`: Unique article/fact identity slug (e.g., `row_level_security_policies` or unique article slug).
  - Update `TaxonomyClassifier` (`classify_article`, `classify_youtube_video`, `classify_git_repo`, `classify_note`) and `FactExtractionPipeline` to use this 7-tier structure, pulling assigned `topic` (`Kingdom`) and `sub_topic` (`Phylum/Class`) when available and inferring clean topic/sub-topic coordinates when classifying.

---

### 6. Issue #127: `MAX_FACT_CHAR_COUNT` Configuration & LLM Re-Prompting to Shorten Facts
- **Configuration Exposure (`src/kb_web/config.py`, `src/kb_web/routers/admin.py`, `src/kb_web/templates/admin.j2.html`)**:
  - Add `max_fact_char_count` (`KB_MAX_FACT_CHAR_COUNT`, default `144`) to `Config`, persisted in `settings_external` / `kb-web.json`, and exposed in `/admin` under "Engine Thresholds & Operational Limits".
- **Extraction Enforcement & Re-Prompting (`src/kb_web/context_mesh/pipeline.py`)**:
  - Instruct the LLM in `build_system_prompt()` and `extract_from_text()` that every extracted `"statement"` MUST be `<= {max_fact_char_count}` characters.
  - Add `shorten_fact_statement(stmt_text: str, max_chars: int) -> str`:
    - Whenever an extracted statement has `len(stmt_text) > max_chars`, re-prompt the Ollama model (`"Shorten the following fact to at most {max_chars} characters while preserving its core meaning and context. Output ONLY the shortened fact sentence."`).
    - If the model is offline or the re-prompted text still exceeds `max_chars`, apply a clean clause/word-boundary condensation so no saved fact ever exceeds `max_fact_char_count` characters.

---

### 7. Issue #128: AI Topic & Sub-Topic Assignment Pipeline Steps, Governance & Re-Queueing
- **Database Schema & Config (`src/kb_web/models_orm.py`, `src/kb_web/config.py`)**:
  - Add columns to `FetchedPage`:
    - `topic = Column(String, nullable=True, index=True)` (Top-level General Topic / Kingdom)
    - `sub_topic = Column(String, nullable=True, index=True)` (2-level Sub-Topic path, e.g. `Fishing/Ultralight`)
    - `topic_status = Column(String, default="unassigned", index=True)` (`unassigned`, `pending`, `approved`, `denied`)
  - Add `TopicGovernanceORM` table (`taxonomy_topics`) tracking governed topics & sub-topics:
    - `id`, `name` (e.g., `News` or `Fishing/Ultralight`), `level` (`topic` or `sub_topic`), `parent_topic`, `status` (`allowed`, `pending`, `denied`), `created_at`, `updated_at`.
  - Seed default allowed top-level topics (`News`, `Software Documentation`, `Blogpost/Article`, `Reference`, `Resource`, `Hobby/Leisure`) on initialization and expose `allowed_topics` in `Config` & `/admin`.
- **Ingestion Pipeline & Autonomous Worker Steps (`src/kb_web/pipeline.py`, `src/kb_web/worker.py`, `src/kb_web/taxonomy/engine.py`)**:
  - Implement `assign_topic_and_subtopic(url, title, md_content, tags, config, client)`:
    - AI step assigns a Top-Level Topic (checked against `allowed_topics` and excluding any `denied` blocklisted topics) and a 2-level Sub-Topic (`Phylum/Class`), updating `FetchedPage.topic`, `FetchedPage.sub_topic`, `FetchedPage.topic_status`, and registering/updating the 7-tier `TaxonomyEntityORM` and associated `ContextStatementORM` paths.
  - Add **Stage 3b (Topic & Sub-Topic Assignment)** in `run_ingest_pipeline_background` (`src/kb_web/pipeline.py`).
  - Register **`topic_assignment` ServerJob** (`Topic & Sub-Topic Assignment Agent`) in `AutonomousWorker` (`src/kb_web/worker.py`) to process any articles or videos where `topic` is NULL/empty or `topic_status == 'unassigned'`.
- **User Approval / Denial & Re-Queueing (`src/kb_web/routers/taxonomy.py`, `templates/taxonomy.j2.html`, `templates/admin.j2.html`)**:
  - Endpoints:
    - `GET /api/taxonomy/topics` — lists allowed, pending, and denied topics/sub-topics along with article/video counts.
    - `POST /api/taxonomy/topics/approve` — approves a topic or sub-topic (marking matching articles `topic_status = "approved"` and adding to allowed topics).
    - `POST /api/taxonomy/topics/deny` — denies/deletes a topic or sub-topic:
      1. Records the topic/sub-topic as `denied` in `TopicGovernanceORM` (blocklisted so AI won't re-propose it).
      2. Finds all `FetchedPage` (articles & videos) assigned to that topic/sub-topic, clears their `topic` / `sub_topic`, and sets `topic_status = "unassigned"`.
      3. Deletes `WorkerJobExecution` records for `job_id="topic_assignment"` on those URLs and removes them from `autonomous_worker._recent_targets["topic_assignment"]` so they are immediately **re-added to the queue for reassignment**.
    - `POST /api/taxonomy/topics/assign-now` — triggers immediate AI topic & sub-topic assignment for a specific URL or batch of unassigned items.
- **UI Exposure (`templates/taxonomy.j2.html`, `templates/view_page.j2.html`, `templates/admin.j2.html`)**:
  - Add Topic & Sub-Topic Governance tab/panel in `/taxonomy` to add allowed topics, approve/deny topics & sub-topics, and view queued items for reassignment.
  - Show Topic & Sub-Topic badges with quick Approve / Deny & Re-queue buttons on `/view/page`.

---

## Verification Plan
1. Write comprehensive unit and integration tests in `tests/test_issues_122_to_128.py` covering:
   - Fact CRUDS endpoints & UI rendering (`/facts`, create, update, delete, bulk delete, lexical & vector search) (#122).
   - Fact extraction awareness of existing document facts & vector similarity deduplication preventing near-duplicate facts (#123).
   - Decoupled pipeline & worker execution ensuring failed wikis never cause infinite fact generation loops (#124).
   - Rejecting a fact automatically deletes it from the database (#125).
   - 7-tier taxonomy coordinate assignment (`Kingdom` = General Topic, `Phylum/Class` = 2-level Sub-Topic, `Order/Family` = Source/Content, `Genus/Species` = Unique to article) (#126).
   - `MAX_FACT_CHAR_COUNT` (144 chars) enforcement and LLM re-prompt shortening (#127).
   - AI Topic & Sub-Topic assignment pipeline step, allowed topics check, topic approval, and topic denial/deletion blocklisting + re-queueing articles/videos for reassignment (#128).
2. Run `verify_ui_templates.py` and `generate_uat_report.py`.
3. Run full pre-commit verification (`uv run python build.py`).
4. Merge into `development` and `production` and push.

