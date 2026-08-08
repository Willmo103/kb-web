# Implementation Plan - Standalone Server Admin CLI Submodule

This plan details the updated approach to build a standalone, separately-installable CLI command-line client (`kb-cli`) packaged as a git submodule `kb-web-cli` within the repository, with its own build pipeline integrated into the main one.

## User Review Required

> [!IMPORTANT]
> 1. **Submodule Git Repository**: The CLI package will reside in the subdirectory `kb-web-cli`, initialized as its own standalone git repository with independent VCS tracking.
> 2. **Standalone Installation**: The CLI package will contain its own `pyproject.toml` exposing the console script entrypoint `kb-cli` (or `kb-web-cli`), using `typer` and `httpx` to communicate with the LIVE server.
> 3. **Integrated Build Pipeline**: The parent repository's `build.py` script will be updated to trigger build packaging for both packages (`kb-web` and `kb-web-cli`).

## Proposed Changes

---

### Database Schema Updates

#### [MODIFY] [db.py](file:///c:/src/kb-web/src/kb_web/db.py)
- Inside the `init_db` function, initialize the database tables:
  - `cli_api_keys`: stores active API keys.
  - `registered_clients`: stores registered computer names and used API keys.

---

### Admin Portal Configuration

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Update `get_admin_dashboard` to retrieve:
  - `cli_keys`: all active CLI keys.
  - `registered_clients`: list of registered computer client machines.
- Add POST routers:
  - `/admin/cli/keys/create`: generates a new UUID API key, records it, and redirects to dashboard.
  - `/admin/cli/keys/delete`: revokes/deletes an API key.
  - `/admin/cli/clients/delete`: de-registers a client machine.

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- Add a new "CLI Integration" card section at the bottom of the grid displaying:
  - List of active CLI API Keys (with key name, truncated value, and a "Revoke" button).
  - An inline API key generation form.
  - List of registered computer clients (computer name, used key name, registered date, status, and a "Revoke Client" action button).

---

### Server CLI API Router

#### [NEW] [cli_api.py](file:///c:/src/kb-web/src/kb_web/routers/cli_api.py)
- Create new APIRouter `/api/cli` requiring header `X-API-KEY`:
  - `POST /register`: Registers a client computer name.
  - `POST /import/url`: Synchronous JSON URL ingestion wrapper.
  - `GET /pages`: Lists recent articles and videos.
  - `POST /pages/action`: Triggers `regenerate-wiki`, `download-video`, or `regenerate-tags` for a page URL.
  - `GET /collections`: Lists collections and item counts.
  - `POST /collections/item`: Adds or removes pages from a collection.
  - `GET /tags`: Lists all tags.
  - `POST /tags/operation`: Adds/removes tags from a page.
  - `POST /agent/query`: Retrieves database contexts matching keywords and feeds them to Ollama model as RAG prompt context.

#### [MODIFY] [server.py](file:///c:/src/kb-web/src/kb_web/server.py)
- Import and mount `cli_api.router` in `app.include_router(...)`.

---

### Standalone CLI Submodule `kb-web-cli`

#### [NEW] [kb-web-cli/pyproject.toml](file:///c:/src/kb-web/kb-web-cli/pyproject.toml)
- Define standalone package metadata:
  - Dependencies: `typer`, `httpx`, `click`.
  - Console script entrypoint: `kb-cli = "kb_web_cli.main:app"`.

#### [NEW] [kb-web-cli/src/kb_web_cli/main.py](file:///c:/src/kb-web/kb-web-cli/src/kb_web_cli/main.py)
- Implement Typer CLI client commands:
  - `install`: registers client computer name and saves config locally to `~/.kb/cli-config.json`.
  - `import`: posts a URL to the server for processing.
  - `list`: lists recent articles and videos.
  - `action`: triggers page operations on the server.
  - `collections`: views collections or manages collection items.
  - `tags`: views tags or manages page tags.
  - `query`: queries the server-side RAG agent with custom prompt strings.

---

### Parent Repository Integration

#### [MODIFY] [build.py](file:///c:/src/kb-web/build.py)
- Update clean and build steps to handle `kb-web-cli`:
  - Clean `kb-web-cli/dist` directory.
  - Build wheel/sdist packaging for `kb-web-cli` package.

---

## Verification Plan

### Automated Tests
- Create a unit test `test_cli_client_server_integration` in `tests/test_server.py` verifying API endpoints.
- Execute `uv run pytest` to ensure all tests pass.

### Manual Verification
- Generate an API key from the Web UI.
- Run `kb-cli install` and check that registration succeeded and client is visible in Web UI.
- Run CLI query and page actions to check correct console output formatting.
