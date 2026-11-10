## Release v0.5.16 (Staging Production -> Master)

This draft pull request tracks the next stage of verified increments (`v0.5.16`) staged on `production` for eventual promotion into `master` following the repository tiered release lifecycle.

### Baseline Release Synchronized (`v0.5.15`)
- **Dynamic Knowledge Tree & Folder Architecture (`taxonomy/steered_tree.py`, `templates/taxonomy.j2.html`)**:
  - Transformed the static biological taxonomy tree into a flexible, multi-level file-tree knowledge graph with equal folder representation (`📁`).
  - Added dynamic node creation (`add_node`) and recursive pruning (`delete_node`) with REST endpoints `POST /api/taxonomy/tree/add-node` and `POST /api/taxonomy/tree/delete-node`.
- **Direct Permanent Topic & Sub-Topic Deletion (`taxonomy/engine.py`, `routers/taxonomy.py`)**:
  - Added `delete_topic_or_subtopic(...)` and `POST /api/taxonomy/topics/delete` with cascade unassignment across database items and statements.
- **Topic & Folder Editing Modal & Cascading API (`taxonomy/engine.py`, `routers/taxonomy.py`, `templates/taxonomy.j2.html`)**:
  - Added `edit_topic(...)` and `POST /api/taxonomy/topics/edit` (`EditTopicRequest`), cascading renames across DB and steered tree.
- **Dedicated Library Imports & Placement Portal (`taxonomy/engine.py`, `routers/taxonomy.py`, `templates/taxonomy.j2.html`)**:
  - Added `GET /api/taxonomy/library-items` with live search, filters, pagination, and single/bulk placement.
- **Bulk Item & Fact Relocation Across Folders (`taxonomy/engine.py`, `routers/taxonomy.py`, `templates/taxonomy.j2.html`)**:
  - Batch relocation for library pages, articles, notes, videos (`POST /api/taxonomy/items/bulk-move`) and context mesh statements (`POST /api/taxonomy/facts/bulk-move`).
- **Steered Tree Governance & Personal VK Context Layer (`context_mesh/personal_vk.py`, `worker.py`)**:
  - Gating criteria questions, domain blacklists, content lifecycle auto-freeze / auto-refetch with Gotify push alerts, and curated personal VK layer.

### Upcoming Increments (`v0.5.16`)
- Ongoing verified features and bugfixes merged from `development` -> `production` will accumulate in this PR prior to the next formal release cut.
