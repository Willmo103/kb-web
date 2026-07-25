---
name: document-code-issue-and-fix
description: Documents code bugs, root-cause analyses, and resolution details in CHANGELOG.md and repository docs.
---
# Document Code Issue and Fix Skill

Use this skill whenever a bug, defect, or unexpected runtime issue is encountered and resolved in `kb-web`.

## Execution Steps

1. **Record Root Cause**:
   Document the exact trigger, exception log line, file path, and line numbers responsible for the bug.

2. **Document Resolution**:
   Detail the fix applied (e.g. schema migration, route guard update, LLM output sanitization).

3. **Update CHANGELOG.md**:
   Add an entry under the `[Fixed]` section in `CHANGELOG.md`.

4. **Add Unit Test**:
   Ensure a pytest regression test is added in `tests/test_server.py` to prevent future regressions.
