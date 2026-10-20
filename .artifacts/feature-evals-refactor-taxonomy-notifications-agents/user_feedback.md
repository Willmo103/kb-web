# User Feedback & Comprehensive Requirements

**Date**: 2026-10-19  
**Branch**: `feature/evals-refactor-taxonomy-notifications-agents`

---

## 1. Autonomous Custom Agent System ("Mini OpenClaw")
- **Conceptual Model**: A custom agent is distinct from background workflow processes. It has its own **agency** to manage a designated topic or domain (e.g., personal data, code docs, news, static personal info).
- **Self-Directed Context & Working Memory**:
  - Starts with a user-supplied guiding system prompt.
  - Builds its own context, records observations, creates working notes, and formulates its own task list in the background.
- **Two Distinct Page Entities**:
  1. **`TopicWikiPage`**:
     - Represents a structured page in the agent's curated domain wiki.
     - Stores logical path (`logical_path` / slug), title, markdown body, internal wiki links (`links_json`), and explicit references (`references_json`) citing main library articles/notes/videos.
     - Renders with a curated wiki base template featuring sidebar path navigation, breadcrumbs, and cross-references.
  2. **`AgentPage`**:
     - Dynamic canvas page created by the agent, accessible via URL using an ID hash.
     - Can be permanent or temporary (with optional expiration).
     - Supports two render modes:
       - **Themed Mode**: Uses the site's inherited base template with styling and theme support.
       - **Raw Mode**: Pure raw HTML document without the inherited base template, giving the agent complete canvas freedom.
       - Interactive forms/inputs to collect user responses or grant approvals.
- **Steered Grounding & Controlled Discovery**:
  - Can steer grounding processes to generate/regenerate immutable indices and synthetic evaluation pairs for its chosen topic.
  - Can discover and import links strictly selected from already imported items (no random unanchored external crawling).
- **Local Python Kernel with Human-in-the-Loop Approval**:
  - Capability to execute python scripts/commands in the local `.venv` environment (`.venv/Scripts/python.exe` / `.venv/bin/python`).
  - Strict security guard: **Requires explicit user approval** before any proposed function or command is executed.
- **Proactive User Notifications**:
  - Ability to send push/gotify/web notifications to the user.
  - Specifically pairs with the dynamic page generator to send an interactive form and collect immediate user decisions or approvals.

---

## 2. Evals Studio Refactoring & Per-Model Options
- **Model Type Filtering**:
  - Isolate models by type: only display completion/chat LLMs on LLM evals; only display decision/SystemOne models on Decision evals; only display vector embedding models on Embedding evals.
- **Per-Model Parameter Configuration**:
  - Allow configuring separate temperature, prompt, and generation parameters (`temperature`, `top_p`, `top_k`, `num_predict`, `num_ctx`) per model.
  - Include informative hover tooltips explaining the behavior and trade-offs of each parameter.
- **Free-Form Evaluation & Empty Prompts**:
  - Decouple from fixed predefined use-cases; allow general free-form evaluation of LLM, Decision, and Embedding models.
  - Allow inserting a new **EMPTY prompt** for custom scratchpad testing alongside system presets.
- **"Set As..." Prompt Promotion**:
  - Provide a `Set As...` button on each prompt card within the Evaluation Studio to directly apply/promote a tested prompt to a server system prompt or agent configuration.

---

## 3. Notes Deletion & Taxonomy Folder Pruning
- **Defect**: When notes are deleted from the server, empty taxonomy categories and folders that contained them remain behind as orphaned stubs.
- **Requirement**: When notes are deleted, automatically inspect their taxonomy categories and prune empty folders (cascade cleanup of orphaned taxonomy nodes).

---

## 4. Notifications Reviewable in Perpetuity
- **Requirement**: Notifications must be reviewable in perpetuity until explicitly deleted by the user.
- **Capability**: Provide a persistent notifications view/history where past notifications remain accessible, with read/unread indicators, filtering, and explicit deletion controls.
