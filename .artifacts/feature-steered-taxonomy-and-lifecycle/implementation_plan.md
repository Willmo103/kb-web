# Implementation Plan: Steered Taxonomy Tree, Gating Questions, Lifecycle Automation & Personal VK Layer

**Branch**: `feature/steered-taxonomy-and-lifecycle`  
**Target Baseline**: `development`  
**Related Requirements**: User-guided taxonomy routing, frozen tree governance, per-node gating questions, domain/source blacklisting, auto-freeze/auto-refetch lifecycle, taxonomy reset/nuke, non-core worker pause ("Core Only" preset), and nested personal VK context layer.

---

## 1. Problem Statement & Architecture Vision

Currently, `src/kb_web/taxonomy/engine.py` prompts the LLM with an open-ended prompt to invent arbitrary `topic` and `sub_topic` strings (`"Fishing/Ultralight"`, `"Activism/Removal-Efforts"`). This leads to unconstrained hallucinations that disregard existing structure.

This implementation provides:
1. **Steered Taxonomy Tree Structure (`SteeredTaxonomyTree`)**:
   - A configurable, user-curated hierarchical tree schema where nodes define:
     - `name`: Token identifier
     - `level`: `kingdom` | `phylum` | `class` | `order` | `family` | `genus` | `species`
     - `is_frozen`: Boolean flag preventing automatic creation of unauthorized branches
     - `gating_questions`: List of explicit qualification questions
     - `blacklisted_domains`: List of forbidden domain patterns (e.g. `youtube.com`, `reddit.com`)
     - `lifecycle_action`: `"none"` | `"freeze"` | `"refetch"`
     - `refetch_interval_hours`: Scheduled re-fetch interval (e.g., 24, 72, 168 hours)
     - `children`: Nested child nodes
2. **Layer-by-Layer Hierarchical Guided Decision Classifier (`SteeredHierarchicalClassifier`)**:
   - Layer 1 (Kingdom): Presents candidate root choices filtered by blacklists. Evaluates gating questions via Ollama choice/decision gating.
   - Layer 2 (Phylum): Passes down only the valid children of the selected Kingdom. Evaluates gating questions.
   - Layer 3 (Class): Passes down only valid children of the selected Phylum.
   - If content fails gating or matches a blacklisted domain, it is routed to an unassigned/review queue with explicit diagnostic audit notes.
3. **Taxonomy Nuke & Reset Endpoint (`POST /api/taxonomy/nuke`)**:
   - Atomically wipes all taxonomy entities (`TaxonomyEntityORM`), taxonomy item associations (`TaxonomyItem`), and resets page topics (`FetchedPage.topic = None, sub_topic = None, topic_status = 'unassigned'`).
4. **Autonomous Worker Granular Control ("Core Only" Preset)**:
   - Introduces a one-click `/api/jobs/pause-non-core` and `/api/jobs/resume-all` control.
   - Suspends `topic_assignment`, `embedding_refresh`, `synthetic_qa`, `rag_eval`, `link_crawler`, and `fact_extraction`.
   - Keeps core features active and running: **AI wiki curation** (`wiki_curation`) and **tagging** (`tag_curation`).
5. **Content Lifecycle Engine & Gotify Alerting**:
   - Automatically sets `FetchedPage.is_frozen = 1` for nodes marked with `lifecycle_action: "freeze"`.
   - Schedules and performs periodic re-fetches for nodes marked with `lifecycle_action: "refetch"`, updating page snapshots and dispatching formatted Gotify push alerts with article coordinates.
6. **Curated Nested Personal VK (Value-Knowledge) Context Layer**:
   - Dedicated schema and CRUD endpoints (`GET/PUT /api/context-mesh/personal-vk`).
   - Injected into `SubconsciousContextInjector` as `<personal_values_context>`, grounding both agent interactions and taxonomy decisions in the user's interests, values, and principles.

---

## 2. Proposed Changes & Technical Architecture

### Component 1: Steered Taxonomy Models & Storage
- **File**: `src/kb_web/taxonomy/steered_tree.py`
  - `SteeredTaxonomyNode`: Pydantic model with fields:
    - `id`: str
    - `name`: str
    - `level`: `TaxonomyLevel` (kingdom, phylum, class, etc.)
    - `description`: Optional[str]
    - `is_frozen`: bool = False
    - `gating_questions`: List[str] = Field(default_factory=list)
    - `blacklisted_domains`: List[str] = Field(default_factory=list)
    - `lifecycle_action`: Literal["none", "freeze", "refetch"] = "none"
    - `refetch_interval_hours`: Optional[int] = None
    - `children`: List[SteeredTaxonomyNode] = Field(default_factory=list)
  - `SteeredTaxonomyTreeManager`:
    - Loads/saves from `~/.kb/steered_taxonomy_tree.json` and database fallback `SettingExternal`.
    - Provides default seeding matching existing standard topics (Software Documentation, Reference, Resource, News, Hobby/Leisure, Blogpost/Article).
    - Methods: `get_tree()`, `save_tree()`, `find_node()`, `get_valid_children()`, `evaluate_domain_blacklist()`.

### Component 2: Layer-by-Layer Decision Engine
- **File**: `src/kb_web/taxonomy/engine.py` (extend and wire `SteeredHierarchicalClassifier`)
  - At each level:
    1. Filter out candidate nodes if source domain/host matches `blacklisted_domains`.
    2. Format candidate choices with description and gating questions.
    3. Query Ollama decision prompt (or `systemone` gating if available) asking:
       `Which candidate node best matches the item? Evaluate against gating questions: [Q1, Q2, ...]`.
    4. Validate response strictly matches one of the candidate IDs. If frozen and no candidate matches or gating fails, mark `topic_status = 'gating_failed'` and retain unassigned.
    5. Recurse down to child level using selected node.
  - Apply lifecycle rule on chosen leaf:
    - If `lifecycle_action == "freeze"`, set `page.is_frozen = 1`.
    - If `lifecycle_action == "refetch"`, mark for periodic refetching.

### Component 3: Taxonomy Nuke & Governance Endpoints
- **File**: `src/kb_web/routers/taxonomy.py` & `src/kb_web/taxonomy/service.py`
  - `POST /api/taxonomy/nuke`:
    - Query parameter `confirm=true`
    - Wipes `TaxonomyEntityORM`, `TaxonomyItem`, resets `FetchedPage` topic/sub_topic/status.
  - `GET /api/taxonomy/tree`: Returns current steered tree hierarchy with per-node gating, blacklists, and lifecycle rules.
  - `PUT /api/taxonomy/tree`: Updates steered tree schema.
  - `POST /api/taxonomy/classify-steered`: Triggers guided layer-by-layer classification for a given page or URL.

### Component 4: Worker Job Controls & Refetch Scheduler
- **File**: `src/kb_web/worker.py`
  - Add `pause_non_core_jobs()`: disables secondary jobs while keeping `wiki_curation` and `tag_curation` enabled.
  - Add `resume_all_jobs()`: restores standard job execution.
  - Add `register_job("lifecycle_refetch")`: checks pages due for refetching based on node `refetch_interval_hours`, executes refetch, updates page, and sends Gotify notification via `config.get_notifier().send()`.
- **File**: `src/kb_web/routers/jobs.py` (and Admin UI template)
  - `POST /api/jobs/pause-non-core`
  - `POST /api/jobs/resume-all`
  - Status indicators reflecting "Core Only" active mode.

### Component 5: Curated Nested Personal VK Context Layer
- **File**: `src/kb_web/context_mesh/personal_vk.py`
  - Model `PersonalVKContext`: nested arbitrary JSON structure with schema validation.
  - Storage in `~/.kb/personal_vk_context.json` & `SettingExternal`.
  - Service functions `get_personal_vk_context()` and `save_personal_vk_context(dict)`.
- **File**: `src/kb_web/routers/context_mesh.py`
  - `GET /api/context-mesh/personal-vk`
  - `PUT /api/context-mesh/personal-vk`
- **File**: `src/kb_web/context_mesh/injector.py`
  - Include `<personal_values_context>` in assembled prompt blocks.

---

## 3. Verification & Testing Strategy

1. **Unit & Integration Tests**:
   - `tests/test_steered_taxonomy_and_lifecycle.py`:
     - Test steered tree serialization, parsing, and persistence.
     - Test domain blacklisting preventing assignment to restricted nodes.
     - Test gating question evaluation and layer-by-layer choice filtering.
     - Test frozen tree enforcement: refusing unauthorized LLM branches.
     - Test taxonomy nuke endpoint: full deletion of entities and item coordinate reset.
     - Test worker "pause-non-core" vs "resume-all", ensuring wiki and tag jobs remain active.
     - Test content auto-freeze (`is_frozen = 1`) on designated nodes.
     - Test content auto-refetch with mocked Gotify notification.
     - Test personal VK nested JSON CRUD and prompt injection in `<personal_values_context>`.
2. **Pre-Commit Checks**:
   - `uv run pytest tests/test_steered_taxonomy_and_lifecycle.py`
   - `uv run pytest` (full regression test suite)
   - `uv run python build.py`
3. **UAT & UI Verification**:
   - Run `ui-component-uat-check` to verify Jinja2 templates and admin controls.
   - Run `generate-uat-testing-artifact` to generate logs in `uat/reports/`.
4. **Documentation**:
   - Update `CHANGELOG.md`, `README.md`, and `GEMINI.md`.

