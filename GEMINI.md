# kb-web - Agent Instruction Guide

Welcome, Agent! This `GEMINI.md` file is the master instruction guide for the `kb-web` package. It outlines the package architecture, development standards, history, agent rules, and self-documentation workflow.

---

## Agent Initialization Rules

> [!IMPORTANT]
> **1. Understand Development Status on Initialization**
> Upon working in this repository, you MUST read and understand the current package status, past release iterations (v5 through v8), and architecture by reviewing this `GEMINI.md` file and `README.md`.
>
> **2. Public Documentation & Secrets Policy**
> This repository is **PUBLIC**. Never document or commit sensitive configuration details, private credentials, production tokens, or personal environment information.
>
> **3. Gated Pre-Commit & Build Verification**
> Before committing changes or submitting work for User Acceptance Testing (UAT), you MUST run pre-commit verification checks (`uv run pytest`, `uv run python build.py`) to guarantee that all unit tests pass and build artifacts compile cleanly. When running tests locally, ensure Gotify alerts are disabled to avoid spamming notification channels (by default, `kb_core.notifier.Gotify` is globally mocked in `tests/test_server.py`, but you can also unset `GOTIFY_URL` and `GOTIFY_TOKEN` in your shell environment).
>
> **4. Mandatory Self-Documentation Policy**
> Before completing any task iteration, feature addition, or bug fix, you MUST:
> - Document all user-facing and technical changes in `CHANGELOG.md` under the current version header.
> - Keep `README.md` updated with any CLI, service, configuration, or environment changes.
> - Update this `GEMINI.md` file if architecture, routes, or workflows evolve.
> - Log root causes and fixes using the `document-code-issue-and-fix` skill.
>
> **5. Strict Pre-Commit UI UAT & Artifact Verification**
> All UI modifications MUST undergo local User Acceptance Testing (UAT) before committing. You MUST:
> - Run template & theme verification (`ui-component-uat-check`).
> - Gather user feedback using interactive custom HTML forms (`collect-uat-feedback-and-create-issues`).
> - Automatically parse form JSON into actionable agent issues (`parse_uat_issues.py`).
> - Generate and commit VCS testing artifacts in `uat/reports/` (`generate-uat-testing-artifact`).

---

## Package Overview & Ecosystem Role

`kb-web` is the central web ingestion portal, PWA target, Chrome browser extension endpoint, and knowledge curation app in the `kb` (Knowledge-Base) suite. It enables users to:
1. **Ingest Web Content**: Ingest URLs via PWA share target, Chrome browser extension, or direct API endpoint (`/api/import/html`).
2. **AI Wiki & Tag Curation**: Clean and restructure scraped pages into clean markdown wiki entries with Ollama LLMs and assign curated tags.
3. **Vector & Semantic Search**: Index and search web knowledge using Qdrant vector database and EmbeddingGemma models.
4. **Virtual Sites & Links**: Group related ingested URLs into virtual domain portals and custom link collections.
5. **YouTube & Media Tools**: Extract metadata, transcripts, and video details using `yt-dlp` and `ffmpeg`.
6. **MCP & REST Endpoints**: Expose Model Context Protocol (MCP) server endpoints (`kb-web-mcp.service`) and standardized REST endpoints (`/api/articles`, `/api/videos`, `/api/sites`, `/api/tags`) for external AI agents and frontend consuming.
7. **Database View & Pagination**: Serve indexed web cards via pre-aggregated PostgreSQL view `vw_page_cards` with responsive UI pagination. Note: SQLite is being phased out in favor of PostgreSQL.

---

## Local Agent Rules (`.agent/rules/`)

- [development_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/development_rules.md): Monorepo spirit, vertical slices, SQLite/Pydantic, Typer CLI + daemons.
- [documentation_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/documentation_rules.md): Self-documentation, changelog policies, and README sync.
- [python_coding_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/python_coding_rules.md): FastAPI, Pydantic, Qdrant, Ollama, and test standards.
- [git_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/git_rules.md): Git branching, commit formatting, and working tree standards.
- [uat_and_ui_testing_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/uat_and_ui_testing_rules.md): Pre-commit UI UAT overview & testing artifact standard.
- [ui_component_uat_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/ui_component_uat_rules.md): Strict UAT rules for Jinja2 templates, CSS, PWA & Extension UI.
- [vcs_testing_artifact_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/vcs_testing_artifact_rules.md): VCS testing artifact generation and commit requirements (`uat/`).
- [custom_html_feedback_rules.md](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/rules/custom_html_feedback_rules.md): Interactive HTML form feedback collection & issue parser workflow.

---

## Local Agent Skills (`.agent/skills/`)

- [collect-uat-feedback-and-create-issues](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/skills/collect-uat-feedback-and-create-issues/SKILL.md): Generates interactive HTML feedback form, parses JSON form response into agent issues via `parse_uat_issues.py`.
- [generate-uat-testing-artifact](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/skills/generate-uat-testing-artifact/SKILL.md): Generates VCS testing logs and reports in `uat/` via `generate_uat_report.py`.
- [ui-component-uat-check](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/skills/ui-component-uat-check/SKILL.md): Pre-commit automated template & theme check via `verify_ui_templates.py`.
- [pre-commit-checks](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/skills/pre-commit-checks/SKILL.md): Runs `uv sync`, `pytest`, `ruff`, and `build.py`.
- [document-code-issue-and-fix](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/skills/document-code-issue-and-fix/SKILL.md): Formats changelog logs and bug fix records.
- [kb-web-browser-extension](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/skills/kb-web-browser-extension/SKILL.md): Extension testing & configuration.
- [kb-web-service-management](file:///c:/Users/Will/Desktop/will_mono/remotes/kb-mono/remotes/kb-web/.agent/skills/kb-web-service-management/SKILL.md): Systemd service configuration.

## Chat Turn Instructions

- Artifacts: All artifacts (`implimantation_plan.md`, `walkthrough.md`, etc.) should always be saved in the `./.artifacts` folder in the root of the project.
 - a *subfolder* should be created for the specific action that is being taken; e.g. `/.artifacts/feature-001/` This should **match the git branch from the `production` branch that the feature or fix is being developed on**.
 - All files should be in **Markdown** format with clear headings and sections.
 - all user feedback for the given turn should be documented as `user_feedback.md` in the artifacts folder. This should be done **before** any code is changed or committed. If no feedback is received, then this file should still be created and documented as such.
