# Subsystem Deep Dive: API & Routers Directory

The API & Routers subsystem encompasses all 23 route modules providing HTTP endpoints for the HTML frontend, JSON REST API, CLI commander, and headless AI agents.

---

## 1. Complete Router Directory

| Module (`src/kb_web/routers/`) | Route Prefix | Auth | Key Endpoints | Description |
|---|---|---|---|---|
| `auth.py` | `/` | Public / Session | `GET /login`, `POST /login`, `POST /logout` | User session login, rate limiter, credential checks |
| `pages.py` | `/pages` | Session / API Key | `GET /pages`, `GET /pages/{url}`, `POST /pages/edit` | Article viewer, reader mode, Markdown edits |
| `api.py` | `/api` | Session / API Key | `GET /api/articles`, `GET /api/search`, `POST /api/import/html` | Core public REST endpoints for web ingestion and search |
| `rest_api.py` | `/api/v1` | Bearer Token / API Key | `GET /api/v1/articles`, `GET /api/v1/taxonomies` | OpenAPI v1 REST specifications for external integrations |
| `cli_api.py` | `/api/cli` | CLI API Key | `POST /api/cli/import`, `POST /api/cli/rag` | Headless CLI endpoints for `kb-web-cli` operations |
| `taxonomy.py` | `/taxonomy`, `/api/taxonomy` | Session / API Key | `GET /taxonomy`, `POST /api/taxonomy/nodes`, `POST /api/taxonomy/items/bulk-move`, `POST /api/taxonomy/nuke` | Knowledge tree browser, node governance, bulk relocations |
| `notes.py` | `/notes`, `/api/notes` | Session / API Key | `GET /notes`, `POST /notes/create`, `PUT /notes/{id}` | Markdown notes CRUD and coordinate association |
| `collections.py` | `/collections`, `/api/collections`| Session / API Key | `GET /collections`, `POST /collections`, `POST /collections/{id}/items` | Custom groupings, virtual folders, link lists |
| `workspaces.py` | `/workspaces`, `/api/workspaces`| Session / API Key | `GET /workspaces`, `POST /api/workspaces`, `POST /api/workspaces/{id}/files` | Monaco Editor persistent workspaces & WASM execution |
| `admin.py` | `/admin` | Session (Admin) | `GET /admin`, `POST /admin/settings`, `GET /admin/users` | System admin portal, configuration editor, statistics |
| `admin_batch.py` | `/admin/batch` | Session (Admin) | `POST /admin/batch/reindex`, `POST /admin/batch/purge` | High-volume batch operations and maintenance |
| `agent_board.py` | `/agents` | Session / API Key | `GET /agents`, `POST /agents/trigger` | Autonomous topic agent monitor & trigger board |
| `agent_pages.py` | `/pages/agent` | Public / Session | `GET /pages/agent/{hash_id}` | Dynamic canvas viewer for agent-generated HTML/Markdown |
| `rag_reports.py` | `/reports/rag` | Session / API Key | `GET /reports/rag`, `POST /reports/rag/generate` | Agentic RAG report generator and viewer |
| `reports.py` | `/reports`, `/api/reports`| Session / API Key | `GET /reports`, `GET /api/reports/metrics` | System analytics, growth charts, scheduled reports |
| `evals.py` | `/evals` | Session / API Key | `GET /evals`, `POST /evals/run`, `POST /evals/compare`| Model Evaluation Studio, prompt & model matrix testing |
| `embeddings.py` | `/api/embeddings` | Session / API Key | `POST /api/embeddings/generate`, `POST /api/embeddings/reindex` | Vector embedding maintenance & similarity search |
| `worker.py` | `/api/jobs` | Session / API Key | `GET /api/jobs`, `POST /api/jobs/{id}/run`, `POST /api/jobs/pause-non-core` | Background job controls, pause states, status |
| `conversations.py`| `/chat`, `/api/chat` | Session / API Key | `GET /chat`, `POST /api/chat/messages` | Multi-turn conversational interface with LLMs |
| `sites.py` | `/sites` | Session / API Key | `GET /sites`, `GET /sites/{domain}` | Domain-level virtual portals and site wikis |
| `errors.py` | `/admin/errors` | Session (Admin) | `GET /admin/errors`, `POST /admin/errors/clear` | System error log browser and clearer |
| `links.py` | `/links`, `/api/links` | Session / API Key | `GET /links`, `POST /api/links` | Standalone link bookmarking (candidate for consolidation) |
| `graph.py` | `/graph`, `/api/graph` | Session / API Key | `GET /graph`, `GET /api/graph/data` | Experimental tag force-directed graph (legacy) |

---

## 2. Authentication & Authorization Patterns

- **Session Cookies**: Browser UI requests authenticate via an encrypted HTTP-only session cookie containing an HMAC signature.
- **API Keys (`X-API-Key` or `Authorization: Bearer <key>`)**: REST, CLI, and MCP requests authenticate against the `cli_api_keys` table.
- **Brute-Force Rate Limiting**: The login endpoint (`/login`) applies strict client IP tracking, returning HTTP 429 when failed attempts exceed configured thresholds.

---

## 3. Standard Response Contracts & Error Handling

All JSON REST endpoints conform to standard status conventions:

- `200 OK` / `201 Created`: Standard success with JSON payload.
- `400 Bad Request`: Validation failure (returns `{ "detail": "Specific reason" }`).
- `401 Unauthorized`: Missing or invalid credentials.
- `403 Forbidden`: Insufficient role (e.g. non-admin accessing `/admin`).
- `404 Not Found`: Target resource does not exist.
- `422 Unprocessable Entity`: Pydantic schema validation error.
- `500 Internal Server Error`: Unhandled exception (automatically recorded in `server_error_logs`).

