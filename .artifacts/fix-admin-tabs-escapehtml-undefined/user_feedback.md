# User Feedback — fix/admin-tabs-escapehtml-undefined

## Reported Issue (2026-10-14)
After merging `feature/expose-system-messages-admin-portal` (Issue #92) into `production`, the Admin Portal (`/admin`) is broken:

- Browser console error:
  ```
  admin:2239 Uncaught ReferenceError: escapeHtml is not defined
      at admin:2239:61
      at Array.map (<anonymous>)
      at updateActivePromptUI (admin:2226:55)
      at admin:2093:13  (Monaco require callback)
  ```
- Screenshots: The **General & System** tab renders correctly, but **Prompts & Pipeline**, **Backups & Database**, **Media & YouTube**, and **Diagnostics & CLI** tabs render completely blank.

## Instructions
- Familiarize with repo agent files and artifacts before fixing.
- Fix the regression introduced by the last merge into production.

## Additional Feedback
None received yet.
