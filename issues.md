# Open Issues

## 9. Web UI Performance Latency, Pagination, & REST API Overhaul
@performance @ui @api

### Description
Following the database migration to PostgreSQL and SQLAlchemy ORM, loading the main web UI dashboard (`/` and `/pages`) has become significantly latent. Loading all articles simultaneously without pagination and executing N+1 queries for collection metadata causes high database round-trip delays, large memory consumption, and browser DOM rendering lag.

Additionally, we need to phase out legacy SQLite support and standardize on PostgreSQL, exposing backend functionality through clean REST API endpoints for external applications (e.g. fetching articles, video transcripts, sites, and tags) and updating the web frontend to consume these API endpoints reactively with pagination.

### Key Objectives
1. **Phasing Out SQLite Support**:
   - Standardize on PostgreSQL as the primary database engine.
   - Leverage PostgreSQL-native capabilities (e.g. `string_agg`, composite index scans) for data pre-processing and aggregation.

2. **Database Pre-Processing & Views**:
   - Create a database view (`vw_page_cards`) that pre-joins `fetched_pages`, `youtube_videos`, and `collections`, pre-aggregating collection titles via `string_agg`.
   - Exclude heavy raw text columns (`html_content`, `md_content`) from card summary queries to reduce memory hydration and data transmission.
   - Add database indexes on `fetched_pages.fetched_at`, `collection_items.source_id`, and `youtube_videos.creator`.

3. **Standardized REST API Endpoints**:
   - `GET /api/articles`: Paginated (`page`, `limit`), search (`q`), tag filter (`tag`), sorting.
   - `GET /api/articles/detail`: Full article details with markdown and wiki summary.
   - `GET /api/videos`: Paginated video cards (`creator`, `tag`, `page`, `limit`).
   - `GET /api/videos/transcript`: Video transcript segments, plain text transcript, and chapter breakdown.
   - `GET /api/sites`: Aggregated domain list with page counts and sample URLs.
   - `GET /api/tags`: Unique tags list with item counts.

4. **Frontend Reactive UI Overhaul**:
   - Implement responsive pagination controls (Previous, Next, Page Numbers, Page Size selector).
   - Implement debounced search (300ms) without page reloads.
   - Instant tab switching between Articles, Videos, and Sites.
   - Deep-linkable URL parameters (`history.pushState`).
   - Skeleton loading placeholders for cards.

---
