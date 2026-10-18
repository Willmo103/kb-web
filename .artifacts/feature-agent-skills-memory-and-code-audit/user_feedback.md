# User Feedback — feature/agent-skills-memory-and-code-audit (2026-10-17)

## Task 1 — Agent skills & memory
- Examine the last sessions' logs for things that should become simple skills, or that should expand existing skills.
- `gh` CLI is used heavily → create dedicated **but generalized** skills that:
  1. Add guardrails to destructive or consequential tasks.
  2. Give more clearly defined output and better logging, for the record and for visibility into actions agents take.
- Start recording `.agent/memory/*.md` files for things worth remembering when encountered.
  - Add a rule to record issues for specific packages or settings as new memories.
  - Add a broader guideline: watch for anything that *should* be remembered to help future sessions.

## Task 2 — Code audit
- Audit for bugs, misconfigurations, HTML errors, insecure configurations, dead or outdated features, and speed/efficiency optimizations.
- Deliver a **single-page interactive HTML presentation** of findings and recommendations, including the exact issue text to post to the repo.
- The user can check or uncheck issues, then submit the selection to GitHub (or otherwise send the selection back to the model).

## Task 3 — Bug fix
- YouTube video downloads seemingly have **no sound**. Videos stored earlier through the download feature **do** have sound when played back in the UI.

## Additional Feedback
None received yet.
