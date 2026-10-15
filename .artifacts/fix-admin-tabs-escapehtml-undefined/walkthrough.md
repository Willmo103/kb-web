# Walkthrough — Fix Admin Portal Blank Tabs & `escapeHtml` ReferenceError

Branch: `fix/admin-tabs-escapehtml-undefined` → merged into `development`
Regression source: Issue #92 Prompt Studio merge (`311f01c` / `309b403`)

## Root Causes
1. **Blank tabs** — The `tab-prompts` refactor in `admin.j2.html` dropped 4 closing `</div>` tags after the
   *Quick Diagnostics* `</dl>`. Prompts, Backups, Media, and Diagnostics panes were nested inside `#tab-general`,
   so `switchAdminTab()` hid all of them whenever General was hidden.
2. **`escapeHtml is not defined`** — `updateActivePromptUI()` (revision history) and the status banner called
   `escapeHtml()`, which the admin template never defined. This threw inside the Monaco `require` callback.

## Changes
- `src/kb_web/templates/admin.j2.html`: put back the 4 missing closing tags; added a null-safe `escapeHtml()` helper.
- `tests/test_system_prompts_admin.py`: added `test_admin_portal_tab_panes_are_siblings` (HTML parser checks that no
  tab pane is nested in another) and `test_admin_portal_defines_escape_html`.
- `CHANGELOG.md`: added a `Fixed` entry under 0.5.9.

## Verification
- Both new tests **failed** on the broken template and **pass** with the fix.
- `uv run pytest`: **188 passed**.
- `verify_ui_templates.py`: **0 warnings**.
- `uv run python build.py`: **SUCCESS**.
- `ruff`: no new lint errors from this change. The existing repo-wide errors are unchanged.
- Browser UAT: done by the user in their dedicated test environment (`kb-test`).
