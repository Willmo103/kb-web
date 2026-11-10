# User Feedback - Documentation & Codebase Audit (`docs`)

## Date: 2026-11-10
## Branch: `docs` (branched from `master`)

### User Request:
"create a new branch from main 'docs' where the ./docs folder will be fully fleshed out using the artifacts and examining the codebase. EVERY INCH of code needs documentation I also want to map the codebase and look for dangling code that can be removed and archived."

### Key Objectives & Requirements:
1. **Branch Creation**: Create and work on branch `docs` branched off `master` (the repository's primary release trunk).
2. **Comprehensive `./docs` Documentation**:
   - Flesh out `./docs` into a multi-section technical knowledge repository documenting every module, subsystem, workflow, and data structure across `kb-web`.
   - Synthesize architectural decisions and historical context from past iteration artifacts (`.artifacts/`), release logs, and the living codebase.
   - Provide exhaustive module-by-module documentation covering all core files, routers, background worker jobs, agent harnesses, context mesh, taxonomy engine, evaluations, and CLI/MCP integrations.
3. **Codebase Mapping**:
   - Provide an exhaustive codebase directory and file map detailing lines of code, responsibilities, dependencies, key functions/classes, and call flows for all 67+ Python files and associated templates/scripts.
4. **Dangling & Dead Code Audit**:
   - Analyze the codebase for deprecated pathways (e.g. SQLite legacy pathways being superseded by PostgreSQL, legacy category clusters state machine vs steered tree, unreferenced router methods, orphan tables, unused helpers).
   - Document specific candidates for pruning and safe archival.

