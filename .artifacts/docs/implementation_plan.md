# Implementation Plan: Comprehensive `./docs` Architecture, Codebase Mapping & Dead Code Audit

Flesh out the `./docs` directory into an exhaustive, production-grade technical documentation library using historical artifacts and deep static codebase analysis. Map every module, subsystem, API route, and background job across the entire application, and conduct a systematic audit of dangling and deprecated code suitable for pruning and archival.

---

## 1. Objectives & Scope

1. **Branch Baseline**:
   - Working on dedicated branch `docs` branched off `master`.
2. **Exhaustive Technical Documentation (`./docs`)**:
   - Synthesize knowledge from all past sprint artifacts in `.artifacts/` (v5 through v15) and live code implementations in `src/kb_web/`.
   - Document architecture, subsystems, data models, pipelines, background jobs, and agent protocols.
3. **Comprehensive Codebase Mapping**:
   - Produce a file-by-file directory map covering all 67+ Python files, template components, and script utilities.
   - Document module responsibilities, class/function hierarchies, internal/external dependencies, and runtime data flows.
4. **Dangling, Legacy & Dead Code Audit**:
   - Identify obsolete or redundant code paths (e.g. SQLite legacy pathways being superseded by PostgreSQL, legacy `taxonomy_state_machine.py` Category Clusters vs modern `taxonomy/steered_tree.py`, deprecated router endpoints, orphaned models).
   - Classify findings with risk assessments and recommended archival strategies.

---

## 2. Target Documentation Structure in `./docs`

```
docs/
├── README.md                                # Documentation portal, high-level index, sitemap
├── architecture/
│   ├── overview.md                          # End-to-end architecture, lifecycle tiers, component interactions
│   ├── database_schema.md                   # Updated exhaustive schema reference (SQLAlchemy ORM & Postgres views)
│   ├── codebase_map.md                      # Complete file-by-file module map (67+ files, LOC, symbols, deps)
│   └── dangling_code_audit.md               # In-depth dead code, legacy path, and archival candidate analysis
└── modules/
    ├── core_runtime.md                      # base.py, server.py, config.py, models_orm.py, utils.py, db.py
    ├── ingestion_pipelines.md               # pipeline.py, crawler.py, html_cleaner.py, repo_importer.py, video_manager.py
    ├── taxonomy_and_context_mesh.md         # taxonomy/ (engine, steered_tree, models) & context_mesh/ (pipeline, store, etc.)
    ├── agents_and_rag.md                    # rag_agent.py, custom_agent_engine.py, python_kernel.py, workspace_agent.py
    ├── background_workers.md                # worker.py (job registry, dynamic intervals, pause controls), gotify.py
    ├── api_and_routers.md                   # Exhaustive route directory covering all 23 routers in routers/
    ├── client_and_integrations.md           # CLI commander (cli.py), MCP protocol (mcp_server.py), browser extension
    └── evals_studio.md                      # Model Evaluation Studio, comparative matrices, prompt promotion
```

---

## 3. Detailed Document Outlines

### A. `docs/README.md`
- System overview, navigation matrix, quick reference by domain (Ingestion, AI Curation, Search, Taxonomy, Agents).
- High-level directory structure and reading guide for developers and agents.

### B. `docs/architecture/overview.md`
- Architecture topology: FastAPI async server, PostgreSQL relational store, pgvector / Qdrant vector databases, Ollama LLM / embedding inference, Monaco Editor workspaces, Pyodide WASM kernel.
- Ingestion lifecycle: Web PWA / Browser Extension / CLI -> Ingestion Pipeline -> HTML Cleaner -> AI Markdown Wiki -> Taxonomy Classification -> Context Mesh Statement Extraction -> Vector Chunking.
- 3-Tier Git release architecture (`development` -> `production` -> `master`).

### C. `docs/architecture/database_schema.md`
- Complete table inventory: `fetched_pages`, `page_versions`, `notes`, `collections`, `taxonomy_topics`, `taxonomy_entities`, `context_statements`, `agent_observations`, `topic_wiki_pages`, `agent_pages`, `agent_python_approvals`, `worker_job_executions`, `setting_ollama`, `setting_external`, etc.
- Pre-aggregated view `vw_page_cards` schema and query optimization.
- Foreign key constraints, cascade rules, and index strategies.

### D. `docs/architecture/codebase_map.md`
- Exhaustive table of all 67+ Python source files in `src/kb_web/`:
  - Path & Line Count (LOC)
  - Core Responsibility & Subsystem
  - Primary Classes & Functions
  - Inbound & Outbound Dependencies
  - Key Invariants & Error Handling Principles

### E. `docs/architecture/dangling_code_audit.md`
- Systematic analysis of:
  - **SQLite Legacy Pathways**: `db_migrate_sqlite.py`, legacy SQLite fallbacks across `config.py` and `base.py` after PostgreSQL unification.
  - **Legacy Category Clusters (`taxonomy_state_machine.py`)**: The legacy unsupervised cluster state machine (55KB) versus the modern user-steered knowledge tree (`taxonomy/steered_tree.py` and `engine.py`).
  - **Unreferenced Routes & Deprecated Endpoints**: Endpoints superseded by new unified APIs.
  - **Redundant Helper Utilities**: Duplicate string manipulation, URL parsing, or embedding normalization routines across `utils.py` and module-specific files.
  - **Recommended Archival Plan**: Specific files and blocks that can be safely archived into an `archive/` directory or pruned with zero risk to current functionality.

### F. `docs/modules/` (Subsystem Deep Dives)
- Dedicated reference guides for each major subsystem covering internals, configuration parameters exposed in `/admin`, sequence flows, and error recovery behaviors.

---

## 4. Execution Steps

1. Create feedback artifact (`.artifacts/docs/user_feedback.md`) and implementation plan (`.artifacts/docs/implementation_plan.md`).
2. Present plan to the user for confirmation.
3. Conduct static analysis of all source files and past artifacts to extract accurate metrics, signatures, and dead code indicators.
4. Author all 10 documentation documents in `docs/architecture/` and `docs/modules/`.
5. Verify document integrity, Markdown links, and formatting.
6. Run pre-commit checks (`uv run python build.py` / `uv run pytest`) to ensure documentation changes preserve test stability.
7. Commit and push the `docs` branch to `origin/docs`.

