# Implementation Plan - UI Button Colors, Contrast & Article Grid Layout

This updated plan addresses the user feedback regarding UI button colors/contrast and converts article listing pages into responsive multi-column square grids.

## User Feedback & Requirements

1. **Button Colors & Contrast**:
   - Fix invalid non-standard Tailwind color class names (e.g. `indigo-650`, `indigo-705`, `gray-655`, `red-805`) that were causing buttons like "Open Notes Workspace" to render with transparent backgrounds and invisible white text.
   - Replace with valid high-contrast Tailwind v2 color classes (`indigo-600`, `indigo-700`, `emerald-700`, `gray-800`).
   - Fix status badges ("NONE", "PUBLIC", "PRIVATE") to ensure high legibility and contrast.

2. **Article Grid Layout (Square Cards)**:
   - Convert articles from long, 1-column full-width horizontal rows into a multi-column square grid layout (`grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4`).
   - Format each article card into a compact tile with line-clamp titles, hostname badges, dates, and tag chips to display significantly more articles per screen view.

---

## Proposed Changes

### 1. Fix Button & Badge Color Classes across Templates

#### [MODIFY] [base.j2.html](file:///c:/src/kb-web/src/kb_web/templates/base.j2.html)
- Replace non-standard color classes `text-indigo-650`, `red-808` with valid standard classes `text-indigo-600`, `text-red-700`.

#### [MODIFY] [view_collection.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_collection.j2.html)
- Fix "Open Notes Workspace" button: `bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-2.5 px-4 rounded-lg shadow-sm transition`.
- Fix status/visibility badge styling to ensure high-contrast background and text.
- Replace all occurrences of `indigo-650`, `indigo-705`, `gray-655` with valid standard Tailwind classes (`indigo-600`, `indigo-700`, `gray-700`).

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- Fix button background and hover colors in configuration, pipeline operations, and system message forms.

#### [MODIFY] [collection_editor.j2.html](file:///c:/src/kb-web/src/kb_web/templates/collection_editor.j2.html)
- Fix chat send button and tab header colors: `bg-indigo-600 hover:bg-indigo-700 text-white`.

---

### 2. Multi-Column Square Grid for Articles

#### [MODIFY] [pages_list.j2.html](file:///c:/src/kb-web/src/kb_web/templates/pages_list.j2.html)
- Convert both tagged articles list (lines 136-183) and default knowledge library articles list (lines 361-408) from `space-y-3` rows to `grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4`.
- Restructure article cards into compact square flex boxes with line-clamp title links, domain badges, date timestamps, and tag chips.

---

## Verification Plan

### Automated Tests
- Run `uv run python .agent/skills/ui-component-uat-check/scripts/verify_ui_templates.py` to ensure all 13 HTML templates pass structural syntax checks.
- Run `uv run pytest` to ensure no regression in endpoint responses or template rendering.

### Manual Verification
- Render the UI and verify that button text is clear and readable, and that articles display as a responsive multi-column grid.
