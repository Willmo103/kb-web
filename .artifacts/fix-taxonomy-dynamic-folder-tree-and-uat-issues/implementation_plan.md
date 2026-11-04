# Implementation Plan: Taxonomy Dynamic Folder Tree, Edit Capabilities & UAT Issue Resolutions

Resolve all 7 issues reported in UAT testing feedback, transition the taxonomy system into an equal-node file-tree knowledge graph, enable direct topic/node editing, fix JavaScript runtime errors, eliminate unintentional re-seeding of deleted topics, prevent defaulting unassigned items to "General", add a comprehensive library search & placement portal, and modernize UI copy and icons.

---

## 1. Problem Analysis & Root Causes

1. **Issue 1 (Default Topics Reseeding Bug)**:
   - *Cause*: `ensure_default_topics_seeded(...)` in `taxonomy/engine.py` re-checks `allowed_list` against existing database rows on every call. When all default topics were deleted, the table was empty, causing `ensure_default_topics_seeded` to re-insert all default topics (`Blogpost/Article`, `Hobby/Leisure`, etc.).
   - *Fix*: Track initialization state in `SettingExternal(key="taxonomy_default_topics_initialized", value="1")`. Once initialized, never automatically re-seed deleted topics. If the user deletes all topics, they remain deleted.

2. **Issue 2 (Inability to Edit Topics/Tags)**:
   - *Cause*: `taxonomy` only supported creating and deleting topics; there was no endpoint or UI modal to edit existing topic names, descriptions, statuses, qualification criteria, or blacklists.
   - *Fix*: Implement `edit_topic(...)` in `taxonomy/engine.py` and `POST /api/taxonomy/topics/edit`. Cascade name updates to `TopicGovernanceORM`, `SteeredTaxonomyNode`, `FetchedPage`, `TaxonomyEntityORM`, and `ContextStatementORM`. Add interactive Edit buttons and modal dialogs in both the governance table and tree node details.

3. **Issue 3 (Outdated UI Text on Governance Table)**:
   - *Cause*: Header and subtitle still referenced "Governed general topics (Kingdom) and 2-level sub-topic taxonomies (Phylum/Class)".
   - *Fix*: Update text to "Taxonomy Nodes & Folder Governance" and state that topics function as the immutable folder structure that AI agents MUST categorize within.

4. **Issue 4 (Folder + Button JS Error)**:
   - *Cause*: `selected7TierPath` was referenced in `openAddFolderModal` without being declared in the global JavaScript scope, throwing `Uncaught ReferenceError: selected7TierPath is not defined`.
   - *Fix*: Declare `selected7TierPath`, `selected7TierTitle`, and `selected7TierLevel` globally in `taxonomy.j2.html`, populate them on node click, and add null-safe fallbacks in `openAddFolderModal`.

5. **Issue 5 (Defaulting to "General" instead of "Unclassified")**:
   - *Cause*: `get_7tier_tree` in `taxonomy/engine.py` and `TaxonomyClassifier` fell back to `"General"` for any null or empty taxonomy coordinates, putting 2,736 facts and items under `General/General/general/general`.
   - *Fix*: Replace fallback `"General"` with `"Unclassified"`. Uncategorized facts and items will now display under a distinct `📁 Unclassified` node instead of creating false taxonomy hierarchies.

6. **Issue 6 (Missing Search & Placement for Current Imports)**:
   - *Cause*: `/taxonomy` had no dedicated search interface to query across all imported pages, articles, notes, and videos to place them into folders.
   - *Fix*: Add `GET /api/taxonomy/library-items` supporting full-text search, type filtering, and status filtering. Add a dedicated **"Library Imports & Placement"** tab in `/taxonomy` with instant search, bulk selection checkboxes, and single-click "Place in Folder..." actions.

7. **Issue 7 (Moving from 7-Tier Biological Design to Equal Folder Nodes)**:
   - *Cause*: Tree template used biological rank icons (`👑`, `◆`, `📦`, `🏷️`) and biological tier badges (`FAMILY`, `Kingdom`, `Phylum`).
   - *Fix*: Unify all tree nodes into clean folder representations (`📁`) with equal folder node semantics. Display rich folder metadata and policy cards (qualification criteria, blacklists, lifecycle rules) that are inserted into decision states for each layer.

---

## 2. Proposed Changes

### Backend Core
- [`src/kb_web/taxonomy/engine.py`](file:///c:/src/kb-web/src/kb_web/taxonomy/engine.py):
  - In `ensure_default_topics_seeded`: check `SettingExternal("taxonomy_default_topics_initialized")` to guarantee default topics are only seeded once on first boot and never re-added when cleared.
  - Implement `edit_topic(...)`: atomically update `TopicGovernanceORM`, `SteeredTaxonomyNode`, `FetchedPage.topic`/`sub_topic`, `TaxonomyEntityORM`, and `ContextStatementORM`.
  - In `get_7tier_tree`: replace `"General"` fallbacks with `"Unclassified"` for unassigned items.
  - Add `get_library_items_summary(...)`: query and search imported pages, notes, and videos with classification status and canonical paths.
- [`src/kb_web/routers/taxonomy.py`](file:///c:/src/kb-web/src/kb_web/routers/taxonomy.py):
  - Add `POST /api/taxonomy/topics/edit` (`EditTopicRequest`).
  - Add `GET /api/taxonomy/library-items` (`search`, `status`, `source_type`, `limit`, `offset`).

### Frontend UI & Templates
- [`src/kb_web/templates/taxonomy.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/taxonomy.j2.html):
  - Fix JavaScript global variables: `selected7TierPath`, `selected7TierTitle`, `selected7TierLevel`.
  - Add `modal-edit-topic` modal for editing topic/folder name, description, qualification questions, and domain blacklists.
  - Add **Edit** action button in Topic Governance table rows.
  - Add **Edit Folder** action button in Knowledge Tree node details.
  - Update all tree icons from biological ranks (`👑`, `◆`, `📦`, `🏷️`) to uniform folder icons (`📁`).
  - Replace biological badges with `FOLDER` / `SUBFOLDER` badges and show folder policies (gating questions, blacklists, lifecycle).
  - Add 4th tab: **"Library Imports & Placement"** with live search, item list, checkboxes, and "Assign to Folder..." bulk actions.
  - Update Governance header and subtitle text per Issue 3.

---

## 3. Verification Plan

1. **Unit & API Tests**:
   - Write tests in `tests/test_taxonomy_uat_fixes.py` verifying:
     * Deleting all topics does not re-seed default topics upon subsequent queries or additions.
     * `POST /api/taxonomy/topics/edit` renames topic and cascades changes to `FetchedPage`, `SteeredTaxonomyNode`, and `ContextStatementORM`.
     * `GET /api/taxonomy/library-items` filters and searches library items cleanly.
     * Unclassified items display under `"Unclassified"` rather than `"General"`.
   - Run existing taxonomy test suites:
     `uv run pytest tests/test_dynamic_knowledge_tree.py tests/test_steered_taxonomy_and_lifecycle.py tests/test_taxonomy_and_facts_display.py`
2. **UI & UAT Verification**:
   - Run UI template check: `uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`.
   - Generate UAT testing artifact: `uv run python .agents/skills/generate-uat-testing-artifact/scripts/generate_uat_report.py`.
   - Run `uv run python build.py`.
3. **Commit & Documentation**:
   - Update `CHANGELOG.md`, `README.md`, `GEMINI.md`.
   - Merge `fix/taxonomy-dynamic-folder-tree-and-uat-issues` into `development` and push to remote.

