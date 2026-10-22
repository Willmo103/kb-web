# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.11] - 2026-10-22
### Added
- **Extracted Facts & Context Mesh UI Display (`routers/pages.py`, `templates/view_page.j2.html`)**:
  - Exposed extracted atomic facts and context statements (`ContextStatementORM`) on the Article Profile view.
  - Added dedicated "Extracted Facts & Intent Mesh" card featuring color-coded statement type badges (`Fact` [blue], `Intent` [purple], `Invariant` [rose], `Affordance` [emerald], `Habit` [amber], `Preference` [cyan]), taxonomic layer level badges (`SPECIES`, `GENUS`, etc.), canonical taxonomy coordinates path, review status indicators (`approved`, `flagged`, `rejected`, `unreviewed`), and confidence score ranks.
  - Added interactive one-click evaluation controls (`👍 Approve`, `⚠️ Flag`, `👎 Reject`) with dynamic asynchronous feedback updates via `POST /api/context-mesh/statements/{id}/evaluate`.
  - Added on-demand `⚡ Extract Facts Now` action button calling `POST /api/context-mesh/extract-now`.
- **7-Tier Biological Taxonomy Auto-Population & Library Sync (`taxonomy/engine.py`, `context_mesh/pipeline.py`, `pipeline.py`, `routers/taxonomy.py`)**:
  - Automated taxonomy coordinate registration during page ingestion and fact extraction via `TaxonomyEngine().register_entity(...)`.
  - Implemented `TaxonomyEngine.sync_entities_from_library(limit)` and endpoint `POST /api/taxonomy/sync-entities` to scan existing articles and notes and infer 7-tier coordinates.
  - Implemented `TaxonomyEngine.get_7tier_tree()` and endpoint `GET /api/taxonomy/7tier/tree` compiling a hierarchical 7-tier biological tree of Kingdoms, Phyla, Classes, Orders, and Families with real-time entity and statement counts.
- **Upgraded Interactive Taxonomy & Living Facts Mesh Explorer (`routers/taxonomy.py`, `templates/taxonomy.j2.html`)**:
  - Modernized `/taxonomy` into a dual-view portal featuring:
    * **Tab 1: 7-Tier Biological Ontology & Living Facts Explorer**: Interactive hierarchical tree navigator from Kingdom down to Family, breadcrumb coordinate display, live atomic context facts mesh explorer with statement type filters and search, and mapped physical entity cards with direct article profile links.
    * **Tab 2: Autonomous Category Clusters (Legacy)**: Preserved category tree state machine, clustering crawler, and living category wiki doc reader for full backward compatibility.
    * Added prominent "Sync Taxonomy from Library" button to populate the 7-tier hierarchy with one click.
- **REST & Query API Additions (`routers/taxonomy.py`, `context_mesh/store.py`)**:
  - Added `GET /api/context-mesh/statements` supporting filtering by `url`, `statement_type`, `layer_level`, `eval_status`, `prefix`, and keyword search `query`.
  - Added `POST /api/context-mesh/statements/{id}/evaluate` to update evaluation status and score ranking.
  - Added `POST /api/context-mesh/extract-now` for on-demand fact extraction.
  - Added unit and integration test suite `tests/test_taxonomy_and_facts_display.py` (5 tests passed).
- **Autonomous Worker Target Execution Tracking & Loop Prevention (`src/kb_web/models_orm.py`, `src/kb_web/worker.py`, `src/kb_web/routers/worker.py`)**:
  - Implemented persistent target-level execution tracking model `WorkerJobExecution` (`id`, `job_id`, `target_id`, `status`, `items_count`, `error_message`, `executed_at`) with composite index `(job_id, target_id)`.
  - Added in-memory deduplication tracking `self._recent_targets[job_id]` in `AutonomousWorker` preventing immediate duplicate execution within the same scheduler loop or runtime session.
  - Hardened candidate selection subqueries in `_run_fact_extraction`, `_run_wiki_curation`, `_run_tag_curation`, and `_run_embedding_refresh`:
    - Excludes targets already logged with `status IN ('success', 'skipped')` in `WorkerJobExecution`.
    - Excludes targets present in the runtime `_recent_targets` memory cache.
    - Added `.nullslast()` to all `order_by` clauses (`FetchedPage.fetched_at.desc().nullslast()` and `asc().nullslast()`) preventing PostgreSQL `NULLS FIRST` sorting quirks on unpopulated timestamps.
    - Filters out `NULL` and empty values from downstream artifact subqueries.
  - Automatically logs `status="skipped"` with `items_count=0` whenever an extraction or curation pass produces zero items, permanently preventing infinite loops on un-extractable targets.
  - Added REST and Admin management endpoints: `GET /api/jobs/{job_id}/executions` to inspect target history, `POST /api/jobs/{job_id}/executions/clear` to reset execution logs, and `POST /admin/jobs/{job_id}/executions/clear` for admin portal resets.
  - Added unit test suite `tests/test_worker_job_execution_tracking.py` verifying model persistence, helper functions, sequential deduplication, zero-statement skip handling, and API endpoints (5 tests passed).
- **AI Wiki Versioning, Model Attribution & Historical Restorations (`src/kb_web/models_orm.py`, `routers/admin.py`, `routers/pages.py`, `templates/view_page.j2.html`)**:
  - Added `WikiVersion` ORM model (`url`, `title`, `wiki_content`, `model_name`, `steering_instructions`, `created_at`) with native foreign key `ON DELETE CASCADE` linked to `fetched_pages.url`.
  - Added `wiki_model` column to `FetchedPage` and pre-aggregated database view `vw_page_cards` with SQLite PRAGMA and PostgreSQL migrations.
  - Automatically archive previous AI wiki markdown into `WikiVersion` whenever a page is regenerated (`POST /admin/regenerate/wiki`) or re-fetched (`POST /admin/refetch/page`).
  - Added `POST /admin/wiki/restore` endpoint allowing instantaneous restoration of historical wiki versions with reciprocal archival of active content.
  - Display generating model badge (`🤖 Model: <model_name>`) and historical version selector pills (`v1`, `v2`, `Latest`) directly in the article wiki header.
  - Added historical version preview banner with one-click version restoration button.
  - Wired cascade deletion across all controllers (`handle_delete_page`, `delete_single_article`, `delete_note_api`, and `_cascade_delete_page_urls`) and enabled `PRAGMA foreign_keys=ON` on SQLite database connections.
- **On-the-Fly Model Selection & Custom Steering Directives (`src/kb_web/utils.py`, `routers/admin.py`, `templates/view_page.j2.html`)**:
  - Replaced immediate wiki regeneration with an interactive modal form allowing on-the-fly selection of any locally installed Ollama completion model.
  - Added optional steering instructions textarea allowing custom prompts (e.g., technical architecture focus, bulleted executive summaries, mathematical proof retention) to be dynamically appended to system curation prompts.
  - Updated `extract_wiki_content` to accept custom `model` and `steering_instructions` across both short and chunked long-document generation pipelines.
- **Pseudo-Scheme URL Resolution & Universal Navigation Dispatcher (`src/kb_web/base.py`, `routers/pages.py`, `templates/base.j2.html`, `templates/pages_list.j2.html`)**:
  - Implemented `resolve_entity_url(url)` resolving synthetic internal schemes into clean internal routes: `note://` to Monaco Notes editor (`/notes/edit?url=...`), `workspace://` to workspace IDE (`/workspaces/{id}`), external `http/https` to original targets, and unrecognized schemes to non-clickable badges.
  - Registered `resolve_entity_url` as both a Jinja filter and global helper across all templates.
  - Added universal `GET /open?url=...` redirect dispatcher routing synthetic and external schemes server-side.
  - Added global client-side link click interceptor in `base.j2.html` seamlessly rerouting internal markdown and page links to `/open?url=...` without browser handler errors.
  - Updated article profile (`view_page.j2.html`) and article index list (`pages_list.j2.html` across grid, compact, and client-side search) to resolve internal URLs safely.
  - Added test suite `tests/test_wiki_versions_and_url_routing.py` covering model creation, cascade deletion, URL resolution, dispatcher redirection, modal parameter execution, version restoration, and template rendering (7 tests passed).
- **7-Tier Biological Taxonomy & Context Fact Extraction Mesh (`src/kb_web/taxonomy/`, `src/kb_web/context_mesh/`, `src/kb_web/models_orm.py`)**:
  - Implemented 7-tier biological taxonomy architecture (`Kingdom -> Phylum -> Class -> Order -> Family -> Genus -> Species`) inspired by Orcastrator, moving beyond flat folder-like tags to strict personal knowledge classification.
  - Added `TaxonomyPath` coordinate model supporting canonical delimiter serialization (`to_path_string`), parsing (`from_string`), and Markdown YAML frontmatter generation (`to_yaml_frontmatter`).
  - Added `TaxonomyClassifier` providing heuristic coordinate inferences for ingested web articles, Git repositories, YouTube videos, and notes.
  - Added `TaxonomyEntityORM` and `TaxonomyEntityRecord` for persistent indexing of physical assets and view querying (`TaxonomyEngine.list_entities`).
  - Implemented `ContextMesh` atomic knowledge representation with `ContextStatementORM` supporting both PostgreSQL `SafeVector` and SQLite embeddings.
  - Added `ContextStatement` schema tracking declarative types (`intent_mapping`, `negative_invariant`, `affordance`, `habit`, `preference`, `fact`), taxonomic layers, clickable source citations (`to_citation_markdown`), and score ranks (0.0 to 5.0).
  - Created `ContextStore` with composite vector similarity search (`0.65 * sim + 0.35 * norm_rank`), feedback back-propagation (`update_evaluation`), and dynamic exemplar retrieval (`get_exemplars`).
  - Implemented `FactExtractionPipeline` with live positive/negative exemplar injection in system instructions, unified embedding generation (`get_active_embedding_model`), offline heuristic fallback, and pairwise DPO dataset export (`export_preference_dataset`).
  - Implemented `BubbleDownRetriever` (`src/kb_web/context_mesh/retriever.py`) providing hierarchical context traversal: routes query domain via `d1` decision model (with regex word-boundary fallback) into target Kingdom & Phylum, conducts layer-by-layer vector search (Principles -> Conventions -> Instances), and renders formatted Markdown context blocks with score badges and clickable citations.
  - Implemented `SubconsciousContextInjector` (`src/kb_web/context_mesh/injector.py`) automatically wrapping context in `<subconscious_context>` tags and injecting it directly into agent background instructions without manual search queries.
  - Integrated Stage 4b atomic fact extraction into asynchronous web ingestion pipeline (`src/kb_web/pipeline.py`).
  - Registered `fact_extraction` ServerJob in `AutonomousWorker` (`src/kb_web/worker.py`) for continuous discovery and context mesh extraction of unextracted library pages.
  - Added test suite `tests/test_taxonomic_fact_extraction.py` covering path serialization, classifier heuristics, store CRUD, evaluation transitions, composite vector search, dynamic prompts, d1 decision routing, multi-layer hierarchical traversal, prompt injection, and worker job execution (13 tests passed).
- **Persistent Evaluation Run History & Re-Run Portal (`src/kb_web/models_orm.py`, `routers/evals.py`, `templates/evals.j2.html`)**:
  - Persisted all streaming and batch evaluation executions into new `evaluation_runs` database table (`eval_type`, `title`, `status`, `config_json`, `results_json`, `metrics_json`, `created_at`, `completed_at`).
  - Added dedicated Tab 5 (**Run History**) in the Model Evaluation Studio allowing users to review completed, running, or failed evaluations with latency and token metrics, inspect full model outputs in a modal viewer, delete run records, and restore prompts/model options directly back into the active Studio form.
  - Added REST endpoints: `GET /api/evals/runs`, `GET /api/evals/runs/{id}`, and `DELETE /api/evals/runs/{id}`.
- **Dataset-Only Matrix Evaluations & Randomized Row Sampling (`src/kb_web/routers/evals.py`, `templates/evals.j2.html`)**:
  - Completely removed single article/text input mode from Matrix evaluations, enforcing evaluation discipline strictly against curated datasets.
  - Added randomized/shuffled sampling option (`randomize: bool`) with UI toggle checkbox to pull varied test batches across iterations instead of sequential rows.
  - Added `GET /api/evals/datasets/{id}/fields` extracting active column projections and fetched row keys for client-side template completions.
- **Real-Time Jinja Parameter Syntax Highlighter (`src/kb_web/static/js/jinja_highlighter.js`, `server.py`, `templates/evals.j2.html`, `templates/admin.j2.html`)**:
  - Created reusable client-side module providing real-time Jinja parameter validation across template editors.
  - Renders live visual status pills: green badges for recognized dataset fields (e.g. `{{ data.title }}`) and red animated alert badges for non-matching or misspelled keys.
  - Added click-to-insert available fields explorer bar above editors with field name insertion and count pills.
  - Mounted `/static` directory via FastAPI `StaticFiles` with CSP and security middleware whitelisting.
- **Configurable Worker Agents & Frozen Snapshot Commit Workflow (`src/kb_web/agent_config.py`, `models_orm.py`, `routers/admin.py`, `templates/admin.j2.html`)**:
  - Transformed background worker agents from fixed presets into fully configurable entities with "+ Create Worker Agent" dialog (`POST /api/admin/agents/create`) and custom deletion (`DELETE /api/admin/agents/{id}`).
  - Implemented test execution engine (`POST /api/admin/agents/{id}/test-run`) enabling administrators to test agent prompts and question schemas against sample KB articles prior to deployment.
  - Implemented versioned frozen snapshot commits (`POST /api/admin/agents/{id}/publish`), recording immutable snapshots (`frozen_snapshot_json`) with automatic version number increments and timestamp tracking.

### Changed
- **Direct Database Field Adherence & Elimination of Confusing Aliases (`src/kb_web/agent_config.py`, `templates/admin.j2.html`, `templates/evals.j2.html`)**:
  - Replaced legacy parameter aliases in preconfigured agent templates with canonical database columns from `fetched_pages`:
    * `Link Discovery Gating Agent (d1)`: migrated `page_title` and `base_url` to direct database fields `title` and `url`.
    * `Article Reading Assistant`: migrated `article_content` to database field `md_content or data.content`.
  - Added auto-migration in `ensure_default_agent_configs()` updating any existing rows in the database to standard column names.
  - Registered `available_fields` on all agent configurations combining core database fields (`title`, `url`, `description`, `md_content`, `content`, `tags`, `reading_time_minutes`, `fetched_at`) with specific agent runtime parameters (`candidate_url`, `query`, `question`, etc.), eliminating false-positive "invalid field" alerts.
- **In-Textentry Field Syntax Highlighting & Visual Contrast (`src/kb_web/static/js/jinja_highlighter.js`)**:
  - Injected dedicated `.jinja-editor-wrapper` and `.jinja-backdrop` styling rules into the DOM, enforcing `background-color: transparent !important` on active textareas so underlying highlight pill layers remain visible across both dark and light modes.
  - Configured `<mark>` highlights with `color: transparent !important` and glowing pill box-shadows (`rgba(34, 197, 94, 0.32)` for valid database/runtime fields and `rgba(239, 68, 68, 0.35)` with wavy red underlines for invalid keys), allowing the textarea's crisp native text to render cleanly on top with zero character displacement.
  - Added `ResizeObserver` and scroll synchronization to ensure backdrop and textarea metrics remain in sync upon resizing or dynamic content insertion.
- **Strict Isolation of SystemOne Decision Gating Models (`src/kb_web/agent_config.py`, `routers/evals.py`, `templates/admin.j2.html`, `templates/evals.j2.html`)**:
  - Completely excluded SystemOne decision models (`d1`, `tev1`) from generative completion and wiki creation model selectors across the entire application.
  - Structurally separated the Admin Agent tab into two distinct sections: **Section 1: SystemOne Decision Gating Models** and **Section 2: Generative LLM & Coding Worker Agents**.
  - Respects SystemOne architecture by completely removing invalid configuration controls (tools, system prompts, thinking mode, temperature, top_p, top_k, num_predict) from SystemOne agents, exposing strictly the `state` template and `questions` criteria.

### Fixed
- **Embedding Model Unification & Cross-Space Query Collision Fix (`src/kb_web/utils.py`, `rag_agent.py`, `worker.py`, `cli.py`, `models_orm.py`, `routers/cli_api.py`, `routers/admin.py`, `routers/embeddings.py`, `routers/rag_reports.py`)**:
  - **Root Cause**: Document vectors were indexed using one model (hardcoded `"embeddinggemma"` in `generate_gemma_embeddings_for_page`), while search/RAG queries and article-level embeddings were using another (e.g. `nomic-embed-text` via `config.ollama_embedding_model`). In addition, `find_nearest_chunks` calculated cosine similarity without filtering by `ChunkEmbedding.model_name`, causing distance computations across incompatible vector spaces (e.g. querying with Nomic against Gemma embeddings resulting in degraded or zero matches).
  - **Resolution**:
    * Created centralized `get_active_embedding_model(session=None, config=None)` ensuring a single source of truth across all vector creation, query embedding, and similarity search routines.
    * Refactored `generate_gemma_embeddings_for_page` (aliased as `generate_embeddings_for_page`) to use the active embedding model, explicitly record `ChunkEmbedding.model_name`, and apply prompt prefixes (`search_document: `) dynamically.
    * Updated `find_nearest_chunks` to strictly filter by `ChunkEmbedding.model_name == emb_model`, preventing cross-model vector distance calculations.
    * Synchronized `SettingOllama(key="ollama_embedding_model")` and `SettingExternal(key="active_embedding_model")` across Admin Portal updates, REST API endpoints, and worker jobs.
    * Added `kb-web-cli reindex-embeddings [--model MODEL]` command allowing on-demand reindexing of all document chunks with the active embedding model.
    * Added comprehensive unit test suite `tests/test_embedding_unification.py`.
- **Codebase-Wide Security & Vulnerability Hardening**:
  - `SEC-01`: Converted raw f-string SQL queries in `AgentPrompt` version tracking (`src/kb_web/config.py`) to parameterized queries with bound arguments to prevent SQL injection.
  - `SEC-02`: Fixed Stored XSS vulnerability in global notifications drawer and toast popups (`src/kb_web/templates/base.j2.html`) by introducing `escapeHtml(str)` utility and sanitizing messages, stages, and timestamps before innerHTML assignment.
  - `SEC-03`: Fixed Stored XSS in autonomous topic agent wikis and dynamic canvas pages (`src/kb_web/routers/agent_pages.py`) by wrapping markdown conversion output with `sanitize_html()`.
  - `SEC-04`: Fixed DOM attribute breakout and event injection vulnerabilities in collection viewer, collection editor, and URL import templates (`src/kb_web/templates/view_collection.j2.html`, `collection_editor.j2.html`, `url_import.j2.html`) using HTML entity escaping and `data-url` attributes.
- **Background Worker & Frontend IDE Bug Fixes**:
  - `BUG-01`: Fixed infinite re-indexing loop in background worker vector embedding refresh job (`src/kb_web/worker.py`) by filtering for pages lacking `ChunkEmbedding` records.
  - `BUG-02`: Replaced N-sequential HTTP `DELETE` loop when deleting folders in Workspace IDE (`src/kb_web/templates/workspace_ide.j2.html`) with atomic backend folder prefix deletion request.
  - `BUG-03`: Added `destroy()` lifecycle teardown to `JinjaHighlighter` (`src/kb_web/static/js/jinja_highlighter.js`) to disconnect `ResizeObserver` and remove window resize listener; updated parameter matching regex to handle Jinja pipe filters (`| default(...)`).
  - `BUG-04`: Fixed script race condition in Admin Portal (`src/kb_web/templates/admin.j2.html`) by moving `jinja_highlighter.js` into `extra_head`.
- **Performance Optimizations & Deprecation Notices**:
  - `CONF-01`: Replaced deprecated `sqlalchemy.ext.declarative.declarative_base()` import in `src/kb_web/models_orm.py` with `sqlalchemy.orm.declarative_base()` to eliminate SQLAlchemy 2.0 `MovedIn20Warning`.
  - `PERF-01`: Optimized server boot ghost URL cleanup in `src/kb_web/models_orm.py` to use set-based SQL `DELETE FROM ... WHERE ... IN (subquery)` instead of sequential per-row iteration.
  - `PERF-02`: Batched note vault zip import into single database transaction and throttled concurrent background tasks in `src/kb_web/routers/notes.py`.
  - `PERF-03`: Optimized taxonomy classification note scanning in `src/kb_web/routers/taxonomy.py` with `with_entities(Note.id, Note.url)` to avoid loading full bodies into memory.
  - `ARCH-01`: Removed hardcoded magic `ci.collection_id != 1` assumption in `vw_page_cards` view definition in `src/kb_web/models_orm.py`.
  - `DEPR-01`, `DEPR-02`, `DEPR-03`: Documented formal deprecation paths for legacy 10-item partitioning `taxonomy_state_machine.py`, legacy single-vector tables (`article_embeddings`, `title_embeddings`, `video_embeddings`), and `sqlite_utils` in `src/kb_web/db.py`.

## [0.5.10] - 2026-10-18
### Added
- **Autonomous Topic-Expert Custom Agent System & Dynamic Canvas Pages (`src/kb_web/models_orm.py`, `routers/agent_pages.py`, `custom_agent_engine.py`, `templates/topic_wiki_page.j2.html`, `templates/agent_page_themed.j2.html`)**:
  - **Topic Wiki Domain Pages (`TopicWikiPage`)**: Dedicated entity representing living, curated topic knowledge organized by logical paths (e.g. `/wiki/{agent_id}/architecture`), providing hierarchical navigation trees, markdown rendering, internal wiki linking, and citations back to imported library articles.
  - **Dynamic Agent Canvas Pages (`AgentPage`)**: Distinct canvas entity identified by unique hash IDs (`/pages/agent/{hash_id}`) featuring two rendering modes:
    * `raw`: Emits pure unstyled HTML directly without inherited base template or site chrome.
    * `themed`: Renders rich interactive agent dashboards within base application layout, supporting JSON form schemas, user input capture, and approval decision dialogs.
  - **Topic-Steered Grounding Discovery**: Restricts agent discovery strictly to already-imported library items (`FetchedPage`) in the database, continuously logging findings into `agent_observations` working memory.
  - **Goal-Directed Deliberation Engine**: Background loop reviewing pending self-tasks (`agent_self_tasks`), synthesizing grounding observations, and compiling/updating topic wiki entries.
- **Strict Human-In-The-Loop (HITL) Local Python Execution Kernel (`src/kb_web/python_kernel.py`)**:
  - Gated execution kernel allowing autonomous agents to propose local Python code execution in the `.venv` environment (`propose_python_execution`).
  - Gated behind human review: proposals automatically dispatch high-priority notifications linking to interactive review forms (`AgentPage` with HITL approval action).
  - Enforces fail-safe execution: code runs locally only upon explicit human approval (`execute_approved_code`), capturing isolated stdout/stderr and timestamps in `agent_python_approvals`.
- **Perpetual Notification History Portal & Management API (`src/kb_web/routers/api.py`, `routers/pages.py`, `templates/notifications_history.j2.html`, `templates/base.j2.html`)**:
  - Preserves ingestion notifications indefinitely until explicitly cleared by the user.
  - Added dedicated `/notifications` management portal with server-side pagination, filters by stage (`fetch`, `wiki`, `tags`, `vector`, `video`, `agent`, `error`), status (`success`, `warning`, `failed`, `info`), read/unread state, and keyword search.
  - Added per-notification deletion (`DELETE /api/notifications/{id}`), read state toggle (`PATCH /api/notifications/{id}/read`), and batch deletion (`DELETE /api/notifications`).
- **Evals Studio Model Categorization, Per-Model Generation Overrides, & Prompt Promotion (`src/kb_web/routers/evals.py`, `templates/evals.j2.html`)**:
  - Filtered models strictly by capability across tabs: Tab 1 displays only completion/chat LLMs; Tab 2 displays only Decision/SystemOne gating models (`d1`, `tev1`); Tab 3 displays only vector embedding models (`embeddinggemma`, `nomic-embed-text`, `bge-m3`).
  - Added per-model generation options drawer (`temperature`, `top_p`, `top_k`, `num_predict`, `num_ctx`) with hover tooltips and dynamic parameter overrides in streaming and batch evaluation requests.
  - Added free-form prompt testing via a "+ Add Empty Prompt" scratchpad card.
  - Added "Set As... ▾" prompt promotion select allowing tested prompts to be applied directly to system instructions (`wiki_prompt`, `youtube_wiki_prompt`, `tags_prompt`, `rag_system_prompt`) or custom agents (`POST /api/evals/prompts/promote`).
- **Live SSE Streaming & Thinking Token Buffering for Model Evaluations (`src/kb_web/base.py`, `routers/evals.py`, `templates/evals.j2.html`)**:
  - **Root Cause**: Running multi-model matrix evaluations across multiple prompts and dataset rows caused Cloudflare 524 gateway timeouts (100s idle timeout) on synchronous HTTP POST endpoints. Thinking tokens produced by reasoning models were also uncaptured.
  - **Fix**: Added `stream=True` support to `LoggedOllamaClient.chat()`, dynamically buffering `chunk.message.content` and `chunk.message.thinking` while logging the complete thought trace and output into `ollama_logs`. Implemented Server-Sent Events (SSE) streaming endpoint `POST /api/evals/matrix/stream` that immediately returns `event: start` (<10ms) to reset proxy idle timers, streams tokens live into the UI, updates progress, and renders live collapsible reasoning trace accordions.
- **Dynamic Model Context Discovery & Limit Uncapping (`src/kb_web/routers/evals.py`, `templates/evals.j2.html`)**:
  - **Root Cause**: FastAPI strictly capped `max_tokens` at 16,384, causing 422 validation errors when users tested larger context windows (e.g. 32k or 128k).
  - **Fix**: Raised maximum token validation ceiling to 262,144 tokens. Added `get_model_context_info()` querying Ollama `/api/ps` (for active runtime `context_length`) and `/api/show` (for architecture parameter limits), exposing `GET /api/evals/models/info` and dynamically labeling model context capabilities in UI pills.
- **Cloudflare Beacon CSP Whitelist & Humanized Error Alerts (`src/kb_web/server.py`, `templates/evals.j2.html`)**:
  - Added `https://static.cloudflareinsights.com` and `https://cloudflareinsights.com` to Content-Security-Policy directives (`script-src` and `connect-src`).
  - Added `formatApiError()` in `evals.j2.html` parsing FastAPI 422 validation errors into readable strings instead of `[object Object]` and translating HTML gateway timeouts.
- **Multi-Row Evaluation Datasets & Query Builder (`src/kb_web/routers/evals.py`, `templates/evals.j2.html`, & `models_orm.py`)**:
  - Added dedicated Tab 4 (**Eval Datasets & Query Builder**) in the Model Evaluation Studio allowing users to construct datasets using report filters and table projections.
  - Enforces strict minimum $\ge 20$ matching rows requirement before saving to guarantee evaluation statistical validity.
  - Integrated Jinja2 row templating (`{{ data.<key> }}`) with live Row 0 client previews for Prompt Matrix, Decision Gating, and Embedding Retrieval.
- **Granular Agent Configuration Engine & Admin Exposure (`src/kb_web/agent_config.py`, `models_orm.py`, `routers/admin.py`, & `templates/admin.j2.html`)**:
  - Implemented persistent `agent_configurations` ORM table exposing all parameters for all 11 background and interactive agents (`model`, `call_type`, `system_prompt`, `user_prompt_template`, `thinking`, `temperature`, `num_predict`, `num_ctx`, `top_p`, `top_k`, `tools`, `enabled`).
  - Added dedicated **Agent Configurations** tab in the Admin Portal with category filter pills and live save indicators.
  - Spotlighted the **Maintenance & Error Diagnostics Agent** (`maintenance_agent`), giving administrators full visibility and control over automated log diagnosis.
- **Ollama `d1` / `/v1/systemone` Decision Model Calling Overhaul (`src/kb_web/base.py` & `routers/evals.py`)**:
  - **Root Cause**: `client.systemone()` previously threw `TypeError: Client.systemone() got an unexpected keyword argument 'options'` when chat generation options were passed to decision models.
  - **Fix**: Sanitized `LoggedOllamaClient.systemone()` to strip `options` prior to calling Ollama, normalized question keys (`question` -> `instructions`, `choices` -> `criteria`, `probability` -> `noul`), and added structured deserialization for `noul`, `choice`, `score`, `confidence`, and `probabilities`.
- **Frontend Safe Error Response Parsing (`templates/evals.j2.html`)**:
  - **Root Cause**: Fetch calls in `executeMatrixEval()` and `executeDecisionEval()` ran `await resp.json()` unconditionally on error responses, raising unhandled SyntaxErrors (`Unexpected token '<', "<!DOCTYPE ... is not valid JSON"`) when HTML error pages were returned.
  - **Fix**: Wrapped error extraction with `await resp.text()` and guarded `JSON.parse()`, displaying human-readable server error details.

### Fixed
- **Recursive Taxonomy Category Pruning on Note Deletion (`src/kb_web/routers/notes.py` & `src/kb_web/routers/admin_batch.py`)**:
  - **Root Cause**: Deleting notes (`DELETE /api/notes/{id}` or `DELETE /api/notes/batch`) left behind empty parent taxonomy categories as orphaned stubs in the knowledge base navigation hierarchy.
  - **Fix**: Implemented `_prune_empty_taxonomy_categories()` to recursively prune empty taxonomy categories bottom-up after note deletion or category reassignment, ensuring no empty categories linger in the taxonomy hierarchy.
- **Raw Un-Truncated Report Data Downloads (`src/kb_web/routers/reports.py`)**:
  - **Root Cause**: `export_report_data()` reused UI grid placeholder formatting, causing CSV, XLSX, and JSON downloads to output string literals like `[Content: 77,805 chars]` instead of actual content.
  - **Fix**: Updated `export_report_data()` to set `fetch_heavy=True` and bypass placeholder truncation, streaming complete raw text content into exported files.

### Changed
- **Server Jobs Framework Registration (`src/kb_web/worker.py`)**:
  - Ensured `tag_curation` is registered alongside `wiki_curation`, `embedding_refresh`, `synthetic_qa`, `rag_eval`, and `link_crawler` in the default server jobs registry.

### Security & Hardening
- **Rate-Limit Spoofing Defense & Trusted Reverse Proxies (`routers/auth.py`, `config.py`, `routers/admin.py`, & `templates/admin.j2.html`) (Fixes #93, SEC-01)**:
  - **Root Cause**: `_get_client_ip()` previously trusted the first IP in `X-Forwarded-For` without validating whether the connecting peer was a recognized reverse proxy, allowing brute-force attackers to bypass the 5-attempt login lockout by sending randomized header values.
  - **Fix**: Added `trusted_proxies` property to `config.py` (default: `127.0.0.1, ::1`, configurable via `KB_TRUSTED_PROXIES` and Admin Portal General settings per Rule 7). `_get_client_ip()` verifies `request.client.host` against trusted IPs and CIDR ranges via `ipaddress`, only evaluating `X-Forwarded-For` when forwarded by a trusted proxy and picking the rightmost untrusted hop. Added `_global_failed_attempts` tracking with a 50-attempt global lockout ceiling.
- **Git Repo Import URL Validation & Subprocess Shell Elimination (`src/kb_web/repo_importer.py`) (Fixes #95, SEC-03)**:
  - **Root Cause**: `clone_repo()` passed user-supplied URLs directly to `git clone` with `shell=True` on Windows. A URL beginning with dashes allowed option injection (e.g. `--upload-pack=...`), while `file://` or local paths allowed filesystem exfiltration.
  - **Fix**: Implemented `validate_repo_url()` to reject empty URLs, leading dashes, local filesystem paths, and unsupported protocols. Invoked `git` via `shutil.which("git")` with `shell=False` across all platforms, passing `-c protocol.file.allow=never`, bounded clone depth (`1 <= depth <= 100`), and a `--` argument separator.
- **Stored Markdown/HTML XSS Sanitization & Content-Security-Policy (`src/kb_web/utils.py`, `routers/pages.py`, & `server.py`) (Fixes #94 & #97, SEC-02)**:
  - **Root Cause**: Rendered wiki and article markdown was passed directly into Jinja2 templates via `| safe` without sanitization. Ingested malicious web pages or AI wiki summaries could execute arbitrary script payloads. CSP was absent from response headers.
  - **Fix**: Integrated Rust-backed `nh3` HTML sanitizer (`sanitize_html()`) stripping `<script>`, `<iframe>`, inline event handlers (`onerror`, `onload`), and `javascript:` URIs while preserving standard formatting, syntax highlighting code blocks, and tables. Injected strict `Content-Security-Policy` header in `_inject_security_headers()`.
- **Fail-Closed Default Credentials (`src/kb_web/base.py`, `config.py`, & `routers/admin.py`) (Fixes #96, SEC-04)**:
  - **Root Cause**: Well-known default credentials (`admin123` / `kb-secret-key`) were accepted out-of-the-box by authentication guards.
  - **Fix**: `verify_api_key()` and `is_request_authenticated()` now fail closed, rejecting the default API key `kb-secret-key` with HTTP `401 Unauthorized` unless explicit development flag `KB_ALLOW_INSECURE_DEFAULTS=1` is set. Persistent alert banners notify administrators in the UI if default factory credentials remain active.
- **Cryptographically Random Session Secret (`src/kb_web/base.py` & `config.py`) (Fixes #111, SEC-05)**:
  - **Root Cause**: `_get_session_secret()` derived HMAC session signatures directly from `hashlib.sha256(config.admin_password)`. Knowing the password allowed offline forgery, and password rotation unexpectedly invalidated all active sessions.
  - **Fix**: Generated and persisted an independent 32-byte cryptographically secure session signing secret (`KB_SESSION_SECRET` or persisted in `settings_external`), fully decoupling HMAC cookie verification from administrative passwords.
- **Scrypt Salted Password Hashing & Secret Redaction (`src/kb_web/config.py` & `routers/auth.py`) (Fixes #110, SEC-06)**:
  - **Root Cause**: Passwords were stored in plaintext and written out to `kb-web.json` backup exports.
  - **Fix**: Added `hash_password()` and `verify_password()` using standard library `hashlib.scrypt` with random 16-byte salts (`scrypt$<salt>$<hash>`). Login transparently verifies existing plaintext passwords and automatically migrates them to scrypt hashes. Redacted sensitive secrets (`admin_password`, `api_key`) from `kb-web.json` exports.
- **SSRF Prevention & Internal IP Guard (`src/kb_web/utils.py`) (Fixes #109, SEC-07)**:
  - **Root Cause**: Ingestion targets were fetched without IP resolution checks, permitting requests to loopback addresses (`127.0.0.1`), RFC1918 private subnets, and cloud metadata endpoints (`169.254.169.254`).
  - **Fix**: Added `validate_target_url()` resolving hostnames via `socket.getaddrinfo()` and verifying IP addresses against `is_internal_ip()` (blocking loopback, private, link-local, multicast, and cloud metadata).
- **HTTP Header Hardening (`src/kb_web/server.py`) (Fixes #97, SEC-08)**:
  - Injected `Strict-Transport-Security: max-age=31536000; includeSubDomains` and `Permissions-Policy: geolocation=(), camera=(), microphone=()`. Removed deprecated `X-XSS-Protection` header.

### Fixed
- **Admin Portal Quick Diagnostics Dark Mode Panel (`src/kb_web/templates/admin.j2.html`)**:
  - **Root Cause**: The Quick Diagnostics mini-card in `#tab-general` used unsupported Tailwind 3 arbitrary gradient classes (`bg-gradient-to-br from-indigo-50 to-blue-50 dark:from-slate-800 dark:to-indigo-950`). Under the Tailwind 2.2.19 CDN, the dark-mode classes were unrecognized and the active linear gradient to `#eff6ff` persisted in dark mode, rendering light status text over a stark white box.
  - **Fix**: Replaced gradient classes with standard theme-consistent admin card classes (`bg-white dark:bg-slate-800 border-gray-200 dark:border-slate-700`) and added a dedicated `.quick-diagnostics-panel` rule (`background-color: #111827 !important; border-color: #1e293b !important;`).
- **Prompt Studio Monaco Editor Half-Screen Collapsed Sliver (`src/kb_web/templates/admin.j2.html`)**:
  - **Root Cause**: Monaco editor container and preview column relied on arbitrary Tailwind JIT height classes (`min-h-[520px]`, `h-[500px]`), which were ignored by the Tailwind 2.2.19 CDN. Inside unconstrained flex parents, `#monacoPromptContainer` defaulted to `height: auto` and collapsed into a ~15px horizontal sliver when viewed in half-screen/responsive or editor-only mode.
  - **Fix**: Added explicit CSS dimensions and inline fallback styles (`min-height: 480px; height: 500px;`) across `#studioSplitContainer`, `#promptEditorCol`, `#monacoPromptContainer`, and `#promptMarkdownPreview`. Added debounced `window.resize` listener and follow-up layout triggers in `initPromptMonaco()` and `setViewMode()` to guarantee responsive Monaco re-layout.
- **Non-ASCII Credential Crash (`src/kb_web/base.py` & `config.py`) (Fixes #98, BUG-01)**:
  - **Root Cause**: `hmac.compare_digest` raises `TypeError` when comparing non-ASCII `str` instances, turning non-ASCII passwords or API keys into unhandled HTTP 500 errors.
  - **Fix**: Implemented `safe_compare_digest()` using UTF-8 byte encoding (`a.encode("utf-8")`) and safe None checks.
- **Article View Extra Closing Div (`src/kb_web/templates/view_page.j2.html`) (Fixes #100, HTML-01)**:
  - **Root Cause**: Unmatched extra `</div>` at line 443 prematurely closed the container layout before modal and details elements.
  - **Fix**: Removed the redundant closing tag and verified template balance across all 25 Jinja2 files.
- **Modernized MCP Server Database Connectivity (`src/kb_web/mcp_server.py`) (Fixes #99, BUG-03)**:
  - **Root Cause**: MCP server read the legacy `db.sqlite` database using `sqlite_utils`, presenting empty or stale results on PostgreSQL deployments.
  - **Fix**: Refactored `mcp_server.py` to use `db_session()` and `FetchedPage` SQLAlchemy ORM models, providing transparent support for PostgreSQL and SQLite.

### Performance & Tooling
- **Batched Bulk Maintenance Routines (`src/kb_web/routers/admin.py`) (Fixes #102, PERF-01 & #105, QUAL-01)**:
  - Refactored `run_bulk_description_maintenance()` and `run_bulk_embedding_maintenance()` to stream candidate URLs and commit updates per item, avoiding full-table memory loading and unbounded open database transactions. Replaced bare `print()` calls with structured logging.
- **Optimized Agent Board Summary Distinct Queries (`src/kb_web/agent_memory.py`) (Fixes #103, PERF-02)**:
  - Replaced full-table `session.query(AgentMessage).all()` and in-memory set comprehensions with `session.query(...).distinct()` queries.
- **Crawler Queue Optimization with Deque (`src/kb_web/routers/pages.py`) (Fixes #104, PERF-03)**:
  - Replaced $O(N)$ `queue.pop(0)` list popping with $O(1)$ `collections.deque.popleft()` and added `enqueued` set tracking.
- **Timezone-Aware UTC Timestamps (`src/kb_web/utils.py`) (Fixes #106, QUAL-02)**:
  - Implemented `utc_now_iso()` using `datetime.now(timezone.utc).isoformat()` to eliminate ambiguous naive local timestamps.
- **Automated Div Balance & Structural Template Checking (`.agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`) (Fixes #101, TOOL-01)**:
  - Enhanced pre-commit template checker to automatically verify `<div>` tag balance and syntax across all templates.
- **Package Configuration & Lint Baseline (`pyproject.toml`) (Fixes #107, CFG-01 & #108, CFG-02)**:
  - Synchronized package version to `0.5.10`, updated package description, and established `[tool.ruff]` linting baseline.
- **Code Review & Issue Generator Skill (`.agents/skills/code-review-issue-generator/`)**:
  - Created reusable agent skill with `SKILL.md`, `audit_report_template.html`, `generate_audit_report.py`, and `sweep_codebase.py` for generating interactive review reports with ready-to-post GitHub issues.

## [0.5.9] - 2026-10-13

### Fixed
- **YouTube Offline Downloads Audio Missing (`src/kb_web/utils.py`, `config.py`, `routers/admin.py`, & `templates/admin.j2.html`) (Issue #112)**:
  - **Root cause**: `download_youtube_video()` requested `"format": "mp4/best"` without merging streams. When YouTube omits pre-muxed 720p/1080p MP4 formats, yt-dlp defaulted to video-only streams without sound.
  - **Fix**: Configured yt-dlp with `bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b` and `merge_output_format: "mp4"`, muxing video and audio tracks with ffmpeg.
  - **Rule 7 Exposure**: Exposed `youtube_download_format` property in `Config`, DB (`settings_external`), JSON (`kb-web.json`), and the Admin Portal under **Server Configurations**.
  - Added regression test `test_youtube_download_format_config_and_admin_update` and verified audio stream selector in `test_descriptive_video_download_and_resolution`.
- **Admin Portal blank tabs & `escapeHtml` ReferenceError (`templates/admin.j2.html`)** — regression from Issue #92 Prompt Studio merge:
  - **Root cause 1**: The `tab-prompts` refactor dropped 4 closing `</div>` tags after the *Quick Diagnostics* card, nesting `#tab-prompts`, `#tab-backups`, `#tab-media`, and `#tab-diagnostics` inside `#tab-general`. `switchAdminTab()` hid `#tab-general` and therefore every pane, rendering all non-General tabs blank. Restored the missing closing tags.
  - **Root cause 2**: Prompt Studio's `updateActivePromptUI()` (revision history) and the status banner called `escapeHtml()`, which was never defined in the admin template, throwing `Uncaught ReferenceError: escapeHtml is not defined` inside the Monaco init callback. Added a null-safe local `escapeHtml()` helper.
  - Added regression tests `test_admin_portal_tab_panes_are_siblings` and `test_admin_portal_defines_escape_html` in `tests/test_system_prompts_admin.py`.

### Added
- **Durable Agent Working Memory & Guarded GitHub CLI Operations Skill (`.agents/memory/`, `.agents/skills/gh-cli-operations/`, & `rules/documentation_rules.md`)**:
  - Established `.agents/memory/` directory with `package_caveats.md` and `github_cli_guardrails.md` for capturing durable package quirks, platform gotchas, and safe operational patterns across development turns.
  - Added Section 6 to `.agents/rules/documentation_rules.md` requiring AI agents to record package-specific traps and actively maintain working memory.
  - Implemented `gh-cli-operations` skill and Python script `scripts/gh_safe.py` providing safe, structured execution of `gh` operations with path quoting guardrails, draft PR enforcement, and structured JSON action logging to `.artifacts/gh-actions.log`.
  - Delivered interactive single-page repository code audit report in `.artifacts/feature-agent-skills-memory-and-code-audit/code_audit_report.html`.
- **AI Agent Personas & System Prompt Studio (`config.py`, `routers/admin.py`, & `templates/admin.j2.html`) (Issue #92)**:
  - Exposed all 10 non-numerical hardcoded prompt templates and system directives across the application in `config.py` backed by `AgentPrompt` versioning and `kb-web.json` serialization:
    - `wiki_prompt` (Wiki Extraction System Prompt)
    - `youtube_wiki_prompt` (YouTube Wiki System Prompt)
    - `tags_prompt` (AI Tag Curation System Prompt)
    - `ontology_synthesis_prompt` (Domain Ontology Synthesis Prompt)
    - `rag_system_prompt` (Agentic RAG System Instructions)
    - `rag_report_prompt` (Research Report Compilation Prompt)
    - `taxonomy_system_prompt` (Taxonomy Structuring Instructions)
    - `maintenance_agent_prompt` (Maintenance & Error Diagnostic Prompt)
    - `workspace_agent_prompt` (Workspace Coding Assistant Prompt)
    - `article_chat_prompt` (Article Q&A System Prompt)
  - Updated all consuming modules (`utils.py`, `maintenance_agent.py`, `rag_agent.py`, `workspace_agent.py`, `routers/conversations.py`, `taxonomy_state_machine.py`) to read instructions dynamically from `config`.
  - Added REST API endpoints `GET /api/config/prompts` and `POST /api/config/prompts` supporting live prompt updates and reset-to-default operations.
  - Refactored Admin Portal tab `tab-prompts` into a modern Prompt Studio:
    - Categorized sidebar list for quick selection with search filtering and custom modification status indicators.
    - Embedded Monaco Editor with Markdown syntax, dark mode support, and keyboard shortcuts (Ctrl+S / Cmd+S).
    - Live Obsidian-style Markdown preview powered by `marked.js` updating in real time as the user types.
    - Dynamic view mode controls (Split View, Editor Only, Preview Only).
    - Revision history drawer with full rollback capabilities (`/admin/prompts/set-head`).
- **Modular Server Jobs & Agents Framework (`src/kb_web/worker.py` & `routers/worker.py`)**:
  - Replaced monolithic single-agent worker with decoupled, modular server jobs (`ServerJob` registry managed by `AutonomousWorker`).
  - Independent job scheduling: Each job supports its own timespan interval (`interval_minutes`), enabled/disabled toggle state, and isolated execution lock (`asyncio.Lock`).
  - Dedicated Ollama Model Assignment: Each job can be assigned its own LLM, embedding, or decision model (persisted in DB settings `SettingOllama`/`SettingExternal`).
  - Built-in job suite: `wiki_curation` (AI wiki synthesis), `tag_curation` (topic taxonomy tags), `embedding_refresh` (Qdrant & SafeVector indexing), and extensible foundation stubs for `synthetic_qa`, `rag_eval`, and `link_crawler`.
  - Added REST APIs: `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/run`, `POST /api/jobs/{id}/config`, and admin routes `POST /admin/jobs/{id}/run` and `POST /admin/jobs/{id}/config`.
  - Added comprehensive "Autonomous Server Worker & Jobs" UI grid in `admin.j2.html` featuring status badges, telemetry counters (processed items, total runs, cycle time), inline interval and model inputs, and interactive "Run Now" triggers.
- **Git Repository Web Importer (`src/kb_web/repo_importer.py` & `templates/url_import.j2.html`)**:
  - Ported shallow Git clone and repository analysis engine (`rpr` devtul) from PR #82 commit `98cc195`.
  - Added `POST /api/import/repo` REST endpoint accepting repository URL, branch, max depth, file size limits, and target collection.
  - Generates comprehensive markdown repository directory tree, ingests source files, and indexes into knowledge base under canonical `repo://` URI scheme.
  - Added 3rd tab **"📦 Pull & Import Git Repo"** to the `/import` UI (`url_import.j2.html`) with interactive options for branch selection, collection assignment, file size caps, and tree depth.
- **Strict Configuration Transparency & Admin Exposure (Rule 7 Compliance)**:
  - Added Rule 7 to `GEMINI.md` and Rule 6 to `.agents/rules/development_rules.md` strictly prohibiting arbitrary hidden hardcoded limits.
  - Lifted and exposed note taxonomy limit (previously capped at 100 notes in `taxonomy.py`) through configurable dynamic setting `taxonomy_batch_limit` (default: 500, configurable up to 5000).
  - Exposed operational engine thresholds in `config.py` with DB backing: `rag_search_top_k`, `similarity_threshold`, `ollama_timeout`, `notifications_poll_interval_seconds`, `page_cards_per_page`, `crawler_default_max_pages`, and `repo_import_default_depth`.
  - Added **"Engine Thresholds & Operational Limits"** configuration card to the General tab in the Admin portal (`admin.j2.html` and `routers/admin.py`).
- **Workspace IDE Live Reactivity & Multi-Language Syntax Highlighting**:
  - Added `GET /api/workspaces/{workspace_id}/files` endpoint returning the complete current workspace virtual filesystem.
  - Implemented `refreshWorkspaceFilesFromServer()` and automatic background polling in `workspace_ide.j2.html` to reflect agent file creation/modification live without requiring page refreshes or re-entering the workspace.
  - Added syntax highlighting and language inference in `workspaces.py` and `workspace_ide.j2.html` for PowerShell (`.ps1`, `.ps`, `.psm1`, `.psd1`) and Windows Batch (`.cmd`, `.bat`).

### Fixed
- **Notification Dropdown Display & Toast URLs (`base.j2.html` & `routers/api.py`)**:
  - Fixed client-side parsing mismatch where `/api/notifications` returns `{ unread_count, notifications }` envelope but the UI expected a bare list, resolving the empty "No notifications yet" bug.
  - Added URL-matching and parameter extraction in `get_notifications` to resolve target page URLs and ids.
  - Updated notification links in the header dropdown and floating toast alerts to direct to `/view/page?url=...` for instant article viewing.
  - Added full dark mode support (`bg-slate-800`, `border-slate-700`, `text-slate-200`) to the notification dropdown panel.
- **Admin Model Selector & Dark Mode Polishing (`admin.j2.html`)**:
  - Eliminated duplicate input and select boxes for Ollama models on the Prompts tab; replaced with unified text input backed by native `<datalist id="admin_model_options">` displaying loaded VRAM models.
  - Fixed dark mode classes in Quick Diagnostics mini-card and prompt generation sections.
- **Import Page Configuration Context (`base.py`, `routers/admin.py`, & `url_import.j2.html`)**:
  - Bound `_jinja_env.globals["config"] = config` globally in `base.py` to prevent any template from failing with `UndefinedError` when accessing application configurations.
  - Passed `config=config` explicitly in `get_import_url_page()` and `handle_incoming_mobile_share()` in `admin.py`.
  - Added safe default fallback in `url_import.j2.html` line 277: `{{ (config.repo_import_default_depth if (config is defined and config) else 1) or 1 }}`.
  - Added regression test `test_import_page_renders_with_config_context` in `tests/test_server.py`.

## [0.5.8] - 2026-10-12
### Added
- **Dedicated Articles Directory (`/articles`)**:
  - Implemented `@router.get("/articles")` route rendering an articles-dedicated index with search, tag filtering, and pagination.
  - Added `📄 Articles` navigation link to global desktop navbar and mobile hamburger drawer menu in `base.j2.html`.
  - Added dedicated page title and subtitle for articles archive.
- **Autonomous Background Server Worker Engine (`src/kb_web/worker.py`)**:
  - Implemented `AutonomousWorker` singleton running continuous periodic cycles (configurable via `KB_AUTONOMOUS_WORKER_INTERVAL_MINUTES`, default: 5 min).
  - Single-item wiki generation: Finds oldest uncurated page, prompts Ollama for wiki synthesis, updates database, and generates vector chunk embeddings.
  - Single-item tag curation: Finds oldest untagged page, extracts tags with Ollama, and persists to database.
  - Zero downtime graceful failure: Catches LLM timeouts and connection errors gracefully without crashing the server, emitting notifications to the notification feed.
  - Extensible hook architecture: Provided pluggable extension hooks for synthetic QA question generation, RAG accuracy evaluation, and autonomous outbound link discovery.
  - Integrated worker lifecycle into FastAPI `lifespan` in `server.py` with clean startup and graceful shutdown.
  - Added REST API endpoints `GET /api/worker/status`, `POST /api/worker/cycle`, and `POST /api/worker/toggle`.
  - Added an interactive Autonomous Server Worker status and trigger panel in the Admin Dashboard (`admin.j2.html`).

### Changed
- **Mobile Navigation & Brand Polish**:
  - Removed `hidden sm:inline` from the brand title in `base.j2.html`, ensuring "Knowledge Base" remains visible on mobile screens alongside the book stack emoji (`📚`).
  - Hid the left sidebar navigation (`<aside>`) on mobile viewports (`hidden lg:block`) in `pages_list.j2.html` to eliminate clutter since the global hamburger drawer menu provides full navigation.
- **Admin Portal Desktop & Mobile Layout Enhancements**:
  - Replaced horizontal scrollbar tab navigation (`overflow-x-auto`) on mobile with responsive static button cards (`grid grid-cols-2 sm:grid-cols-3 md:flex md:flex-wrap gap-2`).
  - Added generous margins (`space-y-8`, `my-8`, `pb-28`) and padding across the lower sections of the Admin Backups & Database tab (`tab-backups` in `admin.j2.html`), providing clean breathing room for *Server Database Snapshots* and *Administrative Batch Operations & Content Purge*.

## [0.5.7] - 2026-10-12
### Added
- **Build Script Audit & Optimization (`build.py`)**:
  - Removed unnecessary docker-compose database startup loops, packaging steps (`uv build`), and file copying to remote network folders (`ARTIFACTS_ROOT`).
  - Transformed `build.py` into a lean, fast, reliable pre-commit verification tool executing environment sync (`uv sync`) and full test suite (`uv run pytest -k "not test_extension"`).
- **Pre-Boilerplate Hyperlink Extraction (`src/kb_web/html_cleaner.py`)**:
  - Implemented `extract_links_from_raw_html()` to parse raw untouched HTML and extract all valid hyperlinks before `<header>`, `<nav>`, `<footer>`, `<aside>`, and other boilerplate containers are decomposed.
  - Ensures complete link retention across web pages while generating sanitized Markdown.
- **Resilient Background Ingestion Pipeline (`src/kb_web/pipeline.py`)**:
  - Completely eliminated the blocking synchronous streaming loading page (`StreamingResponse` on `/import/url`), replacing it with FastAPI `BackgroundTasks` asynchronous execution and immediate 303 redirect.
  - Structured pipeline into isolated, re-runnable stages:
    - Stage 1: Immediate fetch and instant persistence of raw HTML and markdown into `FetchedPage` (guarantees zero data loss even if downstream AI models hang or fail).
    - Stage 2: AI Wiki synthesis with generous 1200.0s prompt timeout.
    - Stage 3: AI Tag extraction.
    - Stage 4: Vector and chunk embeddings indexing.
    - Stage 5: Optional offline video downloads.
  - Added content hash duplicate checking to skip redundant LLM synthesis when content is unchanged.
- **Real-Time Notification Feed & Global Toast System**:
  - Added `IngestionNotification` ORM model and SQLite/PostgreSQL table schema.
  - Added REST API endpoints `GET /api/notifications`, `POST /api/notifications/read`, and `POST /api/notifications/clear`.
  - Added notification bell `🔔` with unread count badge and interactive dropdown panel in `base.j2.html`.
  - Added client-side polling and floating toast notifications that alert the user in real-time as each background pipeline stage completes.
- **Responsive Mobile Navigation & Viewport Containment**:
  - Fixed horizontal stretching on phones by hiding the top menu button strip on smaller viewports (`hidden xl:flex`) and adding a collapsible mobile drawer menu with a hamburger toggle button (`☰`).
  - Added horizontal viewport containment (`overflow-x-hidden`) and word breaking (`break-words`, `overflow-x-auto`) across `base.j2.html` and `view_page.j2.html`.
- **Configurable LLM Prompt Timeout (`src/kb_web/config.py` & `base.py`)**:
  - Configured Ollama LLM prompt timeout to `1200.0` seconds (20 minutes) via `KB_OLLAMA_TIMEOUT` and `config.ollama_timeout`, preventing premature timeouts during complex extraction tasks.

## [0.5.6] - 2026-10-09
### Added
- **HTML Boilerplate Stripper & Clean Markdown Generator (`src/kb_web/html_cleaner.py`)**:
  - Implemented DOM sanitization engine decomposing non-content tags (`header`, `nav`, `footer`, `aside`, `script`, `style`, `noscript`, `svg`, `form`, `iframe`, `button`).
  - Added regex pattern matching to decompose boilerplate containers (cookie banners, consent prompts, social share widgets, newsletter modals, and advertisement sidebars).
  - Implemented semantic container detection prioritizing `<article>` and `<main>` tags with substantive text (>250 chars) to eliminate surrounding page chrome.
  - Configured `HTML2Text` with `body_width = 0` (preventing hard line wrap at 78 cols), clean link handling, and collapsed consecutive whitespace.
- **Interactive Dry-Run & Batch Inspection Tool (`scripts/preview_html_cleaning.py`)**:
  - Added interactive CLI runner supporting `--sample <N>`, `--url <url>`, and on-the-fly `--fetch-url <url>` live testing.
  - Generates standalone, interactive side-by-side visual HTML comparison report (`.artifacts/feature-html-boilerplate-stripper-and-cleaner/html_cleaning_preview.html`) displaying Original Raw Markdown vs. Sanitized Clean Markdown with character reduction and line metrics.
  - Safe dry-run by default; `--apply` commits changes with `PageVersion` audit backups and `is_frozen` guardrails.
- **Ingestion Pipeline Upgrades**:
  - Updated `fetch_url()` in `src/kb_web/utils.py` and `POST /api/import/html` in `src/kb_web/routers/api.py` to route through `html_to_clean_markdown()` for all future imported pages.

## [0.5.5] - 2026-10-06
### Added
- **Notes Cascading Deletion & Single-Note Purge Action (`src/kb_web/routers/notes.py`)**:
  - Implemented `_cascade_delete_notes()` resolving foreign key constraint failures across all 10 dependent tables: `chat_conversations`, `chat_messages`, `chunk_embeddings`, `taxonomy_items`, `collection_items`, `collection_actions`, `article_embeddings`, `title_embeddings`, `video_embeddings`, `page_versions`, `links`, and mirrored `fetched_pages`.
  - Added single-note deletion endpoint `DELETE /api/notes/{note_id}` guarded by `is_frozen` immutability status.
  - Re-routed `batch_delete_notes()` in `src/kb_web/routers/admin_batch.py` through the unified `_cascade_delete_notes()` pipeline and decremented taxonomy category item counts.
  - Added individual "🗑️" delete buttons on note cards in `notes_list.j2.html` and note editor view in `note_editor.j2.html`.
  - Fixed FastAPI route collision between static `/api/notes/batch` and parameterized `/api/notes/{note_id}` by registering `admin_batch.router` with high precedence.
- **AI Prompt-Driven Workspace Creation (`src/kb_web/routers/workspaces.py`)**:
  - Added `prompt: Optional[str] = None` and `template: Optional[str] = "web-game"` to `WorkspaceCreateRequest`.
  - Added `_generate_workspace_from_prompt()` calling Ollama to synthesize project names, templates, file hierarchies, and initial working code from natural language prompts, with heuristic fallback.
  - Added AI Prompt input textarea to the new workspace modal in `workspaces_list.j2.html`.
- **Flexible Project Types, Gist Mode & Live Markdown Runner**:
  - Eliminated the 3-template restriction to support arbitrary project types, multi-file Gists, and custom languages (`rust`, `go`, `c`, `markdown`, etc.).
  - Added live rendered Markdown preview runner in `workspace_ide.j2.html` powered by `marked.js` with GitHub Dark theme styling.
  - Added Gist file summary runner for non-executable custom project types.
  - Cleaned up starter template `README.md` markdown files with clean formatting and project instructions.
- **Workspace Hierarchical Directory Tree & Drag-and-Drop Reorganization**:
  - Replaced flat `(folder)/.keep` rows with a true collapsible directory tree using `<details open>`, `📁` folder icons, and hidden `.keep` files.
  - Added folder-specific "New File" (`+`) and "Delete Folder" (`🗑️`) controls.
  - Implemented HTML5 drag-and-drop file movement to reorganize files into folders or move them to the root container.
- **Real-Time Ollama Loaded Models Introspection**:
  - Updated `GET /api/workspaces/models` and added global `GET /api/models` to introspect `{ollama_host}/api/ps` for models actively loaded in VRAM.
  - Grouped and highlighted loaded models with `🟢 Loaded in VRAM` badge at the top of workspace IDE model picker.
  - Added "⚡ Check Loaded Models" button and quick-select picker to the Admin System Settings tab (`admin.j2.html`).
- **Targeted Notes Re-Taxonomy Classification**:
  - Added `POST /api/taxonomy/classify-notes` supporting vault targeting, `limit`, and `force_reclassify`.
  - Added "🏷️ Classify Notes" action button in `notes_list.j2.html` and `taxonomy.j2.html`.
- **Taxonomy Slug Collision Retry Loop & Unique Slug Enforcement (`taxonomy_state_machine.py`)**:
  - Implemented agent retry loop in `_synthesize_new_category()` catching duplicate category slug collisions, re-prompting the LLM harness with collision error feedback to select distinct domain names or merge into the collided category.
  - Added `_ensure_unique_slug()` guaranteeing unique slugs across all taxonomy operations.
- **Taxonomy Source Metadata & Provenance Enrichment**:
  - Added `_format_metadata_summary()` extracting vault, folder path, syntax, version count, source URL, and collections.
  - Injected provenance metadata into `classify_item_class()`, `evaluate_category_fit_tev1()`, and `_synthesize_new_category()`.
  - Enhanced `classify_single_item()` to package complete metadata for notes, articles, videos, and workspaces.

## [0.5.4] - 2026-10-05
### Added
- **Content Freeze & Immutability Engine (`is_frozen`)**:
  - Added `is_frozen = Column(Integer, default=0, index=True)` to `FetchedPage`, `Note`, and `YouTubeVideo` ORM models in `src/kb_web/models_orm.py` and added `is_frozen: Optional[int] = 0` to `HTMLPage` Pydantic model.
  - Created Alembic database migration `1b2c3d4e5f6a_add_content_is_frozen_column.py` with automatic SQLite column check in `models_orm.ensure_views_and_indexes`.
  - Implemented immutability route guards blocking AI wiki regeneration (`/admin/regenerate/wiki`), tag regeneration (`/admin/regenerate/tags`), manual tag updates (`/admin/update/tags`), source page refetching (`/admin/refetch/page`), YouTube video metadata updates (`/admin/regenerate/youtube-metadata`), and note editing (`PUT /api/notes/{id}`) whenever content is marked as frozen.
  - Added Freeze/Unfreeze toggle endpoints: `POST /admin/freeze/page` (redirect), `POST /api/pages/{url_path}/freeze` (JSON), `POST /api/notes/{note_id}/freeze` (JSON), and `POST /api/videos/{video_id}/freeze` (JSON).
  - Added batch freeze/unfreeze endpoint: `POST /api/admin/batch-freeze` supporting bulk updates for pages, notes, and videos.
- **Admin Batch-Delete Suite & Cascading Purge (`src/kb_web/routers/admin_batch.py`)**:
  - Created dedicated batch deletion engine with cascading database cleanup (`_cascade_delete_page_urls`):
    - `DELETE /api/notes/batch`: Batch delete Obsidian notes by note IDs, folder prefix, or vault name, cascading mirrored library pages, chunk embeddings, and taxonomy records.
    - `DELETE /api/sites/{domain}/all`: Batch delete entire virtual domain hosts and all associated pages, embeddings, versions, and site wikis.
    - `DELETE /api/videos/batch`: Batch delete video records and embeddings with optional on-disk media removal from `~/.kb/media/videos`.
    - `DELETE /api/pages/batch`: Batch delete page URLs and dependent embeddings and collection links.
    - `POST /api/admin/batch-delete`: Unified endpoint supporting polymorphic batch deletion across notes, sites, videos, and pages.
- **UI Enhancements for Immutability & Batch Management**:
  - `view_page.j2.html`: Added `❄️ Frozen` badge in header, Freeze/Unfreeze action button in sidebar, and locked styling for tags, wiki regeneration, and refetch actions when frozen.
  - `note_editor.j2.html`: Added `❄️ Frozen Note` indicator, Freeze/Unfreeze button, disabled inputs and locked Save button, and read-only Monaco editor instance when note is frozen.
  - `notes_list.j2.html`: Added multi-select checkboxes on note cards, sticky Batch Action Toolbar (Select All, Freeze, Unfreeze, Batch Delete), and one-click folder and vault deletion in the sidebar hierarchy tree.
  - `view_site.j2.html` & `sites_list.j2.html`: Added "🗑️ Delete Site & All Pages" action buttons with safety confirmations.
  - `admin.j2.html`: Added "Administrative Batch Operations & Content Purge" panel in the Backups & Database tab for notes, domains, and bulk freezing.
- **CI / GitHub Actions Submodule Resolution & Import Guards**:
  - Fixed CI failures on `master` branch by updating submodule URL in `.gitmodules` from relative path `./kb-web-cli` to absolute repository URL `https://github.com/Willmo103/kb-web-cli.git`.
  - Configured `submodules: recursive` under `actions/checkout@v4` in `.github/workflows/test-and-release.yml`.
  - Added defensive `try...except ImportError` guards with `pytest.skip` across `tests/test_cli_auth_and_workspaces.py` and `tests/test_rag_agent_and_reports.py` to prevent CI failures in minimal environments lacking submodules.
- **Taxonomy Schema Healing & Purge Restoration**:
  - Restored table purge statements (`DELETE FROM taxonomy_items; ...`) in `migrations/versions/0a9b8c7d6e5f_one_time_taxonomy_purge.py` along with DDL column checks ensuring `item_class` exists on `taxonomy_items`.
  - Added PostgreSQL idempotent DDL self-healing directly in `models_orm.ensure_views_and_indexes` (`ALTER TABLE taxonomy_items ADD COLUMN IF NOT EXISTS item_class VARCHAR(32) DEFAULT 'Notes';`, `is_frozen` columns on content tables, and `server_error_logs` table creation) ensuring zero schema crashes on server restart.
  - Created Alembic database migration `2c3d4e5f6a7b_add_server_error_logs_and_ensure_columns.py` creating the error logs table and ensuring schema consistency.
- **Persistent Server Error Logging & Gotify Integration**:
  - Added `ServerErrorLog` ORM model in `src/kb_web/models_orm.py` storing timestamp, error type, message, stack trace, HTTP request details, client IP, status, and agent feedback.
  - Enhanced `gotify.py` with `record_server_error()` to persist uncaught 500 errors to the PostgreSQL database, append to `~/.kb/logs/server_errors.jsonl`, and dispatch Gotify alerts with incident ID tags `[#ID]`.
  - Added REST API routes in `src/kb_web/routers/errors.py` (`GET /api/errors`, `GET /api/errors/search`, `GET /api/errors/{id}`, `POST /api/errors/{id}/analyze`).
  - Added "Server Incidents & Agent Diagnosis" tab to `src/kb_web/templates/logs.j2.html` and `src/kb_web/routers/admin.py` for web-based incident review and manual re-analysis.
- **Background Sidecar Maintenance Agent (`src/kb_web/maintenance_agent.py`)**:
  - Implemented automated website maintenance agent running as a non-blocking background sidecar daemon (`run_maintenance_daemon`) and auto-prompted upon uncaught exceptions.
  - Enforced strict 3000-character cap on error prompts (`format_error_prompt`) to prevent context overflows and minimize response latency.
  - Equipped with specialized agent tools:
    - `tool_search_source_code`: Lexical ripgrep-style search across `src/kb_web/`, `tests/`, and `migrations/`.
    - `tool_view_artifacts`: Listing and viewing markdown artifacts in `.artifacts/` and `uat/reports/`.
    - `tool_search_errors`: Search past error incidents by terms, types, and messages.
  - Performs root cause analysis via Ollama with intelligent rule-based fallback, storing diagnostics directly in `ServerErrorLog.agent_feedback` and posting updates to Gotify.
- **CLI Commands for Server Errors & Maintenance Daemon (`kb-web-cli`)**:
  - Added `kb-web-cli error` command group (`list`, `view <id>`, `search <query>`, `analyze <id>`) for terminal-based error investigation.
  - Added `kb-web-cli maintenance-daemon` command for running the background sidecar process.
- **Live Server Test Skill (`live-server-test`)**:
  - Added `.agents/skills/live-server-test/` skill with `audit_live_routes.py` CLI for read-only route auditing of live servers (e.g. `https://kb-test.willmo.dev`) using `curl`.
  - Verifies HTTP status codes, redirect flows, content types, security headers, and latency across public, protected UI, and protected REST API endpoints without triggering admin actions.

## [0.5.3] - 2026-10-03
### Added
- **Hierarchical Notes Folder Tree (Resolves Nested Directory View)**:
  - Added recursive directory parser `build_nested_folder_tree(notes)` in `src/kb_web/routers/notes.py` organizing slash-delimited note paths (`work/dev/notes.md`) into a structured tree of nested folders and leaf files.
  - Enhanced `/api/notes/tree` to return `nested_tree` alongside `tree` for full backward compatibility.
  - Updated `src/kb_web/templates/notes_list.j2.html` with recursive macro `render_folder_node` featuring collapsible `<details open>` chevrons, folder and document icons, note count badges, and indented multi-level nesting.
- **Prior 6-Class Item Classification Decision Gate & State Policy Directives**:
  - Added `classify_item_class()` in `src/kb_web/taxonomy_state_machine.py` executing a preliminary `tev1` (`ollama.systemone`) choice decision across 6 canonical classes: `Personal`, `Documentation`, `Notes`, `Articles`, `Source Code`, and `Unclassifiable`.
  - Injected structured `policies: [...]` arrays into the decision model `state` dict enforcing classification guidelines (e.g., personal lifestyle and dating content as `Personal`, API documentation and technical references as `Documentation`, code snippets as `Source Code`).
  - Added handling for `Unclassifiable` items: records an observation memory to the `#taxonomy` channel on the cross-agent message board and bypasses category domain assignment.
  - Added `item_class` column to `TaxonomyItem` ORM model and persisted classification across all assigned taxonomy items.
- **Preliminary "Fits at All" Decision Gate (`fits_any_category`)**:
  - Integrated preliminary `noul` gate question `fits_any_category` with explicit policy directives into `evaluate_category_fit_tev1()` prior to evaluating specific candidate categories.
  - Bypasses category fit evaluation immediately and prompts clean new domain synthesis whenever an item does not fit existing categories at all.
- **Meaningful Domain Naming & Generic Label Rejection**:
  - Implemented `_is_generic_domain_name()` and `_derive_meaningful_domain_name()` in `src/kb_web/taxonomy_state_machine.py` enforcing meaningful, semantic domain names (e.g. "Personal Lifestyle & Dating", "DevOps & Cloud Infrastructure") and strictly rejecting generic numbered placeholders (`Domain 10`, `Category 3`).
- **Thematic Domain Containment During Category Partitioning**:
  - Enforced parent-child containment during 10-item partitioning inner loops in `partition_category()`: all newly synthesized sub-categories are pinned directly under the parent domain (`parent_id = category.id`), keeping reclassifications strictly inside the original chosen domain.
- **Alembic Database Migration & CLI Rollback Support**:
  - Created migration `migrations/versions/f92d84291a25_add_taxonomy_classification.py` for `taxonomy_categories` and `taxonomy_items` (including `item_class` column and indexes).
  - Added `rollback()` and `rollback_single()` helper functions in `src/kb_web/scripts/deploy_migrations.py`.
  - Added `kb-web-cli db rollback` CLI command in `src/kb_web/cli.py` supporting downgrades to specific revisions or relative steps (`-1`).
- **Notes Ingestion Pipeline (Titling, Tagging, Link Extraction, Skip Wiki)**:
  - Added strict web URL extraction (`extract_valid_urls`) in `src/kb_web/utils.py` filtering for valid HTTP/HTTPS URLs while rejecting local relative paths, internal anchor fragments, non-web schemes (`file:`, `mailto:`, `javascript:`), and stripping trailing punctuation.
  - Added automatic note titling (`generate_note_title`) synthesizing concise, accurate titles from markdown headings or content when notes are untitled or blank.
  - Updated note background ingestion in `src/kb_web/routers/notes.py`: applies automatic titling, extracts web links (saved to `Note.links` as JSON array and mirrored to `FetchedPage.links`), and assigns tags, while explicitly **skipping AI wiki generation**.
  - Linked note enrichment events directly to the cross-agent message board.
- **Autonomous Category Taxonomy State Machine & Decision Integration**:
  - Created autonomous, self-organizing category taxonomy engine in `src/kb_web/taxonomy_state_machine.py` completely independent of existing user collections.
  - **Cold Start**: Initiates with 0 categories; the inaugural item prompts the LLM to invent the first category and its initial authoritative wiki documentation.
  - **Top-Down Decision Gate**: Evaluates incoming items against existing categories using `tev1` (`ollama.systemone`) with a top-down choice question across leaf branches or `new_category`, followed by a `fit_confidence` noul verification check.
  - **Living Category Wiki Docs**: Every category possesses a living `doc` wiki attribute updated and synthesized by an LLM upon each new item assignment.
  - **10-Item Threshold & Inner Partitioning Loop**: When any category reaches 10 items, global item additions are paused (`is_partitioning_paused()`), and all 10 items are partitioned into 2 or more distinct child sub-categories. The parent category is transformed into a pure group container (`is_container=1`, direct `item_count=0`), and global additions unpause once the inner loop concludes.
  - **Tree Representation**: Tree structure formatted hierarchically for classifier prompts (`format_category_tree_for_prompt`) and visualized in the interactive web ontology browser.
  - **Autonomous Background Crawler**: Scheduled background indexing task (`crawl_and_classify_all`) that crawls unclassified articles, notes, videos, and studio workspaces sequentially through the decision state machine.
  - **Taxonomy Web Studio & REST Endpoints**: Interactive tree browser, living wiki reader, and crawler controls at `/taxonomy` (`src/kb_web/templates/taxonomy.j2.html`) and `/api/taxonomy/*`.
- **Centralized Agent Memory & Cross-Agent Message Board**:
  - Created persistent shared memory engine in `src/kb_web/agent_memory.py` backed by `AgentMessage` ORM model.
  - Channel-based coordination (`#taxonomy`, `#ingestion`, `#workspaces`, `#rag`) and structured memory types (`decision`, `observation`, `lifecycle`, `state_machine`, `artifact`).
  - Added `tool_post_memory` in `src/kb_web/agent_tools.py` and wired automatic logging across all agent workflows (`workspace_agent.py`, `rag_agent.py`, `notes.py`, `taxonomy_state_machine.py`).
  - Added dedicated Agent Message Board UI at `/agents/board` (`src/kb_web/templates/agent_board.j2.html`) with channel tabs, agent filters, live feed, and post modal.
  - Added top-level navigation links (`🗂️ Taxonomy` and `🧠 Board`) in `src/kb_web/templates/base.j2.html`.
- **CLI Subcommand Suites**:
  - Added `kb-web-cli taxonomy crawl` (with `--limit`) and `kb-web-cli taxonomy tree`.
  - Added `kb-web-cli board list` (with `--channel`, `--agent`, `--limit`).
- **Authentication & Power Loss Resilience**:
  - Implemented persistent disk caching (`~/.kb/configs/db_settings_cache.json`) for configuration settings in `src/kb_web/config.py`. Prevents delayed database recovery or power failures from reverting administrator credentials back to development defaults (`admin123`).
  - Added connection health resilience in `src/kb_web/base.py` (`get_engine`) with `pool_recycle=300`, `pool_pre_ping=True`, and 5-second connection timeout to avoid hanging connections.
  - Added public `/api/health` endpoint returning system operational health without requiring session cookies.
- **CLI Authentication Hardening & Remote Restart (Resolves CLI 401 Unauthorized)**:
  - Updated `is_request_authenticated` and `verify_api_key` in `src/kb_web/base.py` to authenticate registered database CLI API keys (`CliApiKey` / `cli_api_keys`) as well as the master key. Resolves HTTP 401 Unauthorized errors on CLI ingestion.
  - Added `POST /api/cli/system/restart` endpoint enabling authenticated remote server restart signals.
  - Added `restart` command in `kb-web-cli/src/kb_web_cli/main.py` with automated health polling against `/api/health` to confirm server reboot.
- **Workspace Versioning & Freeze-to-Article**:
  - Created `WorkspaceSnapshot` ORM model in `src/kb_web/models_orm.py` and REST endpoints in `src/kb_web/routers/workspaces.py` for creating immutable tagged snapshots (`POST /api/workspaces/{id}/snapshots`), listing snapshots, and restoring workspace files (`POST /api/workspaces/{id}/snapshots/{snapshot_id}/restore`).
  - Implemented `POST /api/workspaces/{id}/snapshots/{snapshot_id}/freeze-article` to compile snapshot file manifests and syntax-highlighted source code into permanent Knowledge Base articles (`FetchedPage`).
  - Integrated version snapshots sidebar drawer, snapshot tagging, restore modal, and publish actions into the Monaco IDE in `src/kb_web/templates/workspace_ide.j2.html`.
- **Coding Agent Tools & Native `ollama.systemone` Tev1 Decision Integration**:
  - Upgraded project `ollama` dependency to `>=0.6.3` supporting native `ollama.systemone()`.
  - Implemented `systemone` method on `LoggedOllamaClient` in `src/kb_web/base.py` with logging to database table `ollama_logs`.
  - Created `src/kb_web/agent_tools.py` with structured tools: `tool_create_file` (with commentary annotations), `tool_read_file` (1-indexed line window slicing), and `tool_edit_file` (precise search-and-replace modification).
  - Created `src/kb_web/workspace_agent.py` integrating `tev1:latest` structured decision gating for classifying intent (`choice`), target file selection, and reading need assessment (`noul`).
  - Added CLI terminal agent harness in `kb-web-cli` (`kb-web-cli workspace agent <workspace_id>` and `kb-web-cli agent <workspace_id>`).
- **Autonomous Agentic RAG Report Generator & Tev1 Decision Scoring (Resolves Feature Request)**:
  - Eliminated the single-article chat drawer on `src/kb_web/templates/view_page.j2.html` and replaced legacy `/conversations` routes with HTTP 302 redirect to `/reports/rag`.
  - Built multi-sub-agent retrieval engine in `src/kb_web/rag_agent.py`:
    - `tag_search_subagent`: taxonomy and article/note tag matching.
    - `vector_rag_subagent`: query embedding similarity search across `ChunkEmbedding` (supports PostgreSQL `pgvector` and SQLite cosine fallback).
    - `text_search_subagent`: full-text lexical search across titles, markdown content, and note bodies.
    - `aggregate_candidates`: provenance boosting and candidate deduplication.
    - `tev1_scoring_subagent`: evaluates retrieved candidates against user query and research purpose using native `ollama.systemone` with up to 64 questions per turn across 6 technical dimensions (relevance, code actionability, technical depth, architectural authority, factual density, synthesis readiness).
    - `compile_rag_report`: synthesizes top-scored candidates into a structured publication-grade Markdown research report.
  - Added RAG report UI in `src/kb_web/templates/rag_report.j2.html` with query input, presets, live pipeline stepper, `tev1` decision matrix table, rendered report markdown viewer with Copy/Download/Save to Notes buttons, and recent reports drawer.
  - Implemented REST endpoints in `src/kb_web/routers/rag_reports.py`: `GET /reports/rag`, `POST /api/reports/rag/generate`, `GET /api/reports/rag`, `GET /api/reports/rag/{id}`, `POST /api/reports/rag/{id}/save-to-notes`, and `DELETE /api/reports/rag/{id}`.
  - Added CLI command in `kb-web-cli/src/kb_web_cli/main.py`: `kb-web-cli rag report "<query>"` with `--purpose`, `--output`, `--model`, and `--save-notes` flags.
- **Workspace Agent Welcome Card Update (UAT Feedback Resolution)**:
  - Updated the workspace IDE agent welcome card in `src/kb_web/templates/workspace_ide.j2.html` with `tev1 Gated` badge, active tool definitions (`create_file`, `read_file`, `edit_file`), and CLI command reference (`kb-web-cli workspace agent <ws_id>`).
- **Site-Wide Muted Neon Dark Mode & Moon/Sun Circle Toggle (Resolves Feature Request)**:
  - Designed and implemented a high-contrast muted neon retro dark theme in `src/kb_web/templates/base.j2.html`.
  - Uses deep obsidian/slate backgrounds (`#090e17` / `#111827`), technological slate borders (`#1e293b`), high-contrast sharp typography (`#f8fafc` / `#cbd5e1`), and muted neon accents (electric cyan `#38bdf8`, neon violet `#c084fc`, emerald `#34d399`, amber `#fbbf24`, rose `#f87171`).
  - Added an interactive circular Moon/Sun toggle button (`theme-circle-toggle`) with smooth 360-degree rotation micro-animation and stateful SVG icon swapping across both authenticated and guest navigation headers.
- **Fully Configurable RAG Process & Gating Questions Persistence**:
  - Implemented configurable RAG pipeline in `src/kb_web/rag_agent.py` supporting customizable search channels (toggles for tag search, vector cosine search, lexical text search), doc retrieval limits, candidate pool size, top sources to synthesize, minimum similarity threshold, and minimum decision score threshold.
  - Added dynamic decision gating question management supporting up to 64 questions per turn via native `ollama.systemone` with dynamic batching.
  - Implemented database persistence and retrieval for RAG configuration (`get_rag_pipeline_config`, `save_rag_pipeline_config`) using `SettingExternal(key="rag_pipeline_config")`.
  - Added REST API endpoints in `src/kb_web/routers/rag_reports.py`: `GET /api/reports/rag/config`, `POST /api/reports/rag/config`, `POST /api/reports/rag/config/reset`.
  - Added collapsible **Pipeline Configuration** panel in `src/kb_web/templates/rag_report.j2.html` allowing users to configure retrieval, customize gating questions, save to database, and reset to defaults directly from the RAG screen.
- **Production UI Naming & Terminology Audit**:
  - Audited site templates to remove internal developer shorthand, verbatim conversational terms, and library feature branding across buttons and links.
  - Replaced "ERP Grid" with "Reporting".
  - Replaced "tev1 Decision Gated" with "Decision Gated".
  - Replaced "Engine Wiki Storage File" with "Article Profile".
  - Replaced "Ollama Coding Agent" with "Coding Assistant".
  - Codified permanent rule in `GEMINI.md`: Rule 6 (Production UI Naming & Terminology Standard).

## [0.5.2] - 2026-09-29
### Fixed
- **Jinja2 Autoescape & XSS Hardening (Resolves #75)**:
  - Configured `autoescape=jinja2.select_autoescape(["html", "xml", "j2.html", "html5"])` in `src/kb_web/base.py` on the package Jinja2 environment.
  - Defensively escaped note content, summaries, vault names, and titles in `src/kb_web/templates/notes_list.j2.html`.
  - Added null-safe date slicing `{{ (n.updated_at or '')[:10] }}` to prevent `TypeError` when note update timestamps are unset.
  - Eliminated raw script injections from imported notes that triggered `Uncaught SyntaxError: Unexpected token '.'` and broke browser JavaScript evaluation.
- **Notes Modal Trigger Declarations & Event Listeners**:
  - Defined modal toggle functions (`openPasteModal`, `closePasteModal`, `openVaultUploadModal`, `closeVaultUploadModal`) in `{% block extra_head %}` so functions are declared globally on `window` before DOM buttons render.
  - Added explicit element IDs (`open-paste-modal-btn`, `open-vault-modal-btn`, `empty-create-note-btn`) and registered secondary event listeners on `DOMContentLoaded`.
  - Enabled backdrop click dismiss and `Escape` key listeners for modal accessibility and clean teardown.
- **PWA Web Share Target Manifest Enctype**:
  - Added `"enctype": "application/x-www-form-urlencoded"` to `share_target` in `GET /manifest.json` (`src/kb_web/server.py`), satisfying W3C Web Share Target API specifications and removing the browser manifest warning.
- **Service Worker Lifecycle & No-Op Fetch Removal**:
  - Replaced empty/no-op fetch event listener in `GET /sw.js` with standard service worker lifecycle event handlers (`install` with `skipWaiting()` and `activate` with `clients.claim()`), eliminating Chromium no-op navigation overhead warnings.
- **Automated Regression Test Suite**:
  - Added `test_issue75_notes_modal_freeze_and_pwa_manifest` in `tests/test_sprint6_features.py` testing note autoescaping, script declaration, manifest enctype, and service worker lifecycle compliance.

## [0.5.1] - 2026-09-28
### Fixed
- **LoggedOllamaClient Generate & Attribute Delegation (Resolves #73)**:
  - Implemented `generate(self, *args, **kwargs)` on `LoggedOllamaClient` in `src/kb_web/base.py` with execution duration tracking and logging to `ollama_logs`.
  - Added `__getattr__(self, name)` delegation to forward unhandled method calls to the underlying `ollama.Client`.
- **Dynamic Workspace Model Discovery from Ollama `/tags`**:
  - Added `GET /api/workspaces/models` and `GET /api/workspaces/tags` endpoints in `src/kb_web/routers/workspaces.py` querying installed models via `client.list()`.
  - Integrated dynamic model selector dropdowns into the workspace IDE (`workspace_ide.j2.html`) in both the AI Assistant subheader and Settings modal, with dynamic reload via Ollama `/tags` and persistent model selection via `localStorage`.
- **Workspace Agent Chat & Clean Error Handling**:
  - Updated `workspace_agent_chat_api` in `src/kb_web/routers/workspaces.py` to use structured `client.chat` messages, falling back to `generate`.
  - Removed simulated fake file modification template (`app.js`) on errors, returning clean error diagnostics and preventing false diff cards from rendering on failure.
- **Strict Codeblock Diff Action Matching**:
  - Refined `parseAndAttachDiffActions` in `workspace_ide.j2.html` to strictly validate target file paths (`^[a-zA-Z0-9_\-\./]+\.[a-zA-Z0-9]{1,10}$`), disallow directory traversal tokens (`..`), and ensure valid file extensions.
  - Suppressed diff action buttons (`[Review Diff]` / `[Apply]`) when the response is conversational or contains standard language codeblocks without explicit file targets.
  - Cleanly stripped `file:<path>` metadata lines from code block text in chat bubbles.

## [0.5.0] - 2026-09-28
### Added
- **Global Site-Wide Authentication Guard (Resolves #71)**:
  - Enforced full-site authentication gating across all web UI routes (`/`, `/pages`, `/view/page`, `/notes`, `/workspaces`, `/similarity/...`, `/conversations`, `/reports`, `/collections`, `/links`, etc.). Unauthenticated users are redirected with HTTP 303 to `/login?next={url}`.
  - Restricted public allowlist strictly to: `/login`, `/logout`, `/favicon.ico`, `/icon.png`, `/manifest.json`, and `/sw.js`.
  - Added REST and internal API gating requiring either an authenticated session cookie or valid API key (`X-API-Key` or `Authorization: Bearer <key>`), returning standard 401 Unauthorized JSON error responses for unauthenticated requests.
  - Added media asset route guard rejecting unauthenticated requests to `/media/...` with 401 Unauthorized.
  - Preserved login return redirection via `next` query parameter after successful authentication.
- **Brute-Force Login Rate Limiting**:
  - Implemented thread-safe sliding-window rate limiter on `POST /login` tracking failed authentication attempts per client IP. Exceeding 5 failures within a 60-second window triggers an immediate HTTP 429 Too Many Requests response.
- **HTTP Security Headers Middleware**:
  - Automatically injected standard enterprise security headers across all responses: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`, and `Referrer-Policy: strict-origin-when-cross-origin`.
- **Dynamic HTTPS Session Cookie Security**:
  - Enabled dynamic detection of secure connections via `request.url.scheme == "https"` or reverse-proxy `X-Forwarded-Proto: https` header, automatically setting the `Secure=True` cookie attribute when running behind HTTPS/TLS proxies.
- **Path Traversal & ZipSlip Safeguards**:
  - Hardened Obsidian vault archive extraction (`POST /api/notes/upload-vault`) against ZipSlip directory traversal vulnerabilities by disallowing path traversal tokens and validating canonical destination boundaries.
  - Enforced strict path sanitization on virtual workspace file CRUD endpoints (`/api/workspaces/...`).
- **Default Credential Posture Warnings**:
  - Added server boot-time security checks warning administrators in application logs if default development secrets (`admin123` or `kb-secret-key`) remain active.
  - Added visual security alert banners in the Admin Portal General tab alerting users to change default passwords and API keys.
- **Comprehensive Security Test Suite**:
  - Added dedicated test suite `tests/test_security_hardening.py` verifying full-site route gating, API key authentication, login brute-force rate limiting, security headers, ZipSlip prevention, and session cookie properties.

### Changed
- Refactored `base.py` authentication helpers to use constant-time `hmac.compare_digest` to prevent side-channel timing attacks.
- Updated `base.j2.html` navigation header to hide internal application navigation links for unauthenticated sessions, rendering a minimal gateway header instead.
- Hardened `ParsedUrl.from_url` in `models.py` against malformed port casting exceptions on non-standard URLs and Windows local path schemes.

## [0.4.0] - 2026-09-18
### Added
- **Main Page Semantic RAG Chunk Search Across Articles & Videos (Resolves #62)**:
  - Added semantic chunk search endpoint `POST /api/rag/search` using high-dimensional cosine similarity across chunk vectors stored in PostgreSQL `chunk_embeddings` with SQLite fallback.
  - Added dedicated RAG search bar, model selector dropdown, result count slider, and real-time similarity score indicator directly on the home page (`src/kb_web/templates/pages_list.j2.html`).
  - Added chunk anchor hydration and jump-link support to article view (`src/kb_web/templates/view_page.j2.html`), displaying discrete chunk boundaries with direct anchor highlighting (`#chunk-N`) and semantic proximity badges.
- **Multi-Model Embedding Reindexing, Model Comparison & Vector Source Toggle (Resolves #63)**:
  - Added `ChunkEmbedding.model_name` tracking column to support indexing the same documents across multiple embedding models (e.g. `embeddinggemma`, `nomic-embed-text`, `bge-m3`, `all-minilm`).
  - Added multi-model management endpoints in `src/kb_web/routers/embeddings.py`:
    - `GET /api/embeddings/models`: Discovers installed Ollama models and per-model chunk index statistics.
    - `GET /api/embeddings/active-model` & `POST /api/embeddings/active-model`: Dynamically reads and toggles the active embedding model source used throughout the app.
    - `POST /api/embeddings/reindex`: Background worker for re-embedding all stored knowledge base pages with any selected model.
    - `POST /api/embeddings/compare`: Executes queries across multiple models simultaneously and compares ranked chunk similarity side-by-side.
  - Added visual model comparison explorer UI at `/similarity/compare` (`src/kb_web/templates/embedding_comparison.j2.html`) with dual-column ranked chunk preview, similarity percentage dials, and reindex triggers.
- **Persistent Article-Level Ollama Chat & Dedicated Conversations Dashboard (Resolves #64)**:
  - Added ORM models `ChatConversation` and `ChatMessage` to `src/kb_web/models_orm.py` to persist conversational threads, message roles (`user`, `assistant`, `system`), and associated article links.
  - Added conversation API endpoints in `src/kb_web/routers/conversations.py`:
    - `GET /api/conversations`: Lists conversations filtered by article URL or general threads.
    - `POST /api/conversations`: Creates or resumes conversations for a given article.
    - `GET /api/conversations/{id}`: Retrieves full message history.
    - `POST /api/conversations/{id}/messages`: Sends user prompts to Ollama LLM, includes article context as system prompt, records responses, and updates thread timestamps.
    - `DELETE /api/conversations/{id}`: Deletes a conversation thread.
  - Added sliding interactive chat drawer to the article view (`src/kb_web/templates/view_page.j2.html`) with model selector, conversation history retention, auto-scrolling, and responsive markdown rendering.
  - Added dedicated global conversations dashboard at `/conversations` (`src/kb_web/templates/conversations_list.j2.html`) displaying conversation cards, linked article badges, message counters, and thread deletion.
- **Personal Knowledge Notes, Code Ingestion, Monaco Editor & Obsidian Vault Mirroring (Resolves #65)**:
  - Added ORM model `Note` to `src/kb_web/models_orm.py` supporting `url` (`note://...`), `title`, `content`, `syntax`, `vault_name`, `folder_path`, `checksum`, and timestamps.
  - Added full note management router `src/kb_web/routers/notes.py`:
    - `GET /api/notes`: Lists notes with vault and search filtering.
    - `GET /api/notes/tree`: Generates hierarchical directory trees grouped by vault and subfolder.
    - `POST /api/notes/paste`: Instant paste ingestion for markdown notes and multi-language code snippets with auto-chunking and vector embedding generation.
    - `GET /api/notes/{id}` & `PUT /api/notes/{id}`: Full CRUD operations for note viewing and editing.
    - `POST /api/notes/upload-vault`: Unpacks Obsidian vault `.zip` archives, mirrors folder hierarchies, extracts markdown files, saves image attachments to media storage, and embeds chunks.
  - Added notes hub UI at `/notes` (`src/kb_web/templates/notes_list.j2.html`) featuring an interactive vault tree sidebar, recent notes cards, and modals for note creation and vault upload.
  - Added full-page Monaco code editor at `/notes/editor` (`src/kb_web/templates/note_editor.j2.html`) supporting syntax highlighting, theme selection (`vs-dark`, `vs-light`), keyboard shortcuts (`Ctrl+S`), live character counters, and auto-saving.
- **Admin Portal Ergonomic Tabbed Layout Overhaul (Resolves #66)**:
  - Completely refactored `src/kb_web/templates/admin.j2.html` from an endless vertical scrolling view into a clean, 5-tab responsive dashboard:
    - Tab 1 (`tab-general`): General settings, auth token reset, Gotify configuration, system directories.
    - Tab 2 (`tab-prompts`): AI curation & wiki generation system prompts.
    - Tab 3 (`tab-backups`): JSON/SQLite backup downloads, upload restoration, and database view sync.
    - Tab 4 (`tab-media`): Media disk usage, image/audio/video purge controls, and orphan cleanup.
    - Tab 5 (`tab-diagnostics`): Live system info, dependency status, disk space, and logging links.
  - Implemented persistent tab state via URL hash (`#general`, `#prompts`, `#backups`, `#media`, `#diagnostics`) and `localStorage`.
  - Preserved all existing HTML anchor IDs and form action endpoints to guarantee backward compatibility.
- **Dynamic ERP-Style Custom Report Builder & Data Grid (Resolves #67)**:
  - Added ORM models `SavedReportView` and `ScheduledReportJob` to `src/kb_web/models_orm.py`.
  - Added report API endpoints in `src/kb_web/routers/reports.py`:
    - `GET /api/reports/tables`: Introspects available database tables, column names, and data types.
    - `POST /api/reports/query`: Dynamic multi-table SQL query generator with automated primary/foreign key joins (e.g., `fetched_pages` to `youtube_videos`, `collections`, or `chunk_embeddings`), multi-condition filtering, sorting, column aliasing, and lazy placeholders (`[HTML: X KB]`, `[Vector: N-dim]`) for heavy data fields to prevent client memory bloat.
    - `GET /api/reports/views` & `POST /api/reports/views`: Saves and retrieves custom user report definitions and view states.
    - `GET /api/reports/export`: Streams high-volume report exports in `.csv`, `.json`, and native Excel `.xlsx` format (via `openpyxl`).
    - `POST /api/reports/schedule`: Allows configuring scheduled automated report extraction jobs.
- **In-Browser Replit-Lite Workspaces with Pyodide Python WASM & Ephemeral Ollama Coding Agent (Resolves #70)**:
  - Added database models `Workspace` and `WorkspaceFile` to `src/kb_web/models_orm.py` supporting persistent multi-file workspaces across browser sessions with cascading deletions.
  - Added workspace router `src/kb_web/routers/workspaces.py` supporting starter project templates (`web-game`, `python-demo`, `blank`), full CRUD, ZIP packaging export streaming, workspace duplication, and ephemeral Ollama agent streaming chat (`/api/workspaces/{id}/agent/chat`).
  - Added responsive studio dashboard UI at `/workspaces` (`src/kb_web/templates/workspaces_list.j2.html`) and top-nav link `💻 Studio` in `src/kb_web/templates/base.j2.html`.
  - Added in-browser IDE at `/workspaces/{id}` (`src/kb_web/templates/workspace_ide.j2.html`) featuring Monaco Editor, Pyodide Python 3 WASM in-browser execution runtime, live sandboxed HTML/JS preview with console log interceptor, resizable layout panes, and Ollama agent file diff review/apply workflow.

### Fixed
- **Monaco Editor Notes Loading Failure (Uncaught ReferenceError: require is not defined)**:
  - Fixed template block mismatch between `base.j2.html` (`extra_head`) and `note_editor.j2.html` (`head_extra`), ensuring the `vs/loader.min.js` AMD loader is injected prior to editor initialization.
  - Added resilient DOM polling fallback in `note_editor.j2.html` to guarantee `require` is loaded before instantiating Monaco models.
- **Article View "Chat About Article" Trigger Button Inaction**:
  - Resolved DOM lookup race condition in `src/kb_web/templates/view_page.j2.html` by converting eager top-level element bindings (`chat-drawer`, `chat-drawer-backdrop`, `chat-messages-container`, `chat-user-input`, `chat-submit-btn`) into lazy accessor methods evaluated at click time.
- **Custom Report Data Grid Group By Query Failure**:
  - Replaced raw SQL `GROUP BY` syntax with ERP group ordering and clustering (`ORDER BY {gtbl}.{gcol} ASC, ...`) to prevent unaggregated column syntax errors across database engines.
  - Fixed default `sort_by` column table referencing (`fetched_pages.fetched_at`) when executing queries against non-base tables such as `notes`.
  - Added collapsible visual group headers (`📁 Group: value (N records)`) and safe error rendering in `src/kb_web/templates/reports.j2.html`.

## [0.3.0] - 2026-09-12
### Added
- **UI Performance & Latency Overhaul with Database View (Resolves #56)**:
  - Created pre-aggregated PostgreSQL database view `vw_page_cards` joining `fetched_pages`, `youtube_videos`, and `collections` with `string_agg(c.title, ', ')`, completely eliminating N+1 collection queries on index feeds.
  - Added targeted database performance indexes on `fetched_pages.fetched_at DESC`, `collection_items.source_id`, and `youtube_videos.creator` in Alembic migration `c72b89d412e1_add_page_card_view_and_indexes.py` and `ensure_views_and_indexes()`.
  - Added dedicated, high-performance REST API router `src/kb_web/routers/rest_api.py` serving lightweight JSON payloads for web frontends and external client agents:
    - `GET /api/articles`: Paginated article cards with search (`q`), tag filtering (`tag`), sort order, and metadata.
    - `GET /api/articles/detail`: Full article details with markdown and raw HTML (on-demand only).
    - `GET /api/videos`: Paginated YouTube video profiles with creator aggregation and duration/view counts.
    - `GET /api/videos/transcript`: Timestamped subtitle transcript extraction and segment parsing (`[MM:SS]` formatting).
    - `GET /api/sites`: Virtual domain directory grouped by hostname and article counts.
    - `GET /api/tags`: Tag cloud index with frequency counts.
  - Added responsive UI pagination and dynamic reactive search controls to `src/kb_web/templates/pages_list.j2.html`:
    - Responsive pagination bar with Previous/Next buttons, active page pills, item counters, and limit selector.
    - Client-side reactive JavaScript controller with 300ms search input debouncing, animated skeleton loading placeholders (`animate-pulse`), and seamless URL address bar state synchronization (`history.pushState`).
    - Added comprehensive unit test suite in `tests/test_rest_api.py` covering pagination bounds, query filtering, transcript segment extraction, cascade deletion, collections endpoints, and HTML shell responses.
  - **REST API Cascade Deletion (`DELETE /api/articles`)**:
    - Added `DELETE /api/articles` endpoint for external agents and client apps, supporting cascading removal of articles, YouTube video metadata, vector embeddings, collection memberships, and history revisions.
  - **Collections REST API Endpoints (`GET /api/collections`, `GET /api/collections/ungrouped`)**:
    - Added paginated endpoints for collections and ungrouped items with query filtering for client applications and agent tools.
  - **Dismissible Toast Flash Banners**:
    - Added responsive green success (`?msg=...`) and red error (`?error=...`) alert banners to `src/kb_web/templates/base.j2.html` with SVG icons and dismiss triggers.
  - **Ghost Stub Purge Routine**:
    - Added automated ghost stub cleanup in `ensure_views_and_indexes()` and database view definition to eliminate orphaned `Archived Item (...)` placeholders resurrected during migration.
  - **Webpage Crawl Link Discovery, Interactive Multi-Selection, and AI Pre-Checking (Resolves #60)**:
    - Added modular crawler engine in `src/kb_web/crawler.py` featuring robust URL normalization (`normalize_url`), anchor/tracking parameter stripping (`utm_*`, `ref`), same-domain link discovery (`extract_candidate_links`), already-ingested status detection, Ollama LLM structured curation (`ai_curate_candidate_links`), and background batch ingestion with Gotify notifications (`run_batch_crawl_ingestion`).
    - Added structured AI pre-checking system prompt prioritizing substantive technical documentation, articles, and guides while strictly filtering out foreign language variants (`/zh/`, `/ja/`, `/es/`, etc.), sitemaps, RSS feeds, legal/privacy boilerplate, authentication links, and social channels; supports user-defined custom driving instructions.
    - Added administrative REST endpoints in `src/kb_web/routers/admin.py`:
      - `POST /api/crawl/discover`: Extracts same-domain candidate URLs from seed page.
      - `POST /api/crawl/ai-filter`: Runs structured LLM curation with explanation.
      - `POST /api/crawl/enqueue`: Dispatches background scraping task for selected URLs into designated collections.
    - Added interactive "🕷️ Crawl & Discover URLs" tab to `/import` (`src/kb_web/templates/url_import.j2.html`) with candidate search filter, Select All / None / New Only toggles, dynamic selection counter badge, AI Pre-Select button, target collection selector with inline collection creation modal, and background enqueue toast alert.
    - Added direct deep crawl discovery shortcut on page profile view (`src/kb_web/templates/view_page.j2.html`).
    - Added comprehensive unit tests in `tests/test_crawler.py` covering URL normalization, HTML link parsing, AI structured JSON response handling, and API endpoints.
  - **Qdrant Collection Export & Automatic Vector Synchronization (Resolves #61)**:
    - Added `@router.post("/collections/view/{collection_id}/sync")` in `src/kb_web/routers/collections.py` matching the collection view sync trigger.
    - Added automated collection creation on the server if a collection with the requested identifier or name does not already exist in the database.
    - Added automated collection creation on the Qdrant vector server (`PUT /collections/{name}`) with Cosine distance and correct vector dimensions (`768` for `nomic-embed-text` or dynamically inferred from vectors).
    - Added on-demand chunk embedding generation for collection items lacking vectors prior to Qdrant export.
    - Applied URL quote encoding for collection names in Qdrant API requests to safely support spaces, commas, and special characters.
    - Added graceful handling of unauthenticated or local Qdrant servers when `QDRANT_API_KEY` is not provided.
    - Added comprehensive unit tests in `tests/test_qdrant_sync.py` verifying collection creation, vector point uploads, unconfigured URLs, and error states.
  - **Database Compound Indexing for Collections**:
    - Added compound performance index `idx_collection_items_col_source` on `collection_items (collection_id, source_id)` in Alembic migration `e81c74291a23_add_collection_items_compound_index.py` and `ensure_views_and_indexes()`.

### Changed
- **Phasing out SQLite in favor of PostgreSQL as Primary Storage Engine**:
  - Initiated deprecation of SQLite as primary production storage engine; optimized database queries, views, and indexes specifically for PostgreSQL.
  - Excluded heavy `html_content` and `md_content` fields from default article hydration queries to minimize network transfer overhead.
  - Optimized virtual site domain extraction in `view_all_pages` to project only `(url, title)` instead of full table scans.

### Fixed
- **Fixed Qdrant Sync 404 & Undefined Error Modal (Resolves #61)**:
  - Resolved 404 Not Found error caused by missing `@router.post("/collections/view/{collection_id}/sync")` route.
  - Updated status modal JavaScript in `src/kb_web/templates/view_collection.j2.html` to parse `data.message`, `data.detail`, and HTTP status codes, preventing `'undefined'` messages from displaying.
- **Fixed `/links` 500 Internal Server Error (Resolves #59)**:
  - Decoupled ORM `Link` rows into plain dictionaries inside `db_session()` in `src/kb_web/routers/links.py` to prevent SQLAlchemy 2.0 `DetachedInstanceError` when accessing attributes after session teardown.
  - Guarded `link.created_at[:10]` and `link.last_clicked_at[:10]` against `NoneType` subscripting in `src/kb_web/templates/links.j2.html`.
- **Restored Live Server DB Logging & Filtered Alembic Plugin Spam (Resolves #59)**:
  - Re-attached `DatabaseLogHandler` directly to `kb_web`, `uvicorn.error`, `uvicorn.access`, and root loggers inside `lifespan(app)` in `src/kb_web/server.py` to ensure request logging and uncaught exceptions persist after Gunicorn/Uvicorn worker process initialization.
  - Added filter in `DatabaseLogHandler.emit()` in `src/kb_web/base.py` to exclude noisy `alembic` and `plugins` migration setup messages from flooding `system_logs`.
  - Configured `fileConfig(..., disable_existing_loggers=False)` in `migrations/env.py` and set `lg.disabled = False` in `setup_logging()` to prevent Alembic startup migrations from muting runtime server and application loggers.
- **Optimized `/admin` Dashboard Latency from 7.92s to <5ms (Resolves #59)**:
  - Replaced full-table scan and Python list comprehension in `get_admin_dashboard()` (`session.query(FetchedPage).all()`) with an efficient SQL aggregate query (`func.count(FetchedPage.url).filter(...)`), eliminating multi-megabyte HTML/markdown deserialization overhead.
- **Optimized `/view/site` Profile Latency & Fixed Character-Split Tags (Resolves #59)**:
  - Replaced full-table scans in `view_site_profile()` with lightweight column projections and separate domain URL counts.
  - Parsed JSON-encoded `tags` strings into lists of strings (`_parse_tags`) to prevent Jinja from iterating over raw JSON strings character by character into single-letter pills.
  - Populated `safe_url = quote_plus(url)` on site page items so links route properly to page profiles.
- **Severe 11+ Second Latency on `/collections` and `/collections/view/{id}` (Resolves #58)**:
  - Eliminated full-table scans that eagerly loaded multi-megabyte `html_content`, `md_content`, and `text_content` across all 286 database pages on admin loads.
  - Replaced Pydantic `HTMLPage` model inflation on ungrouped pages and admin dropdown lists with lightweight column projections `(FetchedPage.url, FetchedPage.title)` and dictionaries, reducing query execution time from 11.33s to 0.028s (~400x speedup).
  - Replaced N+1 query loop in `view_collection` with a single grouped subquery for other collection memberships.
  - Projected only required fields in `view_collection_editor`, excluding heavy raw HTML payloads.
- **PostgreSQL Cascade Deletion & Foreign Key Violations (Resolves #56)**:
  - Fixed `ForeignKeyViolation` and 404 failure in `handle_delete_page` (`/admin/delete/page`) by cascading deletions across `article_embeddings`, `title_embeddings`, `video_embeddings`, `chunk_embeddings`, `collection_items`, `collection_actions`, `youtube_videos`, `page_versions`, `links`, and `fetched_pages`.
  - Replaced unhandled HTTP 404 raw JSON exceptions on deletion with user-friendly redirects to `/?error=...` toast banners.
  - Fixed migration script `db_migrate_sqlite.py` and WebSocket import to skip orphaned child records rather than synthesizing empty `Archived Item (<url>)` dummy cards.
  - Filtered out hollow ghost stubs in PostgreSQL view `vw_page_cards`.
- Fixed `AttributeError` / `OperationalError` during database snapshot export by ignoring database views in `db_snapshot.py`.
- Excluded view models from `Base.metadata.create_all()` to prevent accidental table creation before view instantiation.
- Resolved `NameError: name 'func' is not defined` in `src/kb_web/routers/pages.py`.
- Replaced deprecated `regex` parameter with `pattern` in FastAPI Query annotations across `rest_api.py`.

## [0.2.0] - 2026-09-09
### Added
- **Complete PostgreSQL & SQLAlchemy Migration (Resolves #30)**:
  - Migrated core database operations, models, configurations, and logs to SQLAlchemy ORM, providing complete dialect-agnostic support for SQLite and PostgreSQL (resolving #43, #46).
  - Implemented custom SQLAlchemy TypeDecorator `SafeVector` that dynamically maps to `pgvector.sqlalchemy.Vector` on PostgreSQL and a JSON-encoded Text fallback on SQLite (resolving #42).
  - Added custom comparator support for `SafeVector` (defining `.cosine_distance()`, `.l2_distance()`, and `.max_inner_product()`) that automatically delegates to pgvector comparators under PostgreSQL (resolving #42).
  - Implemented thread-safe connection pooling, dialect configuration in `Config`, and transaction-managed `db_session` middleware (resolving #44).
  - Added automatic PostgreSQL sequence synchronization (`setval`) inside database initialization and seeding routines.
  - Closed Sprint 2 (#41) and Sprint 3 (#45) milestones.
- **Unified Database CLI Suite (`kb-web db`, Resolves #47)**:
  - `migrate-sqlite`: Migrate SQLite database to PostgreSQL environments (`dev`, `test`, `live`) in foreign-key dependency order, sanitizing NUL characters, auto-generating parent stubs for orphaned records, and syncing sequences.
  - `deploy`: Deploy migrations across targets (`dev`, `test`, `live`, `all`) and ensure PostgreSQL pgvector column compatibility.
  - `snapshot`: Create point-in-time multi-table JSON snapshots of database tables saved locally in `Config.backups_dir`.
  - `sync-snapshot`: Synchronize snapshots from live database directly into test database.
  - `replication-setup`: Automated publisher (`kb_live_pub`) and subscriber (`kb_test_sub`) setup for PostgreSQL logical replication.
  - `replication-status`: Real-time inspection of PostgreSQL replication slots, publications, and active subscriptions.
  - `backup-videos`: Automated ZIP archive backup of all local YouTube videos with strict retention of maximum 2 archives.
  - `restore-videos`: Restores YouTube video files from backup ZIP into `media/videos` with automatic database indexing.
  - `reindex-videos`: Scans `media/videos` directory, extracts YouTube video IDs, and links them to `youtube_videos.local_path`.
- Added Alembic migration `b52a19d8c638_setup_pg_publication.py` setting up `CREATE PUBLICATION IF NOT EXISTS kb_live_pub FOR ALL TABLES;` on PostgreSQL.
- Added video management subsystem (`video_manager.py`) with recursive media scanning, video ID regex parsers, automated 2-backup max ZIP retention, and index repair.
- Added server-side local backup storage in `Config.backups_dir` (`~/.kb/kb-web_backups`) with full Admin Dashboard UI controls for creating, downloading, restoring, and deleting database JSON and video ZIP archives.
- Added diagnostic fallback for `/admin/ws/import` on HTTP GET requests when reverse proxies drop WebSocket Upgrade headers, alongside direct HTTP multipart file upload.

### Fixed
- Resolved `ValueError: expected list or ndarray` in `SafeVector` by deserializing JSON vector strings before binding to `pgvector.sqlalchemy.Vector`.
- Removed hardcoded dimension restriction from `SafeVector` in `models_orm.py`, allowing 768-dimension `nomic-embed-text` vectors without length mismatch errors.
- Fixed `AttributeError: 'Config' object has no attribute 'get_db'` by implementing `Config.get_db()` and fixing settings read/write helpers.
- Resolved `ValueError: A string literal cannot contain NUL (0x00) characters` during PostgreSQL imports by stripping NUL bytes in `clean_record` and `websocket_import`.
- Resolved `ForeignKeyViolation` on migration from SQLite by synthesizing placeholder parent records in `fetched_pages` for orphaned embeddings and video rows.
- Fixed `export_database` and snapshot creation when running in SQLite or default target mode.
- Updated automated unit test suite (`pytest`) to run against parameterized sqlite/postgresql dialects, resolving foreign keys, binary serialization, and dimensions assertions.

## [0.1.32] - 2026-08-13
### Added
- Implemented duplicate URL import verification across UI, CLI, and REST endpoint pipelines, archiving changed pages to `page_versions` and bypassing LLM processing on identical content (resolving Issue #33).
- Added parallel background video downloading option to the URL import page, complete with dynamic JavaScript detection of YouTube URLs (resolving Issue #34).

### Fixed
- Resolved `sqlite3.OperationalError: database is locked` errors during test suite execution by fully consuming streaming responses in test client requests and closing database connections immediately after use.
- Avoided `sqlite_utils.db.NotFoundError` crashes on duplicate checks for new URLs by using `rows_where` queries instead of `get`.

## [0.1.31] - 2026-08-12
### Security
- Added `Depends(verify_auth)` to the `GET /links` and `GET /links/go` endpoints, securing the saved links views and tracking from unauthorized users (resolving Issue #31).

### Fixed
- Globally mocked `kb_core.notifier.Gotify` in the test suite setup fixture (`tests/test_server.py`) to prevent real alerts and notifications from being fired during automated tests.

### Documented
- Added documentation under the Running Automated Tests section of `README.md` and init rules of `GEMINI.md` to guide developers on disabling Gotify notifications when running test suites.

## [0.1.30] - 2026-08-10
### Added
- Implemented `kb-cli logs` command in CLI tool allowing remote inspection of server system logs with `--limit` parameter persistence.
- Added `GET /api/cli/logs` endpoint in CLI API router returning database system logs (ordered by most recent first).
- Added clipboard copy button (`📋 Copy`) next to redacted CLI API keys in Admin Dashboard with HTTPS and HTTP fallback support.

### Changed
- Converted layout containers across all web templates (`admin`, `collection_editor`, `collections`, `logs`, `pages_list`, `similarity_graph`, `sites_list`, `view_collection`, `view_page`, `view_site`, `base`) from static max-widths (`max-w-4xl`, `max-w-5xl`, `max-w-6xl`, `max-w-7xl`) to reactive full-width `max-w-[95%] w-full` layout containers.
- Increased default Ollama client connection timeout from 90s to 300s in `src/kb_web/base.py` and CLI HTTP client timeouts to 300s in `kb-web-cli/src/kb_web_cli/main.py` to prevent timeout errors during Ollama cold-starts and heavy model reasoning calls.

## [0.1.29] - 2026-08-07
### Added
- Implemented regular webpage links saving and cataloging dashboard (`/links`).
- Added click usage and redirection tracking (`/links/go?id=...`) to increment click count and record last clicked timestamp.
- Implemented Chromium standard HTML bookmarks file importer to upload and bulk populate saved links directory.
- Restored the missing `generate_gemma_embeddings_for_page` implementation block.

### Fixed
- Fixed Ollama reasoning `think` parameter compatibility crashes with older Ollama servers by only passing the argument conditionally when enabled.
- Propagated exceptions in `extract_wiki_content` and `extract_tags_content` so that ingestion failures show actual errors instead of silently creating broken `"Ingestion Backup"` pages.
- Broken circular dependency import inside `cli_api.py` by importing the Jinja2 environment from `..base`.

## [0.1.28] - 2026-08-05
### Added
- Implemented standalone CLI package `kb-web-cli` as a nested git submodule containing `kb-cli` console command executable wrapper.
- Added server-side CLI API router endpoints (`/api/cli`) exposing client registration, synchronous ingestion, tag/collection updates, and context-aware RAG agent query tasks.
- Integrated dashboard CLI Integration configuration card panel, displaying generated API keys, registered computer terminal clients, and administrative revoke action forms.
- Added comprehensive unit test suite `test_cli_client_server_integration` verifying full REST/CLI flow.

## [0.1.27] - 2026-08-04
### Added
- Implemented descriptive YouTube video filenames formatting as `[Creator] - Title [VideoId].mp4` upon local offline downloads.
- Added a directory-scan matching fallback to dynamically check `media/videos/` for any filenames matching `*{video_id}*`, preventing breakage from stale database paths.
- Added comprehensive mock unit test `test_descriptive_video_download_and_resolution` to assert filename pattern and dynamic resolution.

### Fixed
- Fixed directory glob lookup character-range patterns parsing bug for filenames containing square brackets `[` `]` by utilizing direct filesystem iterators.

## [0.1.26] - 2026-08-04
### Added
- Migrated all configuration settings (Ollama, Gotify, Qdrant details) to the database with dynamic, thread-safe sync.
- Implemented system prompt versioning and curation in the database (via table `agent_prompts`), displaying full history dropdowns and providing "Use This Version" rollback buttons in the Admin Dashboard.
- Added a quick "Assign Item" collections sidebar form on the Collections dashboard.
- Appended robust unit tests verifying video offline badge states, DB config migrations, prompt rollback operations, and log limits persistence.

### Fixed
- Fixed YouTube videos missing the collections badge, collection form dropdowns, and "Change Collections" action details by correctly passing collection template variables.
- Fixed collections created via `/import` screen being created as private by default, updating them to public to match standard collections dashboards.
- Fixed collections created via `/import` screen setting incorrect `source_type` ("articles") for video URLs, dynamically resolving it to "videos".
- Fixed offline video player detection logic to check both the DB-recorded path and the default location in the media directory for offline files.
- Fixed server log display to sort in reverse chronological order (most recent first) across log rendering and downloads.
- Implemented persistent line limit preferences on server logs using request cookies, defaulting limit options to 100.

## [0.1.25] - 2026-08-01
### Fixed
- Fixed YouTube transcript wiki generation hangs by disabling reasoning latency (`think=False`) for intermediate chunk summaries.
- Fixed FastAPI event loop blocking hangs by wrapping synchronous ingestion steps (`fetch_url`, `extract_wiki_content`, etc.) in a threadpool utilizing `run_in_threadpool`.
- Fixed background tasks thread-safety by opening a new connection handle via `_get_db()` within worker functions instead of sharing the request's database connection.
- Optimized tag extraction and collection suggestions by setting `think=False` to prevent unnecessary reasoning delays.
### Removed
- Excised the entire cron job scheduler and management subsystem:
  - Deleted `cron_scheduler.py` and `src/kb_web/routers/cron.py`.
  - Deleted UI templates `cron_jobs.j2.html` and `view_cron_job.j2.html`.
  - Removed table initializations for `cron_jobs` and `cron_job_runs` in `src/kb_web/db.py` and added a startup routine to drop these tables if they exist.
  - Excised all references in `server.py` and `graph.py`.

## [0.1.24] - 2026-07-25
### Added
- Condensed all history, architecture, and agent instructions into package-level `GEMINI.md`.
- Implemented sub-divided development rules in `.agent/rules/` (`development_rules.md`, `documentation_rules.md`, `python_coding_rules.md`, `git_rules.md`, `uat_and_ui_testing_rules.md`, `ui_component_uat_rules.md`, `vcs_testing_artifact_rules.md`, `custom_html_feedback_rules.md`).
- Implemented automated UAT testing & feedback skills in `.agent/skills/`:
  - `collect-uat-feedback-and-create-issues`: Interactive HTML feedback form template (`uat_feedback_form.html`) and issue parser script (`parse_uat_issues.py`) to convert user JSON submissions into actionable agent tasks.
  - `generate-uat-testing-artifact`: Script (`generate_uat_report.py`) and template (`uat_report_template.md`) to generate VCS-tracked test logs and reports in `uat/`.
  - `ui-component-uat-check`: Automated Jinja2 template & theme verifier script (`verify_ui_templates.py`).
  - Added skills for `pre-commit-checks`, `document-code-issue-and-fix`, `kb-web-browser-extension`, and `kb-web-service-management`.

## [0.1.23] - 2026-06-14
### Changed
- Fixed invisible collections action buttons.
- Allowed accepting multiple AI suggestion groupings consecutively without page reload using AJAX updates.
- Added think=False argument to all remaining Ollama chat sessions to disable reasoning latency.

## [0.1.22] - 2026-06-14
### Added
- Refactored and modularized `server.py` into FastAPI APIRouters under `src/kb_web/routers/` (auth, pages, sites, admin, api, collections, cron, graph) and helper libraries (`utils.py`, `gotify.py`, `cron_scheduler.py`).
- Implemented custom user Collections manager with CRUD operations, inline collection classification, and AI-suggested group recommendations using Ollama.
- Fixed HTML attribute escaping inside the AI collection suggestions acceptance forms, resolving formatting and unclosed quote bugs during submission.
- Passed format="json" option to Ollama client.chat and added regex-based fallback to guarantee robust parsing of AI collection suggestions responses.
- Created interval-based scheduled Cron Jobs configuration dashboard with execution run history logging, generated outputs download, and success/failure notification triggers.
- Integrated Obsidian-style interactive visualizer using Vis.js representing embedding similarity relationships between pages, sites, creators, and tags.
- Embedded a server log viewer panel directly in the admin dashboard tailing the `kb-web.log` stream.
- Setup Gotify tracebacks logging to push uncaught exceptions and context variables directly to administrators.

## [0.1.21] - 2026-06-13
### Added
- Implemented layout fix for YouTube iframe container on Tailwind CSS v2 via explicit aspect-ratio style.
- Implemented text chunking helper `chunk_text` and segmented ingestion/synthesis pipeline to handle long documents/transcripts safely (preventing Ollama context overload crashes).
- Integrated `max_input_length` config property (default 20,000 chars) with environment/json loading/saving, and added form control in admin panel.
- Eliminated standalone Tags page and replaced navbar "Tags" link with "Videos" (linking to `/?view=videos`).
- Simplified Video creator filtering by removing sidebar count listings and showing a clear filter header on creator selections.
- Implemented tag query param filter on main route to render a unified matching articles and videos grid.
- Converted all tag displays and creator metadata labels to active clickable links.

## [0.1.20] - 2026-06-13
### Added
- Created a separate `youtube_videos` database table referencing `fetched_pages` to decouple and represent YouTube uploader metadata.
- Implemented dedicated YouTube videos section (`/?view=videos`) filterable by uploader/creator.
- Added responsive embedded YouTube iframe display directly on the viewing page of video articles.
- Added specialized `youtube_wiki_prompt` system configuration for synthesizing structured chronological video breakdowns with timestamped quotes.
- Implemented markdown list preprocessor to fix single asterisk formatting issues and insert preceding spacing.
- Added `kb-web-mcp.service` configuration file and exposed sse host/port binding parameters in CLI `mcp` start commands.
- Added video details/attributes block rendering (creator, duration, views, channel ID) on the video viewing page.
- Added a "Regenerate Video Attrs" action button and `/admin/regenerate/youtube-metadata` POST endpoint to re-fetch/update video metadata from YouTube.
- Added duration overlays and formatted view counts to the video listing card grid.
- Fixed video validation parsing skipping by declaring optional YouTube-specific fields on the HTMLPage Pydantic model.

## [0.1.19] - 2026-06-07
### Changed
- Simplified site profiles (`/view/site`) to only display the listing of scraped pages under that domain, removing legacy Ollama site-wide wiki generation and cached table references.
- Re-styled page viewer buttons layout to a vertical flex-column formatted directly to the right of the title block.
- Removed tag badges from similar articles in the left sidebar panel.
- Updated unit tests to align with simplified sites logic.

## [0.1.18] - 2026-06-06
### Added
- Created virtual sites index view (`/sites`) and individual site profile views (`/view/site`).
- Added database caching via `site_wikis` table for consolidated site-wide wikis synthesized by Ollama.
- Integrated same-domain scraped links grid on `/view/page` route with confirmation modal ingestion pipelines.
- Rendered original scraped markdown content as styled HTML inside collapsible details element.
- Positioned semantically similar articles panel inside a sticky left sidebar.
- Added `test_virtual_sites` unit test covering new routes, grouping logic, and wiki compilation.

## [0.1.15] - 2026-06-05
### Changed
- Refactored authentication to use stateless, cryptographically signed session cookies (HMAC-SHA256), resolving Gunicorn write contention and database locks.
- Removed legacy `active_sessions` database table and replaced write-on-read token evictions with lock-free CPU checks.
- Implemented thread-local database cache (`threading.local`) and synchronized schema initialization (`init_db`) inside a thread lock.
### Added
- Integration tests `test_get_requests_are_write_free` and `test_concurrent_reads_no_lock` to assert zero write queries on GET requests and thread safety under concurrent requests.

## [0.1.14] - 2026-06-05
### Fixed
- Enabled WAL (Write-Ahead Logging) mode on database connection to allow concurrent reads and writes from multiple Gunicorn processes.
- Set connection timeout to 30 seconds to prevent `database is locked` OperationalErrors during concurrent logins or writes.

## [0.1.13] - 2026-06-05
### Changed
- Replaced in-memory `ACTIVE_SESSIONS` cache with a persistent `active_sessions` table in SQLite database. This fixes session drops across Gunicorn worker processes and server service restarts.
- Modified logout handler to clear active session entries from the persistent SQLite database.

## [0.1.12] - 2026-06-05
### Fixed
- Fixed YouTube video transcript extraction on newer versions of `youtube-transcript-api` that use instance-based APIs.
- Silenced `yt-dlp` warning output regarding missing `ffmpeg` and JavaScript runtimes on target server environments.
- Cleaned up unused imports in testing module.

## [0.1.10] - 2026-06-04
### Added
- Model Context Protocol (MCP) server stdio API integration.
- YouTube transcript and metadata fetching using `youtube-transcript-api` and `yt-dlp`.
- Tags catalog and filtered article index views.
- Description and tag vector embeddings cache using Ollama's embeddings API, plus similar articles lookup.
- Desktop browser bookmarklet support for 1-click sharing.
### Changed
- Refactored verify_auth and login to support next query parameter redirects.
- Changed URL import form input validation to support parsing URLs from copy-pasted blocks.

## [0.1.9] - 2026-06-03
### Added
- FastAPI server with multi-platform Gunicorn/Uvicorn runner.
### Changed
- Added clean steps to `build.py` to purge previous dist artifacts.

## [0.1.8] - 2026-06-01
### Added
- Gunicorn support for production deployments with a CLI integration.

## [0.1.7] - 2026-06-01
### Added
- Admin dashboard with server configuration, pipeline management, and database import/export tools.

## [0.1.6] - 2026-05-31
### Fixed
- Resolved systemd service configuration paths and setup requirements.

## [0.1.5] - 2026-05-31
### Changed
- Updated `ExecStart` path to point to virtual environment binary in `kb-web.service`.

## [0.1.4] - 2026-05-31
### Added
- Service installation and management scripts for production deployment.

## [0.1.0] - 2026-05-30
### Added
- Initial project release with bookmarks database, FastAPI curation ingestion API, and browser extensions integration.
