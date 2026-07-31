# Python Coding Rules & Technical Standards

This file establishes technical standards for Python code, FastAPI router architecture, database models, and external services in `kb-web`.

---

## 1. FastAPI Router Architecture
- All API routes must reside in dedicated router modules under `src/kb_web/routers/` (e.g. `admin.py`, `api.py`, `auth.py`, `collections.py`, `pages.py`, `sites.py`, `graph.py`, `cron.py`).
- Use proper FastAPI dependency injection for session authentication and passcode verification (`auth.py`).

## 2. Pydantic Models & Data Schemas
- Define all input/output payloads as explicit Pydantic models in `src/kb_web/models.py`.
- Validate all incoming raw tab payloads (`HTMLPage`) and URLs (`ParsedUrl`) before passing to scrapers or database helpers.

## 3. Database Interactions
- Database operations must be funneled through `src/kb_web/db.py` using `sqlite-utils`.
- Use parameterized queries to prevent SQL injection vulnerabilities.

## 4. Qdrant & EmbeddingGemma Vector Search
- Vector indexing operations reside in `src/kb_web/utils.py`.
- Ensure Qdrant collection initialization checks gracefully handle fallback when local Qdrant server is unavailable or starting up.

## 5. Ollama LLM Curation Prompts
- Wiki transformation and tag extraction prompts MUST start clean with `# Title` format and avoid extraneous markdown wrappers.
- System prompts must be customizable via Admin settings and fall back to `KB_WIKI_PROMPT` configuration defaults.

## 6. Pre-Commit Validation
- All Python changes MUST pass `uv run pytest` and clean compilation with `uv run python build.py`.
