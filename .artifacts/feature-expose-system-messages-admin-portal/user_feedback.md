# User Feedback

## Turn Metadata
- **Date/Time**: 2026-10-13T19:07:00-05:00
- **Branch**: `feature/expose-system-messages-admin-portal` (branched off `development`)
- **Reference**: GitHub Issue #92

## User Prompt
```text
okay work the system message issue now. in a new branch. merge to development when done
```

## Relevant Issue Description (Issue #92)
```text
Issue: Expose various system messages in the admin portal
In a recent issue all of the hardcoded values across the project were brought to the admin portal to expose the values to alow for live reconfiguration. This DID NOT capture all of the hardcoded values. it only captured the NUMERICAL values. ALLL of the hardcoded system message and prompt template strings that are parts of the configuration need to be added to the admin portal. The admin portal needs to be refactored to layout the various prompts available to edit iin a better way than a prefilled text area; maybe a tab and a monoco editor. (all prompts and system messages should have markdown hilighting. Ideally if it live rendered the markdown as written like obsidian)
```

## Requirements Extracted
1. **System Messages & Prompt Audit**:
   - Audit all system messages and prompt template strings across the codebase (Wiki extraction, YouTube transcript wiki, Tag taxonomy extraction, RAG Assistant system prompt, Collection taxonomy classification, RAG Research Report synthesis, Site Maintenance error diagnosis, Coding Assistant workspace agent, Document article chat, and Domain ontology wiki synthesis).
   - Expose each system message and prompt string to `config.py` with database backing via `SettingOllama` / `SettingExternal` so they can be modified live without server restarts.
   - Update consuming modules (`utils.py`, `rag_agent.py`, `maintenance_agent.py`, `workspace_agent.py`, `conversations.py`, `taxonomy_state_machine.py`) to use `config.<prompt_name>` with fallback to default constants.
2. **Admin Portal UI & UX Refactor (Prompts & System Messages)**:
   - Refactor the "Prompts & Generation" tab in `/admin` (`admin.j2.html`).
   - Replace basic textareas with a modern, tabbed/list prompt selector and embedded **Monaco Editor** configured for Markdown syntax.
   - Add an **Obsidian-style live split preview** displaying real-time rendered Markdown next to / below the editor as the user types.
   - Add "Save Prompt", "Reset to Default", and "Copy to Clipboard" controls.
   - Support updating each prompt via `POST /admin/config` or a dedicated REST endpoint `POST /api/config/prompts`.
3. **Testing & Pre-commit Verification**:
   - Ensure pre-commit checks (`uv run pytest`, template verifier) pass.
   - Merge to `development` when verified.
