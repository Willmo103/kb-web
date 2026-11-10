# Exhaustive Codebase Map: `src/kb_web`

This document provides a complete, file-by-file mapping of all 68 Python source files (34,130 LOC) comprising the `kb-web` application.

---

## 1. Codebase Summary & File Index

| File Path | LOC | Subsystem | Primary Responsibilities | Key Classes & Functions |
|---|---|---|---|---|
| `__init__.py` | 15 | Core | Package entrypoint, version discovery | `get_version()` |
| `base.py` | 819 | Core | Shared base models, logging, env utilities, db session management | `BaseSettings`, `get_db_session()`, `log_action()` |
| `server.py` | 384 | Core | FastAPI application factory, middleware, lifecycle events | `create_app()`, `lifespan()`, `setup_middleware()` |
| `config.py` | 1135 | Core | Central dynamic configuration, admin settings loader, Ollama endpoints | `Settings`, `get_settings()`, `sync_from_db()` |
| `db.py` | 138 | Core | SQLAlchemy engine creation, connection pooling, session maker | `get_engine()`, `get_session()`, `init_db()` |
| `gunicorn_runner.py` | 107 | Core | Production WSGI/ASGI runner, worker management | `UvicornWorker`, `run_gunicorn()` |
| `models.py` | 331 | Core | Pydantic validation schemas for API inputs & outputs | `ArticleCard`, `TagUpdate`, `ImportRequest` (17 schemas) |
| `models_orm.py` | 1594 | Core | SQLAlchemy ORM declarative models, pgvector type definition | `FetchedPage`, `ContextStatementORM`, `PageCardView` (50 models) |
| `utils.py` | 1494 | Core | HTML parsing, text normalization, hashing, date formatting | `clean_text()`, `hash_sha256()`, `extract_domain()` (26 funcs) |
| `pipeline.py` | 633 | Ingestion | URL ingestion orchestrator, cleaning, wiki synthesis trigger | `run_ingestion_pipeline()`, `reprocess_page()` |
| `crawler.py` | 461 | Ingestion | Async sitemap and link crawler with domain depth limits | `crawl_domain()`, `extract_sitemap_urls()` |
| `html_cleaner.py` | 200 | Ingestion | Trafilatura / BeautifulSoup HTML distilling to clean Markdown | `clean_html_to_markdown()`, `strip_boilerplate()` |
| `repo_importer.py` | 541 | Ingestion | Remote Git repo shallow cloner, AST analysis, markdown indexer | `clone_and_index_repo()`, `generate_tree_markdown()` |
| `video_manager.py` | 284 | Ingestion | `yt-dlp` video metadata & transcript extraction | `fetch_youtube_metadata()`, `extract_transcript()` |
| `taxonomy/engine.py` | 2043 | Taxonomy | Layer-by-layer steered decision classification & fact grounding | `TaxonomyEngine`, `classify_item_by_layer()`, `reassign_items()` |
| `taxonomy/steered_tree.py` | 418 | Taxonomy | Hierarchical JSON tree state, node CRUD, gating checks | `SteeredTaxonomyTree`, `add_node()`, `delete_node()`, `bulk_move()` |
| `taxonomy/models.py` | 236 | Taxonomy | Pydantic schemas for steered tree nodes, criteria, and moves | `SteeredTaxonomyNode`, `BulkMoveRequest`, `TopicCreate` |
| `taxonomy/__init__.py` | 64 | Taxonomy | Taxonomy package exports and lazy loaders | `get_taxonomy_engine()`, `get_tree()` |
| `taxonomy_state_machine.py` | 1290 | Taxonomy (Legacy) | Unsupervised Category Clusters clustering state machine | `CategoryClusterStateMachine`, `run_clustering()` |
| `context_mesh/pipeline.py` | 419 | Context Mesh | Fact, invariant, intent, affordance extraction from text | `ContextMeshPipeline`, `extract_statements()` |
| `context_mesh/store.py` | 462 | Context Mesh | Atomic fact CRUD, pgvector deduplication, coordinate filters | `ContextMeshStore`, `insert_statement()`, `deduplicate()` |
| `context_mesh/retriever.py` | 242 | Context Mesh | Semantic vector and coordinate-gated fact retrieval | `ContextMeshRetriever`, `search_facts()` |
| `context_mesh/injector.py` | 79 | Context Mesh | Prompt augmentation with structured fact context | `ContextMeshInjector`, `inject_context()` |
| `context_mesh/personal_vk.py` | 145 | Context Mesh | User nested Personal Value-Knowledge (VK) JSON loader & injector | `PersonalVKManager`, `load_vk_context()`, `inject_vk()` |
| `context_mesh/models.py` | 89 | Context Mesh | Pydantic models for atomic context statements | `StatementCreate`, `StatementFilter`, `MeshQuery` |
| `context_mesh/__init__.py` | 46 | Context Mesh | Module exports | `get_mesh_store()`, `get_mesh_pipeline()` |
| `rag_agent.py` | 929 | Agents | Multi-sub-agent retrieval, tev1 decision scoring, report generation | `RagReportAgent`, `execute_rag_flow()`, `score_candidates()` |
| `custom_agent_engine.py` | 224 | Agents | Autonomous topic agent loop, task dispatch, memory journal | `CustomAgentEngine`, `run_agent_cycle()`, `digest_url()` |
| `maintenance_agent.py` | 367 | Agents | Self-directed database health & taxonomy integrity agent | `MaintenanceAgent`, `audit_broken_references()` |
| `workspace_agent.py` | 322 | Agents | Ollama pair programming agent inside Monaco IDE workspaces | `WorkspaceAgent`, `generate_code_patch()`, `explain_file()` |
| `python_kernel.py` | 190 | Agents | Strictly gated HITL Python execution in `.venv` | `PythonKernel`, `submit_code()`, `execute_approved_code()` |
| `agent_config.py` | 729 | Agents | Agent persona definitions, prompt templates, tool schemas | `AgentConfigManager`, `get_prompt_for_agent()` |
| `agent_memory.py` | 140 | Agents | Agent working memory journal logger | `AgentMemoryJournal`, `record_observation()` |
| `agent_tools.py` | 207 | Agents | Structured tool execution bindings for LLMs | `execute_tool_call()`, `search_knowledge()` |
| `worker.py` | 1222 | Workers | Async background engine, decoupled job registry, pause controls | `BackgroundWorker`, `JobRegistry`, `auto_curate_job()` |
| `gotify.py` | 139 | Workers | Push notification dispatch to Gotify server | `send_gotify_alert()`, `notify_worker_event()` |
| `cli.py` | 393 | Interfaces | Typer CLI commander (`kb-web-cli`) | `app`, `import_url()`, `rag_report()`, `nuke_taxonomy()` |
| `mcp_server.py` | 154 | Interfaces | FastMCP server exposing articles, search & rag to external AI | `mcp`, `search_kb()`, `get_article()` |
| `routers/admin.py` | 1933 | Routers | System admin portal, config editor, database stats, user governance | 52 route handlers (`/admin`, `/admin/settings`, `/admin/users`) |
| `routers/admin_batch.py` | 382 | Routers | Bulk operations: re-indexing, re-tagging, bulk purge | 8 route handlers (`/admin/batch/reindex`, `/admin/batch/purge`) |
| `routers/agent_board.py` | 117 | Routers | Visual dashboard for monitoring autonomous topic agents | 4 route handlers (`/agents`, `/agents/{agent_id}/status`) |
| `routers/agent_pages.py` | 259 | Routers | Dynamic web canvas views for agent-generated HTML/Markdown | 3 route handlers (`/pages/agent/{hash_id}`) |
| `routers/api.py` | 421 | Routers | General public REST endpoints for articles, search, and tags | 9 route handlers (`/api/articles`, `/api/search`) |
| `routers/auth.py` | 223 | Routers | Session authentication, login, logout, brute-force rate limiter | 6 route handlers (`/login`, `/logout`, `/api/auth/token`) |
| `routers/cli_api.py` | 692 | Routers | Authenticated endpoints dedicated to CLI and headless agents | 17 route handlers (`/api/cli/import`, `/api/cli/rag`) |
| `routers/collections.py` | 1432 | Routers | Dynamic collections, folders, and custom link lists | 29 route handlers (`/collections`, `/collections/{id}`) |
| `routers/conversations.py` | 315 | Routers | Multi-turn chat history with LLMs | 6 route handlers (`/chat`, `/api/chat/messages`) |
| `routers/embeddings.py` | 256 | Routers | Vector generation, recalculation, and similarity searches | 7 route handlers (`/api/embeddings/generate`) |
| `routers/errors.py` | 132 | Routers | System error log viewing and clearing | 4 route handlers (`/admin/errors`, `/api/errors/clear`) |
| `routers/evals.py` | 1638 | Routers | Model Evaluation Studio, comparative prompt & model matrices | 24 route handlers (`/evals`, `/evals/runs`, `/evals/compare`) |
| `routers/graph.py` | 112 | Routers | Knowledge graph visualization endpoints | 2 route handlers (`/graph`, `/api/graph/data`) |
| `routers/links.py` | 138 | Routers | External links and bookmark management | 5 route handlers (`/links`, `/api/links`) |
| `routers/notes.py` | 695 | Routers | Markdown note authoring, editing, coordinate linking | 14 route handlers (`/notes`, `/notes/{id}`, `/api/notes`) |
| `routers/pages.py` | 750 | Routers | Article browser, reader view, edit form, version history | 8 route handlers (`/pages`, `/pages/{url}`, `/pages/edit`) |
| `routers/rag_reports.py` | 359 | Routers | Research report viewer, export, and trigger UI | 9 route handlers (`/reports/rag`, `/reports/rag/{id}`) |
| `routers/reports.py` | 1189 | Routers | Metric dashboards, content growth analytics, scheduled reports | 19 route handlers (`/reports`, `/api/reports/metrics`) |
| `routers/rest_api.py` | 669 | Routers | OpenAPI v1 REST specifications for external integrations | 15 route handlers (`/api/v1/articles`, `/api/v1/taxonomies`) |
| `routers/sites.py` | 120 | Routers | Virtual domain portal and site-level wikis | 3 route handlers (`/sites`, `/sites/{domain}`) |
| `routers/taxonomy.py` | 1047 | Routers | Knowledge tree navigation, node CRUD, bulk moves, governance | 35 route handlers (`/taxonomy`, `/api/taxonomy/*`) |
| `routers/worker.py` | 200 | Routers | Worker job status, manual triggers, pause non-core controls | 18 route handlers (`/api/jobs`, `/api/jobs/pause-non-core`) |
| `routers/workspaces.py` | 1260 | Routers | Monaco IDE workspaces, Pyodide WASM preview, snapshotting | 21 route handlers (`/workspaces`, `/api/workspaces/*`) |
| `scripts/__init__.py` | 3 | Scripts | Package identifier | None |
| `scripts/check_db_ready.py` | 22 | Scripts | Startup health probe waiting for PostgreSQL port readiness | `wait_for_db()` |
| `scripts/db_migrate_sqlite.py`| 334 | Scripts (Legacy) | SQLite to PostgreSQL one-way data copier | `migrate_sqlite_to_postgres()` |
| `scripts/db_replication.py` | 195 | Scripts | Read-replica synchronization verification | `verify_replication()` |
| `scripts/db_snapshot.py` | 180 | Scripts | PostgreSQL pg_dump snapshot utility | `create_snapshot()` |
| `scripts/deploy_migrations.py`| 282 | Scripts | Production migration runner applying raw SQL DDL | `apply_migrations()` |
| `scripts/verify_db_schema.py` | 90 | Scripts | Compares ORM models against live database tables | `verify_schema()` |

---

## 2. Deep Dive by Subsystem Architecture

### A. Core Runtime (`src/kb_web/`)
- **`server.py`**: Initializes the FastAPI app, attaches CORS, sets up session cookies with secure samesite flags, mounts static files, and initializes background tasks in the async `lifespan` handler.
- **`config.py`**: Reads `.env` and loads dynamic settings from `setting_ollama` and `setting_external` tables in PostgreSQL. Caches configurations with TTL to guarantee low latency.
- **`models_orm.py`**: Declarative SQLAlchemy models. Implements `SafeVector` comparator to allow seamless testing even when pgvector is mocked.
- **`utils.py`**: Core utilities including SHA-256 computation, domain extraction, clean text normalization, and date parsers.

### B. Ingestion & Media (`src/kb_web/`)
- **`pipeline.py`**: Orchestrates fetch -> clean -> version -> tag -> summarize -> embed. Handles both synchronous interactive imports and async worker queues.
- **`crawler.py`**: Follows hyperlinks recursively within allowed domain scopes and depth budgets.
- **`repo_importer.py`**: Clones Git repositories into a sandboxed temp directory, generates Markdown file tree representations, parses docstrings, and saves the codebase as structured knowledge.
- **`video_manager.py`**: Invokes `yt-dlp` via subprocess to pull metadata, stream URLs, and auto-caption transcripts.

### C. Steered Knowledge Tree & Context Mesh (`src/kb_web/taxonomy/`, `src/kb_web/context_mesh/`)
- **`taxonomy/engine.py`**: Uses Ollama choice-based decision models (like `d1:latest` or `tev1`) to route content layer-by-layer down user-steered folder trees. Evaluates gating questions and enforces domain blacklists.
- **`taxonomy/steered_tree.py`**: Manages the tree JSON representation (`SteeredTaxonomyNode`), handles parent-child relations, and powers atomic bulk relocations.
- **`context_mesh/`**: Extracts atomic facts (<= 144 characters) from articles, computes vector embeddings, rejects duplicates via cosine similarity, and injects context into agent prompts.
- **`context_mesh/personal_vk.py`**: Loads the user's nested Personal Value-Knowledge JSON hierarchy and injects it as immutable context for RAG and agent reasoning.

### D. Autonomous Agents & Developer IDE (`src/kb_web/`)
- **`rag_agent.py`**: Advanced Agentic RAG combining vector similarity, full-text lexical search, and multi-question decision scoring (`tev1`) to produce comprehensive research dossiers.
- **`custom_agent_engine.py`**: Autonomous topic agents that scan their assigned coordinates, author living topic wikis (`topic_wiki_pages`), and publish dynamic canvas pages (`agent_pages`).
- **`python_kernel.py`**: Sandboxed Python script execution runner with mandatory Human-In-The-Loop approval dialogues before execution.
- **`routers/workspaces.py`**: Monaco Editor workspace server supporting file trees, zip export, Pyodide Python WASM in-browser execution, and Ollama coding assistant pairing.

### E. Background Workers & Operations (`src/kb_web/worker.py`, `src/kb_web/gotify.py`)
- **`worker.py`**: Central engine running an async loop with independent scheduling intervals per job (`auto_curate`, `taxonomy_sort`, `auto_refetch`, etc.). Supports the "Pause Non-Core" mode to freeze all background tasks except core tagging and wiki generation.
- **`gotify.py`**: Dispatches real-time push notifications for critical events, refetch alerts, and errors.

