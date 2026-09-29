# Implementation Plan: Workspace Ollama Settings, LoggedOllamaClient & Codeblock Diff Matching

**Issue**: [#73](https://github.com/Willmo103/kb-web/issues/73)  
**Branch**: `feature/workspace-ollama-settings-and-diff-fix`  
**Base**: `production`  

---

## 1. Problem Analysis & Root Cause

1. **`LoggedOllamaClient` missing `generate`**:
   - `LoggedOllamaClient` in `src/kb_web/base.py` implements `pull`, `push`, `list`, `chat`, and `embeddings`. It does not implement `generate`.
   - When `src/kb_web/routers/workspaces.py` called `client.generate(...)`, it threw `AttributeError: 'LoggedOllamaClient' object has no attribute 'generate'`.
   - Furthermore, `LoggedOllamaClient` did not define `__getattr__`, so any standard method on `ollama.Client` not explicitly defined raised an AttributeError.

2. **Mock Simulation Fallback Generating Fake Diff Actions**:
   - In `src/kb_web/routers/workspaces.py`, the `except Exception as e` block in `agent_chat_api` returned a simulated template with ````file:app.js\n// Generated sample...```` whenever any exception occurred.
   - When the client received this, `parseAndAttachDiffActions` found `file:app.js` and rendered `Action: app.js [Review Diff] [Apply]`, misleading the user into thinking the agent proposed an unwanted modification to `app.js`.

3. **Static Model Input instead of Dynamic `/tags` Discovery**:
   - In `workspace_ide.j2.html`, the model setting was a static `<input type="text" id="settingOllamaModel">` defaulted to `ornith:9b` or `{{ ollama_model }}`.
   - Users cannot see or select which models are currently downloaded on their local Ollama server.
   - Ollama exposes `GET /api/tags` (or `client.list()`), which lists all installed models.

4. **Diff Action Matching Logic**:
   - `parseAndAttachDiffActions` checks for codeblocks, but need strict validation:
     - Must only match if the code block starts with `file:<path>` or language class is `language-file:<path>`.
     - `targetPath` must be a valid file name and path (must have a valid extension, no invalid characters).
     - If the code block is just ordinary markdown or standard code (e.g. ````python`), no diff action card should be rendered.

---

## 2. Proposed Changes

### Component 1: `src/kb_web/base.py`
- Add `def generate(self, *args, **kwargs)` to `LoggedOllamaClient`:
  - Calls `self._client.generate(*args, **kwargs)` with execution duration measurement.
  - Extracts response text safely (`resp.response` or `resp["response"]`).
  - Logs the call details to the database table `ollama_logs` under `prompt_type="generate"`.
  - Handles and logs exceptions properly.
- Add `def __getattr__(self, name)`:
  - Forwards any unhandled calls directly to `self._client` so no standard method is blocked.

### Component 2: `src/kb_web/routers/workspaces.py`
- Update `agent_chat_api`:
  - Support both `client.chat` (preferred for chat-tuned models with structured messages) and `client.generate`.
  - Handle conversation context cleanly.
  - On error / exception: return `{"status": "error", "reply": f"Ollama connection error: {str(e)}", "model": model_name}` without injecting fake ````file:app.js```` code blocks.
- Add endpoint `GET /api/workspaces/models`:
  - Calls `_get_ollama_client().list()` (which queries Ollama `/api/tags`).
  - Returns `{"models": [{"name": m.get("name") or m.get("model"), "model": m.get("model") or m.get("name")} for m in models]}`.

### Component 3: `src/kb_web/templates/workspace_ide.j2.html`
- **Dynamic Model Selector**:
  - Add a model `<select id="workspaceAgentModelSelect">` directly in the AI Assistant header and in the Settings modal.
  - On workspace load, fetch `/api/workspaces/models` and dynamically populate the dropdown with available models.
  - Select `{{ ollama_model }}` or active model by default.
  - Add a refresh button next to the dropdown to re-fetch models on demand.
  - Sync the selected model with `ollamaConfig.model` and `localStorage`.
- **Strict Diff Action Matching**:
  - Refine `parseAndAttachDiffActions`:
    - Only attach action cards when `targetPath` matches a strict file path pattern (e.g. `^[a-zA-Z0-9_\-\./]+\.[a-zA-Z0-9]+$`).
    - Exclude standard programming language identifiers (e.g. `python`, `javascript`, `html`, `css`, `json`, `bash`, `sh`, `sql`, `text`).
    - Remove the `file:` prefix from the displayed code block cleanly so the user doesn't see a raw `file:path` header in their preview.
    - If no valid formatted file code block is present, do NOT create or render an action card.

### Component 4: Testing & Verification
- Add unit tests in `tests/test_sprint6_features.py` or new test file for:
  - `LoggedOllamaClient.generate` logging and response retrieval.
  - `GET /api/workspaces/models` endpoint returning installed models.
  - `POST /api/workspaces/{id}/agent/chat` handling responses and clean errors without hallucinated mock diffs.
- Run `verify_ui_templates.py`.
- Run `build.py` and `pytest`.

---

## 3. Execution Plan
1. Open Draft PR #74 for Issue #73.
2. Update `src/kb_web/base.py` (`generate` and `__getattr__` on `LoggedOllamaClient`).
3. Update `src/kb_web/routers/workspaces.py` (model listing endpoint, chat call, clean error handling).
4. Update `src/kb_web/templates/workspace_ide.j2.html` (dynamic model dropdown from `/tags`, strict diff block matching).
5. Add and run automated tests.
6. Run template and build verifications.
7. Generate VCS UAT artifacts, documentation, and push.
