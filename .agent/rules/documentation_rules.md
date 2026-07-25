# Self-Documentation & Documentation Rules

Agents working in `kb-web` are required to maintain strict self-documentation standards. Code edits without corresponding documentation updates are incomplete.

---

## 1. Mandatory `CHANGELOG.md` Updates
- Every pull request, feature iteration, refactor, or bug fix MUST include an entry in `CHANGELOG.md` under the appropriate release header.
- Categorize updates using clean headings: `Added`, `Changed`, `Fixed`, `Removed`, or `Security`.

## 2. Synchronization of `README.md` and `GEMINI.md`
- **`README.md`**: Update whenever CLI commands, service options, environment variables, or extension setup instructions change.
- **`GEMINI.md`**: Update whenever internal architecture, new route modules (`src/kb_web/routers/`), database schemas, or development workflows evolve.

## 3. Documenting Bug Fixes & Code Issues
- When resolving a code defect, agents MUST log the root cause, original error traceback, and resolution methodology using the `document-code-issue-and-fix` skill.

## 4. Preserving Comments & Inline Context
- Preserve all existing code docstrings, type annotations, and descriptive comments unless the target code logic is explicitly rewritten or removed.
