# Agent Working Memory

This directory stores durable contextual memories, package notes, configuration caveats, and operational lessons learned by AI agents while working across the `kb-web` repository.

## Purpose & Guidelines
1. **Durable Knowledge Retention**: While general architecture is tracked in `GEMINI.md` and `README.md`, specific edge cases, platform gotchas (Windows/Linux/Docker), package quirks (`yt-dlp`, `monaco`, `alembic`, `qdrant`), and command-line guardrails should be recorded here.
2. **Be on the lookout**: Whenever an unexpected bug, tricky dependency conflict, non-obvious API requirement, or subtle operational rule is encountered, agents MUST record or update a corresponding memory document in this directory.
3. **Format**: Use clear, concise markdown documents categorized by domain, package, or component.

## Index of Memories
- [package_caveats.md](file:///c:/src/kb-web/.agents/memory/package_caveats.md) — Known quirks and gotchas for core dependencies (`yt-dlp`, `jinja2`, `sqlite3`/PostgreSQL, `monaco`, `hmac`).
- [github_cli_guardrails.md](file:///c:/src/kb-web/.agents/memory/github_cli_guardrails.md) — Safe patterns and guardrails for `gh` CLI invocations.
