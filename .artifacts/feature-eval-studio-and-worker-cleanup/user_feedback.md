# User Feedback

**Turn Date**: 2026-10-18  
**Branch**: `feature/eval-studio-and-worker-cleanup`  

## User Feedback Received:
> I want to eliminate the remaining placeholder items that I did not directly request a refactor for. Then before we impliment the new worker agents I want to create the eval studio first so that I can side-by-side test out the potential promps and questions I want to use in the the actual workers so that I can know that its working. 
>
> oe more thing; don't we log the ollama model requests seperately? I should be able to review those if they exist in the admin portal. sort of like the grid search in reports. (IGNORE THIS IF OLLAMA LOGS ARE NOT SEPERATELY STORED)
>
> bug: reporting is supposted to display token strings; `[ ... ]` for easing the load on the ui from rendering heavy data, but they are supposted to be *in* the report download.

## User Clarifications:
- **Worker Registry & Admin UI**: Remove Tag Taxonomy Agent (`tag_curation`) from the worker registry and Admin UI, keeping Vector Embedding Indexer.
- **Eval Studio Interface**: Create a dedicated top-level `/evals` page in the navigation bar for prompt, decision, and embedding evaluations.
- **Ollama Logs**: Ollama calls are already tracked in the `ollama_logs` table via `LoggedOllamaClient`. Expose this table in `/reports` and the Admin Portal so requests, options, durations, and responses can be filtered and inspected.
- **Reporting Export Bug**: In `export_report_data()`, ensure exports stream the full un-truncated text rather than the UI preview tokens (`[Content: ... chars]`).
