# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
