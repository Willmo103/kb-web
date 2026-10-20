# PR: Evals Studio Overhaul, Taxonomy Pruning, Perpetual Notifications, and Custom Topic Agents

## Overview
This PR delivers four coordinated feature tracks:

1. **Evals Studio Overhaul & Prompt Promotion (`/evals`)**:
   - Model capability filtering across tabs: Chat/Completion LLMs on Tab 1, Decision models (`d1`, `tev1`) on Tab 2, Vector Embedding models on Tab 3.
   - Per-model generation parameter overrides drawer (`temperature`, `top_p`, `top_k`, `num_predict`, `num_ctx`) with hover tooltips and dynamic parameter propagation into SSE streams.
   - Free-form evaluation scratchpad with "+ Add Empty Prompt".
   - "Set As... ▾" button on prompt cards backed by `POST /api/evals/prompts/promote` to promote tested prompts directly into server instructions or custom agents.

2. **Recursive Bottom-Up Taxonomy Category Pruning**:
   - Deleting individual notes (`DELETE /api/notes/{id}`) or batch deleting notes (`DELETE /api/notes/batch`) recursively cleans empty parent categories bottom-up, preventing lingering empty taxonomy stubs.

3. **Perpetual Ingestion Notifications & History Portal (`/notifications`)**:
   - Notifications remain perpetually until explicitly deleted.
   - Dedicated management view with pagination, filters by stage and status, read/unread state, keyword search, per-item delete, and batch delete (`DELETE /api/notifications`).
   - "View All History →" shortcut in the top navigation bell dropdown.

4. **Autonomous Topic-Expert Custom Agent System ("Mini OpenClaw")**:
   - `TopicWikiPage`: Curated living domain wiki pages with logical paths, navigation trees, and article citations (`/wiki/{agent_id}/{path}`).
   - `AgentPage`: Dynamic agent canvas reachable by hash token (`/pages/agent/{hash_id}`), supporting both `themed` mode (with site chrome and interactive forms) and `raw` mode (pure unstyled HTML).
   - Strict Human-In-The-Loop (HITL) local Python execution kernel (`python_kernel.py`) in `.venv`, requiring explicit human approval before execution.
   - Grounding discovery strictly restricted to already-imported library items.
   - Dedicated Decision Gating Questions & Criteria JSON editor in Admin Portal Agent Configurations.

## Verification
- `verify_ui_templates.py`: All 29 HTML templates verified (0 warnings).
- `pytest`: All 236 tests passing (including 19 new tests across 4 test files).
- `build.py`: Pre-commit pipeline completed successfully.
- VCS UAT reports generated in `uat/reports/`.
