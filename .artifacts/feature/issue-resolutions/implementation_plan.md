# Implementation Plan - Layout, API Keys, and CLI Logs

This plan outlines the technical changes to resolve the layout width constraints, add copy to clipboard functionality for client API keys, and expose the server logs command in the CLI.

## Proposed Changes

### 1. Layout Width Constraints (Issue 8)

We will update the templates to use a reactive and wider `max-w-[95%] w-full mx-auto` container instead of restrictive static max-widths (`max-w-4xl`, `max-w-5xl`, `max-w-6xl`, `max-w-7xl`).

#### [MODIFY] [base.j2.html](file:///c:/src/kb-web/src/kb_web/templates/base.j2.html)
- Change header container from `max-w-5xl mx-auto` to `max-w-[95%] w-full mx-auto`.

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- Change main container from `max-w-4xl` to `max-w-[95%] w-full`.

#### [MODIFY] [collection_editor.j2.html](file:///c:/src/kb-web/src/kb_web/templates/collection_editor.j2.html)
- Change main container from `max-w-7xl pb-4` to `max-w-[95%] w-full pb-4`.

#### [MODIFY] [collections.j2.html](file:///c:/src/kb-web/src/kb_web/templates/collections.j2.html)
- Change main container from `max-w-5xl pb-12` to `max-w-[95%] w-full pb-12`.

#### [MODIFY] [links.j2.html](file:///c:/src/kb-web/src/kb_web/templates/links.j2.html)
- Change main container from `max-w-5xl mx-auto px-4 pb-12` to `max-w-[95%] w-full mx-auto pb-12`.

#### [MODIFY] [logs.j2.html](file:///c:/src/kb-web/src/kb_web/templates/logs.j2.html)
- Change main container from `max-w-5xl pb-12` to `max-w-[95%] w-full pb-12`.

#### [MODIFY] [pages_list.j2.html](file:///c:/src/kb-web/src/kb_web/templates/pages_list.j2.html)
- Change main container from `max-w-6xl` to `max-w-[95%] w-full`.

#### [MODIFY] [similarity_graph.j2.html](file:///c:/src/kb-web/src/kb_web/templates/similarity_graph.j2.html)
- Change main container from `max-w-6xl pb-12` to `max-w-[95%] w-full pb-12`.

#### [MODIFY] [sites_list.j2.html](file:///c:/src/kb-web/src/kb_web/templates/sites_list.j2.html)
- Change main container from `max-w-4xl` to `max-w-[95%] w-full`.

#### [MODIFY] [view_collection.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_collection.j2.html)
- Change main container from `max-w-6xl pb-12` to `max-w-[95%] w-full pb-12`.

#### [MODIFY] [view_page.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html)
- Change outer container from `max-w-7xl pb-8` to `max-w-[95%] w-full pb-8`.
- Change intermediate panels from `max-w-6xl mx-auto` to `max-w-none`.
- Change flex layout container from `max-w-7xl mx-auto` to `max-w-none`.

#### [MODIFY] [view_site.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_site.j2.html)
- Change outer container from `max-w-7xl pb-8` to `max-w-[95%] w-full pb-8`.
- Change intermediate panels from `max-w-6xl mx-auto` to `max-w-none`.

---

### 2. Client API Key Copy-to-Clipboard Functionality (Issue 7)

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- Add a "Copy" button next to each generated API Key that copies the full key securely using browser `navigator.clipboard`.
- Implement `copyToClipboard(text, element)` helper function in the script block.

---

### 3. Expose Server Logs via CLI (Issue 6)

#### [MODIFY] [cli_api.py](file:///c:/src/kb-web/src/kb_web/routers/cli_api.py)
- Implement `GET /api/cli/logs` to retrieve the database server logs. Returns a list of JSON records matching `SELECT * FROM system_logs ORDER BY rowid DESC LIMIT ?`.

#### [MODIFY] [main.py](file:///c:/src/kb-web/kb-web-cli/src/kb_web_cli/main.py)
- Implement `kb-cli logs` command using Typer.
- Read/write the preferred limit in the local `.kb/cli-config.json` under `"log_limit"` key (defaults to 100).
- Sort the displayed logs from top to bottom (most recent first, as received from the server).

---

## Verification Plan

### Automated Tests
- We will run the unit test suite (`pytest`) to ensure no regressions are introduced.

### Manual Verification
- Render the UI in a browser subagent session to confirm layout responsiveness and clipboard copy function.
- Invoke the CLI logs command to verify the retrieved log entries format and log_limit persistence.
