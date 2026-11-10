# Dangling, Legacy & Dead Code Audit

This document details all identified legacy, deprecated, redundant, or orphaned code components across `src/kb_web`. It assesses the technical debt, risk level, and recommended archival action for each candidate.

---

## 1. Executive Summary

| Candidate Component | Type | LOC | Risk Level | Recommended Action |
|---|---|---|---|---|
| `src/kb_web/taxonomy_state_machine.py` | Legacy Subsystem | 1,290 | Low | Archive to `archive/legacy_taxonomy/` |
| `src/kb_web/scripts/db_migrate_sqlite.py` | Legacy Script | 334 | Very Low | Archive to `archive/scripts/` |
| `src/kb_web/base.py` (SQLite PRAGMA routines) | Dead Code Path | ~45 | Very Low | Prune SQLite pragma branches |
| `src/kb_web/routers/graph.py` | Orphaned Prototype | 112 | Low | Deprecate or integrate with knowledge tree |
| `src/kb_web/routers/links.py` | Superseded Router | 138 | Low | Consolidate into Collections API |
| Redundant HTML Stripping Helpers (`utils.py`) | Redundant Helpers | ~60 | Very Low | Standardize on `html_cleaner.py` |

---

## 2. In-Depth Candidate Analysis

### Candidate 1: `src/kb_web/taxonomy_state_machine.py` (1,290 LOC)
- **Background**:
  Implemented in early v4/v5 releases to automatically group ingested articles into unsupervised category clusters using high-dimensional cosine centroids and an autonomous state machine.
- **Why It Is Obsolete**:
  The system has transitioned entirely to a **user-steered hierarchical knowledge tree** (`taxonomy/steered_tree.py` and `taxonomy/engine.py`). The user explicitly steers the folder tree, defines gating questions, and enforces strict layer-by-layer classification.
- **Current Footprint**:
  - `taxonomy_state_machine.py` is 1,290 lines long.
  - It is currently imported only in `routers/taxonomy.py` to service the legacy "Autonomous Category Clusters (Legacy)" tab.
- **Risk Assessment**:
  **Low**. Archiving this file and retiring Tab 3 in `/taxonomy` simplifies the router, removes 1,290 lines of unmaintained code, and eliminates user confusion between legacy clusters and modern steered folders.
- **Action Plan**:
  1. Move `src/kb_web/taxonomy_state_machine.py` to `archive/taxonomy_state_machine.py`.
  2. In `routers/taxonomy.py`, remove the cluster trigger route and cluster queries.
  3. In `templates/taxonomy.html`, remove or hide the legacy Tab 3.

---

### Candidate 2: `src/kb_web/scripts/db_migrate_sqlite.py` (334 LOC)
- **Background**:
  A one-off migration script written when `kb-web` migrated from SQLite to PostgreSQL.
- **Why It Is Obsolete**:
  The database migration is 100% complete. Both development and production environments, along with all 321 unit tests, run natively against PostgreSQL with pgvector. The SQLite database is no longer maintained or populated.
- **Risk Assessment**:
  **Very Low**. No active production or development workflow invokes this script.
- **Action Plan**:
  Move `scripts/db_migrate_sqlite.py` to `archive/scripts/db_migrate_sqlite.py` for historical reference.

---

### Candidate 3: SQLite Pragma & Fallback Branches in `base.py` & `config.py` (~60 LOC)
- **Background**:
  `base.py` and `config.py` still retain fallback logic that configures SQLite connections, sets `PRAGMA journal_mode=WAL`, and creates local `.db` files when `DATABASE_URL` is missing.
- **Why It Is Obsolete**:
  PostgreSQL is a hard requirement for the pgvector extension and `vw_page_cards` materialized views. If PostgreSQL is missing, the application fails to start properly. Retaining SQLite fallback logic creates false impressions that SQLite is supported.
- **Risk Assessment**:
  **Very Low**.
- **Action Plan**:
  Remove the `sqlite://` connection branches, enforcing PostgreSQL connection validation at startup via `scripts/check_db_ready.py`.

---

### Candidate 4: `src/kb_web/routers/graph.py` (112 LOC)
- **Background**:
  An experimental force-directed D3.js knowledge graph visualization endpoint (`/graph` and `/api/graph/data`) that links articles sharing common tags.
- **Why It Is Obsolete / Dangling**:
  The graph view has not been updated since v4. It does not reflect steered knowledge tree coordinates, context mesh statements, or topic agents.
- **Risk Assessment**:
  **Low**.
- **Action Plan**:
  Either upgrade `/graph` to render the modern hierarchical knowledge tree, or archive the router to `archive/routers/graph.py` and remove the dangling navigation link.

---

### Candidate 5: `src/kb_web/routers/links.py` (138 LOC)
- **Background**:
  Implements a simple `links` table for saving standalone external URLs without ingesting full content.
- **Why It Is Obsolete / Dangling**:
  In modern `kb-web`, external resources are either fully ingested via `/api/import/html` (with full AI wikis, tags, and context statements) or grouped into `/collections`. The `links` table is virtually unused.
- **Risk Assessment**:
  **Low**.
- **Action Plan**:
  Archive to `archive/routers/links.py` or consolidate into `routers/collections.py`.

---

### Candidate 6: Redundant Sanitization Routines in `utils.py` (~60 LOC)
- **Background**:
  `utils.py` contains legacy regex-based HTML tag strippers and markdown converters that predate the integration of `html_cleaner.py` (which uses `trafilatura` and `beautifulsoup4`).
- **Risk Assessment**:
  **Very Low**.
- **Action Plan**:
  Prune obsolete regex functions in `utils.py` and ensure all consumers import directly from `html_cleaner.py`.

---

## 3. Recommended Archival Directory Layout

```
archive/
├── README.md                          # Explains why each component was retired
├── legacy_taxonomy/
│   └── taxonomy_state_machine.py      # Unsupervised Category Clusters (1,290 LOC)
├── scripts/
│   └── db_migrate_sqlite.py           # SQLite to PostgreSQL migration tool (334 LOC)
└── routers/
    ├── graph.py                       # Experimental tag force-graph (112 LOC)
    └── links.py                       # Legacy raw link bookmarks (138 LOC)
```
Total recoverable LOC: **~2,000 LOC** of legacy technical debt.

