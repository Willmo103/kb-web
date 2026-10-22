# Implementation Plan - Facts Display & 7-Tier Taxonomy Population

## 1. Problem Statement
The user inquired:
> "factsvare being exported but where are they displayed? the taxonomy is also not populating either"

1. **Facts are extracted into `context_statements` table, but displayed nowhere in the UI**:
   - The Article Profile page ([`view_page.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html)) does not query or render extracted context statements (facts).
   - There is no central interface in the application to browse, filter by statement type (`fact`, `intent_mapping`, `negative_invariant`, `affordance`, `habit`, `preference`), or evaluate statements.
2. **Taxonomy is not populating**:
   - `TaxonomyClassifier` infers 7-tier coordinates (`TaxonomyPath`) during fact extraction, but never registers entities into `TaxonomyEntityORM` via `TaxonomyEngine().register_entity(...)`.
   - Ingestion pipelines ([`pipeline.py`](file:///c:/src/kb-web/src/kb_web/pipeline.py)) do not register taxonomy coordinates.
   - The `/taxonomy` page ([`taxonomy.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/taxonomy.j2.html)) only reads the deprecated `TaxonomyCategory` / `TaxonomyItem` table (which is cold-started at 0 categories), completely disconnected from the 7-tier biological taxonomy and context statements.

---

## 2. Proposed Architecture & Solution

### A. Automatic Taxonomy Entity Registration
1. In [`src/kb_web/context_mesh/pipeline.py`](file:///c:/src/kb-web/src/kb_web/context_mesh/pipeline.py):
   - In `extract_from_page(url, title, md_content, tags)`:
     ```python
     tax_path = TaxonomyClassifier.classify_article(url=url, title=title, tags=tags)
     # Automatically register entity in taxonomy_entities table
     TaxonomyEngine().register_entity(
         taxonomy=tax_path,
         physical_location=url,
         attributes={"title": title or url, "tags": tags or [], "source_type": "article"},
     )
     ```
2. In [`src/kb_web/pipeline.py`](file:///c:/src/kb-web/src/kb_web/pipeline.py):
   - In Stage 4b, ensure `TaxonomyEngine().register_entity(...)` is called for any ingested page, git repo, or video.
3. In [`src/kb_web/routers/taxonomy.py`](file:///c:/src/kb-web/src/kb_web/routers/taxonomy.py):
   - Add endpoint `POST /api/taxonomy/sync-entities` (and admin button) to scan all `FetchedPage` rows and populate `TaxonomyEntityORM` for all existing articles.

### B. Display Facts on Article Profile Page (`/article?url=...`)
1. In [`src/kb_web/routers/pages.py`](file:///c:/src/kb-web/src/kb_web/routers/pages.py):
   - In `view_page(url)`:
     Query `ContextStatementORM` where `source_uri == decoded_url`.
     Pass `context_statements` list and `taxonomy_entity` to `view_page.j2.html`.
2. In [`src/kb_web/templates/view_page.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html):
   - Add a dedicated **"Extracted Facts & Intent Mesh"** section/tab featuring:
     * Statement type pill badge with color coding:
       - `FACT`: Blue (`bg-blue-50 text-blue-700`)
       - `INTENT_MAPPING`: Purple (`bg-purple-50 text-purple-700`)
       - `NEGATIVE_INVARIANT`: Red (`bg-rose-50 text-rose-700`)
       - `AFFORDANCE`: Emerald (`bg-emerald-50 text-emerald-700`)
       - `HABIT`: Amber (`bg-amber-50 text-amber-700`)
       - `PREFERENCE`: Cyan (`bg-cyan-50 text-cyan-700`)
     * 7-tier biological taxonomy coordinates path (e.g., `knowledge / text / human_read / github_com / ...`).
     * Taxonomic layer depth badge (`SPECIES`, `GENUS`, `ORDER`, etc.).
     * Interactive evaluation buttons (`Approve`, `Flag`, `Reject`) and score rating.
     * "Extract Facts Now" button calling on-demand extraction if zero statements are present.

### C. Upgraded Taxonomy & Facts Explorer (`/taxonomy`)
1. In [`src/kb_web/routers/taxonomy.py`](file:///c:/src/kb-web/src/kb_web/routers/taxonomy.py):
   - Update `GET /taxonomy` to support both:
     * **7-Tier Biological Taxonomy & Context Mesh** (primary modern view).
     * **Legacy Category Tree** (secondary/legacy tab).
   - Add API routes:
     * `GET /api/context-mesh/statements`: Filter statements by `url`, `statement_type`, `layer_level`, `eval_status`, `query`, or `limit`.
     * `POST /api/context-mesh/statements/{id}/evaluate`: Update evaluation status (`approved`, `flagged`, `rejected`) and feedback.
     * `POST /api/context-mesh/extract-now`: Trigger on-demand fact extraction for a URL.
     * `GET /api/taxonomy/7tier/tree`: Hierarchical 7-tier tree structure populated from `taxonomy_entities` and `context_statements`.
2. In [`src/kb_web/templates/taxonomy.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/taxonomy.j2.html):
   - Build dual-view or enhanced workspace:
     * **Tab 1: 7-Tier Biological Ontology & Living Facts**:
       Left pane: Tree of Kingdom -> Phylum -> Class -> Order -> Family.
       Right pane: Selected node's entities and extracted atomic context statements with type filters and evaluation controls.
     * **Tab 2: Legacy Category State Machine** (preserved for backward compatibility).
     * Action button: "Sync Taxonomy from Library" (`/api/taxonomy/sync-entities`).

---

## 3. Verification & Testing
- Unit tests in `tests/test_taxonomy_and_facts_display.py`:
  * Entity registration in `TaxonomyEngine` when `extract_from_page` runs.
  * `POST /api/taxonomy/sync-entities` correctly populates `taxonomy_entities` from existing pages.
  * `GET /api/context-mesh/statements` queries statements with type, layer, and status filters.
  * `POST /api/context-mesh/statements/{id}/evaluate` updates evaluation status and score.
  * `GET /article?url=...` template renders context statements when present.
  * `GET /taxonomy` renders 7-tier taxonomy tree and entities.
- Pre-commit verification:
  * `uv run pytest tests/test_taxonomy_and_facts_display.py`
  * `uv run pytest`
  * `uv run python build.py`
- Self-documentation:
  * Update `CHANGELOG.md` under `[0.5.11]`
