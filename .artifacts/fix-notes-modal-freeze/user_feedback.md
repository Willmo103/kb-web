# User Feedback

## User Request & Reported Console Log
- **Date**: 2026-09-29
- **Reported Incident**:
  When visiting the `/notes` URL and clicking either "Upload Obsidian Vault" or "New Note / Code", the UI freezes and buttons fail to open modals.
- **Browser Console Errors**:
  ```
  Fetch event handler is recognized as no-op. No-op fetch handler may bring overhead during navigation. Consider removing the handler if possible.
  notes:2926 Uncaught SyntaxError: Unexpected token '.'
  manifest.json:1 Manifest: Enctype should be set to either application/x-www-form-urlencoded or multipart/form-data. It currently defaults to application/x-www-form-urlencoded
  notes:101 Uncaught ReferenceError: openPasteModal is not defined
      at HTMLButtonElement.onclick (notes:101:196)
  ```
- **Instructions**:
  - Create the issue on GitHub.
  - Fix all reported issues:
    1. Resolve modal script execution and freeze on `/notes`.
    2. Prevent unescaped note content and scripts from breaking HTML / JS execution (enable Jinja2 autoescape & defensive HTML escaping).
    3. Ensure modal functions are defined early and robustly bound to modal trigger elements.
    4. Address PWA manifest warning regarding `enctype` on `share_target`.
    5. Remove no-op fetch handler warning in `sw.js`.
  - Verify with unit tests, UI component checks, and build verification.
  - Merge and close back into `production` upon completion.
