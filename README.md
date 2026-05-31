# kb-web

A standalone web application and CLI wrapper for the Knowledge Base (kb) ecosystem. It provides a FastAPI web portal for capturing and importing web pages, cleaning them using Ollama LLM agents, searching the archive, and streaming database exports.

## Core Features

- **PWA Web Ingestion Target**: Registers as a share target on mobile and desktop web browsers, enabling quick clicks to ingest URLs directly.
- **Chrome Browser Extension Ingest**: Features an unpackaged Chrome extension targeting `/api/import/html` to instantly post raw tab HTML, bypassing authentication and JavaScript obstacles.
- **AI Wiki Conversion**: Rewrites raw scraped web pages into clean, highly structured markdown wiki entries starting with H1 titles `# Title` using Ollama.
- **Tag Curation & Editing**: Automates tag generation through Ollama classification prompts and allows manual tag updates inside the UI.
- **Interactive Action Triggers**: Supports 1-click Wiki and Tag re-generation directly on the page view profile.
- **Administrative Settings Portal**: Prefills and updates Ollama hosts/models, system prompts, API keys, and Gotify details directly from the Web UI.
- **Chunked WS Ingest**: Supports uploading JSON database backups over WebSockets.
- **JSON Streams**: Streams database records out as downloadable files.

---

## Codebase Structure

- `src/kb_web/config.py`: Configuration class extending the base `kb_core` configuration to support LLM, API keys, and web UI variables.
- `src/kb_web/db.py`: Database helper setting up and migrating `title` and `tags` columns in the shared SQLite database.
- `src/kb_web/models.py`: Pydantic validation schemas (`ParsedUrl` and `HTMLPage`) representing stored pages.
- `src/kb_web/server.py`: FastAPI application routing, route guards, and background tasks.
- `src/kb_web/cli.py`: Typer command launcher.
- `src/kb_web/templates/`: Jinja2 templates for login, dashboard lists, configuration inputs, and profile views.
- `browser_extension/`: Source directory containing manifest, options menu, and background worker for Chrome imports.
- `kb-web.service`: Systemd service template for Linux deployments.

---

## Configuration Settings

The application is configured using environment variables, or alternatively, by placing a configuration file at `~/.kb/configs/kb-web.json` (editable directly inside the Admin portal).

| Variable | Default Value | Description |
|---|---|---|
| `KB_PASSWORD` | `admin123` | Passcode protecting administrative pages and imports. |
| `KB_API_KEY` | `kb-secret-key` | Token required in headers for Chrome Extension posts. |
| `KB_OLLAMA_HOST` | `http://localhost:11434` | Endpoint pointing to the Ollama server. |
| `KB_OLLAMA_MODEL` | `gemma4:latest` | LLM model target for wiki entries and tags. |
| `GOTIFY_URL` | None | Gotify host server address. |
| `GOTIFY_TOKEN` | None | Gotify application token. |
| `KB_WIKI_PROMPT` | System prompt | Custom prompt template for LLM cleanups. |

---

## Local Development

### 1. Synchronize Dependencies
Sync your virtual environment using `uv`:
```bash
uv sync
```

### 2. Launch Local Server
Use the CLI to launch the FastAPI application in development mode:
```bash
uv run kb-web serve --port 8050 --reload
```

Then visit `http://localhost:8050/pages` to view the archive index or `http://localhost:8050/` to log in and import new URLs.

---

## Chrome Browser Extension Setup

To load the manual sync browser extension on your local machine:

1. Open your browser's extensions page (`chrome://extensions/` for Chrome).
2. Enable **Developer mode** using the toggle in the top-right corner.
3. Click **Load unpacked** in the top-left corner.
4. Select the directory `/srv/kb-web/browser_extension` (or local equivalent).
5. Open the Extension Options page to configure:
   - **FastAPI API Endpoint URL**: `http://localhost:8050/api/import/html`
   - **Ingestion API Key**: matching `KB_API_KEY` (default: `kb-secret-key`)
6. Click the extension toolbar icon on any webpage to sync its HTML content. The icon badge indicates status: "SYNC" (blue), "OK" (green), "ERR" (red).

---

## Running Automated Tests

Run the test suite to verify route parsing and model constraints:
```bash
uv run pytest
```

---

## Production Linux Server Deployment (Git Flow)

This codebase is deployed on a Linux server by cloning the repository to `/srv/kb-web/`.

### 1. Clone & Set Ownership
Ensure the repository is checked out at `/srv/kb-web` and owned by your system user:
```bash
# Clone or move the repository
sudo git clone <repo_url> /srv/kb-web
sudo chown -R will:will /srv/kb-web
```

### 2. Setup Virtual Environment & Install
Create a Python virtual environment and install the package dependencies:
```bash
cd /srv/kb-web
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
```

### 3. Scaffolding Environment Variables
Create the environment configuration file:
```bash
cat <<EOF > /srv/kb-web/.env
KB_PASSWORD=your_secure_password
KB_API_KEY=your_extension_auth_key
KB_OLLAMA_HOST=http://localhost:11434
# GOTIFY_URL=http://your-gotify-server
# GOTIFY_TOKEN=your-token
EOF
```

### 4. Configure Systemd Service
Copy the systemd configuration file and reload the daemon:
```bash
sudo cp /srv/kb-web/kb-web.service /etc/systemd/system/kb-web.service
sudo systemctl daemon-reload
```

### 5. Manage Service
Enable and start the daemon:
```bash
sudo systemctl enable --now kb-web

# To check logs or status
sudo systemctl status kb-web
sudo journalctl -u kb-web -f
```
