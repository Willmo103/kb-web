# User Feedback: Biological Taxonomy & Subconscious Fact Extraction Mesh

## User Input (Turn 1)
- **Date**: 2026-10-21
- **Prompt**:
  > "check out the code in C:/src/orcastration, specifically the taxonomy stuff and knoweledge extraction. formulate a plan to inport this logic to take place of the taxonomy stuff.
  > 
  > intent: replace taxonomy logic with ... taxonomical taxonomy logic. (this is what was attemped with the "general collection" and automatic collection addtions in this project; true_intent: have knoweledge added to the database in-hopes of a agentic system that automatically pulls embdded facts and knoweledge, as a humam brain does, without having to search for it; injecting it into the prompt via background processes; this is/was a portion of that as well as other things but I value what this has become, I want to steer it back towards the goal though"

## True Intent & Vision Analysis
1. **Biological 7-Tier Taxonomy**: Replace the current ad-hoc, flat folder-like category state machine in `kb-web` with the principled 7-tier biological classification hierarchy (`Kingdom -> Phylum -> Class -> Order -> Family -> Genus -> Species`) from `orcastrator`.
2. **Atomic Fact & Intent Extraction**: When knowledge is ingested (articles, repos, notes, videos), automatically distill the raw content into atomic declarative `ContextStatement` records (`fact`, `preference`, `habit`, `negative_invariant`, `intent_mapping`, `affordance`), complete with hard clickable source provenance, confidence, and taxonomic coordinates.
3. **Subconscious Brain-Like Memory Injection**: Implement the "Hierarchical Bubble-Down Retriever" to automatically surface relevant facts and intent across taxonomic layers and inject them directly into agent prompts in the background, freeing agents from having to manually formulate search queries to recall context.
4. **Preserve Current Value**: Seamlessly integrate this vision into `kb-web` without discarding the web curation, wiki generation, and RAG capabilities that have already been developed.

## User Decision (Turn 1)
- **Selected Action**: Proceed with Phase 1 & 2: Build the core 7-tier taxonomy models, `context_statements` database table, and `FactExtractionPipeline` with Ollama.
- **Status**: Completed and fully verified with 8 unit tests + 256 full suite tests passing.

---

## User Input (Turn 2)
- **Date**: 2026-10-21
- **Prompt**:
  > "continue with next stage. DON not merge this into development or Prod. This may be an experimental branch only."

## Intent & Scope for Turn 2
1. **Proceed to Phase 3 (Hierarchical Bubble-Down Retriever & Subconscious Prompt Auto-Injector)** and **Phase 4 (Worker Job & Ingestion Hook)**.
2. **Branch Isolation Constraint**: All work remains strictly isolated on the experimental branch `feature/taxonomic-fact-extraction-mesh`. Under NO circumstances will this branch be merged into `development` or `production`.
- **Status**: Completed and fully verified with 13 unit tests + 256 full suite tests passing.

---

## User Input (Turn 3)
- **Date**: 2026-10-21
- **Prompt**:
  > "give the entire codebase a onceover and look for logical errors and misconfigurations. just do a general cleanup report for potential misconfigurations and logical errors. Evaluate portions of code that might need to be phased out and or depricated."

## Intent & Scope for Turn 3
1. **Codebase-Wide Audit**: Inspect the entire codebase for logical errors, misconfigurations, legacy dead code, deprecated components, and performance anti-patterns.
2. **Interactive Code Review Report**: Use the `code-review-issue-generator` skill to produce both a detailed audit artifact report and an interactive glassmorphic HTML review dashboard with filtered severity categories and actionable cleanup recommendations.
3. **Deprecation & Phasing-Out Evaluation**: Specifically evaluate components eligible for deprecation or removal (e.g. legacy flat taxonomy state machine, ghost stub tables, duplicate embedding columns, obsolete SQLite migration workarounds).
- **Status**: Completed initial sweep and generated interactive report `audit_report.html` and markdown summary.

---

## User Input (Turn 4)
- **Date**: 2026-10-21
- **Prompt**:
  > "search one more time and ensure you found all of the logical errors and stale code. Look into the HTML templates as well. audit all JS code on the UI too (as part of the codebase audit)"

## Intent & Scope for Turn 4
1. **Deep Template & Frontend Audit**: Thoroughly inspect all Jinja2 templates in `src/kb_web/templates/` for unescaped variables (XSS), missing CSRF/auth tokens, dead route links, broken conditionals, and missing error UI states.
2. **Client-Side JavaScript Audit**: Thoroughly audit all JS modules in `src/kb_web/static/js/` and inline `<script>` blocks for memory leaks, unhandled Promise rejections, DOM element null dereferences, event listener leaks, and deprecated browser APIs.
3. **Comprehensive Backend Deep-Dive**: Re-scan backend python routers, models, and workers for logical discrepancies, dead endpoints, stale configuration keys, and silent failure paths.
4. **Unified Multi-Tier Report**: Incorporate all HTML, JS, and backend findings into an updated `audit_findings.json`, regenerating the interactive HTML report and detailed cleanup artifact.

---

## User Input (Turn 5)
- **Date**: 2026-10-21
- **Prompt**:
  > "gix all issues. do this in the current branch push to development when done"

## Intent & Scope for Turn 5
1. **Fix All Identified Issues**: Systematically remediate all security vulnerabilities, frontend logic bugs, performance bottlenecks, and deprecation notices across the backend, templates, and UI JavaScript:
   - `SEC-02`: Global layout Stored XSS in `base.j2.html` (sanitize notifications and toast messages with `escapeHtml()`).
   - `SEC-03`: Stored XSS in `agent_pages.py` (add `sanitize_html(rendered_body)` before rendering in topic wikis and themed canvas pages).
   - `BUG-01`: Fix `worker.py` embedding refresh worker loop so it only selects pages lacking chunk embeddings.
   - `SEC-01`: Parameterize SQL queries in `config.py:719-726`.
   - `BUG-02`: Fix Workspace IDE folder deletion in `workspace_ide.j2.html` to issue a single atomic recursive folder deletion request.
   - `BUG-03`: Add `destroy()` lifecycle teardown to `jinja_highlighter.js` and update parameter regex to support Jinja filter pipes.
   - `BUG-04`: Move `jinja_highlighter.js` script tag in `admin.j2.html` to avoid `DOMContentLoaded` evaluation race conditions.
   - `SEC-04`: Escape URLs in `view_collection.j2.html`, `collection_editor.j2.html`, and `url_import.j2.html`.
   - `CONF-01`: Update `declarative_base()` import in `models_orm.py` to `sqlalchemy.orm.declarative_base`.
   - `PERF-01`: Batch startup ghost URL cleanup in `models_orm.py`.
   - `PERF-02`: Batch note insertions in `notes.py` vault zip unpacker.
   - `PERF-03`: Optimize `trigger_classify_notes` in `taxonomy.py` with SQL-level exclusion.
   - `DEPR-01`, `DEPR-02`, `DEPR-03`: Mark legacy taxonomy state machine, fragmented embedding tables, and `sqlite_utils` with deprecation notices.
2. **Branch Workflow & Verification**:
   - Perform all fixes on the current branch `feature/taxonomic-fact-extraction-mesh`.
   - Run full verification suite (`uv run pytest`, `uv run python build.py`).
   - Update `CHANGELOG.md` and docs.
   - Fast-forward merge / push verified increment into `development` as requested by the user.

---

## User Input (Turn 6)
- **Date**: 2026-10-21
- **Prompt**:
  > "proceed"
- **Action & Status**:
  - Gated pre-commit test suite executed (`uv run pytest`) — 261 passed, 0 failed in 331 seconds.
  - Pre-commit build pipeline executed (`uv run python build.py`) — dependencies synchronized, test suite re-verified cleanly, build completed with 0 errors.
  - Refined SQLAlchemy `select()` construct in `src/kb_web/worker.py` eliminating subquery warning.
  - Updated `CHANGELOG.md` documenting security hardening (`SEC-01` through `SEC-04`), bug fixes (`BUG-01` through `BUG-04`), performance improvements (`PERF-01` through `PERF-03`), and deprecations (`DEPR-01` through `DEPR-03`).
  - Updated `audit_findings.json` setting `status: "fixed"` across all 16 remediated items, and re-compiled interactive `audit_report.html`.
  - Staging changes, committing on `feature/taxonomic-fact-extraction-mesh`, merging into `development`, and pushing to remote `development`.
