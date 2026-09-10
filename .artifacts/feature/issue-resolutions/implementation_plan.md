# Implementation Plan - Article Typography, 3-Column Grid & Prompt Modal Editor

This plan details the design updates to refine the article card visual hierarchy and implement a spacious Prompt Editor Modal in the Admin Portal.

## Proposed Changes

### 1. Article Card Typography & Max 3-Column Grid

#### [MODIFY] [pages_list.j2.html](file:///c:/src/kb-web/src/kb_web/templates/pages_list.j2.html)
- Change grid container from `grid-cols-4` to max 3 columns: `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5`.
- **Title**: Make article title the largest and boldest part of the card: `<h2 class="text-base sm:text-lg font-extrabold text-gray-900 leading-snug line-clamp-3 mb-2">`.
- **Collection Badge**: Shrink collection badge to a sleek, compact indicator (`text-[10px] font-semibold px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-150`).
- **Domain Badge**: Compact domain display (`text-[10px] font-mono bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded`).

---

### 2. Admin System Prompt Editor Modal

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- In the Server Configurations card, replace small static prompt textareas with:
  - Read-only preview box displaying current prompt snippet.
  - "✏️ Edit Wiki Prompt in Modal" and "✏️ Edit YouTube Prompt in Modal" buttons.
- Create `#promptModal` overlay dialog with:
  - Title & description.
  - Large full-featured `<textarea id="modalPromptInput" rows="14" class="w-full font-mono text-xs p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 shadow-inner">`.
  - "Save Prompt" button that updates the main configuration form and submits changes cleanly.

---

## Verification Plan

### Automated Tests
- Run `verify_ui_templates.py` to ensure all 14 Jinja2 templates compile cleanly.
- Run `uv run pytest` to ensure no route or template rendering breakage.

### Manual Verification
- Verify that article titles are the primary visual focus on cards in the 3-column grid.
- Open the Admin Dashboard and verify clicking "Edit Prompt" pops open the spacious modal dialog.
