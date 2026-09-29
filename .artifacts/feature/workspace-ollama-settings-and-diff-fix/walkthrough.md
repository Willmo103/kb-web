# Workspace Ollama Settings, LoggedOllamaClient & Diff Matching Walkthrough

**Issue**: [#73](https://github.com/Willmo103/kb-web/issues/73)  
**PR**: [#74](https://github.com/Willmo103/kb-web/pull/74)  
**Branch**: `feature/workspace-ollama-settings-and-diff-fix`  
**Base**: `production`  

---

## 1. Problem & Root Causes

1. **`'LoggedOllamaClient' object has no attribute 'generate'`**:
   - `LoggedOllamaClient` in `src/kb_web/base.py` wrapped `ollama.Client` for SQL logging (`ollama_logs`) and timeouts. It defined `pull`, `push`, `list`, `chat`, and `embeddings`, but lacked `.generate()` and lacked attribute forwarding (`__getattr__`).
   - When the workspace coding agent called `client.generate(...)`, an `AttributeError` was immediately raised.

2. **Unwanted Hallucinated Diff Card (`Action: app.js`)**:
   - In `src/kb_web/routers/workspaces.py`, the fallback `except Exception as e` handler caught the `AttributeError` and returned a hardcoded mock suggestion:
     ```markdown
     Note: Ollama server connection was unavailable ('LoggedOllamaClient' object has no attribute 'generate').
     Simulated suggestion for '...':
     ```file:app.js
     // Generated sample by AI Agent
     console.log('Update applied successfully!');
     ```
     You can review or apply this change.
     ```
   - In `workspace_ide.j2.html`, `parseAndAttachDiffActions` saw `file:app.js` and rendered `Action: app.js [Review Diff] [Apply]`, even though the user was asking a question about their `pythonrc.py` file!

3. **Ollama Models Configuration**:
   - The workspace model configuration was a static text input defaulting to `{{ ollama_model }}` or `ornith:9b`.
   - The UI did not pull models dynamically from Ollama's `/tags` endpoint (`client.list()`), making it inconvenient to pick from locally installed models.

---

## 2. Implemented Fixes

### A. `src/kb_web/base.py`
- Implemented `generate(self, *args, **kwargs)` on `LoggedOllamaClient`:
  - Measures execution duration and logs requests, options, responses, and errors directly to the SQLite `ollama_logs` table under `prompt_type="generate"`.
- Implemented `__getattr__(self, name)`:
  - Automatically delegates any unhandled method or attribute call (e.g. `tags`, `ps`, `show`, `copy`, `delete`) directly to `self._client`.

### B. `src/kb_web/routers/workspaces.py`
- Added endpoint `GET /api/workspaces/models` (aliased as `/api/workspaces/tags`):
  - Placed before parameterized route `/api/workspaces/{workspace_id}` to prevent FastAPI 422 routing collisions.
  - Queries `_get_ollama_client().list()` (Ollama `/tags`) and returns installed model names.
- Updated `workspace_agent_chat_api`:
  - Invokes `client.chat` with structured `system` and `user` messages, falling back to `generate`.
  - Added explicit system prompt instructions:
    > "IMPORTANT: If you are answering a question, reviewing code, explaining concepts, or having a discussion without modifying any files, output standard conversational markdown or regular code blocks (e.g. ```python or ```javascript). Never use the ```file:path syntax unless proposing an actual file creation or edit."
  - Replaced the mock file hallucination on errors with clean error diagnostic reporting (`status: "error"` and no fake `file:app.js` code blocks).

### C. `src/kb_web/templates/workspace_ide.j2.html`
- **Dynamic Model Selection from `/tags`**:
  - Added model selection dropdown directly inside the AI Assistant subheader with an interactive refresh button to reload models from Ollama's `/tags`.
  - Added model selection dropdown inside the Settings modal synchronized with the active model.
  - Automatically persists chosen model in `localStorage` (`ws_model_{workspace_id}`) across browser reloads.
- **Strict Diff Action Matching**:
  - Updated `sendAiMessage`: If `data.status === "error"`, renders a clean warning banner and skips diff parsing entirely.
  - Refined `parseAndAttachDiffActions`:
    - Strictly checks that `targetPath` matches `^[a-zA-Z0-9_\-\./]+\.[a-zA-Z0-9]{1,10}$` (must have a valid file extension and no directory traversal `..`).
    - If the message contains conversational text or standard programming language codeblocks (`python`, `javascript`, etc.), no diff action buttons (`Review Diff` / `Apply`) are rendered.
    - Strips the `file:<path>` header line from the displayed code block so it displays clean syntax.

---

## 3. Verification & Test Results

| Test Suite / Tool | Command / Path | Result |
|---|---|---|
| **Workspace & Ollama Unit Tests** | `uv run pytest tests/test_sprint6_features.py -k test_workspace_ollama_agent_and_models` | **Passed** |
| **Sprint 6 Full Feature Suite** | `uv run pytest tests/test_sprint6_features.py` | **12 / 12 passed** (47.74s) |
| **Repository Regression Suite** | `uv run pytest tests/` | **98 / 98 passed** (74.03s) |
| **UI Template & UAT Verifier** | `verify_ui_templates.py` | **21 templates passed**, 0 warnings |
| **Build & Distribution Pipeline** | `uv run python build.py` | **100% Success** (Wheel & tar.gz packaged) |
| **VCS UAT Report** | [uat_report_workspace_ollama_settings_and_diff_fix_20260928_222501.md](file:///c:/src/kb-web/uat/reports/uat_report_workspace_ollama_settings_and_diff_fix_20260928_222501.md) | **Generated & Committed** |
