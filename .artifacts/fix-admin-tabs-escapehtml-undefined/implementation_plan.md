# Implementation Plan — Fix Admin Portal Blank Tabs & `escapeHtml` ReferenceError

Branch: `fix/admin-tabs-escapehtml-undefined` (from `development`)
Regression source: `311f01c` / merge `309b403` (Issue #92 Prompt Studio)

## Root Causes

### 1. Missing closing `</div>` tags in `#tab-general` (blank tabs)
In `src/kb_web/templates/admin.j2.html`, the Issue #92 refactor replaced the old prompts form and accidentally dropped
4 closing tags after the *Quick Diagnostics* `</dl>` (diagnostics card, right column, grid, `#tab-general`).
As a result `#tab-prompts`, `#tab-backups`, `#tab-media`, and `#tab-diagnostics` were parsed as **children of `#tab-general`**.
`switchAdminTab()` hides `#tab-general`, which hides every nested pane → all non-General tabs appear empty.

Div balance per section (before fix): General `+4`, all other tabs `0`.

### 2. `escapeHtml` not defined in admin template (ReferenceError)
The new Prompt Studio code calls `escapeHtml()` in `updateActivePromptUI()` (version history render) and in the
status banner helper, but no `escapeHtml` function exists in `admin.j2.html` or `base.j2.html`
(each template defines its own local helper). The error aborts the Monaco init callback.

## Proposed Changes

### `src/kb_web/templates/admin.j2.html`
- Add the 4 missing `</div>` closing tags after the Quick Diagnostics `</dl>`.
- Define a local `escapeHtml(str)` helper at the top of the admin controller `<script>` block (null-safe, escapes `& < > " '`).

### `tests/test_system_prompts_admin.py`
- Add `test_admin_portal_tab_panes_are_siblings`: parse rendered `/admin` HTML with `html.parser` and assert each
  `.admin-tab-pane` is not nested within another pane.
- Add `test_admin_portal_defines_escape_html`: assert `function escapeHtml` is defined when `escapeHtml(` is used.

### Docs
- `CHANGELOG.md`: `Fixed` entry under current version.
- `walkthrough.md` in this artifacts folder.

## Verification
- `uv run pytest`, `uv run ruff check .`, `verify_ui_templates.py`, `uv run python build.py`.
- Browser UAT: load `/admin`, switch through all 5 tabs, confirm no console errors.
