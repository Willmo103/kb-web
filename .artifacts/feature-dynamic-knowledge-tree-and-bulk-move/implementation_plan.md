# Implementation Plan: Dynamic Knowledge Tree / Folder Graph, Direct Topic Deletion & Bulk Relocation

**Branch**: `feature/dynamic-knowledge-tree-and-bulk-move`  
**Target Baseline**: `development`  
**Related Requirements**: Interactive file-tree/folder knowledge graph, direct permanent topic/sub-topic deletion, arbitrary node creation, and bulk relocation for articles, notes, videos, and context facts.

---

## 1. Problem Statement & Architecture Vision

The user reported that the current taxonomy interface is too rigid and passive:
- Unwanted topics/sub-topics can only be toggled to `[DENIED]` instead of directly deleted.
- The 7-tier biological taxonomy coordinate model is overly rigid; users need a **fluid, folder-like Knowledge Tree / Graph** where folders and categories can be created, renamed, nested to arbitrary depths, and deleted.
- Content (articles, notes, videos) and atomic facts should be able to reside at any level in the hierarchy, with the ability to **move large quantities of files and facts** between folders/nodes in bulk.
- The tree must represent both knowledge organization and the user's subjective contextual grounding layer.

---

## 2. Proposed Changes & Technical Architecture

### Component 1: Topic & Node Deletion Engine (`src/kb_web/taxonomy/engine.py`)
- **Direct Permanent Deletion**:
  - `delete_topic_or_subtopic(name: str, level: str, reassign_to: Optional[str] = None)`:
    - Permanently deletes matching rows from `TopicGovernanceORM`.
    - If `level == "topic"`, cascades deletion to child sub-topics.
    - Removes matching nodes from the steered tree (`SteeredTaxonomyTreeManager`).
    - For items assigned to this topic/subtopic:
      - If `reassign_to` is provided, reassigns them to that target topic.
      - Otherwise, resets `FetchedPage.topic = None, sub_topic = None, topic_status = 'unassigned'`.
    - Updates `TaxonomyEntityORM` and `ContextStatementORM` coordinates accordingly.

### Component 2: Bulk Relocation / Re-parenting Engine (`src/kb_web/taxonomy/engine.py`)
- **Bulk Item Move**:
  - `bulk_move_items(item_uris: List[str], target_topic: str, target_sub_topic: Optional[str] = None)`:
    - Atomically updates `FetchedPage` records for all provided URLs:
      - Sets `topic = target_topic`
      - Sets `sub_topic = target_sub_topic or "General"`
      - Sets `topic_status = 'approved'`
    - Re-registers `TaxonomyEntityORM` records with updated taxonomy paths.
    - Updates corresponding `ContextStatementORM` canonical paths for statements originating from those items.
    - Returns updated counts and audit statistics.
- **Bulk Fact Relocation**:
  - `bulk_move_facts(statement_ids: List[str], target_kingdom: str, target_phylum: Optional[str] = None, target_class: Optional[str] = None)`:
    - Updates `ContextStatementORM.kingdom`, `phylum`, `class_name`, and `canonical_path` for all selected statements.

### Component 3: Dynamic Folder Tree Management (`src/kb_web/taxonomy/steered_tree.py`)
- **Dynamic Node CRUDS**:
  - `add_node(parent_id: Optional[str], name: str, level: Optional[str] = None, description: str = "")`:
    - Inserts a new node under `parent_id` (or at the root) in `SteeredTaxonomyTreeManager`.
    - Synchronizes with `TopicGovernanceORM`.
  - `delete_node(node_id: str, delete_children: bool = True)`:
    - Recursively removes the node and its children from the steered tree.
    - Synchronizes with `TopicGovernanceORM` and resets orphaned items.

### Component 4: REST API Endpoints (`src/kb_web/routers/taxonomy.py`)
- `POST /api/taxonomy/topics/delete`:
  - Body: `{"name": str, "level": "topic" | "sub_topic", "reassign_to": Optional[str]}`
  - Permanently purges the topic/sub-topic.
- `POST /api/taxonomy/items/bulk-move`:
  - Body: `{"urls": List[str], "target_topic": str, "target_sub_topic": Optional[str]}`
  - Moves all listed items into the target topic/folder.
- `POST /api/taxonomy/facts/bulk-move`:
  - Body: `{"statement_ids": List[str], "target_path": str, "target_topic": str, "target_sub_topic": Optional[str]}`
  - Relocates all listed context facts into the destination path.
- `POST /api/taxonomy/tree/add-node`:
  - Body: `{"parent_id": Optional[str], "name": str, "level": Optional[str], "description": Optional[str]}`
  - Adds a new folder node to the tree.
- `POST /api/taxonomy/tree/delete-node`:
  - Body: `{"node_id": str, "delete_children": bool}`
  - Deletes a folder node from the tree.

### Component 5: Dynamic File-Tree UI/UX (`src/kb_web/templates/taxonomy.j2.html`)
- **View 2 (Topic Governance Table)**:
  - Add a red **"Delete"** button next to each topic and sub-topic.
  - Clicking "Delete" prompts with a quick confirm dialog, deletes the topic/sub-topic via `POST /api/taxonomy/topics/delete`, and instantly removes the row from the table with a smooth fade animation.
- **View 1 (Knowledge File Tree & Bulk Move)**:
  - Upgrade the tree navigator with folder icons (`📁`, `📂`) and inline action buttons:
    - **"+ New Folder"** button to dynamically create child folders under any selected node.
    - **"Delete Folder"** button to purge the selected folder node.
  - Item list in the selected folder displays **checkboxes** with a "Select All" toggle.
  - A sticky **Bulk Action Toolbar** appears when 1 or more items are selected:
    - Shows count: `"3 items selected"`.
    - **"Move to Folder..."** button triggering a destination folder selector modal.
    - Instant bulk move execution via `/api/taxonomy/items/bulk-move`.
  - Fact list in the selected folder also supports bulk selection and relocation.

---

## 3. Verification & Testing Strategy

1. **Unit & Integration Tests (`tests/test_dynamic_knowledge_tree.py`)**:
   - Test permanent topic and sub-topic deletion and cascade reset on `FetchedPage` and `TaxonomyEntityORM`.
   - Test bulk moving multiple articles to a new topic/subtopic.
   - Test bulk moving context facts to a new path.
   - Test dynamic node addition and deletion in `SteeredTaxonomyTreeManager`.
   - Test all new REST endpoints with authenticated test client.
2. **Template & Pre-Commit Verification**:
   - `python .agents\skills\ui-component-uat-check\scripts\verify_ui_templates.py` (0 warnings).
   - `uv run pytest tests/test_dynamic_knowledge_tree.py`
   - `uv run pytest tests/test_steered_taxonomy_and_lifecycle.py tests/test_taxonomy_and_facts_display.py`
   - `python .agents\skills\generate-uat-testing-artifact\scripts\generate_uat_report.py`
3. **Documentation**:
   - Update `CHANGELOG.md`, `README.md`, and `GEMINI.md`.

