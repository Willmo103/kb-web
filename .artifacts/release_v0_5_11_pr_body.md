## Release v0.5.11 (Staging Production -> Master)

This pull request merges the verified `production` baseline into `master` following the repository tiered release lifecycle.

### Overview of Included Enhancements & Fixes (v0.5.11)

#### 1. Extracted Facts & Context Mesh UI Display
- **Article Profile Integration (`routers/pages.py`, `templates/view_page.j2.html`)**:
  - Exposed extracted atomic facts and context statements (`ContextStatementORM`) on the Article Profile view.
  - Added dedicated "Extracted Facts & Intent Mesh" card featuring color-coded statement type badges (`Fact` [blue], `Intent` [purple], `Invariant` [rose], `Affordance` [emerald], `Habit` [amber], `Preference` [cyan]), taxonomic layer level badges (`SPECIES`, `GENUS`, etc.), canonical taxonomy coordinates path, review status indicators (`approved`, `flagged`, `rejected`, `unreviewed`), and confidence score ranks.
  - Added interactive one-click evaluation controls (`👍 Approve`, `⚠️ Flag`, `👎 Reject`) with dynamic asynchronous feedback updates via `POST /api/context-mesh/statements/{id}/evaluate`.
  - Added on-demand `⚡ Extract Facts Now` action button calling `POST /api/context-mesh/extract-now`.

#### 2. 7-Tier Biological Taxonomy Auto-Population & Living Facts Mesh Explorer
- **Automatic Entity Registration (`pipeline.py`, `context_mesh/pipeline.py`, `taxonomy/engine.py`)**:
  - Automated taxonomy coordinate registration during page ingestion and fact extraction via `TaxonomyEngine().register_entity(...)`.
  - Added `TaxonomyEngine.sync_entities_from_library(limit)` and endpoint `POST /api/taxonomy/sync-entities` to scan existing articles and notes and infer 7-tier coordinates.
  - Built `TaxonomyEngine.get_7tier_tree()` and endpoint `GET /api/taxonomy/7tier/tree` compiling a hierarchical 7-tier biological tree of Kingdoms, Phyla, Classes, Orders, and Families with real-time entity and statement counts.
- **Modernized `/taxonomy` Interface (`templates/taxonomy.j2.html`, `routers/taxonomy.py`)**:
  - **Tab 1: 7-Tier Biological Ontology & Living Facts Explorer**: Interactive hierarchical tree navigator from Kingdom down to Family, breadcrumb coordinate display, live atomic context facts mesh explorer with statement type filters and search, and mapped physical entity cards with direct article profile links.
  - **Tab 2: Autonomous Category Clusters (Legacy)**: Preserved category tree state machine, clustering crawler, and living category wiki doc reader for full backward compatibility.
  - Added prominent `⚡ Sync Taxonomy from Library` button to populate the 7-tier hierarchy with one click.
  - Backfilled **331 library items** (237 pages + 94 notes) into 7-tier biological hierarchy.

#### 3. AI Wiki Versioning, Model Attribution & Historical Restorations
- Added `WikiVersion` ORM model (`url`, `title`, `wiki_content`, `model_name`, `steering_instructions`, `created_at`) with native foreign key `ON DELETE CASCADE` linked to `fetched_pages.url`.
- Added `wiki_model` column to `FetchedPage` and pre-aggregated database view `vw_page_cards`.
- Automatically archive previous AI wiki markdown into `WikiVersion` whenever a page is regenerated (`POST /admin/regenerate/wiki`) or re-fetched (`POST /admin/refetch/page`).
- Added `POST /admin/wiki/restore` endpoint allowing instantaneous restoration of historical wiki versions with reciprocal archival of active content.
- Display generating model badge (`🤖 Model: <model_name>`) and historical version selector pills directly in the article wiki header with one-click restoration preview.

#### 4. On-the-Fly Model Selection & Custom Steering Directives
- Replaced immediate wiki regeneration with an interactive modal form allowing on-the-fly selection of any locally installed Ollama completion model.
- Added optional steering instructions textarea allowing custom prompts (e.g., technical architecture focus, bulleted executive summaries, mathematical proof retention) to be dynamically appended to system curation prompts.

#### 5. Pseudo-Scheme URL Resolution & Universal Navigation Dispatcher
- Implemented `resolve_entity_url(url)` resolving synthetic internal schemes into clean internal routes: `note://` to Monaco Notes editor (`/notes/edit?url=...`), `workspace://` to workspace IDE (`/workspaces/{id}`), external `http/https` to original targets, and unrecognized schemes to non-clickable badges.
- Added universal `GET /open?url=...` redirect dispatcher routing synthetic and external schemes server-side.
- Added global client-side link click interceptor in `base.j2.html` seamlessly rerouting internal markdown and page links to `/open?url=...` without browser handler errors.

#### 6. Autonomous Worker Target Execution Tracking & Loop Prevention
- Implemented persistent target-level execution tracking model `WorkerJobExecution` with composite index `(job_id, target_id)`.
- Added in-memory deduplication tracking `self._recent_targets[job_id]` in `AutonomousWorker` preventing duplicate execution within the same scheduler loop.
- Automatically logs `status="skipped"` with `items_count=0` whenever an extraction or curation pass produces zero items, permanently preventing infinite loops on un-extractable targets.
- Added management endpoints `GET /api/jobs/{job_id}/executions` and `POST /api/jobs/{job_id}/executions/clear`.

#### 7. Embedding Model Unification
- Unified embedding model resolution across vector indexing, query retrieval, and configuration to prevent dimensionality mismatches.

---

### Verification & Testing
- Full build pipeline verification (`uv run python build.py`): **278/278 passed**.
- Template syntax & structural completeness (`verify_ui_templates.py`): **29/29 verified with 0 warnings**.
- VCS testing artifacts: `uat/reports/uat_report_facts_display_and_taxonomy_population_20261022_081152.md`.
