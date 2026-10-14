# Implementation Plan: Expose System Messages & Prompts in Admin Portal with Monaco Editor & Markdown Live Preview

## Problem Statement & Goals
Previously, only numerical operational limits (such as `taxonomy_batch_limit`, `rag_search_top_k`, and `ollama_timeout`) were exposed in the Admin Portal under Rule 7 configuration transparency. All prompt templates, LLM system instructions, and task messages remained hardcoded across various modules (`utils.py`, `rag_agent.py`, `maintenance_agent.py`, `workspace_agent.py`, `conversations.py`, `taxonomy_state_machine.py`), preventing administrators and users from tweaking agent behaviors, tones, or extraction guidelines without code edits.

Furthermore, the existing Admin "Prompts & Generation" tab relied on basic `<textarea>` fields inside click-to-edit modals, offering no syntax highlighting or preview.

### Target Objectives
1. **Comprehensive System Prompts & Messages Registry (`src/kb_web/config.py`)**:
   - Extract and define standard default constants for ALL agent system prompts across the system.
   - Expose dynamic getters and setters with database backing (`SettingOllama` / `SettingExternal` in `models_orm.py`) for:
     - `wiki_prompt` (Wiki extraction & sanitization)
     - `youtube_wiki_prompt` (YouTube transcript synthesis & video breakdowns)
     - `tags_prompt` (Topic taxonomy keyword extraction)
     - `rag_system_prompt` (Knowledge collection assistant system instruction)
     - `taxonomy_system_prompt` (Ontology folder classification prompt)
     - `rag_report_prompt` (Publication-grade research report synthesis prompt)
     - `maintenance_agent_prompt` (Error diagnostics & root-cause analysis agent prompt)
     - `workspace_agent_prompt` (Autonomous workspace coding agent system instruction)
     - `article_chat_prompt` (Document-grounded reading assistant instruction)
     - `ontology_synthesis_prompt` (Domain wiki synthesis & category generator prompt)
   - Provide a helper `config.get_all_prompts()` returning full metadata (key, title, category, description, active value, default value).

2. **Connect Consuming Components**:
   - Refactor consuming modules to pull the dynamic prompt from `config` with fallback to default constant:
     - `utils.py`: `extract_tags_content` uses `getattr(config, "tags_prompt", DEFAULT_TAGS_PROMPT)`.
     - `rag_agent.py`: `synthesize_research_report` uses `getattr(config, "rag_report_prompt", DEFAULT_RAG_REPORT_PROMPT)`.
     - `maintenance_agent.py`: `diagnose_server_error` uses `getattr(config, "maintenance_agent_prompt", DEFAULT_MAINTENANCE_AGENT_PROMPT)`.
     - `workspace_agent.py`: `run_workspace_agent_turn` uses `getattr(config, "workspace_agent_prompt", DEFAULT_WORKSPACE_AGENT_PROMPT)`.
     - `routers/conversations.py`: `article_conversation_chat_endpoint` uses `getattr(config, "article_chat_prompt", DEFAULT_ARTICLE_CHAT_PROMPT)`.
     - `taxonomy_state_machine.py`: uses `getattr(config, "ontology_synthesis_prompt", DEFAULT_ONTOLOGY_SYNTHESIS_PROMPT)`.

3. **Admin API & Persistence Endpoints**:
   - Update `handle_config_update` in `src/kb_web/routers/admin.py` to accept all prompt fields.
   - Add REST API `GET /api/config/prompts` and `POST /api/config/prompts` in `src/kb_web/routers/admin.py` to allow live AJAX saving and resetting individual prompts.

4. **Admin Portal UI Refactor (`src/kb_web/templates/admin.j2.html`)**:
   - Redesign `tab-prompts` into a modern Studio layout:
     - **Prompt Selector Sidebar / Tabs**: Clean list categorizing prompts by function (Curation, Research & RAG, Diagnostics, Coding & Chat).
     - **Monaco Editor Instance**: Embedded editor with Markdown highlighting (`language: 'markdown'`), line numbers, word wrap, and automatic light/dark theme switching (`vs` / `vs-dark`).
     - **Obsidian-Style Live Preview**: Split-pane rendered Markdown viewer (`marked.js`) dynamically updating in real-time as the user types.
     - **Control Toolbar**: Quick actions for "Save Prompt", "Reset to Default", "Copy to Clipboard", and "Toggle Split Preview".

5. **Testing & Pre-commit Verification**:
   - Create unit tests in `tests/test_system_prompts_admin.py` validating getter/setter DB persistence and API endpoints.
   - Run UI component verification (`verify_ui_templates.py`) and full `pytest`.
   - Merge into `development`.
