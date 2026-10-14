# Walkthrough - AI Agent Personas & System Prompt Studio (Issue #92)

## Overview
This feature exposes all system message strings, agent persona prompts, and curation prompt templates across the `kb-web` application directly into the Admin Portal (`/admin#tab-prompts`), satisfying **Rule 7 (Strict Configuration Transparency & Admin Exposure)**.

Rather than simple plain textareas, the Prompt Studio provides a full in-browser Markdown editing studio equipped with Monaco Editor, categorized navigation, Obsidian-style real-time Markdown rendering, version rollback, and REST endpoints for live re-configuration.

---

## Changes Implemented

### 1. Configuration & Storage (`src/kb_web/config.py`)
- Exposed all 10 non-numerical system instructions and persona prompts:
  1. `wiki_prompt`: Wiki Extraction & Markdown Synthesis
  2. `youtube_wiki_prompt`: YouTube Video Breakdown & Quotes
  3. `tags_prompt`: AI Tag Taxonomy & Keywords
  4. `ontology_synthesis_prompt`: Domain Ontology Synthesis
  5. `rag_system_prompt`: Collection Knowledge Assistant (RAG)
  6. `rag_report_prompt`: Research Report Synthesis
  7. `taxonomy_system_prompt`: Hierarchical Filetree Taxonomist
  8. `maintenance_agent_prompt`: Site Maintenance & Error Diagnostics
  9. `workspace_agent_prompt`: Workspace Autonomous Coding Assistant
  10. `article_chat_prompt`: Article Document Reading Assistant
- Added automatic versioning in the `AgentPrompt` table (via `_set_agent_prompt` incrementing `version` and setting `is_head=1`).
- Persisted active prompts to `kb-web.json` on `config.save()`.
- Implemented `config.get_all_prompts()` returning full prompt registry metadata (id, label, name, category, description, value, default).

### 2. Consuming Modules Updated
- `src/kb_web/utils.py`: `extract_tags_content` now queries `getattr(config, "tags_prompt", DEFAULT_TAGS_PROMPT)`.
- `src/kb_web/maintenance_agent.py`: `diagnose_server_error` uses `getattr(cfg, "maintenance_agent_prompt", DEFAULT_MAINTENANCE_AGENT_PROMPT)`.
- `src/kb_web/rag_agent.py`: `compile_rag_report` uses `getattr(config, "rag_report_prompt", DEFAULT_RAG_REPORT_PROMPT)`.
- `src/kb_web/workspace_agent.py`: `run_workspace_agent_turn` uses `getattr(config, "workspace_agent_prompt", DEFAULT_WORKSPACE_AGENT_PROMPT)`.
- `src/kb_web/routers/conversations.py`: `article_conversation_chat_endpoint` uses `getattr(config, "article_chat_prompt", DEFAULT_ARTICLE_CHAT_PROMPT)`.
- `src/kb_web/taxonomy_state_machine.py`: `_synthesize_inaugural_domain` and `_synthesize_new_category` use `getattr(config, "ontology_synthesis_prompt", DEFAULT_ONTOLOGY_SYNTHESIS_PROMPT)`.

### 3. REST API Endpoints (`src/kb_web/routers/admin.py`)
- `GET /api/config/prompts`: Returns all 10 configured prompts with current values and defaults.
- `POST /api/config/prompts`: Accepts `{ "prompt_id": str, "prompt_text": str, "reset_default": bool }` to dynamically update or reset any prompt.
- Generalized `/admin/prompts/set-head` to support rolling back any prompt type to an earlier revision.

### 4. Admin Portal UI Refactor (`src/kb_web/templates/admin.j2.html`)
- Replaced basic form textareas in `tab-prompts` with a full-width **AI Agent Personas & System Prompt Studio**:
  - **Sidebar Navigator**: Search filter, categorized prompt cards (`Curation`, `Research & Architecture`, `Diagnostics & Coding`), and modification state badges (`Default` vs `Customized`).
  - **Monaco Editor**: Syntax-highlighted Markdown editing, automatic layout recalculation when switching admin tabs, line/char count stats, and keyboard shortcut `Ctrl+S`/`Cmd+S`.
  - **Obsidian Live Markdown Preview**: Real-time rendering powered by `marked.js` with styled headers, code blocks, tables, and blockquotes.
  - **View Controls**: Toggle between Split View, Editor Only, and Preview Only.
  - **Action Toolbar**: `Save Prompt`, `Reset Default`, and `Copy to Clipboard`.
  - **Version History Drawer**: Displays past revisions with date timestamps and one-click "Restore Version X" buttons.

---

## Verification Results

### Unit Tests (`uv run pytest tests/test_system_prompts_admin.py -v`)
- `test_config_registry_contains_all_ten_prompts`: PASSED
- `test_agent_prompt_versioning_and_persistence`: PASSED
- `test_api_get_prompts`: PASSED
- `test_api_update_prompt_and_reset_default`: PASSED
- `test_api_update_prompt_validation`: PASSED
- `test_admin_portal_renders_prompt_studio`: PASSED

### Full Test Suite & Build Pipeline
- `uv run pytest`: **186 passed** across 17 test modules.
- `verify_ui_templates.py`: **0 warnings** across all 25 Jinja2 templates.
- `uv run python build.py`: **SUCCESS**.
