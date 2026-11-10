# Subsystem Deep Dive: Client & External Integrations

This subsystem details the external interfaces connecting `kb-web` with command lines, IDEs, external AI agents, and web browsers.

---

## 1. Components & File Layout

| Component | Technology | Primary Function |
|---|---|---|
| `cli.py` | Typer / Click | Headless CLI commander (`kb-web-cli`) |
| `mcp_server.py` | FastMCP | Model Context Protocol server exposing knowledge to AI tools |
| `browser_extension/` | Manifest V3 (JS/HTML) | Unpackaged Chrome & Firefox extension for 1-click web clipping |
| `static/pwa/` | ServiceWorker / WebApp | Progressive Web App and Web Share Target integration |

---

## 2. CLI Commander (`kb-web-cli`)

Built with `typer`, `kb-web-cli` provides an authenticated, terminal-native interface for scripting and headless automation.

### Core Commands:
- `kb-web-cli import <url> [--tags tag1,tag2]`: Triggers the full web ingestion pipeline.
- `kb-web-cli rag report "<query>"`: Executes agentic RAG and prints publication-grade markdown to stdout or file.
- `kb-web-cli taxonomy nuke --confirm`: Resets all taxonomy assignments across the database.
- `kb-web-cli worker status`: Displays active worker jobs, pause state, and queued items.
- `kb-web-cli worker pause-non-core`: Toggles the non-core worker pause state.

---

## 3. Model Context Protocol (MCP) Server (`mcp_server.py`)

Runs as a dedicated systemd service (`kb-web-mcp.service`) or standalone process via FastMCP, allowing external agents (such as Claude Desktop, Cursor, or Antigravity) to query knowledge directly:

### Exposed MCP Tools:
1. `search_knowledge(query: str, limit: int = 5)`: Executes hybrid vector + lexical search, returning top article cards and relevance scores.
2. `get_article(url: str)`: Returns the clean markdown text and AI-generated wiki for a specific URL.
3. `get_context_statements(query: str, statement_type: Optional[str] = None)`: Queries the Context Mesh for verified atomic facts and invariants.
4. `list_taxonomy_tree()`: Returns the current steered folder tree hierarchy.

---

## 4. Browser Extension (`browser_extension/`)

An unpackaged Manifest V3 browser extension compatible with Google Chrome, Chromium, and Mozilla Firefox:

- **Background Service Worker**: Injects context menu actions ("Send to kb-web") and manages API authentication tokens.
- **Popup UI**: Allows the user to inspect the current page, select custom tags, choose a destination folder in the steered knowledge tree, and trigger ingestion with one click.
- **Notification Feedback**: Displays real-time status pills confirming successful extraction, AI wiki synthesis, and categorization.

---

## 5. Progressive Web App (PWA) & Web Share Target

- **Service Worker (`sw.js`)**: Caches static assets, themes, and CSS for offline UI shell rendering.
- **Web Share Target API**: Allows mobile browsers (Android Chrome, iOS Safari) to share URLs directly to `kb-web` via the OS system share sheet, forwarding payloads directly to `/import`.

