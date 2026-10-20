# Implementation Plan: Evals Studio Refactoring, Taxonomy Cleanup, Persistent Notifications, and Autonomous Agent Engine

**Action Directory**: `.artifacts/feature-evals-refactor-taxonomy-notifications-agents/`  
**Git Branch**: `feature/evals-refactor-taxonomy-notifications-agents`

---

## 1. System Overview

This implementation executes four coordinated feature tracks:
1. **Track A: Evals Studio Overhaul & Prompt Promotion (`/evals`)**:
   - Strict model classification across evaluation tabs (LLM, Decision, Embedding).
   - Per-model parameter configuration (`temperature`, `top_p`, `top_k`, `num_ctx`, `num_predict`) with tooltip descriptions.
   - Free-form prompt testing with an "+ Add Empty Prompt" scratchpad button.
   - "Set As..." prompt promotion button to promote tested prompts directly to server configurations.
2. **Track B: Taxonomy Folder Pruning on Note Deletion**:
   - Clean up orphaned taxonomy folders/categories when notes are deleted.
3. **Track C: Persistent Notifications Archive & History Portal (`/notifications`)**:
   - Review notifications in perpetuity until explicitly deleted by the user.
   - Dedicated notification management page with filtering (by stage, status, unread) and individual/batch deletion.
4. **Track D: Autonomous Topic-Expert Custom Agent System ("Mini OpenClaw")**:
   - **`TopicWikiPage` Entity**: Structured domain wiki pages with logical paths, wiki inter-links, and citations back to main library items.
   - **`AgentPage` Entity**: Dynamic canvas pages (themed base template or pure raw HTML mode, temporary or permanent, interactive form schemas).
   - Local Python kernel execution with strict Human-In-The-Loop approval gating.
   - Background deliberation loop to steer grounding, discover links from imported items, and curate topic wikis.

---

## 2. Technical Design & Architecture

### Track A: Evals Studio Overhaul (`src/kb_web/routers/evals.py` & `templates/evals.j2.html`)
1. **Model Classification**:
   - Classify Ollama models so Tab 1 only displays completion LLMs, Tab 2 only displays Decision/SystemOne models (`d1`, `tev1`), and Tab 3 only displays vector embedding models (`embeddinggemma`, `nomic-embed-text`, etc.).
2. **Per-Model Parameters**:
   - In Matrix setup, allow selecting models and configuring independent options per model:
     - `temperature` (Tooltip: Randomness: 0.0 = deterministic; 1.0 = creative).
     - `top_p` (Tooltip: Nucleus sampling probability cutoff).
     - `top_k` (Tooltip: Limits candidate tokens to top K at each step).
     - `max_tokens` (Tooltip: Generation token ceiling).
3. **Free-Form Prompts & "Set As..." Button**:
   - Add "+ Add Empty Prompt" button to initialize a blank prompt card.
   - On each prompt card, add a "Set As..." dropdown button allowing users to promote the tested prompt to `wiki_prompt`, `youtube_wiki_prompt`, or `agent_configurations`.
   - Expose endpoint `POST /api/evals/prompts/promote`.

---

### Track B: Taxonomy Folder Pruning on Note Deletion (`src/kb_web/routers/notes.py` & `admin_batch.py`)
1. In `_cascade_delete_notes()`:
   - Identify all `TaxonomyCategory` records associated with the deleted notes.
   - After deleting `TaxonomyItem` links, recursively inspect affected categories:
     - Check if `category.items` count is 0 AND no child categories exist.
     - If empty, delete the category from `taxonomy_categories`.
     - Recursively check and prune empty parent categories up the tree.

---

### Track C: Persistent Notifications Portal (`src/kb_web/routers/api.py`, `routers/pages.py`, & `templates/`)
1. **Backend**:
   - Update `GET /api/notifications` to support pagination (`offset`, `limit`), filter by `stage`, `status`, and `is_read`.
   - Add `DELETE /api/notifications/{id}` for single notification deletion.
   - Add `DELETE /api/notifications` with filter query to delete specific ranges.
2. **Frontend**:
   - Create template `src/kb_web/templates/notifications_history.j2.html` accessible at `/notifications`.
   - Displays all historical notifications in perpetuity with search, filter pills (All, Unread, Errors, Imports, Curation), and explicit deletion controls.
   - Top navbar bell icon links to `/notifications` with "View Full History".

---

### Track D: Autonomous Custom Agent System ("Mini OpenClaw")
1. **ORM Models (`src/kb_web/models_orm.py`)**:
   - `CustomAgent`: `id`, `name`, `topic_domain`, `system_prompt`, `model`, `status`, `interval_minutes`, `created_at`.
   - `TopicWikiPage`:
     - `id`: integer primary key
     - `agent_id`: string (owning agent)
     - `logical_path`: string (e.g. `architecture/storage`, `notes/quickstart`)
     - `title`: string
     - `body_markdown`: text
     - `links_json`: text (JSON array of internal wiki links)
     - `references_json`: text (JSON array of `{url, title, note_id}` citing library articles)
     - `metadata_json`: text (tags, status, category)
     - `created_at`, `updated_at`
   - `AgentPage`:
     - `hash_id`: string primary key (e.g. 16-character token)
     - `agent_id`: string
     - `title`: string
     - `render_mode`: string (`"themed"` or `"raw"`)
     - `body_content`: text (markdown for themed mode, raw HTML for raw mode)
     - `form_schema_json`: text (optional interactive form fields)
     - `user_response_json`: text (submitted user response)
     - `is_temporary`: integer (0 or 1)
     - `expires_at`: string
     - `created_at`
   - `AgentPythonApproval`: `id`, `agent_id`, `code`, `purpose`, `status`, `output`, `created_at`, `executed_at`.
   - `AgentObservation`: `id`, `agent_id`, `observation_type`, `content`, `source_url`, `created_at`.
   - `AgentSelfTask`: `id`, `agent_id`, `task_description`, `status`, `result`, `created_at`, `completed_at`.

2. **Web Rendering & Endpoints (`src/kb_web/routers/agent_pages.py`)**:
   - `GET /wiki/{agent_id}/{path:path}`: Renders a `TopicWikiPage` within a topic-focused wiki layout (tree sidebar navigation, article references, markdown styling).
   - `GET /pages/agent/{hash_id}`: Renders an `AgentPage`:
     - If `render_mode == "raw"`, returns pure HTML response without site chrome.
     - If `render_mode == "themed"`, renders within the site layout with interactive forms or approval controls.
   - `POST /api/pages/agent/{hash_id}/submit`: Captures form input or approval decision.

3. **Local Python Execution with Human Approval (`src/kb_web/python_kernel.py`)**:
   - Agent proposes code execution -> creates `AgentPythonApproval` record and an `AgentPage` approval link.
   - Dispatches a notification to the user.
   - When user clicks "Approve", executes via `.venv/Scripts/python.exe` and stores stdout/stderr.

4. **Background Agent Engine (`src/kb_web/custom_agent_engine.py`)**:
   - Periodically triggers the agent deliberation cycle:
     - Reviews observations, sets tasks, steers grounding generation for topic pages, imports links found in existing articles, and updates its `TopicWikiPage` articles.

---

## 3. Testing & Verification

1. **Unit Tests**:
   - `tests/test_evals_freeform_and_per_model.py`: Verify model filtering, per-model options, prompt promotion endpoint.
   - `tests/test_notes_taxonomy_prune.py`: Verify deleting notes cleanly prunes empty taxonomy folders.
   - `tests/test_notifications_history.py`: Verify notification pagination, persistence, filtering, and single/batch deletion.
   - `tests/test_custom_agent_pages.py`: Verify `TopicWikiPage` path routing, `AgentPage` themed vs raw rendering, form submission, and Python execution approvals.
2. **UI Verification**: Run `verify_ui_templates.py`.
3. **Pre-commit checks**: `uv run pytest` and `uv run python build.py`.
