# Implementation Plan - Admin Portal Dark Mode Diagnostics Card & Monaco Prompt Editor Height Fix

## Problem Analysis
1. **Quick Diagnostics Panel Dark Mode Inconsistency**:
   - In `src/kb_web/templates/admin.j2.html` (lines 316-335), the Quick Diagnostics panel is configured with `class="bg-gradient-to-br from-indigo-50 to-blue-50 dark:from-slate-800 dark:to-indigo-950 p-6 rounded-2xl border border-indigo-100 dark:border-slate-700 shadow-sm"`.
   - The application loads the standalone CDN build `tailwindcss@2.2.19/dist/tailwind.min.css`. `dark:from-slate-800` and `dark:to-indigo-950` do not exist in Tailwind v2.2.19 CDN.
   - The active `background-image: linear-gradient` from `from-indigo-50 to-blue-50` continues rendering bright light-blue/white in dark mode, causing white-on-white text readability issues.
   - **Fix**: Standardize the panel markup to use `bg-white dark:bg-slate-800 border-gray-200 dark:border-slate-700` and add a scoped `.quick-diagnostics-panel` class with explicit dark mode CSS (`background: #111827 !important; background-image: none !important; border-color: #1e293b !important;`).

2. **Monaco Prompt Editor Collapsing in Half-Screen Mode**:
   - In `src/kb_web/templates/admin.j2.html`, container dimensions are styled with arbitrary utility classes (`min-h-[520px]`, `h-[500px]`, `max-h-[600px]`).
   - Tailwind 2 CDN ignores arbitrary JIT values like `h-[500px]`. As a result, `#monacoPromptContainer` has `height: auto` and `min-height: 0` inside an unconstrained flex container.
   - In half-screen or Editor-only mode, Monaco measures its container, receives `~15-18px`, and collapses into a narrow horizontal sliver.
   - **Fix**:
     - Define concrete CSS rules in `admin.j2.html` `<style>`:
       ```css
       #studioSplitContainer { min-height: 520px; }
       #promptEditorCol { min-height: 480px; }
       #monacoPromptContainer { width: 100%; min-height: 480px; height: 500px; }
       #promptMarkdownPreview { min-height: 480px; height: 500px; }
       #promptsListContainer { max-height: 600px; }
       ```
     - Add inline style fallbacks (`style="min-height: 480px; height: 500px;"`) to guarantee proper height across all viewport sizes and split/editor view modes.
     - Add a debounced `window.resize` listener to trigger `promptMonacoEditor.layout()` whenever the user resizes the browser window or snaps to half-screen.

---

## User Review Required
> [!IMPORTANT]
> The Prompt Editor minimum height will be pinned at `480px` (with standard height `500px`) so that even on half-screen or mobile stacked view, the prompt code and Markdown preview remain comfortably readable and editable without collapsing.

---

## Proposed Changes

### `src/kb_web/templates/admin.j2.html`
- **Add Scoped CSS Rules**:
  - Add dark-mode rule for `.quick-diagnostics-panel`:
    ```css
    html.dark .quick-diagnostics-panel {
        background-color: #111827 !important;
        background-image: none !important;
        border-color: #1e293b !important;
    }
    ```
  - Add structural height rules for `#studioSplitContainer`, `#promptEditorCol`, `#monacoPromptContainer`, `#promptMarkdownPreview`, and `#promptsListContainer`.
- **Update Quick Diagnostics Element**:
  - Replace the unsupported `bg-gradient-to-br from-indigo-50 to-blue-50 dark:from-slate-800 dark:to-indigo-950` with standard admin card classes and `quick-diagnostics-panel`.
- **Update Prompt Studio Elements**:
  - Ensure `#studioSplitContainer`, `#promptEditorCol`, `#monacoPromptContainer`, and `#promptMarkdownPreview` have explicit inline style heights in addition to class attributes.
  - In `switchAdminTab` and window resize, ensure `promptMonacoEditor.layout()` is executed reliably.

---

## Verification Plan

### Automated Verification
1. **Template Validation**:
   - Run `python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py` to ensure all Jinja2 blocks, tags, and theme attributes are balanced and valid.
2. **Pytest Suite**:
   - Run `uv run pytest tests/test_system_prompts_admin.py tests/test_server.py` to confirm no regressions in admin route handling and template rendering.

### Visual & Browser Verification
3. **Browser Verification**:
   - Render the Admin page with dark mode enabled (`html.dark`) to verify:
     - The Quick Diagnostics panel renders with dark background `#111827` and slate border `#1e293b`, matching other cards.
     - The Monaco Prompt editor in `#tab-prompts` renders with `500px` height both in full-screen and half-screen (< 1024px) responsive views, eliminating the collapsed "sliver" bug.
