# User Feedback & Architecture Analysis

## 1. User Inquiry
- **Date**: 2026-10-22
- **Branch**: `feature/facts-display-and-taxonomy-population`
- **User Prompt**:
  > "factsvare being exported but where are they displayed? the taxonomy is also not populating either"

## 2. Root Cause Analysis

### A. Missing UI Exposure for Extracted Facts (`context_statements`)
1. **Background Extraction without UI Presentation**:
   - `FactExtractionPipeline` extracts atomic declarative context statements and saves them to `ContextStatementORM` in the `context_statements` table.
   - However, **no router endpoint or Jinja2 template** in the entire application renders these statements.
   - On the Article Profile page (`/article?url=...`, [`src/kb_web/templates/view_page.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html)), only Wiki, Raw Markdown, Chunk Embeddings, and Versions are rendered. Extracted facts are not queried or displayed.
   - There is no central interface to browse, filter by statement type (`fact`, `intent_mapping`, `negative_invariant`, `affordance`, `habit`, `preference`), evaluate, or review confidence and provenance.

### B. Why Taxonomy Was Not Populating
1. **Unregistered Entities during Ingestion/Extraction**:
   - In [`src/kb_web/context_mesh/pipeline.py`](file:///c:/src/kb-web/src/kb_web/context_mesh/pipeline.py), `TaxonomyClassifier.classify_article(...)` computed the 7-tier taxonomic coordinates (`TaxonomyPath`), but `TaxonomyEngine().register_entity(...)` was never called to persist the entity into `TaxonomyEntityORM` (`taxonomy_entities` table).
   - In the ingestion pipeline ([`src/kb_web/pipeline.py`](file:///c:/src/kb-web/src/kb_web/pipeline.py)), taxonomy registration was completely omitted.
2. **Decoupled Taxonomy UI**:
   - The `/taxonomy` route ([`src/kb_web/routers/taxonomy.py`](file:///c:/src/kb-web/src/kb_web/routers/taxonomy.py) and [`src/kb_web/templates/taxonomy.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/taxonomy.j2.html)) was exclusively reading from the legacy, deprecated `TaxonomyCategory` / `TaxonomyItem` tables from `taxonomy_state_machine.py`.
   - As a result, even when articles and facts are indexed, the `/taxonomy` page showed "Cold Start: 0 Categories".

## 3. Desired Solution
1. **Automatic Taxonomy Population**:
   - Automatically register taxonomy entities in `TaxonomyEngine` whenever an article, note, repo, or video is ingested or facts are extracted.
   - Provide a background sync tool / endpoint (`POST /api/taxonomy/sync-entities`) to instantly index all existing library pages into the 7-tier taxonomy.
2. **Article Profile Facts Section (`view_page.j2.html`)**:
   - Query and display extracted context statements on the article profile page with type badges, taxonomic layers, score ranks, and evaluation status.
   - Allow on-the-spot evaluation (Approve / Reject / Flag / Score) and on-demand fact re-extraction.
3. **Upgraded Taxonomy & Facts Explorer (`/taxonomy`)**:
   - Transform `/taxonomy` into a comprehensive 7-tier biological taxonomy & living context mesh browser.
   - Enable browsing nodes (Kingdom -> Phylum -> Class -> Order -> Family -> Genus -> Species) and viewing facts and library entities mapped to each coordinate.
   - Filter facts by statement type, layer level, and evaluation status.
