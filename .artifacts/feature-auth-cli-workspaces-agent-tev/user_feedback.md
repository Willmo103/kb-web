# User Feedback - Authentication Hardening, CLI Restart, Workspace Versioning & Agent Tools with Tev1

## User Request Summary
- **Date**: 2026-10-02
- **Context & Feedback**:
  1. **Authentication & Server Recovery after Power Loss**:
     - A power loss state at the user's house caused the server to reboot.
     - Upon spinning back up, the authentication mechanism broke and the user was unable to log back in until returning home and running a restart script.
     - Requested: A remote restart command from the CLI (`kb-web-cli restart`) to cleanly reboot/reload the service.
     - Requested: Investigate and harden the authentication mechanism against sudden restarts/power loss so credentials and session states remain consistent even if the database is in recovery or slow to start.
  2. **CLI Authentication Failure (401 Unauthorized)**:
     - Following authentication hardening, `kb-web-cli` stopped working with `Error 401: {"detail":"Unauthorized: Authentication required."}` when submitting requests like `kb-web-cli import 'https://test.com/some-page'`.
     - Root cause: The global authentication middleware only checked the hardcoded server API key (`KB_API_KEY`) and session cookies, failing to validate registered client CLI API keys stored in the database (`CliApiKey` / `cli_api_keys`).
  3. **Coding REPL / Workspace Additions**:
     - Workspaces are morphing into live-editable repositories for scripts (e.g. `pythonrc.py`, PowerShell Profiles, multi-device scratch pads).
     - Sub-class / feature for workspace version control: track file versions and create tagged, immutable snapshots of workspace files at a given state.
     - Frozen workspace versions should be viewable as Knowledge Base articles.
  4. **Workspace Coding Agent Tools**:
     - Enhance the workspace coding agent with legitimate tools:
       - Create files by choice with names and optional annotations.
       - Read sections of files instead of piping entire workspace content into the system prompt.
       - Edit files via target/replacement tools.
     - Implement a terminal harness for interactive coding agent pairing directly from the CLI.
  5. **Incorporate `tev1` Decision Agent**:
     - Incorporate the `tev1` decision model (`tev1:latest` / `tev1:4b`).
     - Use `ollama.systemone(...)` directly through the project's `ollama` dependency (updated to `>=0.6.3`) without requiring external SDK packages.
     - Use `tev1` in the agent harness for fast, structured decision making, classification, and gating.

---

## Turn 2 - Agentic RAG Report Generator & Elimination of File Chat
- **Date**: 2026-10-02
- **Context & Feedback**:
  1. **Eliminate "Chat with a File" Feature**:
     - The user noted that single-article chat ("chat with a file" drawer on `view_page.j2.html` / `/api/conversations/chat`) was poorly conceived and requested its complete elimination.
  2. **Agentic RAG Report Generator**:
     - Instead of chatting with a single file, the user wants a powerful RAG report generator where they can enter a query or question and trigger an agentic multi-sub-agent RAG workflow:
       - **Tag-Searching Sub-Agent**: explores article and note tags matching or related to the user's research topic.
       - **Query-RAG Sub-Agent**: formulates targeted search queries, embeds them, and executes vector similarity search against Qdrant / `ChunkEmbedding`.
       - **Pure Text Search Sub-Agent**: conducts lexical / full-text search against article and note content, titles, and descriptions.
       - **Tev1 Decision Scoring Sub-Agent (up to 64 questions per turn)**: uses `ollama.systemone` with model `tev1` to evaluate candidate articles/chunks against the user's research purpose using multi-criteria questions (relevance, code actionability, technical depth, freshness, information density, etc.) to vet and rank candidates.
       - **Synthesis & Report Compiler Agent**: aggregates the top-ranked vetted candidates into a comprehensive Markdown research report with executive summary, answers, code, and source links.
  3. **Visual Modeling**:
     - The user requested that the architecture and workflow be modeled in a Mermaid diagram and presented in the implementation plan.
  4. **UAT Tester Fix - Workspace Agent Welcome Card**:
     - The UAT tester noted that the initial welcome card in the workspace IDE agent panel still displayed the legacy static text ("Tip: I automatically detect ```file:path/to/file.ext``` blocks with instant Apply to Workspace buttons").
     - Requested: Update the welcome card to explicitly highlight the newly implemented agent tools (`create_file`, `read_file`, `edit_file`), `tev1` decision gating, and the CLI terminal pairing command.

---

## Turn 3 - Site-Wide Dark Mode Toggle (Muted Neon / Cyber Retro Dark)
- **Date**: 2026-10-03
- **Context & Feedback**:
  1. **Site-Wide Dark Mode Toggle**:
     - User requested a site-wide `dark` mode toggle across the entire application.
     - Placed in the base HTML template (`base.j2.html`) so it is globally available in the navigation header across all pages.
  2. **Aesthetic Direction**:
     - High-contrast neon, but muted/dulled (e.g. cyber/retro dark aesthetic: deep obsidian/slate backgrounds `#0b0f19` / `#0f172a`, muted neon cyan/teal/violet/amber accents, borders with subtle glowing/neon tint `#1e293b`/`#334155`, high contrast crisp text `#f8fafc` / `#e2e8f0`).
  3. **Toggle UI Component**:
     - Moon/Sun circle toggle button ("Moon/Sun circle toggle. I think its cute").
     - Smooth rotation and switch transition between Sun (☀️) and Moon (🌙).
     - Persists theme choice across page loads via `localStorage` (with immediate inline script in `<head>` to prevent flash of light theme / FOUC).

---

## Turn 5 - Notes Tagging & URL Filtering, Autonomous Taxonomy State Machine, and Agent Memory Message Board
- **Date**: 2026-10-03
- **Context & Feedback**:
  1. **Notes Ingestion Pipeline (Tagging, Titling, URL Link Extraction)**:
     - Apply automated tagging, titling, and URL link extraction (strictly filtered for actual valid URLs) to Notes (`Note`).
     - Skip wiki generation for notes (preserving the user's original note text while enriching metadata).
  2. **Autonomous Category Taxonomy State Machine**:
     - Create an agentic background indexing and re-indexing job using the decision model (`tev1`) and LLM.
     - Iterates through existing articles, notes, videos in the database and classifies them into an autonomous hierarchical category tree.
     - **Cold Start & Evolution**: Starts with zero categories. The first category is generated by the LLM from the first item.
     - **Decision Gating**: For subsequent items, the decision model determines whether the item fits an existing category or if a new category is needed.
     - If it fits, it is assigned. If not, the LLM creates a new category based on the item and existing categories.
     - **Distinction from Collections**: These `categories` are completely independent of manual user `collections`.
     - **Hierarchical Sub-Categorization (10-Item Threshold)**:
       - When any category reaches 10 items, an inner partitioning loop triggers: at least half (>=5) of its items must be split into a child sub-category.
       - Adding new items to any category is paused until this inner loop completes.
       - Tree-structured presentation for categories with sub-categories during classification.
       - State machine must be modeled with a Mermaid state diagram in the implementation plan.
     - **Category Wiki**:
       - Each category possesses a `doc` attribute (category wiki) synthesized by the LLM and updated whenever an item is added.
     - **New Ingestions**:
       - New articles, videos, notes, or workspace snapshots trigger this classification process.
     - The user requested input and discussion over the exact questions and states for each step.
  3. **Cross-Agent Memory / Message Board Tool**:
     - Provide a persistent shared agent memory tool / message board that agents across all interactions and background jobs are required to consult and update.
  4. **User Design Decisions Confirmed**:
     - **Decision Question Format**: Top-down choice question where `tev1` chooses among active category tree branches or `new_category`, followed by a `noul` confidence check.
     - **10-Item Partitioning Strategy**: When a category reaches 10 items, partition all 10 items into 2 or more distinct child sub-categories, keeping the parent category as a pure group container.
     - **Agent Memory UI**: Dedicated top-level navigation item ("Agent Board" / `/agents/board`) with real-time logs, channel filters, and search.

---

## Turn 6 - Implementation Plan Presentation Rule, Notes Nested Tree, Meaningful Domain Names & Containment, Prior 6-Class Gating, and Policy Enforcement
- **Date**: 2026-10-03
- **Context & Feedback**:
  1. **Implementation Plan Presentation Rule**:
     - User requested a strict rule added that whenever implementation plans are saved in `.artifacts/`, the agent MUST ALWAYS present the plan directly to the user in the response before proceeding to execute or ask for sign-off.
     - Codified in `GEMINI.md` under Chat Turn Instructions.
  2. **Photo 1 - Notes Sidebar Nested Folder Tree Hierarchy**:
     - In Photo 1, note folders with slash paths (e.g. `dev_notes/TESTS`, `dev_notes/SystemMessages`, `dev_notes/agent skills/uv skill`, `dev_notes/agent skills`) displayed as flat folder entries all on the same level.
     - Requested: Display notes as a true recursive nested directory tree where parent folders contain child subfolders and files with collapsible tree navigation.
  3. **Photo 2 - Meaningful Domain Naming & Sub-Category Containment**:
     - In Photo 2, taxonomy categories were defaulting to generic labels like `Domain 10`, `Domain 11`, `Domain 12` covering items like "Date Ideas".
     - Requested: The classification pipeline must strictly instruct agents and fallback synthesizers to name domains with meaningful, authoritative names (e.g. "Personal Lifestyle & Dating", "DevOps & Cloud Infrastructure"). Numeric placeholders and generic labels ("Domain X") are strictly prohibited.
     - Sub-categories and reclassification must remain strictly **INSIDE** the original chosen domain (i.e. child sub-categories are thematic specializations within the parent domain boundary).
  4. **"Fits at All" Decision Gate**:
     - Add an explicit decision gate evaluating whether an incoming item fits any existing category *at all* before adding to any category or collection.
     - If not, cleanly branch to create a new meaningful domain category.
  5. **Prior 6-Class Item Classification Gate**:
     - Run a prior classification check categorizing incoming items into 6 distinct classes:
       - `Personal`: Personal notes, personal information, journal thoughts, date ideas.
       - `Documentation`: Code resources, reference documents, technical manuals.
       - `Notes`: General markdown notes that are not personal and not documentation or code.
       - `Articles`: Web articles, news essays, YouTube video transcripts.
       - `Source Code`: Flattened code, workspace snapshots, scripts.
       - `Unclassifiable`: Catchall for corrupted, unreadable, or unclassifiable items.
     - The determined item class is stored on `TaxonomyItem.item_class` and fed into subsequent decision gates.
  6. **Policy Directives in Decision Model State**:
     - Decision models perform significantly better when explicit "policy" directives are provided in the `state` object.
     - Enforce structured policy directives in the `state` object for all `client.systemone` decision steps (thematic purity, domain containment, non-generic naming, class boundary rules).
  7. **Rollback Latest Migrations & Purge Test Classification Information**:
     - The user requested rolling back the latest migrations to remove the test classification information created during testing in the database.
     - Add the migration script for revision `f92d84291a25` (`f92d84291a25_add_taxonomy_classification.py`) linking `e81c74291a23` -> `f92d84291a25` with full `upgrade()` and `downgrade()` logic.
     - Execute the downgrade/rollback to remove the classification records and tables from the test/dev database, restoring a clean state for the new pipeline.




