# Implementation Plan - Fix Notes Page Modal Freezing & PWA Manifest Warnings

## Problem Analysis
1. **Root Cause of `Uncaught SyntaxError: Unexpected token '.'` and `ReferenceError: openPasteModal is not defined`**:
   - `_jinja_env = jinja2.Environment(loader=jinja2.PackageLoader("kb_web", "templates"))` in `src/kb_web/base.py` lacks `autoescape`. In Jinja2, default autoescape is `False`.
   - When personal notes or Obsidian vault notes contain code snippets, HTML tags, or unclosed script tags, the raw characters (`<script>`, quotes, brackets) are directly injected into the rendered HTML body.
   - Any raw `<script>` tag or broken HTML attribute causes the browser parser to interpret subsequent markup as JavaScript, failing on unexpected tokens like `.` in CSS classes (`notes:2926 Uncaught SyntaxError: Unexpected token '.'`).
   - Consequently, the script tag at the bottom of the template fails to execute, leaving `openPasteModal` and `openVaultUploadModal` undefined when the user clicks button elements at the top of the page.
2. **Missing `enctype` in `manifest.json`**:
   - Chrome requires `enctype` (such as `application/x-www-form-urlencoded`) on Web Share Target definitions.
3. **No-op Fetch Handler Warning in `sw.js`**:
   - `sw.js` registers `self.addEventListener('fetch', function(event) {});`, which Chromium flags as a no-op handler introducing navigation overhead.

## Proposed Changes
1. **Enable Jinja2 Autoescape (`src/kb_web/base.py`)**:
   - Set `autoescape=jinja2.select_autoescape(["html", "xml", "j2.html", "html5"])`.
2. **Defensive Template Hardening (`src/kb_web/templates/notes_list.j2.html`)**:
   - Move modal JavaScript declarations (`openPasteModal`, `closePasteModal`, `openVaultUploadModal`, `closeVaultUploadModal`) into the `<head>` or early in the document so functions are available immediately.
   - Attach event listeners via both `window` methods and `addEventListener` on DOMContentLoaded.
   - Defensively escape `n.title`, `n.wiki_summary`, and `n.content`.
   - Safely handle `(n.updated_at or '')[:10]` when `updated_at` could be null.
3. **PWA Manifest & Service Worker Fixes (`src/kb_web/server.py`)**:
   - In `/manifest.json`, add `"enctype": "application/x-www-form-urlencoded"` to `share_target`.
   - In `/sw.js`, replace the dummy fetch listener with standard PWA lifecycle event listeners (`install` and `activate` with `skipWaiting` and `clients.claim()`).
4. **Automated Testing & Verification**:
   - Add unit tests verifying:
     - Notes containing raw HTML/`<script>` tags are escaped properly on `/notes`.
     - `/manifest.json` returns `"enctype": "application/x-www-form-urlencoded"`.
     - `/sw.js` does not have an empty fetch handler.
   - Run `uv run pytest`.
   - Run `uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`.
   - Run `uv run python build.py`.
   - Run `uv run python .agents/skills/generate-uat-testing-artifact/scripts/generate_uat_report.py`.
5. **Git & Issue Management**:
   - Create GitHub issue via `gh issue create`.
   - Create and checkout branch `fix-notes-modal-freeze`.
   - Commit changes, push branch, open PR and merge into `production`.
   - Close GitHub issue.
