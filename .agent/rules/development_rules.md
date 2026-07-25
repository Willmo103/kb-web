# Monorepo Development Rules & Core Philosophy

All code written within `kb-web` MUST embody the overarching principles of the Knowledge Base (`kb`) monorepo ecosystem.

---

## 1. Vertical-Slice Package Architecture
- `kb-web` is designed as a standalone, localized vertical slice. It contains its own web ingestion, database schemas, PWA portal, Chrome extension, CLI, vector search, and API routers.
- Avoid introducing tight runtime dependencies on unversioned sibling packages. Shared utilities MUST be imported strictly via standard configuration schemas (`kb-core`).

## 2. Local Database & Schema Standards
- Use `sqlite-utils` paired with `pydantic` schemas for local SQLite storage (`~/.kb/kb.db` or configured target).
- Never perform silent database column mutations without registering migration handlers inside `src/kb_web/db.py`.

## 3. CLI + Daemon Launcher Pattern
- All service launcher functionalities must be exposed via the Typer CLI (`src/kb_web/cli.py`).
- Server processes must support daemonized background execution (e.g. launching background loops via subprocess without keeping open terminals, using `pythonw` or systemd).

## 4. No Symptom Patching & Zero Masking
- **Strict Prohibition**: NEVER swallow exceptions, comment out failing test assertions, or return dummy empty arrays to hide underlying errors.
- If a route, scraping call, or vector index operation fails, trace the root cause back to the upstream data provider or model payload and fix the contract cleanly.

## 5. Design & Aesthetic Palette
- All UI layouts (Jinja2 templates, PWA views, HTML forms) must adhere to the Solarized Light (`#fdf6e3`) and Retro Dark (`#002b36` / `#073642`) palettes.
- Interface components must feature responsive flex/grid styling, crisp fonts, and retro orange (`#cb4b16`) and turquoise (`#2aa198`) accents.
