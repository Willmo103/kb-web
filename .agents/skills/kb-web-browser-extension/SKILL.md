---
name: kb-web-browser-extension
description: Instructions for testing, configuring, and verifying the unpackaged Chrome/Firefox browser extension in browser_extension/.
---
# Chrome Browser Extension Skill for kb-web

Use this skill when developing, testing, or updating the browser extension in `browser_extension/`.

## Extension Components
- `manifest.json`: Manifest v3 manifest defining host permissions, background worker, and options page.
- `background.js`: Service worker forwarding page HTML to `/api/import/html`.
- `options.html` / `options.js`: Configuration UI setting API endpoint and `KB_API_KEY`.
- `popup.html`: Quick-trigger status popup.

## Verification Steps

1. Open `chrome://extensions/` in Chrome or `about:debugging` in Firefox.
2. Enable **Developer mode**.
3. Load unpacked extension from directory: `remotes/kb-web/browser_extension`.
4. Configure options page:
   - Endpoint: `http://localhost:8050/api/import/html`
   - API Key: `kb-secret-key` (or configured key)
5. Test page HTML POST ingestion against local FastAPI server.
