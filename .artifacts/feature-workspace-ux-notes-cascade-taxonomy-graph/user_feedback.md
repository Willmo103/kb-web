# User Feedback Log

**Date**: October 06, 2026
**Branch**: `feature/workspace-ux-notes-cascade-taxonomy-graph`
**Source**: Field usage review and user notes recorded during production testing.

---

## 1. Recorded Feedback Items

1. **Notes Deletion Broken**: Foreign key constraint failures occur when deleting notes because multiple dependent tables (`chat_conversations`, `chunk_embeddings`, `taxonomy_items`, `collection_items`, `article_embeddings`, `title_embeddings`, `fetched_pages`) point to note URLs and IDs without cascading deletes.
2. **Workspace README.md Formatting**: The formatting of `README.md` files in newly created workspaces is malformed or displays broken markdown without live rendered markdown preview.
3. **Prompt-Driven Workspace Generation**: Users want to enter a text prompt to have an AI agent automatically invent the project type, architecture, initial files, and executable code for a new workspace.
4. **Flexible Project Types (Gist & Arbitrary)**: Eliminate the strict 3-type project restriction (`web-game`, `python-demo`, `blank`). Support arbitrary project types and general multi-file Gists, while preserving execution runners for Python WASM and HTML/JS sandboxes and markdown rendering.
5. **Real-time Ollama Loaded Models Display**: Users need to see which Ollama models are *currently loaded in VRAM/memory* (via `/api/ps`) across all model selectors and settings interfaces in the UI with a distinct visual indicator.
6. **Targeted Notes Re-Taxonomy Classification**: Provide a dedicated action/endpoint to re-trigger taxonomy classification specifically on unclassified notes (with optional vault targeting and re-classification override).
7. **Workspace Folders UI/UX**:
   - Folders currently display raw `(foldername)/.keep` as a flat file string.
   - Must display hierarchical folder trees with folder icons (`📁`).
   - Folder contents must be collapsible.
   - Files must be reorganizable via drag-and-drop into and out of folders.
8. **Taxonomy Slug Collision Retry Loop & Graph Harness**:
   - The taxonomy agent creates duplicate category slugs, causing unique constraint database crashes.
   - Catch slug collisions and re-prompt the AI in a feedback loop with the error `slug with that name already exists`.
   - Process should be graph-driven with error feedback to locate the optimal taxonomical path and re-classify/re-order items.
9. **Taxonomy Source Metadata Enrichment**:
   - Enrich the item state passed to the taxonomy agent with source metadata: Collection, Age, Version, Source URL, Vault name, Folder path, and syntax.

---

## 2. Action Plan Alignment
All 9 items will be addressed in a cohesive vertical slice covering database cascading, workspace UI/backend enhancements, Ollama model introspection, and taxonomy state machine graph harness improvements.
