---
trigger: always_on
---

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

## 5. Mandatory Implementation Plan Presentation
- Whenever an implementation plan is created or updated and saved in `./.artifacts/`, the agent MUST ALWAYS present the implementation plan directly to the user in the response immediately after saving it in the artifacts folder, before asking for confirmation or proceeding to write code. (use the `present` tool **always** for this action)

## 6. Agent Working Memory Guidelines (`.agents/memory/`)
- AI agents MUST maintain and consult the `.agents/memory/` directory for technical lessons learned, edge cases, and environment-specific gotchas.
- **Record specific package issues**: Whenever a non-obvious bug, package limitation, or configuration trap is solved (e.g. `yt-dlp` stream selection, `hmac` string encoding, Windows CLI path quoting), the agent MUST record the root cause and guardrails in a memory file under `.agents/memory/`.
- **Be on the lookout**: Agents should proactively look out for knowledge, recurring patterns, and failure modes that could aid future agent turns, capturing them in memory files for durable cross-session recall.

