# kb-web Technical Documentation

Welcome to the comprehensive technical documentation for **`kb-web`**, the central web ingestion portal, PWA target, Chrome extension endpoint, autonomous agent workspace, and knowledge curation platform in the `kb` (Knowledge-Base) suite.

---

## Documentation Navigation Matrix

| Section | Document | Description |
|---|---|---|
| **Architecture** | [`docs/architecture/overview.md`](architecture/overview.md) | High-level system architecture, subsystem topologies, and 3-tier release lifecycle |
| **Architecture** | [`docs/architecture/database_schema.md`](architecture/database_schema.md) | Exhaustive SQLAlchemy ORM models, indexes, relations, and `vw_page_cards` view |
| **Architecture** | [`docs/architecture/codebase_map.md`](architecture/codebase_map.md) | Complete file-by-file module mapping across all 68 Python source files (34,130 LOC) |
| **Architecture** | [`docs/architecture/dangling_code_audit.md`](architecture/dangling_code_audit.md) | Deep audit of legacy, deprecated, and dead code pathways suitable for pruning and archival |
| **Subsystems** | [`docs/modules/core_runtime.md`](modules/core_runtime.md) | Server initialization, configuration persistence, security hardening, database pooling |
| **Subsystems** | [`docs/modules/ingestion_pipelines.md`](modules/ingestion_pipelines.md) | Web ingestion, shallow git cloning, YouTube audio/metadata extraction, HTML stripping |
| **Subsystems** | [`docs/modules/taxonomy_and_context_mesh.md`](modules/taxonomy_and_context_mesh.md) | Steered Knowledge Tree, Topic Governance, Atomic Context Mesh, Personal VK Context |
| **Subsystems** | [`docs/modules/agents_and_rag.md`](modules/agents_and_rag.md) | Agentic RAG, Tev1 decision gating, Custom Topic Agents, HITL Python Kernel, Workspaces |
| **Subsystems** | [`docs/modules/background_workers.md`](modules/background_workers.md) | Autonomous worker engine, decoupled background jobs registry, dynamic scheduling, Gotify alerts |
| **Subsystems** | [`docs/modules/api_and_routers.md`](modules/api_and_routers.md) | Comprehensive REST and HTML route directory across all 23 FastAPI routers in `routers/` |
| **Subsystems** | [`docs/modules/client_and_integrations.md`](modules/client_and_integrations.md) | Typer CLI commander (`kb-web-cli`), Model Context Protocol (MCP) server, Chrome extension |
| **Subsystems** | [`docs/modules/evals_studio.md`](modules/evals_studio.md) | Model Evaluation Studio, multi-model prompt matrix, comparative calibration, prompt promotion |

---

## System Overview & Primary Capabilities

`kb-web` bridges raw web content, local AI models, and human knowledge workflows:

1. **Multi-Source Ingestion**: Ingests articles, markdown vaults, remote git repositories, YouTube transcripts, and browser extension bookmarks.
2. **AI Wiki Generation & Tag Curation**: Transforms dirty HTML scrapes into concise, structured Markdown wikis using Ollama LLMs with automatic deduplication and keyword tagging.
3. **Hybrid Semantic & Vector Retrieval**: Dual-indices content into PostgreSQL (`pgvector`) and Qdrant vector databases using unified EmbeddingGemma representations.
4. **Autonomous Agentic RAG & Decision Calibration**: Multi-agent retrieval pipelines vetted by native `ollama.systemone` `tev1` decision matrices (up to 64 questions per turn) compiling publication-grade research reports.
5. **Steered Knowledge Tree & Equal-Node Graph**: User-governed hierarchical file tree beyond rigid biological tiers, supporting arbitrary folder layers, qualification gating criteria, domain blacklists, and atomic bulk relocation of items and context mesh statements.
6. **Living Topic Wikis & Custom Autonomous Agents**: Specialized autonomous topic agents with private task queues, working memory observations, and living wiki pages with logical paths and citations.
7. **Human-In-The-Loop (HITL) Execution**: Gated Python kernel for agents executing in the local virtual environment with mandatory human review before execution.
8. **Decoupled Background Job Registry**: Autonomous worker running background jobs (auto-curation, tagging, synthetic QA, RAG evaluations, crawler, fact extraction, lifecycle re-fetch) with independent scheduling intervals, individual model bindings, and one-click "Core Only" suspension controls.
9. **Full Authentication & Enterprise Security**: Session cookie and API key guards across all endpoints, constant-time verification (`hmac.compare_digest`), ZipSlip path traversal prevention, CSP headers, stored HTML/Markdown sanitization (`nh3`), and default credential alerts.
10. **In-Browser Workspaces & Python WASM**: Multi-file coding IDE with Monaco Editor, Pyodide Python WASM execution, sandbox web previews, and ephemeral LLM coding assistants.

---

## Reading Guide & Development Workflows

- **New Contributors**: Start with [`docs/architecture/overview.md`](architecture/overview.md) to understand process boundaries and the 3-tier branch architecture (`development` -> `production` -> `master`), followed by [`docs/architecture/codebase_map.md`](architecture/codebase_map.md) to locate specific subsystems.
- **Database Developers**: Review [`docs/architecture/database_schema.md`](architecture/database_schema.md) for table definitions, composite indexes, and view query structures.
- **Refactoring & Cleanup**: Consult [`docs/architecture/dangling_code_audit.md`](architecture/dangling_code_audit.md) before removing or modifying legacy pathways (e.g. SQLite legacy fallbacks or the old Category Clusters state machine).
- **API Consumers**: Reference [`docs/modules/api_and_routers.md`](modules/api_and_routers.md) for exhaustive request/response schemas and authentication requirements across all 23 routers.
