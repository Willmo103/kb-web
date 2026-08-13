# Sprint 2: SQLAlchemy ORM & pgvector Searches (Issue #41)

* **Sprint Goal**: Declare SQLAlchemy ORM models, session pool configurations, and adapt embedding vector queries to utilize native PostgreSQL `pgvector` distance searches.
* **Parent Issue**: #30 (PostgreSQL | SQLAlchemy Support)
* **Estimated Duration**: 14 Days

---

## Detailed Task List

### 1. SQLAlchemy ORM Schema mapping (Sub-Issue #43)
- [ ] Install SQLAlchemy ORM dependency: `pip install sqlalchemy pgvector`.
- [ ] Create `src/kb_web/models_orm.py` and declare ORM mapping classes using the declarative base pattern.
- [ ] Map active SQLite tables to SQLAlchemy classes, specifying model field types, indexes, and relationships:
  - `FetchedPage` (table: `fetched_pages`)
  - `PageVersion` (table: `page_versions`)
  - `Collection` (table: `collections`)
  - `CollectionItem` (table: `collection_items`)
  - `CollectionNote` (table: `collection_notes`)
  - `Link` (table: `links`)
  - `SystemLog` (table: `system_logs`)
- [ ] Setup view mappings (`vault_master`, `repo_master`, `valid_repo_files`) using the declarative ORM read-only format.

### 2. Database Session & Dialect configs (Sub-Issue #44)
- [ ] Add the `DATABASE_URL` string setting inside `src/kb_web/config.py`.
- [ ] Refactor connection pool engine mappings in `src/kb_web/base.py` to:
  - Dynamically instantiate engines matching configured DB dialects (SQLite vs. PostgreSQL).
  - Add pool settings (`pool_size=10`, `max_overflow=20`) to PostgreSQL drivers.
  - Implement a thread-scoped transaction session generator (`db_session`).

### 3. pgvector integration & Vector Searching Refactor (Sub-Issue #42)
- [ ] Map embeddings columns inside `models_orm.py` (`ArticleEmbedding`, `VideoEmbedding`, `ChunkEmbedding`) using the `Vector` field type:
  ```python
  from pgvector.sqlalchemy import Vector
  embedding = Column(Vector(1536))  # 1536 size matches EmbeddingGemma / OpenAI dimensions
  ```
- [ ] Ensure database startup triggers `CREATE EXTENSION IF NOT EXISTS vector;` on PostgreSQL connection instances.
- [ ] Refactor similarity search operations inside `src/kb_web/utils.py` and pages/RAG routers:
  - Replace SQLite text-to-float math searches with SQLAlchemy queries utilizing the native cosine distance (`<=>`) or L2 distance (`<->`) operators.
