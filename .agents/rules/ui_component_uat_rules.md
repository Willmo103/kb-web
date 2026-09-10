# UI Component User Acceptance Testing (UAT) Rules

This document establishes strict rules for testing user interface (UI) components in `kb-web` prior to committing any changes to version control.

---

## 1. Mandatory Pre-Commit UI UAT Verification
- **No Direct UI Commits**: Agents MUST NOT commit changes to Jinja2 templates (`src/kb_web/templates/`), CSS stylesheets, JavaScript files, or browser extension UI components (`browser_extension/`) without executing local User Acceptance Testing (UAT).
- **Scope of Verification**:
  1. **Web Dashboard & Profile Views**: Ingestion feed (`/`), page profile view (`/pages/{id}`), tag editor, and collections portal.
  2. **Admin & Settings Portal**: Passcode verification, prompt editor, Gotify/Ollama settings, and API key manager.
  3. **PWA & Chrome Extension**: Mobile share target, extension popup badge status, and options page.

## 2. Aesthetics & Layout Pass Criteria
- **Solarized Light**: Background `#fdf6e3`, card headers `#eee8d5`, text `#586e75`, accents `#cb4b16` (orange) / `#2aa198` (turquoise).
- **Retro Dark**: Background `#002b36`, card containers `#073642`, text `#93a1a1`.
- **Zoom Compatibility**: Interfaces must remain clean, unclipped, and readable at 70% zoom on wide displays and responsive down to mobile viewports.

## 3. UAT Execution Process
1. Launch local test server (`uv run kb-web serve --port 8050`).
2. Run automated template & route verification (`uv run python .agent/skills/ui-component-uat-check/scripts/verify_ui_templates.py`).
3. Present custom HTML feedback page to the user (`collect-uat-feedback-and-create-issues`).
4. Generate VCS testing artifact report (`generate-uat-testing-artifact`).
5. Only commit after all UAT issues are resolved and verified.
