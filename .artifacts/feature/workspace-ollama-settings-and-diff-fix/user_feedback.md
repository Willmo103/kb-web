# User Feedback & Requirements

**Issue**: [#73](https://github.com/Willmo103/kb-web/issues/73)  
**Branch**: `feature/workspace-ollama-settings-and-diff-fix`  
**Date**: 2026-09-28  

---

## User Request

> "This issue should be closed the branch was merged.
> 
> --- 
> # Next Issue and fix:
> ## Workspace Ollama Settings
> 
> The agent workspace agent is failing it is misconfigured and trying to use the API (from the imported HTML workspace) and the LoggedOllamaClient class (photo attached). The modles should all be pulled from the /tags endpoint, and the Ollama client should be the same one (or JUST the api since it may be using js) but it should work. ALSO the whole matching thing should be fixed (not displayed if there is no formatted file codeblock)"

---

## Attached Screenshot Details
- Interface shows `Agent (gemma4:e4b)` chat card.
- Error message in response:
  > "Note: Ollama server connection was unavailable ('LoggedOllamaClient' object has no attribute 'generate'). Simulated suggestion for 'What do you think of my pythonrc.py terminal file? is there anything you would recommend I change or add (imoports, functions, etc? ...':
  > // Generated sample by AI Agent
  > console.log('Update applied succes
  > [Action: app.js] [Review Diff] [Apply]
  > You can review or apply this change."

---

## Key Requirements Identified

1. **Fix Ollama Client Integration in Workspace Agent**:
   - `LoggedOllamaClient` in `src/kb_web/base.py` lacks a `.generate()` method and lacks delegation via `__getattr__`.
   - Implement `.generate()` on `LoggedOllamaClient` with proper logging to the `ollama_logs` table.
   - Implement `__getattr__` to forward any unhandled method calls directly to the wrapped `ollama.Client`.
   - Update `agent_chat_api` in `src/kb_web/routers/workspaces.py` to use `client.chat` (and/or `generate`) consistently with `conversations.py`.
   - Remove the fallback simulation that injects mock ````file:app.js```` codeblocks on errors.

2. **Ollama Models Pulled from `/tags`**:
   - Models must be dynamically fetched from Ollama's `/tags` (via `client.list()`).
   - Expose an endpoint `GET /api/workspaces/models` (or `/api/workspaces/tags`) returning installed models.
   - Replace the static text input in `src/kb_web/templates/workspace_ide.j2.html` with a dynamic model selector dropdown populated from this endpoint.
   - Add model selector directly in the AI Assistant header so the user can easily see and switch models without opening settings.

3. **Fix File Codeblock Diff Matching**:
   - Ensure the diff action card (`[Action: filename] [Review Diff] [Apply]`) is strictly displayed ONLY when a formatted ````file:<filename>```` code block is returned.
   - Do NOT display diff action cards for general chat, question answers, conversational text, or standard code blocks (e.g. ````python`, ````javascript`).
